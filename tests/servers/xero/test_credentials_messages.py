"""Offline tests: clear errors when Xero credentials are incomplete."""

import asyncio
from unittest.mock import patch, MagicMock

import pytest

from src.servers.xero import main as xero_main


def _creds(value):
    client = MagicMock()
    client.get_user_credentials.return_value = value
    return patch.object(xero_main, "create_auth_client", return_value=client)


def test_no_organisation_gives_reconnect_message():
    creds = {"access_token": "t", "metadata": {}}
    resp = MagicMock(status_code=200)
    resp.json.return_value = []
    http = MagicMock()

    async def get(*a, **k):
        return resp

    http.__aenter__.return_value.get = get
    with _creds(creds), patch.object(xero_main.httpx, "AsyncClient", return_value=http):
        with pytest.raises(ValueError, match="No Xero organisation is connected"):
            asyncio.run(xero_main.get_xero_credentials("c1"))


def test_missing_token_gives_reconnect_message():
    creds = {"metadata": {"tenantId": "x"}}
    with _creds(creds):
        with pytest.raises(ValueError, match="sign-in is missing or expired"):
            asyncio.run(xero_main.get_xero_credentials("c1"))


def test_complete_credentials_pass():
    creds = {"access_token": "t", "metadata": {"tenantId": "x"}}
    with _creds(creds):
        assert asyncio.run(xero_main.get_xero_credentials("c1")) == ("t", "x")
