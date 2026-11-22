"""Credential handling for the Telegram Bot API MCP server.

A connection holds one secret: the bot token that @BotFather issues
(``123456789:AA...``). In Nango it is an API key connection on the built-in
``telegram`` provider, so the token is ``credentials.apiKey``. Local
credentials (``python main.py auth``) store the same ``apiKey`` field.

The token grants full control of the bot. It must never reach a log line, an
error message or a tool result; ``mask_token`` removes it from text.
"""

import getpass
import logging
import re
from typing import Any, Dict, Optional

from src.auth.credential_errors import (
    MISSING,
    SETUP_INCOMPLETE,
    CredentialError,
    credential_error_from_last,
)
from src.auth.factory import create_auth_client

logger = logging.getLogger(__name__)

SERVICE_NAME = "telegram"

BOT_TOKEN_PATTERN = re.compile(r"^[0-9]+:[a-zA-Z0-9_-]+$")
# Anything that looks like a bot token, with or without the "bot" URL prefix.
_TOKEN_IN_TEXT = re.compile(r"(bot)?\d{5,}:[A-Za-z0-9_-]{20,}")
MASK = "<bot-token>"

_TOKEN_KEYS = ("apiKey", "api_key", "API_KEY", "bot_token", "token")


def mask_token(text: Any, token: Optional[str] = None) -> str:
    """Return ``text`` with the bot token (and anything shaped like one) masked."""
    text = "" if text is None else str(text)
    if token:
        text = text.replace(token, MASK)
    return _TOKEN_IN_TEXT.sub(MASK, text)


class TokenMaskingFilter(logging.Filter):
    """Masks bot tokens in log records (httpx logs every request URL)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed record, leave it alone
            return True
        masked = mask_token(message)
        if masked != message:
            record.msg = masked
            record.args = ()
        return True


def install_log_masking() -> None:
    """Attach the masking filter to the HTTP client loggers once."""
    for name in ("httpx", "httpcore"):
        target = logging.getLogger(name)
        if not any(isinstance(f, TokenMaskingFilter) for f in target.filters):
            target.addFilter(TokenMaskingFilter())


def parse_bot_token(credential_data: Optional[Dict[str, Any]]) -> str:
    """Return the bot token from a stored credential payload.

    Raises:
        CredentialError: ``credentials_missing`` when there is no token,
            ``setup_incomplete`` when the value is not shaped like a bot token.
    """
    if not credential_data:
        raise CredentialError(SERVICE_NAME, MISSING)
    token = None
    for key in _TOKEN_KEYS:
        value = credential_data.get(key)
        if isinstance(value, str) and value.strip():
            token = value.strip()
            break
    if not token:
        raise CredentialError(SERVICE_NAME, MISSING)
    if not BOT_TOKEN_PATTERN.match(token):
        raise CredentialError(
            SERVICE_NAME,
            SETUP_INCOMPLETE,
            "Telegram bot token is not valid. Reconnect Telegram with the token "
            "from @BotFather (it looks like 123456789:AA...).",
        )
    return token


async def get_credentials(
    user_id: str, service_name: str, api_key: Optional[str] = None
) -> str:
    """Return the bot token for a connection."""
    auth_client = create_auth_client(api_key=api_key)
    if hasattr(auth_client, "async_get_user_credentials"):
        credential_data = await auth_client.async_get_user_credentials(
            service_name, user_id
        )
    else:
        credential_data = auth_client.get_user_credentials(service_name, user_id)
    if not credential_data:
        # Nango records why the lookup failed (missing, expired, revoked).
        raise credential_error_from_last(service_name)
    return parse_bot_token(credential_data)


def authenticate_and_save_credentials(
    user_id: str, service_name: str, scopes=None
) -> Dict[str, Any]:
    """Prompt for a bot token and save it with the auth client (local use)."""
    token = getpass.getpass("Enter your Telegram bot token (from @BotFather): ")
    token = token.strip()
    if not BOT_TOKEN_PATTERN.match(token):
        raise ValueError("That does not look like a Telegram bot token")
    credentials = {"apiKey": token}
    create_auth_client().save_user_credentials(service_name, user_id, credentials)
    logger.info(f"Saved Telegram bot credentials for user {user_id}")
    return credentials
