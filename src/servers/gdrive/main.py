import asyncio
import base64
import io
import json
import os
import sys
from typing import Optional, Iterable

# Add both project root and src directory to Python path
# Get the project root directory and add to path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import logging
from pathlib import Path

from mcp.types import (
    Resource,
    TextContent,
    Tool,
    ImageContent,
    EmbeddedResource,
    BlobResourceContents,
)
from mcp.server.lowlevel.helper_types import ReadResourceContents
from src.utils.mcp_compat import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from src.utils.google.util import authenticate_and_save_credentials, get_credentials

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SERVICE_NAME = Path(__file__).parent.name
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


async def create_drive_service(user_id, api_key=None):
    """Create a new Drive service instance for this request"""
    credentials = await get_credentials(user_id, SERVICE_NAME, api_key=api_key)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


FOLDER_MIME = "application/vnd.google-apps.folder"
MAX_FILE_BYTES = 10 * 1024 * 1024
FILE_FIELDS = "id,name,mimeType,modifiedTime,size,parents,webViewLink,driveId"
EXPORT_TYPES = {
    "application/vnd.google-apps.document": "text/markdown",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.drawing": "image/png",
}


def escape_query(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def resource_uri(file):
    kind = {
        FOLDER_MIME: "folder",
        "application/vnd.google-apps.document": "document",
        "application/vnd.google-apps.spreadsheet": "spreadsheet",
        "application/vnd.google-apps.presentation": "presentation",
    }.get(file["mimeType"], "file")
    return f"gdrive://{kind}/{file['id']}"


async def list_files(service, query, arguments):
    params = {
        "q": query,
        "pageSize": arguments.get("page_size", 100),
        "fields": f"nextPageToken,incompleteSearch,files({FILE_FIELDS})",
        "supportsAllDrives": True,
        "includeItemsFromAllDrives": True,
        "corpora": "user",
    }
    if arguments.get("page_token"):
        params["pageToken"] = arguments["page_token"]
    if arguments.get("drive_id"):
        params.update(driveId=arguments["drive_id"], corpora="drive")
    result = await asyncio.to_thread(service.files().list(**params).execute)
    for file in result.get("files", []):
        file["uri"] = resource_uri(file)
    return result


def download_content(request):
    """Bound downloads, including files whose metadata has no size (exports)."""
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request, chunksize=256 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk()
        if buffer.tell() > MAX_FILE_BYTES:
            raise ValueError("File exceeds the 10 MiB content limit")
    return buffer.getvalue()


async def read_file(service, file_id):
    # Resolve shortcuts without allowing cycles to cause unbounded requests.
    seen = set()
    for _ in range(6):
        if file_id in seen:
            raise ValueError("Drive shortcut cycle detected")
        seen.add(file_id)
        metadata = await asyncio.to_thread(
            service.files()
            .get(
                fileId=file_id,
                fields=f"{FILE_FIELDS},shortcutDetails",
                supportsAllDrives=True,
            )
            .execute
        )
        mime = metadata["mimeType"]
        if mime != "application/vnd.google-apps.shortcut":
            break
        file_id = metadata["shortcutDetails"]["targetId"]
    else:
        raise ValueError("Too many nested Drive shortcuts")
    if mime == FOLDER_MIME:
        raise ValueError("This item is a folder; use list_files with its folder_id")
    if int(metadata.get("size", 0)) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 10 MiB content limit")
    if mime.startswith("application/vnd.google-apps."):
        if mime not in EXPORT_TYPES:
            raise ValueError(f"Content export is not supported for {mime}")
        mime = EXPORT_TYPES[mime]
        request = service.files().export(fileId=file_id, mimeType=mime)
    else:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    content = await asyncio.to_thread(download_content, request)
    # Keep binary formats binary, even if their bytes happen to decode as UTF-8.
    if (
        mime.startswith("text/")
        or mime
        in (
            "application/json",
            "application/xml",
            "application/javascript",
            "image/svg+xml",
        )
        or mime.endswith(("+json", "+xml"))
    ):
        content = content.decode("utf-8-sig")
    return metadata, mime, content


def create_server(user_id, api_key=None):
    """Create a new server instance with optional user context"""
    server = Server("gdrive-server")

    server.user_id = user_id
    server.api_key = api_key

    @server.list_resources()
    async def handle_list_resources(
        cursor: Optional[str] = None,
    ) -> list[Resource]:
        """List files from Google Drive"""
        logger.info(
            f"Listing resources for user: {server.user_id} with cursor: {cursor}"
        )

        drive_service = await create_drive_service(
            server.user_id, api_key=server.api_key
        )

        results = await list_files(
            drive_service,
            "trashed = false",
            {
                "page_size": 10,
                "page_token": cursor,
            },
        )
        files = results.get("files", [])

        # The compatibility decorator returns a bare resource list. Tools expose
        # nextPageToken for clients that need complete, paginated traversal.
        return [
            Resource(
                uri=resource_uri(file), mimeType=file["mimeType"], name=file["name"]
            )
            for file in files
        ]

    @server.read_resource()
    async def handle_read_resource(uri: str) -> Iterable[ReadResourceContents]:
        """Read a file from Google Drive by URI"""
        logger.info(f"Reading resource: {uri} for user: {server.user_id}")

        drive_service = await create_drive_service(
            server.user_id, api_key=server.api_key
        )

        # Extract file_id from the new URI format
        uri_parts = str(uri).split("://")
        if len(uri_parts) > 1:
            path_parts = uri_parts[1].split("/", 1)
            if len(path_parts) > 1:
                file_id = path_parts[1]
            else:
                raise ValueError(f"Invalid URI format: {uri}")
        else:
            # Handle legacy format for backward compatibility
            file_id = str(uri).replace("gdrive:///", "")

        _, mime_type, content = await read_file(drive_service, file_id)
        return [ReadResourceContents(content=content, mime_type=mime_type)]

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """List available tools"""
        logger.info(f"Listing tools for user: {server.user_id}")
        paging = {
            "page_size": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "description": "Results per page (default 100).",
            },
            "page_token": {"type": "string", "description": "Previous nextPageToken."},
            "drive_id": {"type": "string", "description": "Optional shared drive ID."},
        }
        return [
            Tool(
                name="search",
                description="Search Drive files and folders by text. Returns IDs, URIs and pagination.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "folder_id": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Limit search to direct children of this folder.",
                        },
                        **paging,
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="list_files",
                description="Browse direct children of a Drive folder, including shared drives. Use returned folder IDs to descend into subfolders.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "folder_id": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Folder ID (default root of My Drive). For a shared drive root, use its drive ID.",
                        },
                        "folders_only": {"type": "boolean", "default": False},
                        **paging,
                    },
                },
            ),
            Tool(
                name="read_file",
                description="Get Drive file contents by ID. Exports Docs as Markdown, Sheets as CSV and Slides as text. Binary files return an embedded base64 resource; no PDF/Office text extraction or OCR. Maximum 10 MiB.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "minLength": 1},
                        "offset": {
                            "type": "integer",
                            "minimum": 0,
                            "default": 0,
                            "description": "Character offset for text continuation.",
                        },
                        "max_chars": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100000,
                            "default": 50000,
                        },
                    },
                    "required": ["file_id"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[TextContent | ImageContent | EmbeddedResource]:
        """Handle tool execution requests"""
        arguments = arguments or {}
        if name not in ("search", "list_files", "read_file"):
            raise ValueError(f"Unknown tool: {name}")
        drive_service = await create_drive_service(
            server.user_id, api_key=server.api_key
        )
        if name in ("search", "list_files"):
            clauses = ["trashed = false"]
            folder_id = arguments.get("folder_id")
            if name == "list_files":
                folder_id = folder_id or "root"
                if arguments.get("folders_only"):
                    clauses.append(f"mimeType = '{FOLDER_MIME}'")
            else:
                clauses.append(
                    f"fullText contains '{escape_query(arguments['query'])}'"
                )
            if folder_id:
                clauses.append(f"'{escape_query(folder_id)}' in parents")
            result = await list_files(drive_service, " and ".join(clauses), arguments)
            return [TextContent(type="text", text=json.dumps(result))]

        metadata, mime, content = await read_file(drive_service, arguments["file_id"])
        uri = resource_uri(metadata)
        if isinstance(content, str):
            offset = arguments.get("offset", 0)
            if offset > len(content):
                raise ValueError("offset exceeds the file's text length")
            end = min(offset + arguments.get("max_chars", 50000), len(content))
            result = {
                "file": metadata,
                "mimeType": mime,
                "content": content[offset:end],
                "total_chars": len(content),
                "next_offset": end if end < len(content) else None,
            }
            return [TextContent(type="text", text=json.dumps(result))]
        if arguments.get("offset", 0):
            raise ValueError("offset is supported only for text files")
        return [
            TextContent(
                type="text", text=json.dumps({"file": metadata, "mimeType": mime})
            ),
            EmbeddedResource(
                type="resource",
                resource=BlobResourceContents(
                    uri=uri,
                    mimeType=mime,
                    blob=base64.b64encode(content).decode("ascii"),
                ),
            ),
        ]

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """Get the initialization options for the server"""
    return InitializationOptions(
        server_name="gdrive-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


# Main handler allows users to auth
if __name__ == "__main__":
    if sys.argv[1].lower() == "auth":
        user_id = "local"
        # Run authentication flow
        authenticate_and_save_credentials(user_id, SERVICE_NAME, SCOPES)
    else:
        print("Usage:")
        print("  python main.py auth - Run authentication flow for a user")
        print("Note: To run the server normally, use the guMCP server framework.")
