from types import SimpleNamespace

import pytest
from mcp.types import CallToolRequest, TextContent

from src.servers.peakflo import main as peakflo_main


@pytest.mark.asyncio
async def test_exposes_xero_tools_for_file_tenant_with_brokered_xero_connection(
    monkeypatch,
):
    async def resolve_tenant(_token):
        return {"tenantId": "0demoXeroApSG", "sourceSystem": "file"}

    async def resolve_credentials(**kwargs):
        assert kwargs["tenant_id"] == "0demoXeroApSG"
        assert kwargs["source_system"] == "xero"
        assert kwargs["purpose"] == "pfmcp:tool-discovery"
        return {
            "accessToken": "xero-access-token",
            "providerTenantId": "xero-tenant-id",
        }

    monkeypatch.setattr(peakflo_main, "_resolve_peakflo_tenant_context", resolve_tenant)
    monkeypatch.setattr(
        peakflo_main, "get_system_of_record_credentials", resolve_credentials
    )

    assert await peakflo_main._should_expose_xero_tools("peakflo-token") is True


@pytest.mark.asyncio
async def test_does_not_expose_xero_tools_when_broker_cannot_resolve(monkeypatch):
    async def resolve_tenant(_token):
        return {"tenantId": "fileTenant", "sourceSystem": "file"}

    async def resolve_credentials(**_kwargs):
        raise ValueError("xero is not connected for tenant")

    monkeypatch.setattr(peakflo_main, "_resolve_peakflo_tenant_context", resolve_tenant)
    monkeypatch.setattr(
        peakflo_main, "get_system_of_record_credentials", resolve_credentials
    )

    assert await peakflo_main._should_expose_xero_tools("peakflo-token") is False


@pytest.mark.asyncio
async def test_calls_xero_tool_for_file_tenant_with_brokered_credentials(monkeypatch):
    async def resolve_tenant(_token):
        return {"tenantId": "0demoXeroApSG", "sourceSystem": "file"}

    async def resolve_credentials(**kwargs):
        assert kwargs["tenant_id"] == "0demoXeroApSG"
        assert kwargs["source_system"] == "xero"
        assert kwargs["purpose"] == "pfmcp:list_accounts"
        return {
            "accessToken": "xero-access-token",
            "providerTenantId": "xero-tenant-id",
            "credentials": {},
        }

    class FakeXeroServer:
        def __init__(self):
            async def call_handler(request):
                assert isinstance(request, CallToolRequest)
                assert request.params.name == "list_accounts"
                assert request.params.arguments == {"status": "ACTIVE"}
                return SimpleNamespace(
                    root=SimpleNamespace(
                        content=[TextContent(type="text", text="xero result")]
                    )
                )

            self.request_handlers = {CallToolRequest: call_handler}

    def create_xero_server(user_id, api_key=None, credential_resolver=None):
        assert user_id == "user-1"
        assert api_key == "api-key-1"
        assert credential_resolver is not None
        return FakeXeroServer()

    monkeypatch.setattr(peakflo_main, "_resolve_peakflo_tenant_context", resolve_tenant)
    monkeypatch.setattr(
        peakflo_main, "get_system_of_record_credentials", resolve_credentials
    )
    monkeypatch.setattr(peakflo_main.xero_main, "create_server", create_xero_server)

    server = SimpleNamespace(user_id="user-1", api_key="api-key-1")
    content = await peakflo_main._call_xero_tool_via_peakflo_connection(
        server,
        "peakflo-token",
        "xero__list_accounts",
        {"status": "ACTIVE"},
    )

    assert content == [TextContent(type="text", text="xero result")]
