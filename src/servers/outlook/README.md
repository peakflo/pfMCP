# Outlook Server

guMCP server implementation for interacting with Microsoft Outlook.

### Prerequisites

- Python 3.11+
- A Microsoft Entra ID (formerly Azure AD) application registration
- OAuth 2.0 credentials with the following scopes:
  - https://graph.microsoft.com/Mail.ReadWrite
  - https://graph.microsoft.com/Mail.Send
  - offline_access

### Local Authentication

1. [Register a new application in Microsoft Entra ID](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app?tabs=certificate%2Cexpose-a-web-api)
2. Add the required Microsoft Graph API permissions (Mail.ReadWrite, Mail.Send)
3. Configure a redirect URI for your application (e.g., http://localhost:8080)
4. Get your application's client ID and client secret
5. Create an `oauth.json` file:

```
local_auth/oauth_configs/outlook/oauth.json
```

Create the following file with the relevant attributes for your app:

```json
{
  "client_id": "xxxxxxxxxxxxxxxxxxxxx",
  "client_secret": "xxxxxxxxxxxxxxxxxxxxx",
  "redirect_uri": "https://xxxxxxxxxxxxx"
}
```

6. To set up and verify authentication, run:

```bash
python src/servers/outlook/main.py auth
```

### Run

#### Local Development

```bash
python src/servers/local.py --server outlook --user-id local
```

### Available Tools

#### Read Emails

Fetches emails from your Outlook account with various filtering options.

```python
{
    "folder": "string",  # Folder to search in (default: "inbox")
    "count": "integer",  # Number of emails to retrieve (default: 10)
    "filter": "string",  # Filter query (e.g., "isRead eq false" for unread emails)
    "search": "string"   # Search query for email content
}
```

#### Send Email

Send an email using your Outlook account.

```python
{
    "to": "string",     # Recipient email addresses (comma-separated)
    "subject": "string", # Email subject
    "body": "string",    # Email body content
    "cc": "string",     # CC email addresses (comma-separated, optional)
    "bcc": "string"     # BCC email addresses (comma-separated, optional)
}
```

#### Move Email

Move an email to a different folder in your Outlook account.

```python
{
    "messageId": "string",  # The ID of the email to move
    "folderName": "string"  # Destination folder name (e.g., "inbox", "junkemail", "drafts")
}
```

#### Forward Email

Forward an existing email to one or more recipients.

```python
{
    "messageId": "string",    # The ID of the email to forward
    "receipients": ["string"], # List of recipient email addresses
    "comment": "string"       # Optional comment to add to the forwarded email (optional)
}
```

#### Categorize Email

Assign or update categories for an email in your Outlook account.

```python
{
    "messageId": "string",    # The ID of the email to categorize
    "categories": ["string"]  # List of category names to apply to the email
}
```

### Common Folders

The following are some common folder names that can be used:

- inbox
- junkemail
- drafts
- sentitems
- deleteditems

You can also use custom folder names that exist in your Outlook account.
