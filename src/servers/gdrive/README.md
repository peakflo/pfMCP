# Google Drive Server

Drive tools for folder navigation, file contents, discovery and organization.
Uses pfMCP's existing Google/Nango credential flow.

## Tools

- `search(query, folder_id?, page_size=100, page_token?, drive_id?, mime_type?,
  name_contains?, name_equals?, order_by?)`: literal full-text search with optional
  direct-parent, MIME and name filters. Query text is escaped, not raw Drive query
  syntax. Sort examples: `modifiedTime desc` or `folder,name` (no spaces after commas).
- `list_files(folder_id="root", folders_only=false, page_size=100, page_token?,
  drive_id?, mime_type?, name_contains?, name_equals?, order_by?)`: browse direct
  children. Pass returned folder IDs to descend; traversal is not recursive.
- `list_drives(page_size=100, page_token?)`: discover shared-drive IDs and names.
  To browse a shared drive's root, pass its ID as both `folder_id` and `drive_id`
  to `list_files`. Use a subfolder ID as `folder_id` when descending.
- `get_file_info(file_id)`: metadata, parents, version, links, capabilities,
  shortcut target and sharing state, without downloading. Returns metadata of
  the supplied shortcut itself rather than resolving it.
- `list_permissions(file_id, page_size=100, page_token?)`: inspect sharing roles
  and inherited permission details. Does not grant or modify access.
- `read_file(file_id, offset=0, max_chars=50000)`: original contents for regular
  files; native Docs export as Markdown, Sheets as CSV (first sheet), Slides as
  plain text, Drawings as PNG. UTF-8 text returns JSON with metadata,
  `total_chars` and `next_offset`. Binary files return an embedded MCP blob
  resource (base64). Shortcuts resolve to their targets.
- `extract_file_text(file_id, offset=0, max_chars=50000)`: readable text from PDF,
  DOCX, XLSX and PPTX, native Google files and UTF-8 text. Separate from retrieval
  of original binary bytes. Uses the same text pagination as `read_file`.
- `export_file(file_id, mime_type)`: export a native Google file to a supported
  MIME type as an embedded binary resource. Examples: `application/pdf`,
  `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
  (DOCX), `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
  (XLSX), or `application/vnd.openxmlformats-officedocument.presentationml.presentation`
  (PPTX). Google validates the source/target format combination. No conversion of
  regular binary files; use `read_file` to download those.
- `create_folder(name, parent_folder_id="root")`: create a folder.
- `copy_file(file_id, name?, parent_folder_id?)`: copy a file with optional name
  and destination. Google Drive does not recursively copy folders.
- `update_file(file_id, name?, description?, parent_folder_id?, trashed?)`: rename,
  change description, move, trash or restore a file/folder. At least one change
  is required. Moving replaces existing parents with the destination; it does
  not copy. If given a shortcut ID, updates the shortcut itself. `trashed=false`
  restores an item; there is no permanent-delete tool.
- `upload_file(name, mime_type, content? OR content_base64?, parent_folder_id="root",
  target_mime_type?)`: upload UTF-8 text or strict base64 bytes (exactly one).
  `mime_type` describes the source content. Optional `target_mime_type` converts
  to a native Google Doc, Sheet or Slides presentation where Google supports
  the source format. Does not accept local paths or remote URLs.

Search/list results include IDs, names, MIME types, resource URIs, parents, links
and metadata. Continue with the same arguments and the returned `nextPageToken`
as `page_token`; an empty page may still have a token. List/search support up to
1000 items per page; drive/permission listing supports up to 100. A returned
`incompleteSearch` flag means the search was incomplete.

## Examples

1. `list_files` with `{"folders_only":true}` to find My Drive folders.
2. `list_files` with `{"folder_id":"FOLDER_ID"}` to browse one.
3. `read_file` with `{"file_id":"FILE_ID"}` for contents, or `extract_file_text`
   for a PDF/Office file.
4. `create_folder` with `{"name":"Processed","parent_folder_id":"FOLDER_ID"}`,
   then `update_file` with `{"file_id":"FILE_ID","parent_folder_id":"NEW_FOLDER_ID"}`
   to move an item.
5. `upload_file` with `{"name":"notes.txt","mime_type":"text/plain","content":"Hello"}`.

## Limits and content formats

Downloads, uploads and exports are limited to 10 MiB. Text responses contain at
most 100,000 characters per page. Continuation re-reads the source; compare the
returned version and restart at offset zero if it changes. Binary content is
not paginated. Metadata and sharing information remain available without downloads.

Extraction returns document text, not exact layout. DOCX reads body paragraphs
and tables; PPTX reads slide text in slide-file order; XLSX reads all worksheet
XML files with cell coordinates, cached values and formulas when no cached value
exists. It does not evaluate formulas or apply number/date formatting. Text in
headers, notes, images or embedded objects may not be included. Legacy binary
DOC/XLS/PPT are unsupported. Encrypted PDFs are unsupported; scanned/image-only
PDFs require separate OCR. Malformed/unsupported documents return tool errors.

Office extraction permits at most 20 MiB of expanded ZIP entries and rejects
DTD/entity declarations. PDF extraction permits at most 1000 pages and 20 MiB
of decompressed content per page. Extracted PDF/Office text is limited to
2 Mi characters. These limits reduce resource use; this is not an OCR service.

Existing `resources/list` and `resources/read` remain available. Resource
listing retains first-page behavior; tools provide pagination. Blocking Google
API and extraction work runs outside the event loop. Creates/copies/uploads
are not automatically retried, since retries may duplicate results.

## Authentication

Enable the Google Drive API in a Google Cloud project. Hosted calls continue
using their configured Nango connection and its actual Google grants.

- Reading/discovery: `https://www.googleapis.com/auth/drive.readonly`.
- Writing/organizing arbitrary accessible Drive files:
  `https://www.googleapis.com/auth/drive`.
- `drive.file` only permits files the app is authorized to access; it does not
  provide general access to all existing files/folders.

Adding tools does not expand an existing OAuth grant. A read-only connection
can keep using reads, but write tools will fail until the connection has suitable
write grants. Reauthorize the hosted connection using its supported Nango flow
if those grants are needed. File and shared-drive permissions also apply.

For local authentication, configure a Desktop OAuth client, download its JSON
as `local_auth/oauth_configs/gdrive/oauth.json`, and run:

```bash
python src/servers/gdrive/main.py auth          # read-only (default)
python src/servers/gdrive/main.py auth --write  # full Drive write scope
```

The authentication command starts Google's browser-based consent flow.
