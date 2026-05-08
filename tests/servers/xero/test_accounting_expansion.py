import asyncio
import base64
import json
from unittest.mock import AsyncMock, patch

from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

from src.servers.xero import main as xero_main


async def _invoke(tool_name: str, arguments: dict, api_responses: list):
    """Run the call_tool handler with mocked Xero credentials and API client."""
    srv = xero_main.create_server(user_id="test-user")
    handler = srv.request_handlers[CallToolRequest]

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


async def _get_tool_schema(tool_name: str):
    srv = xero_main.create_server(user_id="test-user")
    list_handler = srv.request_handlers[ListToolsRequest]
    result = await list_handler(ListToolsRequest(method="tools/list"))
    return next(t for t in result.root.tools if t.name == tool_name)


async def test_schema_new_tools_exist():
    for tool_name in [
        "list_bank_transfers",
        "list_batch_payments",
        "list_overpayments",
        "list_prepayments",
        "list_purchase_orders",
        "create_purchase_order",
        "update_purchase_order",
        "add_attachment",
        "upload_attachment",
        "email_invoice",
    ]:
        tool = await _get_tool_schema(tool_name)
        assert tool.name == tool_name


async def test_list_bank_transfers_builds_expected_where_clause():
    _, api_mock = await _invoke(
        "list_bank_transfers",
        {
            "fromAccountId": "from-acc",
            "toAccountId": "to-acc",
        },
        api_responses=[{"BankTransfers": []}],
    )

    assert api_mock.call_args.args[0] == "/api.xro/2.0/BankTransfers"
    params = api_mock.call_args.kwargs["params"]
    assert params["order"] == "Date DESC"
    assert (
        params["where"]
        == 'FromBankAccount.AccountID==Guid("from-acc") AND ToBankAccount.AccountID==Guid("to-acc")'
    )


async def test_list_batch_payments_uses_direct_endpoint():
    _, api_mock = await _invoke(
        "list_batch_payments",
        {
            "status": "AUTHORISED",
            "accountId": "bank-acc",
        },
        api_responses=[{"BatchPayments": []}],
    )

    assert api_mock.call_args.args[0] == "/api.xro/2.0/BatchPayments"
    params = api_mock.call_args.kwargs["params"]
    assert params["order"] == "Date DESC"
    assert (
        params["where"]
        == 'Status=="AUTHORISED" AND Account.AccountID==Guid("bank-acc")'
    )


async def test_list_overpayments_uses_overpayments_endpoint():
    _, api_mock = await _invoke(
        "list_overpayments",
        {
            "status": "AUTHORISED",
            "page": 2,
            "pageSize": 50,
            "references": ["Ref-1", "Ref-2"],
        },
        api_responses=[{"Overpayments": []}],
    )

    assert api_mock.call_args.args[0] == "/api.xro/2.0/Overpayments"
    params = api_mock.call_args.kwargs["params"]
    assert params["where"] == 'Status=="AUTHORISED"'
    assert params["page"] == 2
    assert params["pageSize"] == 50
    assert params["References"] == "Ref-1,Ref-2"


async def test_list_prepayments_uses_prepayments_endpoint():
    _, api_mock = await _invoke(
        "list_prepayments",
        {
            "status": "AUTHORISED",
            "invoiceNumbers": ["INV-1", "INV-2"],
        },
        api_responses=[{"Prepayments": []}],
    )

    assert api_mock.call_args.args[0] == "/api.xro/2.0/Prepayments"
    params = api_mock.call_args.kwargs["params"]
    assert params["where"] == 'Status=="AUTHORISED"'
    assert params["InvoiceNumbers"] == "INV-1,INV-2"


async def test_list_purchase_orders_uses_purchase_orders_endpoint():
    _, api_mock = await _invoke(
        "list_purchase_orders",
        {
            "status": "SUBMITTED",
            "dateFrom": "2026-01-01",
            "dateTo": "2026-01-31",
            "page": 1,
            "pageSize": 25,
        },
        api_responses=[{"PurchaseOrders": []}],
    )

    assert api_mock.call_args.args[0] == "/api.xro/2.0/PurchaseOrders"
    params = api_mock.call_args.kwargs["params"]
    assert params["status"] == "SUBMITTED"
    assert params["dateFrom"] == "2026-01-01"
    assert params["dateTo"] == "2026-01-31"
    assert params["page"] == 1
    assert params["pageSize"] == 25


async def test_create_purchase_order_payload():
    _, api_mock = await _invoke(
        "create_purchase_order",
        {
            "contactId": "contact-123",
            "lineItems": [
                {
                    "description": "Paper",
                    "quantity": 2,
                    "unitAmount": 10.5,
                    "accountCode": "400",
                    "taxType": "INPUT",
                }
            ],
            "deliveryDate": "2026-01-20",
            "reference": "PO-123",
            "currencyCode": "USD",
            "attentionTo": "Alex",
        },
        api_responses=[{"PurchaseOrders": [{"PurchaseOrderID": "po-1"}]}],
    )

    assert api_mock.call_args.args[0] == "/api.xro/2.0/PurchaseOrders"
    assert api_mock.call_args.kwargs["method"] == "POST"
    payload = api_mock.call_args.kwargs["data"]["PurchaseOrders"][0]
    assert payload["Contact"]["ContactID"] == "contact-123"
    assert payload["Status"] == "DRAFT"
    assert payload["DeliveryDate"] == "2026-01-20"
    assert payload["Reference"] == "PO-123"
    assert payload["CurrencyCode"] == "USD"
    assert payload["AttentionTo"] == "Alex"
    assert payload["LineItems"][0]["TaxType"] == "INPUT"


async def test_update_purchase_order_requires_draft_status():
    result, api_mock = await _invoke(
        "update_purchase_order",
        {"purchaseOrderId": "po-locked", "reference": "Updated"},
        api_responses=[
            {
                "PurchaseOrders": [
                    {"PurchaseOrderID": "po-locked", "Status": "AUTHORISED"}
                ]
            }
        ],
    )

    text = result.root.content[0].text
    assert "Only DRAFT purchase orders can be updated" in text
    assert api_mock.call_count == 1


async def test_add_attachment_posts_binary_content():
    content = base64.b64encode(b"hello world").decode()

    _, api_mock = await _invoke(
        "add_attachment",
        {
            "entityType": "Invoices",
            "entityId": "inv-123",
            "filename": "receipt.pdf",
            "contentBase64": content,
            "mimeType": "application/pdf",
            "includeOnline": True,
            "idempotencyKey": "idem-123",
        },
        api_responses=[{"Attachments": [{"FileName": "receipt.pdf"}]}],
    )

    assert (
        api_mock.call_args.args[0]
        == "/api.xro/2.0/Invoices/inv-123/Attachments/receipt.pdf"
    )
    assert api_mock.call_args.kwargs["method"] == "POST"
    assert api_mock.call_args.kwargs["content"] == b"hello world"
    assert api_mock.call_args.kwargs["params"] == {"includeOnline": True}
    assert (
        api_mock.call_args.kwargs["extra_headers"]["Content-Type"] == "application/pdf"
    )
    assert api_mock.call_args.kwargs["extra_headers"]["Idempotency-Key"] == "idem-123"


async def test_upload_attachment_puts_binary_content():
    content = base64.b64encode(b"updated").decode()

    _, api_mock = await _invoke(
        "upload_attachment",
        {
            "entityType": "PurchaseOrders",
            "entityId": "po-123",
            "filename": "po.pdf",
            "contentBase64": content,
            "mimeType": "application/pdf",
        },
        api_responses=[{"Attachments": [{"FileName": "po.pdf"}]}],
    )

    assert (
        api_mock.call_args.args[0]
        == "/api.xro/2.0/PurchaseOrders/po-123/Attachments/po.pdf"
    )
    assert api_mock.call_args.kwargs["method"] == "PUT"
    assert api_mock.call_args.kwargs["content"] == b"updated"
    assert (
        api_mock.call_args.kwargs["extra_headers"]["Content-Type"] == "application/pdf"
    )


async def test_add_attachment_rejects_invalid_base64():
    result, api_mock = await _invoke(
        "add_attachment",
        {
            "entityType": "Invoices",
            "entityId": "inv-123",
            "filename": "receipt.pdf",
            "contentBase64": "not-valid-base64",
        },
        api_responses=[],
    )

    text = result.root.content[0].text
    assert "contentBase64" in text
    assert api_mock.call_count == 0


async def test_email_invoice_posts_empty_payload_and_returns_success_message():
    result, api_mock = await _invoke(
        "email_invoice",
        {
            "invoiceId": "inv-789",
            "idempotencyKey": "idem-email",
        },
        api_responses=[{}],
    )

    assert api_mock.call_args.args[0] == "/api.xro/2.0/Invoices/inv-789/Email"
    assert api_mock.call_args.kwargs["method"] == "POST"
    assert api_mock.call_args.kwargs["data"] == {}
    assert api_mock.call_args.kwargs["extra_headers"]["Idempotency-Key"] == "idem-email"

    payload = json.loads(result.root.content[0].text)
    assert payload["Success"] is True
    assert payload["InvoiceID"] == "inv-789"


async def main():
    await test_schema_new_tools_exist()
    await test_list_bank_transfers_builds_expected_where_clause()
    await test_list_batch_payments_uses_direct_endpoint()
    await test_list_overpayments_uses_overpayments_endpoint()
    await test_list_prepayments_uses_prepayments_endpoint()
    await test_list_purchase_orders_uses_purchase_orders_endpoint()
    await test_create_purchase_order_payload()
    await test_update_purchase_order_requires_draft_status()
    await test_add_attachment_posts_binary_content()
    await test_upload_attachment_puts_binary_content()
    await test_add_attachment_rejects_invalid_base64()
    await test_email_invoice_posts_empty_payload_and_returns_success_message()
    print("\nAll 12 accounting expansion tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
