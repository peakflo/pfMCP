"""
Network-free unit tests for NetSuite auth-mode selection and the Peakflo
credential-sharing path (mirrors how Xero is exposed through Peakflo).
"""

import asyncio
from unittest import mock

import pytest
import requests

from src.servers.netsuite import main as ns


# --------------------------------------------------------------------------- #
# NetSuiteClient auth-mode selection
# --------------------------------------------------------------------------- #
def test_base_url_normalizes_account_id():
    client = ns.NetSuiteClient(
        account_id="1234567_SB1",
        consumer_key="ck",
        consumer_secret="cs",
        token_id="ti",
        token_secret="ts",
    )
    assert (
        client.base_url
        == "https://1234567-sb1.suitetalk.api.netsuite.com/services/rest"
    )


def test_tba_signs_request_with_realm():
    client = ns.NetSuiteClient(
        account_id="1234567_SB1",
        consumer_key="ck",
        consumer_secret="cs",
        token_id="ti",
        token_secret="ts",
    )
    # No bearer header in TBA mode.
    assert "Authorization" not in client._headers()

    prepared = requests.Request(
        "POST",
        f"{client.base_url}/query/v1/suiteql",
        json={"q": "SELECT 1"},
        auth=client._auth(),
    ).prepare()
    auth_header = prepared.headers["Authorization"]
    if isinstance(auth_header, bytes):
        auth_header = auth_header.decode()
    assert auth_header.startswith('OAuth realm="1234567_SB1"')
    assert "oauth_signature_method" in auth_header
    assert "HMAC-SHA256" in auth_header


def test_oauth2_bearer_mode():
    client = ns.NetSuiteClient(account_id="1234567", access_token="tok123")
    assert client._auth() is None
    assert client._headers()["Authorization"] == "Bearer tok123"


def test_incomplete_credentials_raise():
    client = ns.NetSuiteClient(account_id="1234567", consumer_key="only_one")
    with pytest.raises(ValueError):
        client._auth()


def test_account_id_required():
    with pytest.raises(ValueError):
        ns.NetSuiteClient(account_id="")


def test_suiteql_escapes_single_quotes():
    client = ns.NetSuiteClient(account_id="1234567", access_token="tok")
    captured = {}

    def fake_execute(query, limit=1000, offset=0):
        captured["query"] = query
        return {"items": []}

    client.execute_suiteql = fake_execute  # type: ignore[assignment]
    client.search_vendor_by_name("O'Brien")
    assert "O''Brien" in captured["query"]


# --------------------------------------------------------------------------- #
# Peakflo credential-broker resolver (shared-access path)
# --------------------------------------------------------------------------- #
def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _patch_broker(pf, payload):
    async def fake(tenant_id, source_system, purpose="workflow"):
        assert source_system == pf.SOURCE_SYSTEM_NETSUITE
        return payload

    return mock.patch.object(pf, "get_system_of_record_credentials", fake)


def test_netsuite_resolver_tba_shape():
    from servers.peakflo import main as pf

    payload = {
        "credentials": {
            "accountId": "1234567_SB1",
            "consumerKey": "ck",
            "consumerSecret": "cs",
            "tokenId": "ti",
            "tokenSecret": "ts",
        }
    }
    with _patch_broker(pf, payload):
        creds = _run(
            pf._build_netsuite_credential_resolver("tenantA", "execute_suiteql")()
        )
    # Resolved kwargs must construct a working TBA client.
    client = ns.NetSuiteClient(**creds)
    assert client.access_token is None
    assert client._auth().__class__.__name__ == "OAuth1"


def test_netsuite_resolver_oauth2_shape():
    from servers.peakflo import main as pf

    payload = {"providerAccountId": "999", "accessToken": "atok"}
    with _patch_broker(pf, payload):
        creds = _run(
            pf._build_netsuite_credential_resolver("tenantA", "create_record")()
        )
    client = ns.NetSuiteClient(**creds)
    assert client._auth() is None
    assert client._headers()["Authorization"] == "Bearer atok"


def test_netsuite_resolver_missing_credentials_raise():
    from servers.peakflo import main as pf

    with _patch_broker(pf, {"credentials": {"accountId": "1"}}):
        with pytest.raises(ValueError):
            _run(pf._build_netsuite_credential_resolver("t", "x")())


def test_source_system_registry_and_matching():
    from servers.peakflo import main as pf

    assert set(pf.SOURCE_SYSTEM_INTEGRATIONS) == {"xero", "netsuite"}
    assert pf._match_source_system_tool("netsuite__execute_suiteql")[0] == "netsuite"
    assert pf._match_source_system_tool("xero__list_accounts")[0] == "xero"
    assert pf._match_source_system_tool("get_tenant")[0] is None
