"""Offline tests of folder browsing and file contents through MCP dispatch."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp import types

from src.servers.gdrive import main as drive


@pytest.fixture
def api():
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "child", "name": "Child", "mimeType": drive.FOLDER_MIME}],
        "nextPageToken": "next",
    }
    service.files.return_value.get.return_value.execute.return_value = {
        "id": "file",
        "name": "File",
        "mimeType": "text/plain",
        "size": "6",
    }
    with patch.object(drive, "create_drive_service", AsyncMock(return_value=service)):
        yield service


async def call(name, arguments):
    return await drive.create_server("test", "key").dispatch(
        types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=name, arguments=arguments),
        )
    )


async def test_discovery():
    result = await drive.create_server("test").dispatch(
        types.ListToolsRequest(method="tools/list")
    )
    assert {t.name for t in result.tools} == {"search", "list_files", "read_file"}


async def test_folder_browsing_shared_drive_pagination(api):
    result = await call(
        "list_files",
        {
            "folder_id": "parent",
            "folders_only": True,
            "drive_id": "shared",
            "page_token": "prev",
            "page_size": 20,
        },
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["nextPageToken"] == "next"
    assert data["files"][0]["uri"] == "gdrive://folder/child"
    params = api.files().list.call_args.kwargs
    assert "'parent' in parents" in params["q"]
    assert drive.FOLDER_MIME in params["q"]
    assert params["driveId"] == "shared" and params["corpora"] == "drive"
    assert params["includeItemsFromAllDrives"] and params["supportsAllDrives"]
    assert params["pageToken"] == "prev" and params["pageSize"] == 20


async def test_default_root_and_empty_page(api):
    api.files().list().execute.return_value = {"files": [], "nextPageToken": "more"}
    result = await call("list_files", {})
    assert json.loads(result.content[0].text) == {"files": [], "nextPageToken": "more"}
    assert "'root' in parents" in api.files().list.call_args.kwargs["q"]


async def test_search_escapes_literals_and_returns_ids(api):
    result = await call("search", {"query": "a'b\\c", "folder_id": "d'e"})
    assert not result.is_error
    assert json.loads(result.content[0].text)["files"][0]["id"] == "child"
    assert api.files().list.call_args.kwargs["q"] == (
        "trashed = false and fullText contains 'a\\'b\\\\c' and 'd\\'e' in parents"
    )


@pytest.mark.parametrize("mime,export", list(drive.EXPORT_TYPES.items())[:3])
async def test_native_exports(api, mime, export):
    api.files().get().execute.return_value.update(mimeType=mime)
    with patch.object(drive, "download_content", return_value=b"hello"):
        result = await call("read_file", {"file_id": "file"})
    assert json.loads(result.content[0].text)["content"] == "hello"
    api.files().export.assert_called_once_with(fileId="file", mimeType=export)
    assert api.files().get.call_args.kwargs["supportsAllDrives"]


async def test_text_paging(api):
    with patch.object(drive, "download_content", return_value=b"abcdef"):
        result = await call(
            "read_file", {"file_id": "file", "offset": 2, "max_chars": 3}
        )
        last = await call("read_file", {"file_id": "file", "offset": 5})
    data = json.loads(result.content[0].text)
    assert (data["content"], data["total_chars"], data["next_offset"]) == ("cde", 6, 5)
    assert json.loads(last.content[0].text)["next_offset"] is None
    api.files().get_media.assert_called_with(fileId="file", supportsAllDrives=True)


async def test_binary_and_drawing_export(api):
    api.files().get().execute.return_value.update(
        mimeType="application/vnd.google-apps.drawing"
    )
    with patch.object(drive, "download_content", return_value=b"\x89PNG\xff"):
        result = await call("read_file", {"file_id": "file"})
    assert not result.is_error
    assert base64.b64decode(result.content[1].resource.blob) == b"\x89PNG\xff"
    assert result.content[1].resource.mime_type == "image/png"


async def test_shortcut_resolution(api):
    api.files().get().execute.side_effect = [
        {
            "mimeType": "application/vnd.google-apps.shortcut",
            "shortcutDetails": {"targetId": "target"},
        },
        {"id": "target", "name": "Target", "mimeType": "text/plain"},
    ]
    with patch.object(drive, "download_content", return_value=b"hello"):
        result = await call("read_file", {"file_id": "shortcut"})
    assert json.loads(result.content[0].text)["file"]["id"] == "target"
    api.files().get_media.assert_called_with(fileId="target", supportsAllDrives=True)


@pytest.mark.parametrize(
    "metadata,error",
    [
        ({"mimeType": drive.FOLDER_MIME}, "folder"),
        ({"size": str(drive.MAX_FILE_BYTES + 1)}, "10 MiB"),
        ({"mimeType": "application/vnd.google-apps.form"}, "not supported"),
    ],
)
async def test_content_errors(api, metadata, error):
    api.files().get().execute.return_value.update(metadata)
    result = await call("read_file", {"file_id": "file"})
    assert result.is_error and error in result.content[0].text
    api.files().get_media.assert_not_called()


@pytest.mark.parametrize(
    "name,args",
    [
        ("read_file", {}),
        ("list_files", {"page_size": 0}),
        ("read_file", {"file_id": "x", "offset": -1}),
        ("search", {"query": ""}),
    ],
)
async def test_invalid_arguments_do_not_access_drive(api, name, args):
    result = await call(name, args)
    assert result.is_error
    drive.create_drive_service.assert_not_awaited()


async def test_legacy_resource_read_binary(api):
    api.files().get().execute.return_value.update(mimeType="application/pdf")
    with patch.object(drive, "download_content", return_value=b"%PDF"):
        result = await drive.create_server("test").dispatch(
            types.ReadResourceRequest(
                method="resources/read",
                params=types.ReadResourceRequestParams(uri="gdrive:///file"),
            )
        )
    assert base64.b64decode(result.contents[0].blob) == b"%PDF"


def test_download_limit_is_enforced_on_chunks():
    def downloader(buffer, request, chunksize):
        result = MagicMock()

        def chunk():
            buffer.write(b"12345")
            return None, False

        result.next_chunk.side_effect = chunk
        return result

    with patch.object(drive, "MAX_FILE_BYTES", 4), patch.object(
        drive, "MediaIoBaseDownload", downloader
    ):
        with pytest.raises(ValueError, match="10 MiB"):
            drive.download_content(MagicMock())


async def test_shortcut_cycle_is_reported(api):
    api.files().get().execute.return_value = {
        "mimeType": "application/vnd.google-apps.shortcut",
        "shortcutDetails": {"targetId": "file"},
    }
    result = await call("read_file", {"file_id": "file"})
    assert result.is_error and "cycle" in result.content[0].text


async def test_api_failure_reaches_client(api):
    api.files().list().execute.side_effect = RuntimeError("Drive unavailable")
    result = await call("list_files", {})
    assert result.is_error and "Drive unavailable" in result.content[0].text


def test_download_uses_media_api():
    import httplib2

    request = MagicMock()
    request.uri = "https://www.googleapis.com/drive/v3/files/file?alt=media"
    request.headers = {}
    request.http.request.return_value = (
        httplib2.Response(
            {
                "status": "200",
                "content-length": "5",
            }
        ),
        b"hello",
    )
    assert drive.download_content(request) == b"hello"


async def test_resources_still_list(api):
    result = await drive.create_server("test").dispatch(
        types.ListResourcesRequest(method="resources/list")
    )
    assert result.resources[0].uri == "gdrive://folder/child"
