# Telegram

The Telegram server acts as a Telegram **user account** through
[Telethon](https://docs.telethon.dev/) (MTProto), not through the Bot API. It
reads and sends messages as the connected person. Each tool call opens a
Telethon client from a stored session string, runs one operation and
disconnects. The server never asks for a phone number or login code.

The tool set is adapted from
[chigwell/telegram-mcp](https://github.com/chigwell/telegram-mcp)
(Apache License 2.0). This server is a rewrite for pfMCP and keeps a focused
subset of that project's tools.

## Credentials

A connection needs three values:

| Field | Secret | Where it is read from |
| --- | --- | --- |
| `session_string` | Yes. It grants full access to the account | Nango `credentials.apiKey` |
| `api_id` | No (app credential, a number) | Nango `connection_config.api_id`, then `metadata.api_id`, then env `TELEGRAM_API_ID` |
| `api_hash` | Low (app credential) | Nango `connection_config.api_hash`, then `metadata.api_hash`, then env `TELEGRAM_API_HASH` |

`apiId`/`apiHash` (camelCase) are accepted as well. `api_id` and `api_hash`
come from <https://my.telegram.org/apps> and identify the application, so a
deployment can set them once with `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`.
Generate the session string with the same `api_id` and `api_hash` that the
server uses.

### Nango

- Provider config key: `telegram`
- Auth mode: `API_KEY`. Store the Telethon `StringSession` string as `apiKey`.
- Put `api_id` and `api_hash` in the connection's `connection_config` (or
  metadata) unless the deployment sets the environment variables.

### Making a session string

Run this once on a trusted machine. Telegram sends a login code to the
account (and asks for the 2FA password if one is set):

```python
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = 123456          # from my.telegram.org
API_HASH = "your_hash"   # from my.telegram.org

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print(client.session.save())
```

Treat the printed string like a password. Ending the session in Telegram
(Settings > Devices) revokes it; tools then fail with `credentials_revoked`.

### Local development

```bash
python src/servers/telegram/main.py auth
```

This prompts for the API ID, API hash and an optional session string. Leave
the session string empty to sign in with a phone number and login code; the
generated session is saved to the local credential store.

## Tools

Chat arguments (`chat_id`, `from_chat_id`, `to_chat_id`) accept a numeric ID
from `list_chats` (for example `-1001234567890`), a `@username`, a `t.me`
link, a phone number, or `me` for Saved Messages.

| Tool | Purpose |
| --- | --- |
| `get_me` | Profile of the connected account |
| `list_chats` | Dialogs, newest first, with unread counts and last message; filter by type, unread, archived |
| `get_chat` | Details of a chat, group, channel or user, including description and member count |
| `get_messages` | Messages from a chat, newest first; pass `next_offset_id` back as `offset_id` for older ones |
| `search_messages` | Text search in one chat (optionally from one user) or across all chats |
| `send_message` | Send text (Markdown, HTML or plain), optionally as a reply or silently |
| `edit_message` | Edit a message the account sent |
| `delete_messages` | Delete up to 100 messages, for everyone by default |
| `forward_messages` | Forward up to 100 messages to another chat |
| `mark_as_read` | Mark a chat as read, optionally up to a message ID |
| `list_contacts` | The account's contacts |
| `get_user` | A user's profile by ID, `@username` or phone |
| `resolve_username` | The user, group or channel that owns a username |
| `get_participants` | Members of a group or channel; filter admins or bots, search by name |

Results are JSON. Telegram rate limits (`FLOOD_WAIT`) are returned as errors
with the wait time; the server does not wait longer than 5 seconds. Each call
is limited to `TELEGRAM_TOOL_TIMEOUT_SECONDS` (default 60).

A session string starts with an empty entity cache. The first lookup of a
numeric ID loads up to 500 dialogs to find it; prefer `@username` for chats
outside the recent list.

Using a user account through the API is subject to Telegram's terms of
service. Sending many messages to people who did not start a conversation can
get the account limited.
