"""
Offline handler-level tests for the get_invoice_pdf tool.

Mocks Xero HTTP calls, Nango credentials, and storage service so tests run
with no network access. Verifies:
  1. get_invoice_pdf appears in tool schema with correct params.
  2. get_invoice_pdf downloads PDF and uploads to storage, returns URL.
  3. get_invoice_pdf calls download_xero_invoice_pdf with correct args.
  4. get_invoice_pdf returns error when download fails.
  5. get_invoice_pdf reports correct file size.
  6. get_invoice_pdf requires invoiceId parameter.
"""

import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock

from mcp.types import ListToolsRequest, CallToolRequest, CallToolRequestParams

from src.servers.xero import main as xero_main

_SENTINEL = object()


async def _invoke(
    tool_name: str,
    arguments: dict,
    pdf_data=_SENTINEL,
    storage_url=None,
):
    """Run the call_tool handler with mocked Xero + Nango + storage."""
    srv = xero_main.create_server(user_id="test-user")
    handler = srv.request_handlers[CallToolRequest]

    creds_mock = AsyncMock(return_value=("fake-token", "fake-tenant"))

    patches = [
        patch.object(xero_main, "get_xero_credentials", creds_mock),
    ]

    download_mock = None
    storage_instance_mock = None

    if pdf_data is not _SENTINEL:
        download_mock = AsyncMock(return_value=pdf_data)
        patches.append(
            patch.object(xero_main, "download_xero_invoice_pdf", download_mock)
        )

    if storage_url is not None:
        storage_instance_mock = MagicMock()
        storage_instance_mock.upload_temporary.return_value = storage_url
        storage_factory_mock = MagicMock(return_value=storage_instance_mock)
        patches.append(
            patch.object(xero_main, "get_storage_service", storage_factory_mock)
        )

    for p in patches:
        p.start()

    try:
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=tool_name, arguments=arguments),
        )
        result = await handler(request)
    finally:
        for p in patches:
            p.stop()

    return result, download_mock, storage_instance_mock


# ==================== Schema Tests ====================


async def test_schema_get_invoice_pdf():
    """get_invoice_pdf tool appears in schema with correct required params."""
    srv = xero_main.create_server(user_id="test-user")
    list_handler = srv.request_handlers[ListToolsRequest]
    result = await list_handler(ListToolsRequest(method="tools/list"))
    tool = next(t for t in result.root.tools if t.name == "get_invoice_pdf")

    props = tool.inputSchema["properties"]
    assert "invoiceId" in props
    assert tool.inputSchema["required"] == ["invoiceId"]
    print("PASS  get_invoice_pdf schema is correct")


# ==================== Happy Path Tests ====================


async def test_downloads_pdf_and_returns_url():
    """get_invoice_pdf downloads PDF data and returns a signed URL."""
    fake_pdf = b"%PDF-1.4 fake-pdf-content-here"
    fake_url = "https://storage.example.com/signed/inv-123.pdf?token=abc"

    result, download_mock, storage_mock = await _invoke(
        "get_invoice_pdf",
        {"invoiceId": "inv-123"},
        pdf_data=fake_pdf,
        storage_url=fake_url,
    )

    # Verify download was called with correct args
    download_mock.assert_called_once_with("inv-123", "fake-token", "fake-tenant")

    # Verify storage upload was called correctly
    storage_mock.upload_temporary.assert_called_once_with(
        data=fake_pdf,
        filename="inv-123.pdf",
        mime_type="application/pdf",
    )

    text = result.root.content[0].text
    assert "inv-123" in text
    assert fake_url in text
    assert "Download URL (expires in 1 hour)" in text
    print("PASS  get_invoice_pdf downloads and returns signed URL")


async def test_accepts_invoice_number():
    """get_invoice_pdf works with an InvoiceNumber (not just GUID)."""
    fake_pdf = b"%PDF-1.4 invoice-number-pdf"
    fake_url = "https://storage.example.com/signed/INV-0041.pdf?token=xyz"

    result, download_mock, _ = await _invoke(
        "get_invoice_pdf",
        {"invoiceId": "INV-0041"},
        pdf_data=fake_pdf,
        storage_url=fake_url,
    )

    download_mock.assert_called_once_with("INV-0041", "fake-token", "fake-tenant")

    text = result.root.content[0].text
    assert "INV-0041" in text
    assert fake_url in text
    print("PASS  get_invoice_pdf works with InvoiceNumber")


async def test_reports_correct_size():
    """get_invoice_pdf reports file size in KB."""
    fake_pdf = b"x" * 5120  # 5 KB
    fake_url = "https://storage.example.com/signed/inv-456.pdf"

    result, _, _ = await _invoke(
        "get_invoice_pdf",
        {"invoiceId": "inv-456"},
        pdf_data=fake_pdf,
        storage_url=fake_url,
    )

    text = result.root.content[0].text
    assert "5.0 KB" in text
    print("PASS  get_invoice_pdf reports correct file size")


# ==================== Error Handling Tests ====================


async def test_download_failure():
    """get_invoice_pdf returns error when PDF download returns empty."""
    result, _, _ = await _invoke(
        "get_invoice_pdf",
        {"invoiceId": "inv-bad"},
        pdf_data=None,
        storage_url="https://storage.example.com/unused",
    )

    text = result.root.content[0].text
    assert "Failed to download" in text or "inv-bad" in text
    print("PASS  get_invoice_pdf handles download failure")


async def test_download_xero_error():
    """get_invoice_pdf surfaces Xero API errors."""
    srv = xero_main.create_server(user_id="test-user")
    handler = srv.request_handlers[CallToolRequest]

    creds_mock = AsyncMock(return_value=("fake-token", "fake-tenant"))
    download_mock = AsyncMock(
        side_effect=Exception("Resource not found in Xero. Details: Invoice not found")
    )

    with patch.object(xero_main, "get_xero_credentials", creds_mock), patch.object(
        xero_main, "download_xero_invoice_pdf", download_mock
    ):
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="get_invoice_pdf", arguments={"invoiceId": "nonexistent"}
            ),
        )
        result = await handler(request)

    text = result.root.content[0].text
    assert "Error" in text
    assert "not found" in text.lower()
    print("PASS  get_invoice_pdf surfaces Xero API errors")


async def test_missing_invoice_id():
    """get_invoice_pdf raises error when invoiceId is missing."""
    result, _, _ = await _invoke(
        "get_invoice_pdf",
        {},
        pdf_data=b"unused",
        storage_url="https://storage.example.com/unused",
    )

    text = result.root.content[0].text
    assert "invoiceId" in text or "required" in text.lower() or "Error" in text
    print("PASS  get_invoice_pdf requires invoiceId")


async def main():
    await test_schema_get_invoice_pdf()
    await test_downloads_pdf_and_returns_url()
    await test_accepts_invoice_number()
    await test_reports_correct_size()
    await test_download_failure()
    await test_download_xero_error()
    await test_missing_invoice_id()
    print(f"\nAll 7 tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
