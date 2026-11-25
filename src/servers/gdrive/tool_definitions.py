"""Schemas for Drive discovery, organization and content tools."""

from mcp.types import Tool, ToolAnnotations

ID = {"type": "string", "minLength": 1}
PAGE = {
    "page_size": {"type": "integer", "minimum": 1, "maximum": 100, "default": 100},
    "page_token": {"type": "string"},
}
TEXT_PAGE = {
    "offset": {"type": "integer", "minimum": 0, "default": 0},
    "max_chars": {"type": "integer", "minimum": 1, "maximum": 100000, "default": 50000},
}
SORT_KEYS = (
    "name",
    "name_natural",
    "folder",
    "createdTime",
    "modifiedTime",
    "recency",
    "quotaBytesUsed",
    "viewedByMeTime",
    "sharedWithMeTime",
    "modifiedByMeTime",
    "starred",
)
FILTERS = {
    "mime_type": {"type": "string", "minLength": 1},
    "name_contains": {"type": "string", "minLength": 1},
    "name_equals": {"type": "string", "minLength": 1},
    "order_by": {
        "type": "string",
        "pattern": r"^("
        + "|".join(SORT_KEYS)
        + r")( desc)?(,("
        + "|".join(SORT_KEYS)
        + r")( desc)?)*$",
    },
}


def tool(
    name,
    description,
    properties,
    required=(),
    *,
    write=False,
    destructive=False,
    **schema
):
    return Tool(
        name=name,
        description=description,
        inputSchema={
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
            **schema,
        },
        annotations=ToolAnnotations(
            readOnlyHint=not write,
            destructiveHint=destructive,
            idempotentHint=not write,
            openWorldHint=True,
        ),
    )


EXTRA_TOOLS = [
    tool(
        "list_drives",
        "Discover accessible shared drives with pagination. Use a drive's ID as folder_id and drive_id in list_files.",
        PAGE,
    ),
    tool(
        "get_file_info",
        "Get file/folder metadata, parents, version, capabilities, links and shortcut target without downloading. Does not resolve shortcuts.",
        {"file_id": ID},
        ["file_id"],
    ),
    tool(
        "list_permissions",
        "Inspect file/folder sharing and inherited permissions, including shared drives. Read-only; does not grant access.",
        {"file_id": ID, **PAGE},
        ["file_id"],
    ),
    tool(
        "create_folder",
        "Create a folder in My Drive or a supplied parent folder, including shared drives. Requires write-capable OAuth grants.",
        {"name": ID, "parent_folder_id": ID},
        ["name"],
        write=True,
    ),
    tool(
        "copy_file",
        "Copy a file, optionally with a new name and destination folder. Does not recursively copy folders. Requires write-capable OAuth grants.",
        {"file_id": ID, "name": ID, "parent_folder_id": ID},
        ["file_id"],
        write=True,
    ),
    tool(
        "update_file",
        "Rename, change description, move to a folder, or trash/restore a file or folder. Operates on the supplied shortcut itself, not its target. Requires write-capable OAuth grants.",
        {
            "file_id": ID,
            "name": ID,
            "description": {"type": "string"},
            "parent_folder_id": ID,
            "trashed": {"type": "boolean"},
        },
        ["file_id"],
        write=True,
        destructive=True,
        anyOf=[
            {"required": [key]}
            for key in ("name", "description", "parent_folder_id", "trashed")
        ],
    ),
    tool(
        "upload_file",
        "Upload a new file from UTF-8 text or base64 bytes (exactly one). No local paths or remote URLs. Maximum 10 MiB. Optional conversion to a native Google document; requires write-capable OAuth grants.",
        {
            "name": ID,
            "mime_type": ID,
            "parent_folder_id": ID,
            "content": {"type": "string", "maxLength": 10 * 1024 * 1024},
            "content_base64": {
                "type": "string",
                "maxLength": 4 * ((10 * 1024 * 1024 + 2) // 3),
            },
            "target_mime_type": {
                "type": "string",
                "enum": [
                    "application/vnd.google-apps.document",
                    "application/vnd.google-apps.spreadsheet",
                    "application/vnd.google-apps.presentation",
                ],
            },
        },
        ["name", "mime_type"],
        write=True,
        oneOf=[
            {"required": ["content"], "not": {"required": ["content_base64"]}},
            {"required": ["content_base64"], "not": {"required": ["content"]}},
        ],
    ),
    tool(
        "export_file",
        "Export a native Google file as PDF, DOCX, XLSX, PPTX, text or other supported MIME type. Returns an embedded binary resource. Maximum 10 MiB; does not change sharing.",
        {
            "file_id": ID,
            "mime_type": ID,
        },
        ["file_id", "mime_type"],
    ),
    tool(
        "extract_file_text",
        "Extract text from PDF, DOCX, XLSX or PPTX; native Google files and text also supported. No OCR; encrypted PDFs and legacy DOC/XLS/PPT are unsupported. Paginated text, 10 MiB input limit.",
        {
            "file_id": ID,
            **TEXT_PAGE,
        },
        ["file_id"],
    ),
]
EXTRA_TOOL_NAMES = {tool.name for tool in EXTRA_TOOLS}
