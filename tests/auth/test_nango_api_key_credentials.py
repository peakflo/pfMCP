"""Offline tests: API key connections keep their key and gain connection fields.

The Telegram server reads ``api_id``/``api_hash`` beside the key, so the Nango
client now passes ``connection_config`` and ``metadata`` through for API key
connections. Existing API key services must still see the same ``apiKey``.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.servers.xero import main as _xero_main  # noqa: F401 - puts src/ on sys.path
from src.auth.clients.NangoAuthClient import NangoAuthClient
from src.auth.constants import AUTH_TYPE_API_KEY


def _client():
    NangoAuthClient._cache.clear()
    return NangoAuthClient(secret_key="s", host="https://nango.test")


def _answer(body):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = body
    return response


def _fetch(service_name, body):
    client = _client()
    with patch(
        "src.auth.clients.NangoAuthClient.requests.get", return_value=_answer(body)
    ):
        result = client.get_user_credentials(service_name, "conn-1")
    NangoAuthClient._cache.clear()
    return result


@pytest.mark.parametrize("service_name", ["tldv", "peakflo", "peakflo-api-key"])
def test_existing_api_key_services_still_get_api_key(service_name):
    result = _fetch(
        service_name, {"credentials": {"type": "API_KEY", "apiKey": "pk_123"}}
    )
    assert result["apiKey"] == "pk_123"
    assert result["type"] == "API_KEY"
    assert result["connection_config"] == {}
    assert result["metadata"] == {}


def test_api_key_connection_passes_connection_config_and_metadata():
    result = _fetch(
        "telegram",
        {
            "credentials": {"type": "API_KEY", "apiKey": "session"},
            "connection_config": {"api_id": "1", "api_hash": "h"},
            "metadata": {"label": "ops"},
        },
    )
    assert result == {
        "type": "API_KEY",
        "apiKey": "session",
        "connection_config": {"api_id": "1", "api_hash": "h"},
        "metadata": {"label": "ops"},
    }


def test_camel_case_connection_config_is_accepted():
    result = _fetch(
        "telegram",
        {
            "credentials": {"apiKey": "session"},
            "connectionConfig": {"api_id": "1"},
        },
    )
    assert result["connection_config"] == {"api_id": "1"}


def test_legacy_metadata_jwt_fallback_is_unchanged():
    # No apiKey: a connection migrated from UNAUTHENTICATED builds a JWT.
    result = _fetch(
        "peakflo",
        {
            "credentials": {},
            "metadata": {
                "tenantId": "t1",
                "privateKey": "private",
                "accessToken": "acc",
            },
        },
    )
    assert set(result) == {"access_token", "expires_at"}


def test_telegram_is_an_api_key_service():
    from src.auth.constants import SERVICE_NAME_MAP

    assert SERVICE_NAME_MAP["telegram"]["auth_type"] == AUTH_TYPE_API_KEY
