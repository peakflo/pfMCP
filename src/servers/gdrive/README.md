# Google Drive Server

pfMCP server implementation for interacting with Google Drive.

### Tools

- `search(query, folder_id?, page_size?, page_token?, drive_id?)`: full-text
  search for files and folders. An optional folder limits results to its direct
  children. Returns JSON with file IDs, names, MIME types, parents, links,
  resource URIs and `nextPageToken` when more results exist.
- `list_files(folder_id="root", folders_only=false, page_size=100,
  page_token?, drive_id?)`: browse a folder's direct children. Pass a returned
  folder ID to browse its children; traversal is not recursive. Pass
  `folders_only=true` to find subfolders. For a shared drive, set `drive_id` and
  use the drive ID as `folder_id` to browse its root.
- `read_file(file_id, offset=0, max_chars=50000)`: retrieve file contents.
  Google Docs export as Markdown, Sheets as CSV (first sheet), Slides as plain
  text and Drawings as PNG. UTF-8 text is returned in JSON with metadata,
  `total_chars` and `next_offset`; pass that offset to continue reading. Each
  continuation reads the file again, so restart if the source changes.
  Shortcuts resolve to their targets. PDFs, Office files and other binary formats
  return an embedded MCP blob resource (base64), without text extraction or OCR.
  Downloads/exports are limited to 10 MiB; a tool error is returned above that
  limit. Folders must be browsed with `list_files`, not `read_file`.

Example: call `list_files` with `{"folder_id":"root","folders_only":true}`,
then `list_files` with the selected folder ID, then `read_file` with a returned
file ID. To fetch more results, repeat the same list/search arguments with the
returned `nextPageToken` as `page_token`. An empty page may still have a next
page token. Search supports literal text, not raw Drive query syntax.

The existing `resources/list` and `resources/read` API remains available.
Resources and tools are separate MCP capabilities; clients supporting only
tools can use the tools above. Resource listing retains its legacy first-page
behavior; use `list_files` for pagination. These operations are read-only and
continue using pfMCP's existing credential flow. Hosted access is limited by the
scopes actually granted to the Nango connection; local scope settings do not
change existing grants.

### Prerequisites

- Python 3.11+
- A Google Cloud Project with Google Drive APIs enabled
- OAuth 2.0 credentials with the following scopes:
  - https://www.googleapis.com/auth/drive.readonly

### Local Authentication

1. [Create a new Google Cloud project](https://console.cloud.google.com/projectcreate)
2. [Enable the Google Drive API and Google Docs API](https://console.cloud.google.com/workspace-api/products)
3. [Configure an OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent) ("internal" is fine for testing)
4. Add OAuth scopes:
   - https://www.googleapis.com/auth/drive.readonly
5. [Create an OAuth Client ID](https://console.cloud.google.com/apis/credentials/oauthclient) for application type "Desktop App"
6. Download the JSON file of your client's OAuth keys
7. Rename the key file to `oauth.json` and place into the `local_auth/oauth_configs/gdrive/oauth.json`

To authenticate and save credentials:

```bash
python src/servers/gdrive/main.py auth
```

This will launch a browser-based authentication flow to obtain and save credentials.
