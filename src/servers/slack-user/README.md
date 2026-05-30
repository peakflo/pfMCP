# Slack User Token pfMCP Server

This MCP server enables posting Slack messages **as the authenticated user** (their real display name, avatar, no bot badge) using user-level OAuth tokens (`xoxp-`).

## How It Differs from the Bot-Based Slack Server

| Feature | `slack` (Bot) | `slack-user` (User Token) |
|---|---|---|
| Token type | `xoxb-` (bot) | `xoxp-` (user) |
| Display name | Bot name | Your real name |
| Bot badge | Yes | No |
| Avatar | Bot icon | Your avatar |
| Transparency | N/A | "_Sent from 20x_" footer |

## Key Behavior

- **Messages appear from the user**: When `send_message` or `create_canvas` is called, the message is posted under the authenticated user's identity.
- **Transparency footer**: All outgoing messages have `_Sent from 20x_` appended to distinguish AI-generated messages from manually typed ones.
- **User-level OAuth scopes**: The Nango integration (`slack-user`) requests user-level scopes during the OAuth flow, granting a `xoxp-` token instead of a `xoxb-` bot token.

## Required OAuth Scopes (User Scopes)

- `chat:write` - Post messages as the user
- `channels:read` - List channels
- `channels:history` - Read channel history
- `groups:read` - List private channels
- `groups:write` - Manage private channels
- `groups:history` - Read private channel history
- `pins:read` / `pins:write` - Pin/unpin messages
- `reactions:write` - Add reactions
- `files:read` / `files:write` - File operations
- `im:read` - Read direct messages
- `channels:manage` - Channel management
- `users:read` - Look up user information

## Nango Integration

The Nango integration ID is `slack-user`. It must be configured in Nango's dashboard with:
- OAuth template: `slack` (Slack's standard OAuth v2)
- **User scopes** (not bot scopes): The scopes listed above should be configured as `user_scopes` in the Nango Slack integration, which causes the OAuth flow to request a user token (`xoxp-`) instead of a bot token (`xoxb-`).

## Tools

All tools from the standard Slack server are available. The key difference is that `send_message` and `create_canvas` append the transparency footer and post as the user.

## Usage

```bash
# Local authentication
python src/servers/slack-user/main.py auth

# Remote (via pfMCP HTTP server)
# POST to /slack-user/{user_id}:{api_key}
```
