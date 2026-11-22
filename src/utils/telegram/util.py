"""Credential handling for the Telegram (user account) MCP server.

A Telegram user-account connection needs three values:

* ``api_id`` / ``api_hash`` - the Telegram application credentials from
  https://my.telegram.org/apps. They identify the *app*, not the user, so a
  deployment may provide them once through the ``TELEGRAM_API_ID`` and
  ``TELEGRAM_API_HASH`` environment variables.
* ``session_string`` - a Telethon ``StringSession`` for the signed-in user.
  This is the secret that grants full access to the user's account and is
  always stored per connection, never in the environment.

In Nango the connection is an API key connection: ``apiKey`` holds the session
string, while ``api_id`` and ``api_hash`` may live in ``connection_config`` or
``metadata``. Local credentials (``python main.py auth``) store the three
fields directly.
"""

import asyncio
import getpass
import logging
import os
from typing import Any, Dict, Optional

from src.auth.credential_errors import (
    MISSING,
    SETUP_INCOMPLETE,
    CredentialError,
    credential_error_from_last,
)
from src.auth.factory import create_auth_client

logger = logging.getLogger(__name__)

SERVICE_LABEL = "Telegram"

_API_ID_KEYS = ("api_id", "apiId", "TELEGRAM_API_ID")
_API_HASH_KEYS = ("api_hash", "apiHash", "TELEGRAM_API_HASH")
_SESSION_KEYS = (
    "session_string",
    "sessionString",
    "TELEGRAM_SESSION_STRING",
    "apiKey",
    "api_key",
)


def _first(sources, keys) -> Optional[str]:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return str(value).strip()
    return None


def parse_credentials(credential_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalise a stored credential payload into ``api_id``, ``api_hash`` and
    ``session_string``.

    Raises:
        CredentialError: when the session string is missing
            (``credentials_missing``) or the app credentials are missing or
            malformed (``setup_incomplete``).
    """
    if not credential_data:
        raise CredentialError("telegram", MISSING)

    connection_config = credential_data.get("connection_config") or (
        credential_data.get("connectionConfig") or {}
    )
    metadata = credential_data.get("metadata") or {}
    sources = (credential_data, connection_config, metadata)

    session_string = _first(sources[:1], _SESSION_KEYS)
    if not session_string:
        raise CredentialError("telegram", MISSING)

    api_id = _first(sources, _API_ID_KEYS) or os.environ.get("TELEGRAM_API_ID")
    api_hash = _first(sources, _API_HASH_KEYS) or os.environ.get("TELEGRAM_API_HASH")
    missing = [
        name
        for name, value in (("api_id", api_id), ("api_hash", api_hash))
        if not value
    ]
    if missing:
        raise CredentialError(
            "telegram",
            SETUP_INCOMPLETE,
            f"{SERVICE_LABEL} setup is incomplete: missing {', '.join(missing)}. "
            "Reconnect Telegram with the API ID and API hash from my.telegram.org.",
        )
    try:
        api_id_int = int(str(api_id).strip())
    except ValueError:
        raise CredentialError(
            "telegram",
            SETUP_INCOMPLETE,
            f"{SERVICE_LABEL} API ID must be a number. Reconnect Telegram.",
        )

    return {
        "api_id": api_id_int,
        "api_hash": str(api_hash).strip(),
        "session_string": session_string,
    }


async def get_credentials(
    user_id: str, service_name: str, api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Return ``{"api_id", "api_hash", "session_string"}`` for a connection."""
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
    return parse_credentials(credential_data)


def _generate_session_string(api_id: int, api_hash: str) -> str:
    """Run Telethon's interactive phone login once and return a session string.

    Only used by the local ``auth`` command; the server never logs in
    interactively.
    """
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    async def _login() -> str:
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.start()
        try:
            return client.session.save()
        finally:
            await client.disconnect()

    return asyncio.run(_login())


def authenticate_and_save_credentials(
    user_id: str, service_name: str, scopes=None
) -> Dict[str, Any]:
    """Prompt for Telegram credentials and save them with the auth client.

    Leave the session string empty to sign in with a phone number and login
    code; the generated session string is then saved.
    """
    logger.info(f"Starting Telegram authentication for user {user_id}...")
    api_id = input("Enter your Telegram API ID (from my.telegram.org): ").strip()
    api_hash = getpass.getpass("Enter your Telegram API hash: ").strip()
    if not api_id or not api_hash:
        raise ValueError("Telegram API ID and API hash are required")
    try:
        api_id_int = int(api_id)
    except ValueError:
        raise ValueError("Telegram API ID must be a number")

    session_string = getpass.getpass(
        "Enter a Telethon session string (leave empty to sign in now): "
    ).strip()
    if not session_string:
        session_string = _generate_session_string(api_id_int, api_hash)

    credentials = {
        "api_id": api_id_int,
        "api_hash": api_hash,
        "session_string": session_string,
    }
    auth_client = create_auth_client()
    auth_client.save_user_credentials(service_name, user_id, credentials)
    logger.info(f"Saved Telegram credentials for user {user_id}")
    return credentials
