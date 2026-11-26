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
    assert {t.name for t in result.tools} == {
        "search",
        "list_files",
        "read_file",
        "list_drives",
        "get_file_info",
        "list_permissions",
        "create_folder",
        "copy_file",
        "update_file",
        "upload_file",
        "export_file",
        "extract_file_text",
    }


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


async def test_shared_drive_discovery(api):
    expected = {"drives": [{"id": "team", "name": "Team"}], "nextPageToken": "next"}
    api.drives().list().execute.return_value = expected
    result = await call("list_drives", {"page_token": "prev", "page_size": 5})
    assert json.loads(result.content[0].text) == expected
    assert api.drives().list.call_args.kwargs["pageToken"] == "prev"
    assert api.drives().list.call_args.kwargs["pageSize"] == 5


async def test_metadata_without_download(api):
    result = await call("get_file_info", {"file_id": "file"})
    assert json.loads(result.content[0].text)["uri"] == "gdrive://file/file"
    assert "capabilities" in api.files().get.call_args.kwargs["fields"]
    api.files().get_media.assert_not_called()


async def test_permissions_inspection(api):
    expected = {
        "permissions": [{"id": "p", "type": "user", "role": "reader"}],
        "nextPageToken": "next",
    }
    api.permissions().list().execute.return_value = expected
    result = await call("list_permissions", {"file_id": "file", "page_token": "prev"})
    assert json.loads(result.content[0].text) == expected
    params = api.permissions().list.call_args.kwargs
    assert params["supportsAllDrives"] and params["pageToken"] == "prev"
    assert "permissionDetails" in params["fields"]
    api.permissions().create.assert_not_called()


async def test_search_filters_and_sort(api):
    result = await call(
        "search",
        {
            "query": "report",
            "name_equals": "Q1's",
            "mime_type": "application/pdf",
            "order_by": "modifiedTime desc,name",
        },
    )
    assert not result.is_error
    params = api.files().list.call_args.kwargs
    assert "name = 'Q1\\'s'" in params["q"]
    assert "mimeType = 'application/pdf'" in params["q"]
    assert params["orderBy"] == "modifiedTime desc,name"


@pytest.mark.parametrize(
    "name,args",
    [
        ("create_folder", {"name": "Invoices", "parent_folder_id": "team"}),
        ("copy_file", {"file_id": "file", "name": "Copy", "parent_folder_id": "team"}),
    ],
)
async def test_create_and_copy(api, name, args):
    method = api.files().create if name == "create_folder" else api.files().copy
    method.return_value.execute.return_value = {
        "id": "new",
        "name": "New",
        "mimeType": drive.FOLDER_MIME if name == "create_folder" else "text/plain",
    }
    result = await call(name, args)
    assert not result.is_error
    assert json.loads(result.content[0].text)["id"] == "new"
    params = method.call_args.kwargs
    assert params["supportsAllDrives"] and params["body"]["parents"] == ["team"]
    if name == "create_folder":
        assert params["body"]["mimeType"] == drive.FOLDER_MIME
    else:
        assert params["fileId"] == "file"
    method.return_value.execute.assert_called_once_with()


async def test_rename_move_trash_and_restore(api):
    api.files().get().execute.return_value = {"parents": ["old"]}
    api.files().update().execute.return_value = {
        "id": "file",
        "name": "Renamed",
        "mimeType": "text/plain",
    }
    result = await call(
        "update_file",
        {
            "file_id": "file",
            "name": "Renamed",
            "parent_folder_id": "new",
            "trashed": True,
        },
    )
    assert not result.is_error
    params = api.files().update.call_args.kwargs
    assert params["addParents"] == "new" and params["removeParents"] == "old"
    assert params["body"] == {"name": "Renamed", "trashed": True}
    await call("update_file", {"file_id": "file", "trashed": False})
    assert api.files().update.call_args.kwargs["body"] == {"trashed": False}


async def test_move_to_existing_parent_does_not_remove_it(api):
    api.files().get().execute.return_value = {"parents": ["same"]}
    api.files().update().execute.return_value = {
        "id": "file",
        "name": "File",
        "mimeType": "text/plain",
    }
    await call("update_file", {"file_id": "file", "parent_folder_id": "same"})
    params = api.files().update.call_args.kwargs
    assert "addParents" not in params and "removeParents" not in params


@pytest.mark.parametrize(
    "content,expected",
    [
        ({"content": "héllo"}, "héllo".encode()),
        ({"content_base64": base64.b64encode(b"\xff\x00").decode()}, b"\xff\x00"),
    ],
)
async def test_upload_original_bytes(api, content, expected):
    api.files().create().execute.return_value = {
        "id": "new",
        "name": "Upload",
        "mimeType": "application/octet-stream",
    }
    result = await call(
        "upload_file",
        {
            "name": "Upload",
            "mime_type": "application/octet-stream",
            "parent_folder_id": "team",
            **content,
        },
    )
    assert not result.is_error
    params = api.files().create.call_args.kwargs
    assert params["media_body"].getbytes(0, 100) == expected
    assert params["body"]["parents"] == ["team"] and params["supportsAllDrives"]


async def test_upload_conversion(api):
    target = "application/vnd.google-apps.document"
    api.files().create().execute.return_value = {
        "id": "new",
        "name": "Doc",
        "mimeType": target,
    }
    result = await call(
        "upload_file",
        {
            "name": "Doc",
            "mime_type": "text/html",
            "content": "<p>Hello</p>",
            "target_mime_type": target,
        },
    )
    assert not result.is_error
    params = api.files().create.call_args.kwargs
    assert params["body"]["mimeType"] == target
    assert params["media_body"].mimetype() == "text/html"


@pytest.mark.parametrize(
    "args",
    [
        {"content_base64": "!!!"},
        {"content": "a", "content_base64": "YQ=="},
        {},
    ],
)
async def test_bad_upload_never_writes(api, args):
    result = await call(
        "upload_file", {"name": "Bad", "mime_type": "text/plain", **args}
    )
    assert result.is_error
    api.files().create.assert_not_called()


async def test_unicode_upload_byte_limit(api):
    with patch.object(drive, "MAX_FILE_BYTES", 3):
        result = await call(
            "upload_file", {"name": "Big", "mime_type": "text/plain", "content": "éé"}
        )
    assert result.is_error and "10 MiB" in result.content[0].text
    api.files().create.assert_not_called()


@pytest.mark.parametrize(
    "name,args",
    [
        ("update_file", {"file_id": "file"}),
        ("update_file", {"file_id": "file", "name": ""}),
        ("create_folder", {"name": ""}),
        ("list_drives", {"page_size": 101}),
        ("search", {"query": "x", "order_by": "name; DROP TABLE files"}),
    ],
)
async def test_extended_schema_errors(api, name, args):
    result = await call(name, args)
    assert result.is_error
    drive.create_drive_service.assert_not_awaited()


@pytest.mark.parametrize(
    "source,target",
    [
        ("application/vnd.google-apps.document", "application/pdf"),
        (
            "application/vnd.google-apps.document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "application/vnd.google-apps.spreadsheet",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (
            "application/vnd.google-apps.presentation",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
    ],
)
async def test_explicit_export_mime(api, source, target):
    api.files().get().execute.return_value.update(mimeType=source)
    with patch.object(drive, "download_content", return_value=b"export bytes"):
        result = await call("export_file", {"file_id": "file", "mime_type": target})
    assert not result.is_error
    assert result.content[1].resource.mime_type == target
    api.files().export.assert_called_once_with(fileId="file", mimeType=target)


async def test_export_rejects_regular_file(api):
    result = await call(
        "export_file", {"file_id": "file", "mime_type": "application/pdf"}
    )
    assert result.is_error and "native Google" in result.content[0].text
    api.files().export.assert_not_called()


async def test_mutation_api_failure_is_not_retried(api):
    api.files().create().execute.side_effect = RuntimeError("Write denied")
    result = await call("create_folder", {"name": "New"})
    assert result.is_error and "Write denied" in result.content[0].text
    api.files().create().execute.assert_called_once_with()


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("list_drives", {}),
        ("get_file_info", {"file_id": "file"}),
        ("list_permissions", {"file_id": "file", "page_token": "next"}),
        ("create_folder", {"name": "New"}),
        ("copy_file", {"file_id": "file", "parent_folder_id": "folder"}),
        (
            "update_file",
            {"file_id": "file", "parent_folder_id": "folder", "name": "New"},
        ),
        ("upload_file", {"name": "New", "mime_type": "text/plain", "content": "hello"}),
        ("export_file", {"file_id": "file", "mime_type": "application/pdf"}),
    ],
)
async def test_requests_build_with_real_google_sdk(name, arguments):
    from google.auth.credentials import AnonymousCredentials
    from googleapiclient.discovery import build

    api = build(
        "drive",
        "v3",
        credentials=AnonymousCredentials(),
        cache_discovery=False,
        static_discovery=True,
    )
    response = {
        "id": "file",
        "name": "File",
        "mimeType": "application/vnd.google-apps.document",
        "parents": ["old"],
        "files": [],
        "drives": [],
        "permissions": [],
    }
    with patch.object(
        drive, "create_drive_service", AsyncMock(return_value=api)
    ), patch(
        "googleapiclient.http.HttpRequest.execute", return_value=response
    ), patch.object(
        drive, "download_content", return_value=b"export"
    ):
        result = await call(name, arguments)
    assert not result.is_error, result.content


async def test_provider_metadata_matches_runtime_tools():
    from pathlib import Path
    import yaml

    config = yaml.safe_load(Path(drive.__file__).with_name("config.yaml").read_text())
    listed = await drive.create_server("test").dispatch(
        types.ListToolsRequest(method="tools/list")
    )
    assert {entry["name"] for entry in config["tools"]} == {
        tool.name for tool in listed.tools
    }
    assert len(config["tools"]) == len(listed.tools)
    for tool in listed.tools:
        if tool.name in {"create_folder", "copy_file", "update_file", "upload_file"}:
            assert tool.annotations.read_only_hint is False
        elif tool.name in drive.EXTRA_TOOL_NAMES:
            assert tool.annotations.read_only_hint is True
