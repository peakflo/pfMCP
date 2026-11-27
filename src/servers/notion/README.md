# Notion pfMCP Server

pfMCP server implementation for interacting with Notion using OAuth authentication.

---

### 📦 Prerequisites

- Python 3.11+
- A Notion integration created at [Notion Developer Portal](https://www.notion.com/my-integrations). For comment tools (`comment_on_page`, `comment_on_block`), enable **insert comment** capability in your [integration settings](https://www.notion.so/profile/integrations).
- A local OAuth config file with your Notion `client_id`, `client_secret`, and `redirect_uri`

Create a file named `oauth.json`:

```json
{
  "client_id": "your-client-id",
  "client_secret": "your-client-secret",
  "redirect_uri": "http://localhost:8080"
}
```

---

### 🔐 Authentication

Before running the server, you need to authenticate and store your OAuth token:

```bash
python main.py auth
```

---

### 🛠️ Supported Tools

This server exposes the following tools for interacting with Notion:

- `list_all_users` – List all users
- `search_pages` – Search all pages
- `list_databases` – List all databases
- `query_database` – Query a Notion database (optional `filter`, `sorts`, `page_size`, `start_cursor`)
- `get_page` – Retrieve a page by ID or URL
- `create_page` – Create a new page in a database (optional `children` blocks for the page body)
- `update_page` – Update a page's properties (page ID or URL)
- `append_blocks` – Append content blocks to a page or block
- `get_block_children` – List content blocks of a page or block
- `comment_on_page` – Add a top-level comment on a page (page ID or URL + comment text)
- `comment_on_block` – Add a comment on a specific block (block ID + comment text)

---

### ▶️ Run

#### Local Development

You can launch the server for local development using:

```bash
./start_remote_sse_server.sh
```

This will start the pfMCP server and make it available for integration and testing.

If you have a local client for testing, you can run it like:

```bash
python RemoteMCPTestClient.py --endpoint http://localhost:8000/notion/local
```

Adjust the endpoint path as needed based on your deployment setup.

---

### 📚 Resources

- [Notion API Documentation](https://developers.notion.com)
- [Official Notion Python Client](https://github.com/ramnes/notion-sdk-py)
