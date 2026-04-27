"""
Offline handler-level test for the update_invoice status field (TSK-16147).

Mocks Xero HTTP calls and Nango credentials so the test runs with no network
access and no real tenant. Verifies:
  1. The status field is in the registered tool schema with the correct enum.
  2. status="AUTHORISED" is forwarded to Xero in the POST payload.
  3. Omitting status leaves the payload unchanged (no Status key).
  4. The DRAFT-only guard still rejects updates against non-DRAFT invoices.
"""

import asyncio
import json
from unittest.mock import patch, AsyncMock

from mcp.types import ListToolsRequest, CallToolRequest, CallToolRequestParams

from src.servers.xero import main as xero_main


def _draft_invoice_response():
    return {"Invoices": [{"InvoiceID": "inv-1", "Status": "DRAFT"}]}


def _authorised_invoice_response():
    return {"Invoices": [{"InvoiceID": "inv-1", "Status": "AUTHORISED"}]}


async def _invoke(tool_name: str, arguments: dict, api_responses: list):
    """Run the call_tool handler with mocked Xero + Nango."""
    srv = xero_main.create_server(user_id="test-user")
    handler = srv.request_handlers[CallToolRequest]

    # Mock the Xero HTTP layer: each call returns the next item in api_responses.
    api_mock = AsyncMock(side_effect=api_responses)
    creds_mock = AsyncMock(return_value=("fake-token", "fake-tenant"))

    with patch.object(xero_main, "call_xero_api", api_mock), patch.object(
        xero_main, "get_xero_credentials", creds_mock
    ):
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=tool_name, arguments=arguments),
        )
        result = await handler(request)
    return result, api_mock


async def test_schema_exposes_status():
    srv = xero_main.create_server(user_id="test-user")
    list_handler = srv.request_handlers[ListToolsRequest]
    result = await list_handler(ListToolsRequest(method="tools/list"))
    tool = next(t for t in result.root.tools if t.name == "update_invoice")
    status = tool.inputSchema["properties"]["status"]
    assert status["type"] == "string"
    assert status["enum"] == ["DRAFT", "SUBMITTED", "AUTHORISED", "DELETED"]
    assert "status" not in tool.inputSchema["required"]
    print("PASS  schema exposes status with correct enum and is optional")


async def test_status_authorised_is_forwarded():
    _, api_mock = await _invoke(
        "update_invoice",
        {"invoiceId": "inv-1", "status": "AUTHORISED"},
        api_responses=[_draft_invoice_response(), _authorised_invoice_response()],
    )
    # Two calls: GET for guard, POST for update
    assert api_mock.call_count == 2
    post_call = api_mock.call_args_list[1]
    payload = post_call.kwargs["data"]
    invoice_payload = payload["Invoices"][0]
    assert invoice_payload["InvoiceID"] == "inv-1"
    assert invoice_payload["Status"] == "AUTHORISED"
    print("PASS  status=AUTHORISED forwarded in POST payload:", invoice_payload)


async def test_status_omitted_means_no_status_key():
    _, api_mock = await _invoke(
        "update_invoice",
        {"invoiceId": "inv-1", "reference": "PO-123"},
        api_responses=[_draft_invoice_response(), _draft_invoice_response()],
    )
    post_call = api_mock.call_args_list[1]
    invoice_payload = post_call.kwargs["data"]["Invoices"][0]
    assert "Status" not in invoice_payload, (
        f"expected no Status key when omitted, got {invoice_payload}"
    )
    assert invoice_payload["Reference"] == "PO-123"
    print("PASS  status omitted -> no Status key in payload:", invoice_payload)


async def test_draft_guard_still_blocks_non_draft():
    non_draft = {"Invoices": [{"InvoiceID": "inv-1", "Status": "AUTHORISED"}]}
    result, api_mock = await _invoke(
        "update_invoice",
        {"invoiceId": "inv-1", "status": "DELETED"},
        api_responses=[non_draft],
    )
    # Handler catches the ValueError and returns an Error TextContent
    text = result.root.content[0].text
    assert "Only DRAFT invoices can be updated" in text, text
    assert api_mock.call_count == 1  # never reached the POST
    print("PASS  non-DRAFT invoice rejected before POST:", text.strip())


async def main():
    await test_schema_exposes_status()
    await test_status_authorised_is_forwarded()
    await test_status_omitted_means_no_status_key()
    await test_draft_guard_still_blocks_non_draft()
    print("\nAll 4 tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
