# Gmail Server

pfMCP server implementation for interacting with Gmail.

### Prerequisites

- Python 3.11+
- A Google Cloud Project with Gmail API enabled
- OAuth 2.0 credentials with the following scopes:
  - https://www.googleapis.com/auth/gmail.modify

### Local Authentication

1. [Create a new Google Cloud project](https://console.cloud.google.com/projectcreate)
2. [Enable the Gmail API](https://console.cloud.google.com/workspace-api/products)
3. [Configure an OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent) ("internal" is fine for testing)
4. Add OAuth scope `https://www.googleapis.com/auth/gmail.modify`
5. [Create an OAuth Client ID](https://console.cloud.google.com/apis/credentials/oauthclient) for application type "Desktop App"
6. Download the JSON file of your client's OAuth keys
7. Rename the key file to `oauth.json` and place into the `local_auth/oauth_configs/gmail/oauth.json`

To authenticate and save credentials:

```bash
python src/servers/gmail/main.py auth
```

This will launch a browser-based authentication flow to obtain and save credentials.

### Tools

#### read_emails
Search and read emails in Gmail with full text body and attachment metadata.

Parameters:
- `query` (string, required) — Gmail search query (e.g. `from:someone@example.com`, `subject:important`)
- `max_results` (integer) — Maximum number of emails to return (default: 10)
- `include_body` (boolean) — Include email body text in results (default: true)
- `include_attachments_info` (boolean) — Include attachment metadata in results (default: true)

Attachment metadata includes `attachmentId` which can be used with `get_attachment` to download files.

#### get_attachment
Download an email attachment and get a temporary download URL.

Parameters:
- `email_id` (string, required) — ID of the email containing the attachment
- `attachment_id` (string, required) — ID of the attachment (from `read_emails` results)

Returns a signed URL (expires in 1 hour) to download the file.

**Storage configuration:**
- For local development: set `STORAGE_PROVIDER=local` (files saved to `LOCAL_STORAGE_DIR`, defaults to `/tmp/pfmcp-attachments`)
- For production: set `STORAGE_PROVIDER=gcs` (default) and `GCS_BUCKET_NAME`

#### send_email
Send an email through Gmail with optional attachments.

Parameters:
- `to` (string, required) — Recipient email address
- `subject` (string, required) — Email subject
- `body` (string, required) — Email body (plain text)
- `cc` (string) — CC recipients (comma separated)
- `bcc` (string) — BCC recipients (comma separated)
- `attachments` (array) — Attachments with `filename`, `content` (base64), and `mimeType`

#### forward_email
Forward an email to recipients, preserving original content and attachments.

Parameters:
- `email_id` (string, required) — ID of the email to forward
- `to` (string, required) — Recipient email address(es) (comma separated)
- `cc` (string) — CC recipients (comma separated)
- `bcc` (string) — BCC recipients (comma separated)
- `additional_message` (string) — Message to add before forwarded content
- `include_attachments` (boolean) — Include original attachments (default: true)

#### update_email
Update email labels (mark as read/unread, move to folders).

Parameters:
- `email_id` (string, required) — Email ID to modify
- `add_labels` (array of strings) — Labels to add (e.g. `INBOX`, `STARRED`, `IMPORTANT`)
- `remove_labels` (array of strings) — Labels to remove (e.g. `UNREAD`)
