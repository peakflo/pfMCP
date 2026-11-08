"""Offline tests: every credential error says exactly which case it is.

No network. The Nango HTTP layer is replaced with fixed answers.
"""

import asyncio
import json
from unittest.mock import patch, MagicMock

import pytest

from src.auth import credential_errors as ce
from src.auth.clients.NangoAuthClient import NangoAuthClient
from src.utils.google import util as google_util
from src.servers.xero import main as xero_main

CONNECTION_ID = "a919a142-3c74-430f-8e0c-b13b0567d92b"


def _answer(status, body):
    r = MagicMock()
    r.status_code = status
    r.text = json.dumps(body) if not isinstance(body, str) else body
    r.json.return_value = body if not isinstance(body, str) else {}
    return r


def _client():
    return NangoAuthClient(secret_key="s", host="https://nango.test")


def _fetch(client, answer):
    with patch("src.auth.clients.NangoAuthClient.requests.get", return_value=answer):
        return client.get_user_credentials("gmail", CONNECTION_ID)


@pytest.mark.parametrize(
    "status,body,code",
    [
        (404, {"error": "not found"}, ce.MISSING),
        (
            400,
            {"error": {"code": "invalid_credentials", "message": "x"}},
            ce.EXPIRED,
        ),
        (
            400,
            {
                "error": {
                    "message": "The refresh limit has been reached for this connection."
                }
            },
            ce.EXPIRED,
        ),
        (400, {"error": "invalid_grant: Token has been expired"}, ce.EXPIRED),
        (400, {"error": "invalid_grant: Token has been revoked"}, ce.REVOKED),
        (401, {"error": "unauthorized"}, ce.EXPIRED),
    ],
)
def test_nango_failure_is_classified(status, body, code):
    ce.clear_failure()
    ce.CredentialError  # keep import used
    ce._last_failure.set(None)
    NangoAuthClient._cache.clear()
    assert _fetch(_client(), _answer(status, body)) is None
    assert ce.last_failure() == ("gmail", code)


def test_empty_credentials_are_missing():
    NangoAuthClient._cache.clear()
    ok = _answer(200, {"credentials": {}, "metadata": {}})
    result = _fetch(_client(), ok)
    assert not result.get("access_token")
    assert ce.last_failure() == ("gmail", ce.MISSING)


@pytest.mark.parametrize(
    "code,phrase",
    [
        (
            ce.MISSING,
            "credentials are missing for this connection. Connect Gmail again.",
        ),
        (
            ce.EXPIRED,
            "credentials have expired and could not be refreshed. Reconnect Gmail.",
        ),
        (ce.REVOKED, "access was revoked. Reconnect Gmail."),
    ],
)
def test_message_and_code(code, phrase):
    error = ce.CredentialError("gmail", code)
    assert str(error).startswith(f"[{code}] Gmail ")
    assert phrase in str(error)
    assert CONNECTION_ID not in str(error)


def test_google_helper_raises_exact_error_without_connection_id():
    NangoAuthClient._cache.clear()
    auth = MagicMock()

    def fail(service, user):
        ce.record_failure(service, ce.EXPIRED)
        return None

    auth.get_user_credentials.side_effect = fail
    with patch.object(google_util, "create_auth_client", return_value=auth):
        with pytest.raises(ValueError) as caught:
            asyncio.run(google_util.get_credentials(CONNECTION_ID, "gmail"))
    assert getattr(caught.value, "code") == ce.EXPIRED
    assert CONNECTION_ID not in str(caught.value)
    assert "expired and could not be refreshed" in str(caught.value)


def test_old_vague_message_is_rewritten_by_the_dispatcher():
    ce.record_failure("gmail", ce.EXPIRED)
    text = ce.translate_exception(
        ValueError(f"Credentials not found for user {CONNECTION_ID}")
    )
    assert text.startswith("[credentials_expired]")
    assert CONNECTION_ID not in text
    # Unrelated errors are not touched.
    assert ce.translate_exception(ValueError("Rate limit hit")) == "Rate limit hit"
    ce._last_failure.set(None)


def _creds(value):
    client = MagicMock()
    client.get_user_credentials.return_value = value
    return patch.object(xero_main, "create_auth_client", return_value=client)


def test_xero_no_credentials_is_missing():
    ce._last_failure.set(("xero", ce.MISSING))
    with _creds(None):
        with pytest.raises(ValueError) as caught:
            asyncio.run(xero_main.get_xero_credentials(CONNECTION_ID))
    assert caught.value.code == ce.MISSING


def test_xero_token_but_no_organisation_is_setup_incomplete():
    resp = MagicMock(status_code=200)
    resp.json.return_value = []
    http = MagicMock()

    async def get(*a, **k):
        return resp

    http.__aenter__.return_value.get = get
    with _creds({"access_token": "t", "metadata": {}}), patch.object(
        xero_main.httpx, "AsyncClient", return_value=http
    ):
        with pytest.raises(ValueError) as caught:
            asyncio.run(xero_main.get_xero_credentials(CONNECTION_ID))
    assert caught.value.code == ce.SETUP_INCOMPLETE
    assert "No Xero organisation is connected" in str(caught.value)


def test_xero_provider_401_is_expired():
    resp = MagicMock(status_code=401)
    http = MagicMock()

    async def get(*a, **k):
        return resp

    http.__aenter__.return_value.get = get
    with _creds({"access_token": "old", "metadata": {}}), patch.object(
        xero_main.httpx, "AsyncClient", return_value=http
    ):
        with pytest.raises(ValueError) as caught:
            asyncio.run(xero_main.get_xero_credentials(CONNECTION_ID))
    assert caught.value.code == ce.EXPIRED


def test_xero_missing_token_never_calls_xero():
    with _creds({"metadata": {"tenantId": "x"}}):
        with pytest.raises(ValueError) as caught:
            asyncio.run(xero_main.get_xero_credentials(CONNECTION_ID))
    assert caught.value.code == ce.MISSING


def test_xero_complete_credentials_pass():
    with _creds({"access_token": "t", "metadata": {"tenantId": "x"}}):
        assert asyncio.run(xero_main.get_xero_credentials(CONNECTION_ID)) == ("t", "x")
