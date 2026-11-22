# Telegram (Bot API)

This server acts as a Telegram **bot** through the
[Telegram Bot API](https://core.telegram.org/bots/api). Each tool call is one
HTTPS request to `https://api.telegram.org/bot<token>/<method>` made with
`httpx`. It does not sign in as a person and has no access to anyone's chat
history.

## Setup

1. In Telegram, open [@BotFather](https://t.me/BotFather) and send `/newbot`.
   Pick a display name and a username that ends in `bot`.
2. BotFather replies with a token such as `123456789:AAE...`. Treat it as a
   password: it gives full control of the bot.
3. Connect Telegram in Peakflo and paste the token. The connection is a Nango
   API key connection on the built-in `telegram` provider; the token is
   stored as `credentials.apiKey`. No other field is needed.
4. Add the bot to the groups or channels it should post in. For a direct chat,
   the person must open the bot and press **Start** (`/start`) first; a bot
   cannot start a conversation.

To regenerate a leaked token use `/revoke` in BotFather, then reconnect.

### What the bot can see

- The bot only sees chats it was added to, and private chats where the user
  pressed `/start`.
- In groups, **privacy mode** is on by default: the bot only receives
  commands, replies to its own messages and mentions. To receive every message,
  turn privacy mode off in BotFather (`/setprivacy` -> Disable, then re-add the
  bot to the group) or make the bot a group admin.
- Actions such as pinning, deleting other people's messages or creating invite
  links need the matching admin right in that chat.
- Bots have no access to message history. Messages sent before the bot joined,
  or while nothing was receiving updates, cannot be read later.

### Local use

```bash
python src/servers/telegram/main.py auth
```

prompts for the token and saves it as `apiKey` with the local auth client.

## Tools

| Tool | Bot API method | Notes |
| --- | --- | --- |
| `get_bot_info` | `getMe` | Bot ID, username, capabilities |
| `get_chat` | `getChat` | Chat details |
| `get_chat_member_count` | `getChatMemberCount` | |
| `get_chat_administrators` | `getChatAdministrators` | Groups and channels |
| `send_message` | `sendMessage` | `parse_mode` HTML / MarkdownV2, `reply_to_message_id`, `disable_notification`, `message_thread_id`, `disable_link_preview`, inline URL `buttons` |
| `send_document` | `sendDocument` | One of `file_url`, `file_id`, `content_base64` + `filename`; `caption` |
| `send_photo` | `sendPhoto` | Same sources as `send_document` |
| `edit_message_text` | `editMessageText` | Messages the bot sent |
| `delete_message` | `deleteMessage` | Own messages; others' only as admin; within 48 hours |
| `forward_message` | `forwardMessage` | Keeps the "Forwarded from" header |
| `copy_message` | `copyMessage` | No forward header; optional new caption |
| `pin_chat_message` | `pinChatMessage` | |
| `unpin_chat_message` | `unpinChatMessage` | Without `message_id`: the latest pin |
| `get_file` | `getFile` | File metadata |
| `download_file` | `getFile` + file download | Returns `content_base64`, `mime_type`, `file_name`, `file_size` |
| `create_chat_invite_link` | `createChatInviteLink` | `name`, `expire_date` (Unix time), `member_limit`, `creates_join_request` |

`chat_id` accepts a numeric ID (users are positive, groups and channels are
negative, for example `-1001234567890`) or a public `@channelusername`.

`buttons` is a list of rows; each row is a list of `{"text": ..., "url": ...}`.

### Not exposed

`getUpdates` is not a tool on purpose. Telegram delivers each update once:
polling from here would take updates away from the webhook that inbound
messages will use, and Telegram refuses `getUpdates` while a webhook is set.

## Limits

- Downloads: at most **20 MB** per file (Bot API limit).
- Uploads: at most **50 MB** for documents and **10 MB** for photos. By URL,
  Telegram fetches the file itself: documents only as PDF, ZIP or GIF up to
  20 MB, photos up to 5 MB. Use `content_base64` for other files.
- Text up to 4096 characters, captions up to 1024.
- Sending: Telegram allows about 1 message per second per chat, 20 per minute
  per group and 30 per second overall. The server paces sends per chat
  (1 per second, 20 per minute for groups and channels) and fails fast with
  `telegram_rate_limited` if a call would wait longer than 5 seconds. A
  Telegram `429` with `retry_after` of 5 seconds or less is retried once.

## Errors

Errors start with a stable code in brackets:

| Code | When |
| --- | --- |
| `credentials_missing` | No token is stored for the connection |
| `setup_incomplete` | The stored value is not shaped like a bot token |
| `credentials_revoked` | Telegram answered `401 Unauthorized` (token revoked or regenerated) |
| `telegram_forbidden` | `403`: the user blocked the bot or never pressed /start, or the bot was removed from the chat or lacks a right |
| `telegram_rate_limited` | `429` (message includes `retry_after`), or the client-side pacing limit |
| `telegram_bad_request` | `400`: for example chat not found, message not found, bad formatting. Includes `migrate_to_chat_id` when a group became a supergroup |
| `telegram_unreachable` | Network error or timeout |
| `telegram_error` | Any other Bot API error |

The bot token never appears in logs, errors or tool results: it is masked
in each of them, including httpx request logs.

## Roadmap

Inbound messages (a trigger on new messages, files and button presses) are a
later phase. They will arrive by webhook (`setWebhook`) handled in
workflow-builder, not by polling here.
