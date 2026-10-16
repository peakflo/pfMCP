# Zendesk Tickets

The Zendesk pfMCP server exposes six ticket tools and ticket-view resources.

| Tool | Purpose |
| --- | --- |
| `list_tickets` | List recent tickets, with `page_size` and `after_cursor` pagination. |
| `get_ticket` | Read a ticket by its numeric `ticket_id`. |
| `search_tickets` | Search tickets with Zendesk query syntax. The server adds `type:ticket`; `page` selects pages 1–10. |
| `create_ticket` | Create a ticket with a subject and initial comment. |
| `update_ticket` | Change ticket fields or add a comment. |
| `add_comment` | Add a public reply or internal note. |

`zendesk://view/{id}` resources list and read Zendesk ticket views and their tickets.

## Nango setup

Configure a Nango OAuth2 integration with provider config key `zendesk` and Zendesk `read` and `write` scopes. workflow-builder uses that key to create the connection. Set `ENVIRONMENT=nango`, `NANGO_SECRET_KEY`, and optionally `NANGO_HOST` for pfMCP. The connection ID is passed to pfMCP as the user ID. API calls use Nango's proxy to resolve the account subdomain and OAuth token.

## Local setup

Local and Gumloop authentication continue to use the existing credential and account-subdomain helpers. For local OAuth, create `local_auth/oauth_configs/zendesk/oauth.json` with `client_id`, `client_secret`, `redirect_uri`, and `custom_subdomain`, then run `python src/servers/zendesk/main.py auth`.

Zendesk Search returns at most 1,000 results per query. Use narrower queries for larger result sets. Search results can take a few minutes to index. A comment on `add_comment` defaults to public; use `public: false` for an internal note.
