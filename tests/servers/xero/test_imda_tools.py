"""
Offline handler-level tests for IMDA reconciliation tools.

Tests the new tools added for IMDA flows:
  - create_bank_transfer: Internal funds movement between bank accounts
  - create_batch_payment: Pay multiple invoices in a single transaction
  - create_overpayment: Handle excess payments (RECEIVE-OVERPAYMENT, SPEND-OVERPAYMENT)
  - create_prepayment: Handle advance payments (RECEIVE-PREPAYMENT, SPEND-PREPAYMENT)
  - list_accounts: Enhanced filtering (type, classType, status)
  - list_bank_transactions: Enhanced filtering (status for unreconciled)

All tests mock Xero HTTP calls and Nango credentials to run offline.
"""

import asyncio
import json
from unittest.mock import patch, AsyncMock

from mcp.types import ListToolsRequest, CallToolRequest, CallToolRequestParams

from src.servers.xero import main as xero_main

# ==================== Test Helpers ====================


async def _invoke(tool_name: str, arguments: dict, api_responses: list):
    """Run the call_tool handler with mocked Xero + Nango."""
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
    """Get the tool schema from list_tools handler."""
    srv = xero_main.create_server(user_id="test-user")
    list_handler = srv.request_handlers[ListToolsRequest]
    result = await list_handler(ListToolsRequest(method="tools/list"))
    return next(t for t in result.root.tools if t.name == tool_name)


# ==================== create_bank_transfer Tests ====================


async def test_create_bank_transfer_schema():
    tool = await _get_tool_schema("create_bank_transfer")
    props = tool.inputSchema["properties"]
    assert "fromAccountId" in props
    assert "toAccountId" in props
    assert "amount" in props
    assert props["amount"]["type"] == "number"
    assert set(tool.inputSchema["required"]) == {
        "fromAccountId",
        "toAccountId",
        "amount",
    }
    print("PASS  create_bank_transfer schema is correct")


async def test_create_bank_transfer_payload():
    transfer_response = {
        "BankTransfers": [
            {
                "BankTransferID": "bt-1",
                "Amount": 500.00,
            }
        ]
    }

    _, api_mock = await _invoke(
        "create_bank_transfer",
        {
            "fromAccountId": "acc-from",
            "toAccountId": "acc-to",
            "amount": 500.00,
            "date": "2026-01-15",
            "reference": "Petty cash replenishment",
        },
        api_responses=[transfer_response],
    )

    assert api_mock.call_count == 1
    call_kwargs = api_mock.call_args_list[0]
    payload = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
    # Check it uses PUT method
    method = call_kwargs.kwargs.get("method") or call_kwargs[1].get("method")
    assert method == "PUT", f"Expected PUT, got {method}"

    transfer = payload["BankTransfers"][0]
    assert transfer["FromBankAccount"]["AccountID"] == "acc-from"
    assert transfer["ToBankAccount"]["AccountID"] == "acc-to"
    assert transfer["Amount"] == 500.00
    assert transfer["Date"] == "2026-01-15"
    assert transfer["Reference"] == "Petty cash replenishment"
    print("PASS  create_bank_transfer sends correct PUT payload:", transfer)


async def test_create_bank_transfer_rejects_missing_fields():
    result, api_mock = await _invoke(
        "create_bank_transfer",
        {"fromAccountId": "acc-from"},
        api_responses=[],
    )
    text = result.root.content[0].text
    assert "required" in text.lower() or "Error" in text
    assert api_mock.call_count == 0
    print("PASS  create_bank_transfer rejects missing required fields")


async def test_create_bank_transfer_rejects_negative_amount():
    result, api_mock = await _invoke(
        "create_bank_transfer",
        {
            "fromAccountId": "acc-from",
            "toAccountId": "acc-to",
            "amount": -100,
        },
        api_responses=[],
    )
    text = result.root.content[0].text
    # MCP framework validates exclusiveMinimum: 0 from the schema
    assert (
        "validation error" in text.lower()
        or "less than" in text.lower()
        or "positive" in text.lower()
    ), f"Unexpected error text: {text}"
    assert api_mock.call_count == 0
    print("PASS  create_bank_transfer rejects negative amount:", text)


async def test_create_bank_transfer_defaults_date():
    transfer_response = {"BankTransfers": [{"BankTransferID": "bt-2"}]}

    _, api_mock = await _invoke(
        "create_bank_transfer",
        {
            "fromAccountId": "acc-from",
            "toAccountId": "acc-to",
            "amount": 100.00,
        },
        api_responses=[transfer_response],
    )

    call_kwargs = api_mock.call_args_list[0]
    payload = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
    transfer = payload["BankTransfers"][0]
    # Should have a Date field set (today's date)
    assert "Date" in transfer, "Expected Date to default to today"
    print("PASS  create_bank_transfer defaults date to today:", transfer["Date"])


# ==================== create_batch_payment Tests ====================


async def test_create_batch_payment_schema():
    tool = await _get_tool_schema("create_batch_payment")
    props = tool.inputSchema["properties"]
    assert "accountId" in props
    assert "date" in props
    assert "payments" in props
    assert props["payments"]["type"] == "array"
    payment_item_props = props["payments"]["items"]["properties"]
    assert "invoiceId" in payment_item_props
    assert "amount" in payment_item_props
    assert set(tool.inputSchema["required"]) == {"accountId", "date", "payments"}
    print("PASS  create_batch_payment schema is correct")


async def test_create_batch_payment_payload():
    batch_response = {
        "BatchPayments": [
            {
                "BatchPaymentID": "bp-1",
                "Payments": [
                    {"PaymentID": "p-1", "Amount": 100.00},
                    {"PaymentID": "p-2", "Amount": 200.00},
                ],
            }
        ]
    }

    _, api_mock = await _invoke(
        "create_batch_payment",
        {
            "accountId": "bank-acc-1",
            "date": "2026-01-15",
            "payments": [
                {"invoiceId": "inv-1", "amount": 100.00},
                {"invoiceId": "inv-2", "amount": 200.00},
            ],
            "reference": "Jan batch",
            "narrative": "January batch payment",
        },
        api_responses=[batch_response],
    )

    assert api_mock.call_count == 1
    call_kwargs = api_mock.call_args_list[0]
    payload = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
    method = call_kwargs.kwargs.get("method") or call_kwargs[1].get("method")
    assert method == "PUT"

    bp = payload["BatchPayments"][0]
    assert bp["Account"]["AccountID"] == "bank-acc-1"
    assert bp["Date"] == "2026-01-15"
    assert len(bp["Payments"]) == 2
    assert bp["Payments"][0]["Invoice"]["InvoiceID"] == "inv-1"
    assert bp["Payments"][0]["Amount"] == 100.00
    assert bp["Payments"][1]["Invoice"]["InvoiceID"] == "inv-2"
    assert bp["Payments"][1]["Amount"] == 200.00
    assert bp["Reference"] == "Jan batch"
    assert bp["Narrative"] == "January batch payment"
    print("PASS  create_batch_payment sends correct PUT payload:", bp)


async def test_create_batch_payment_rejects_missing_fields():
    result, api_mock = await _invoke(
        "create_batch_payment",
        {"accountId": "bank-acc-1"},
        api_responses=[],
    )
    text = result.root.content[0].text
    assert "required" in text.lower() or "Error" in text
    assert api_mock.call_count == 0
    print("PASS  create_batch_payment rejects missing required fields")


async def test_create_batch_payment_rejects_incomplete_payment_items():
    result, api_mock = await _invoke(
        "create_batch_payment",
        {
            "accountId": "bank-acc-1",
            "date": "2026-01-15",
            "payments": [
                {"invoiceId": "inv-1"},  # missing amount
            ],
        },
        api_responses=[],
    )
    text = result.root.content[0].text
    # MCP framework validates required fields in nested array items
    assert (
        "required" in text.lower() or "amount" in text.lower()
    ), f"Unexpected error: {text}"
    assert api_mock.call_count == 0
    print("PASS  create_batch_payment rejects payment items missing amount:", text)


# ==================== create_overpayment Tests ====================


async def test_create_overpayment_schema():
    tool = await _get_tool_schema("create_overpayment")
    props = tool.inputSchema["properties"]
    assert "type" in props
    assert props["type"]["enum"] == ["RECEIVE-OVERPAYMENT", "SPEND-OVERPAYMENT"]
    assert "contactId" in props
    assert "bankAccountId" in props
    assert "lineItems" in props
    assert set(tool.inputSchema["required"]) == {
        "type",
        "contactId",
        "bankAccountId",
        "lineItems",
    }
    print("PASS  create_overpayment schema is correct")


async def test_create_overpayment_receive_payload():
    op_response = {
        "BankTransactions": [
            {
                "BankTransactionID": "bt-op-1",
                "Type": "RECEIVE-OVERPAYMENT",
            }
        ]
    }

    _, api_mock = await _invoke(
        "create_overpayment",
        {
            "type": "RECEIVE-OVERPAYMENT",
            "contactId": "contact-1",
            "bankAccountId": "bank-1",
            "lineItems": [
                {
                    "description": "Overpayment from customer",
                    "quantity": 1,
                    "unitAmount": 50.00,
                    "accountCode": "200",
                }
            ],
            "date": "2026-01-15",
            "reference": "OP-001",
        },
        api_responses=[op_response],
    )

    assert api_mock.call_count == 1
    call_kwargs = api_mock.call_args_list[0]
    payload = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
    method = call_kwargs.kwargs.get("method") or call_kwargs[1].get("method")
    assert method == "PUT"

    tx = payload["BankTransactions"][0]
    assert tx["Type"] == "RECEIVE-OVERPAYMENT"
    assert tx["Contact"]["ContactID"] == "contact-1"
    assert tx["BankAccount"]["AccountID"] == "bank-1"
    assert len(tx["LineItems"]) == 1
    assert tx["LineItems"][0]["UnitAmount"] == 50.00
    assert tx["Date"] == "2026-01-15"
    assert tx["Reference"] == "OP-001"
    print("PASS  create_overpayment RECEIVE sends correct payload:", tx)


async def test_create_overpayment_spend_payload():
    op_response = {
        "BankTransactions": [
            {
                "BankTransactionID": "bt-op-2",
                "Type": "SPEND-OVERPAYMENT",
            }
        ]
    }

    _, api_mock = await _invoke(
        "create_overpayment",
        {
            "type": "SPEND-OVERPAYMENT",
            "contactId": "supplier-1",
            "bankAccountId": "bank-1",
            "lineItems": [
                {
                    "description": "Overpayment to supplier",
                    "quantity": 1,
                    "unitAmount": 75.00,
                    "accountCode": "300",
                }
            ],
        },
        api_responses=[op_response],
    )

    call_kwargs = api_mock.call_args_list[0]
    payload = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
    tx = payload["BankTransactions"][0]
    assert tx["Type"] == "SPEND-OVERPAYMENT"
    print("PASS  create_overpayment SPEND sends correct payload:", tx["Type"])


# ==================== create_prepayment Tests ====================


async def test_create_prepayment_schema():
    tool = await _get_tool_schema("create_prepayment")
    props = tool.inputSchema["properties"]
    assert "type" in props
    assert props["type"]["enum"] == ["RECEIVE-PREPAYMENT", "SPEND-PREPAYMENT"]
    assert "contactId" in props
    assert "bankAccountId" in props
    assert "lineItems" in props
    assert set(tool.inputSchema["required"]) == {
        "type",
        "contactId",
        "bankAccountId",
        "lineItems",
    }
    print("PASS  create_prepayment schema is correct")


async def test_create_prepayment_receive_payload():
    pp_response = {
        "BankTransactions": [
            {
                "BankTransactionID": "bt-pp-1",
                "Type": "RECEIVE-PREPAYMENT",
            }
        ]
    }

    _, api_mock = await _invoke(
        "create_prepayment",
        {
            "type": "RECEIVE-PREPAYMENT",
            "contactId": "customer-1",
            "bankAccountId": "bank-1",
            "lineItems": [
                {
                    "description": "Deposit for Project X",
                    "quantity": 1,
                    "unitAmount": 1000.00,
                    "accountCode": "200",
                    "taxType": "OUTPUT",
                }
            ],
            "date": "2026-02-01",
            "reference": "PP-001",
        },
        api_responses=[pp_response],
    )

    assert api_mock.call_count == 1
    call_kwargs = api_mock.call_args_list[0]
    payload = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
    method = call_kwargs.kwargs.get("method") or call_kwargs[1].get("method")
    assert method == "PUT"

    tx = payload["BankTransactions"][0]
    assert tx["Type"] == "RECEIVE-PREPAYMENT"
    assert tx["Contact"]["ContactID"] == "customer-1"
    assert tx["LineItems"][0]["TaxType"] == "OUTPUT"
    assert tx["LineItems"][0]["UnitAmount"] == 1000.00
    print("PASS  create_prepayment RECEIVE sends correct payload:", tx)


async def test_create_prepayment_spend_payload():
    pp_response = {
        "BankTransactions": [
            {
                "BankTransactionID": "bt-pp-2",
                "Type": "SPEND-PREPAYMENT",
            }
        ]
    }

    _, api_mock = await _invoke(
        "create_prepayment",
        {
            "type": "SPEND-PREPAYMENT",
            "contactId": "supplier-1",
            "bankAccountId": "bank-1",
            "lineItems": [
                {
                    "description": "Advance to supplier",
                    "quantity": 1,
                    "unitAmount": 250.00,
                    "accountCode": "400",
                }
            ],
        },
        api_responses=[pp_response],
    )

    call_kwargs = api_mock.call_args_list[0]
    payload = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
    tx = payload["BankTransactions"][0]
    assert tx["Type"] == "SPEND-PREPAYMENT"
    print("PASS  create_prepayment SPEND sends correct payload:", tx["Type"])


# ==================== list_accounts Enhanced Filtering Tests ====================


async def test_list_accounts_schema_has_filters():
    tool = await _get_tool_schema("list_accounts")
    props = tool.inputSchema["properties"]
    assert "type" in props
    assert "classType" in props
    assert props["classType"]["enum"] == [
        "ASSET",
        "EQUITY",
        "EXPENSE",
        "LIABILITY",
        "REVENUE",
    ]
    assert "status" in props
    assert props["status"]["enum"] == ["ACTIVE", "ARCHIVED"]
    print("PASS  list_accounts schema has type, classType, and status filters")


async def test_list_accounts_type_filter():
    accounts_response = {
        "Accounts": [{"AccountID": "acc-1", "Type": "BANK", "Name": "Checking"}]
    }

    _, api_mock = await _invoke(
        "list_accounts",
        {"type": "BANK"},
        api_responses=[accounts_response],
    )

    call_kwargs = api_mock.call_args_list[0]
    params = call_kwargs.kwargs.get("params")
    assert params is not None
    assert 'Type=="BANK"' in params["where"]
    print("PASS  list_accounts type=BANK filter sends where clause:", params["where"])


async def test_list_accounts_combined_filters():
    accounts_response = {"Accounts": []}

    _, api_mock = await _invoke(
        "list_accounts",
        {"type": "BANK", "classType": "ASSET", "status": "ACTIVE"},
        api_responses=[accounts_response],
    )

    call_kwargs = api_mock.call_args_list[0]
    params = call_kwargs.kwargs.get("params")
    where = params["where"]
    assert 'Type=="BANK"' in where
    assert 'Class=="ASSET"' in where
    assert 'Status=="ACTIVE"' in where
    print("PASS  list_accounts combined filters send where clause:", where)


async def test_list_accounts_no_filter():
    accounts_response = {"Accounts": []}

    _, api_mock = await _invoke(
        "list_accounts",
        {},
        api_responses=[accounts_response],
    )

    call_kwargs = api_mock.call_args_list[0]
    params = call_kwargs.kwargs.get("params")
    # Should pass None or no params when no filters
    assert params is None or "where" not in (params or {})
    print("PASS  list_accounts with no filters sends no where clause")


# ==================== list_bank_transactions Enhanced Filtering Tests ====================


async def test_list_bank_transactions_schema_has_status():
    tool = await _get_tool_schema("list_bank_transactions")
    props = tool.inputSchema["properties"]
    assert "status" in props
    assert props["status"]["enum"] == ["AUTHORISED", "DELETED"]
    print("PASS  list_bank_transactions schema has status filter")


async def test_list_bank_transactions_status_filter():
    txns_response = {"BankTransactions": []}

    _, api_mock = await _invoke(
        "list_bank_transactions",
        {"status": "AUTHORISED"},
        api_responses=[txns_response],
    )

    call_kwargs = api_mock.call_args_list[0]
    params = call_kwargs.kwargs.get("params")
    assert 'Status=="AUTHORISED"' in params["where"]
    print(
        "PASS  list_bank_transactions status filter sends where:",
        params["where"],
    )


async def test_list_bank_transactions_combined_filters():
    txns_response = {"BankTransactions": []}

    _, api_mock = await _invoke(
        "list_bank_transactions",
        {"bankAccountId": "acc-123", "status": "AUTHORISED", "page": 2},
        api_responses=[txns_response],
    )

    call_kwargs = api_mock.call_args_list[0]
    params = call_kwargs.kwargs.get("params")
    where = params["where"]
    assert 'BankAccount.AccountID==Guid("acc-123")' in where
    assert 'Status=="AUTHORISED"' in where
    assert params["page"] == 2
    print(
        "PASS  list_bank_transactions combined filters:",
        where,
        "page=",
        params["page"],
    )


# ==================== Main Runner ====================


async def main():
    # create_bank_transfer tests
    await test_create_bank_transfer_schema()
    await test_create_bank_transfer_payload()
    await test_create_bank_transfer_rejects_missing_fields()
    await test_create_bank_transfer_rejects_negative_amount()
    await test_create_bank_transfer_defaults_date()

    # create_batch_payment tests
    await test_create_batch_payment_schema()
    await test_create_batch_payment_payload()
    await test_create_batch_payment_rejects_missing_fields()
    await test_create_batch_payment_rejects_incomplete_payment_items()

    # create_overpayment tests
    await test_create_overpayment_schema()
    await test_create_overpayment_receive_payload()
    await test_create_overpayment_spend_payload()

    # create_prepayment tests
    await test_create_prepayment_schema()
    await test_create_prepayment_receive_payload()
    await test_create_prepayment_spend_payload()

    # list_accounts enhanced filtering tests
    await test_list_accounts_schema_has_filters()
    await test_list_accounts_type_filter()
    await test_list_accounts_combined_filters()
    await test_list_accounts_no_filter()

    # list_bank_transactions enhanced filtering tests
    await test_list_bank_transactions_schema_has_status()
    await test_list_bank_transactions_status_filter()
    await test_list_bank_transactions_combined_filters()

    print("\nAll 22 tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
