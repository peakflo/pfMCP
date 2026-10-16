# Zendesk Tickets

This pfMCP server exposes four tools for Zendesk Support tickets:

| Tool | Purpose |
| --- | --- |
| `list_tickets` | List recent tickets, with `page_size` and `after_cursor` pagination. |
| `get_ticket` | Read a ticket by its numeric `ticket_id`. |
| `search_tickets` | Search tickets with Zendesk query syntax. The server adds `type:ticket`. |
| `update_ticket` | Change ticket fields or add a public reply or internal note. |

## Setup

Configure a Nango OAuth2 integration with the provider config key `zendesk` and Zendesk read and write scopes. The workflow-builder connector uses that same key. Provide `NANGO_SECRET_KEY` and optionally `NANGO_HOST` to pfMCP. Each workflow-builder connection ID is passed to pfMCP as the user ID. API requests go through Nango's Zendesk proxy, which resolves the account URL and refreshes the OAuth token.

Search is limited to Zendesk's first 1,000 results (pages 1–10 with up to 100 results per page). Use narrower queries for larger result sets. Ticket updates use Zendesk's `PUT /api/v2/tickets/{id}.json` endpoint. A `comment` defaults to a public reply; set `public: false` for an internal note.
