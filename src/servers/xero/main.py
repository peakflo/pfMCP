import os
import sys
from typing import Optional, Dict, Any, List
import json
import base64
import binascii

# Add both project root and src directory to Python path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import logging
from pathlib import Path
from datetime import datetime, timedelta

import httpx
from mcp.types import (
    AnyUrl,
    Resource,
    TextContent,
    Tool,
    ImageContent,
    EmbeddedResource,
)
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from src.auth.factory import create_auth_client
from src.utils.storage.factory import get_storage_service

# Configuration
SERVICE_NAME = Path(__file__).parent.name
XERO_API_BASE = "https://api.xero.com"
ACCOUNTING_API = "/api.xro/2.0"
PAYROLL_API = "/payroll.xro/1.0"

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


async def get_xero_credentials(user_id: str, api_key: str = None) -> tuple:
    """
    Get Xero access_token and tenant_id from Nango.

    Args:
        user_id: The user ID associated with the credentials.
        api_key: Optional API key override.

    Returns:
        Tuple of (access_token, tenant_id).
    """
    auth_client = create_auth_client(api_key=api_key)
    credentials = auth_client.get_user_credentials(SERVICE_NAME, user_id)

    if not credentials:
        raise ValueError(
            f"No Xero credentials found for user {user_id}. "
            "Please authenticate via Nango first."
        )

    access_token = (
        credentials.get("access_token")
        if isinstance(credentials, dict)
        else credentials
    )

    # Tenant ID from Nango connection metadata
    tenant_id = None
    if isinstance(credentials, dict):
        tenant_id = credentials.get("metadata", {}).get("tenantId")

    if not tenant_id:
        # Fallback: call Xero /connections to discover tenant ID
        logger.info("Tenant ID not in metadata, falling back to /connections endpoint")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{XERO_API_BASE}/connections",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if resp.status_code == 200:
                    connections = resp.json()
                    if connections and len(connections) > 0:
                        tenant_id = connections[0].get("tenantId")
                        logger.info(
                            f"Discovered tenant ID from /connections: {tenant_id}"
                        )
                else:
                    logger.error(
                        f"Failed to get Xero connections: {resp.status_code} - {resp.text}"
                    )
        except Exception as e:
            logger.error(f"Error fetching Xero connections: {e}")

    if not access_token or not tenant_id:
        raise ValueError(
            "Invalid Xero credentials: missing access_token or tenantId. "
            "Ensure Nango connection metadata includes tenantId."
        )

    return access_token, tenant_id


def format_xero_error(status_code: int, error_text: str) -> str:
    """Format Xero API errors into human-readable messages."""
    if status_code == 401:
        return (
            "Authentication failed. Your Xero access token may have expired. "
            "Please re-authenticate via Nango."
        )
    elif status_code == 403:
        return (
            "Permission denied. Your Xero connection may not have the required scopes "
            f"for this operation. Details: {error_text}"
        )
    elif status_code == 404:
        return f"Resource not found in Xero. Details: {error_text}"
    elif status_code == 429:
        return (
            "Rate limit exceeded. Xero allows 60 API calls per minute per tenant. "
            "Please wait and try again."
        )
    elif status_code == 400:
        return f"Bad request to Xero API. Please check your parameters. Details: {error_text}"
    else:
        return f"Xero API error (HTTP {status_code}): {error_text}"


async def call_xero_api(
    endpoint: str,
    access_token: str,
    tenant_id: str,
    method: str = "GET",
    data: Dict = None,
    params: Dict = None,
    content: bytes = None,
    extra_headers: Dict[str, str] = None,
) -> Dict:
    """
    Make an API call to Xero.

    Args:
        endpoint: API endpoint path (e.g., "/api.xro/2.0/Contacts").
        access_token: Xero OAuth2 access token.
        tenant_id: Xero tenant (organisation) ID.
        method: HTTP method (GET, POST, PUT).
        data: Request body for POST/PUT.
        params: Query parameters.

    Returns:
        Parsed JSON response from Xero API.
    """
    url = f"{XERO_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "xero-tenant-id": tenant_id,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    if content is not None:
        headers.pop("Content-Type", None)
    if extra_headers:
        headers.update(extra_headers)

    async with httpx.AsyncClient() as client:
        if method.upper() == "GET":
            response = await client.get(url, headers=headers, params=params)
        elif method.upper() == "POST":
            if content is not None:
                response = await client.post(
                    url, headers=headers, params=params, content=content
                )
            else:
                response = await client.post(
                    url, headers=headers, params=params, json=data
                )
        elif method.upper() == "PUT":
            if content is not None:
                response = await client.put(
                    url, headers=headers, params=params, content=content
                )
            else:
                response = await client.put(
                    url, headers=headers, params=params, json=data
                )
        elif method.upper() == "DELETE":
            response = await client.delete(url, headers=headers, params=params)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        if response.status_code >= 400:
            error_text = response.text
            raise Exception(format_xero_error(response.status_code, error_text))

        if not response.content:
            return {}

        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            return response.json()

        try:
            return response.json()
        except ValueError:
            return {"raw_response": response.text}


# Valid Xero entity types that support attachments.
# Maps user-facing names to Xero API endpoint names.
ATTACHMENT_ENTITY_TYPES = {
    "Invoices": "Invoices",
    "CreditNotes": "CreditNotes",
    "BankTransactions": "BankTransactions",
    "BankTransfers": "BankTransfers",
    "Contacts": "Contacts",
    "ManualJournals": "ManualJournals",
    "Quotes": "Quotes",
    "Receipts": "Receipts",
    "RepeatingInvoices": "RepeatingInvoices",
    "Accounts": "Accounts",
    "PurchaseOrders": "PurchaseOrders",
}


def build_line_items_payload(
    line_items_input: List[Dict[str, Any]], include_tracking: bool = True
) -> List[Dict[str, Any]]:
    """Map MCP line item arguments to Xero line item payloads."""
    line_items = []
    for item in line_items_input:
        line_item = {
            "Description": item.get("description", ""),
            "Quantity": item.get("quantity", 1),
            "UnitAmount": item.get("unitAmount", 0),
            "AccountCode": item.get("accountCode", ""),
        }
        if item.get("taxType"):
            line_item["TaxType"] = item["taxType"]
        if item.get("itemCode"):
            line_item["ItemCode"] = item["itemCode"]
        if include_tracking and item.get("tracking"):
            line_item["Tracking"] = [
                {
                    "TrackingCategoryID": t.get("trackingCategoryID"),
                    "TrackingOptionID": t.get("trackingOptionID"),
                }
                for t in item["tracking"]
            ]
        line_items.append(line_item)

    return line_items


def decode_base64_attachment(content_base64: str) -> bytes:
    """Decode base64 file content provided by the MCP caller."""
    try:
        return base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            "contentBase64 must be valid base64-encoded file content"
        ) from exc


async def download_xero_attachment(
    endpoint: str,
    entity_id: str,
    filename: str,
    access_token: str,
    tenant_id: str,
) -> bytes:
    """
    Download attachment binary data from Xero.

    Uses the Xero Attachments API to fetch the raw file content.
    Unlike call_xero_api, this returns raw bytes instead of JSON.

    Args:
        endpoint: Xero entity type (e.g., "Invoices", "CreditNotes").
        entity_id: The GUID of the entity the attachment belongs to.
        filename: The filename of the attachment to download.
        access_token: Xero OAuth2 access token.
        tenant_id: Xero tenant (organisation) ID.

    Returns:
        Raw bytes of the attachment file content.

    Raises:
        Exception: If the download fails (HTTP error).
    """
    from urllib.parse import quote

    url = (
        f"{XERO_API_BASE}{ACCOUNTING_API}"
        f"/{endpoint}/{entity_id}/Attachments/{quote(filename, safe='')}"
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "xero-tenant-id": tenant_id,
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)

        if response.status_code >= 400:
            error_text = response.text
            raise Exception(format_xero_error(response.status_code, error_text))

        return response.content


async def download_xero_invoice_pdf(
    invoice_id: str,
    access_token: str,
    tenant_id: str,
) -> bytes:
    """
    Download the rendered PDF of a Xero invoice.

    Uses the Xero Invoices endpoint with Accept: application/pdf to retrieve
    the system-generated invoice PDF (not a user-uploaded attachment).

    Args:
        invoice_id: The InvoiceID (GUID) or InvoiceNumber of the invoice.
        access_token: Xero OAuth2 access token.
        tenant_id: Xero tenant (organisation) ID.

    Returns:
        Raw bytes of the invoice PDF.

    Raises:
        Exception: If the download fails (HTTP error).
    """
    url = f"{XERO_API_BASE}{ACCOUNTING_API}/Invoices/{invoice_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "xero-tenant-id": tenant_id,
        "Accept": "application/pdf",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)

        if response.status_code >= 400:
            error_text = response.text
            raise Exception(format_xero_error(response.status_code, error_text))

        return response.content


def create_server(user_id, api_key=None):
    """
    Initialize and configure the Xero MCP server.

    Args:
        user_id: The user ID associated with the current session.
        api_key: Optional API key override.

    Returns:
        Server: Configured MCP server instance with registered tools.
    """
    server = Server("xero-server")
    server.user_id = user_id
    server.api_key = api_key

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """Return all available Xero tools."""
        return [
            # ==================== LIST OPERATIONS ====================
            Tool(
                name="list_accounts",
                description="Retrieve a list of accounts (chart of accounts) from Xero. Supports filtering by account type and class for validation of account codes.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "description": "Filter by account type (e.g., BANK, REVENUE, EXPENSE, CURRENT, FIXED, EQUITY, etc.)",
                        },
                        "classType": {
                            "type": "string",
                            "description": "Filter by account class (ASSET, EQUITY, EXPENSE, LIABILITY, REVENUE)",
                            "enum": [
                                "ASSET",
                                "EQUITY",
                                "EXPENSE",
                                "LIABILITY",
                                "REVENUE",
                            ],
                        },
                        "status": {
                            "type": "string",
                            "description": "Filter by account status",
                            "enum": ["ACTIVE", "ARCHIVED", "DELETED"],
                        },
                    },
                },
            ),
            Tool(
                name="list_contacts",
                description="Retrieve a list of contacts from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "integer",
                            "description": "Page number for pagination (starts at 1)",
                            "minimum": 1,
                        },
                        "searchTerm": {
                            "type": "string",
                            "description": "Search term to filter contacts by name",
                        },
                    },
                },
            ),
            Tool(
                name="list_invoices",
                description="Retrieve a list of invoices from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "integer",
                            "description": "Page number for pagination (starts at 1)",
                            "minimum": 1,
                        },
                        "contactIds": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter invoices by contact IDs",
                        },
                        "invoiceNumbers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter invoices by invoice numbers",
                        },
                    },
                },
            ),
            Tool(
                name="list_items",
                description="Retrieve a list of items from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="list_payments",
                description="Retrieve a list of payments from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "integer",
                            "description": "Page number for pagination (starts at 1)",
                            "minimum": 1,
                        },
                    },
                },
            ),
            Tool(
                name="list_quotes",
                description="Retrieve a list of quotes from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "integer",
                            "description": "Page number for pagination (starts at 1)",
                            "minimum": 1,
                        },
                    },
                },
            ),
            Tool(
                name="list_purchase_orders",
                description="Retrieve a list of purchase orders from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "Filter by purchase order status",
                        },
                        "dateFrom": {
                            "type": "string",
                            "description": "Only include purchase orders on or after this date (YYYY-MM-DD)",
                        },
                        "dateTo": {
                            "type": "string",
                            "description": "Only include purchase orders on or before this date (YYYY-MM-DD)",
                        },
                        "order": {
                            "type": "string",
                            "description": "Sort order expression accepted by Xero (e.g., PurchaseOrderNumber ASC)",
                        },
                        "page": {
                            "type": "integer",
                            "description": "Page number for pagination (starts at 1)",
                            "minimum": 1,
                        },
                        "pageSize": {
                            "type": "integer",
                            "description": "Number of records to retrieve per page",
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                },
            ),
            Tool(
                name="list_credit_notes",
                description="Retrieve a list of credit notes from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "integer",
                            "description": "Page number for pagination (starts at 1)",
                            "minimum": 1,
                        },
                    },
                },
            ),
            Tool(
                name="list_bank_transactions",
                description="Retrieve a list of bank account transactions from Xero. Supports filtering by status (e.g., AUTHORISED for unreconciled transactions) and bank account.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "integer",
                            "description": "Page number for pagination (starts at 1)",
                            "minimum": 1,
                        },
                        "bankAccountId": {
                            "type": "string",
                            "description": "Filter by bank account ID",
                        },
                        "status": {
                            "type": "string",
                            "description": "Filter by transaction status (AUTHORISED = unreconciled, DELETED = removed)",
                            "enum": ["AUTHORISED", "DELETED"],
                        },
                    },
                },
            ),
            Tool(
                name="list_bank_transfers",
                description="Retrieve a list of bank transfers from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "fromAccountId": {
                            "type": "string",
                            "description": "Filter by source bank account ID",
                        },
                        "toAccountId": {
                            "type": "string",
                            "description": "Filter by destination bank account ID",
                        },
                        "where": {
                            "type": "string",
                            "description": "Raw Xero where clause to apply",
                        },
                        "order": {
                            "type": "string",
                            "description": "Sort order expression accepted by Xero",
                        },
                    },
                },
            ),
            Tool(
                name="list_batch_payments",
                description="Retrieve a list of batch payments from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "Filter by batch payment status",
                        },
                        "accountId": {
                            "type": "string",
                            "description": "Filter by bank account ID",
                        },
                        "where": {
                            "type": "string",
                            "description": "Raw Xero where clause to apply",
                        },
                        "order": {
                            "type": "string",
                            "description": "Sort order expression accepted by Xero",
                        },
                    },
                },
            ),
            Tool(
                name="list_overpayments",
                description="Retrieve a list of overpayments from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "Filter by overpayment status",
                        },
                        "references": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by a list of overpayment references",
                        },
                        "where": {
                            "type": "string",
                            "description": "Raw Xero where clause to apply",
                        },
                        "order": {
                            "type": "string",
                            "description": "Sort order expression accepted by Xero",
                        },
                        "page": {
                            "type": "integer",
                            "description": "Page number for pagination (starts at 1)",
                            "minimum": 1,
                        },
                        "pageSize": {
                            "type": "integer",
                            "description": "Number of records to retrieve per page",
                            "minimum": 1,
                            "maximum": 100,
                        },
                        "unitdp": {
                            "type": "integer",
                            "description": "Optional unit decimal places precision override",
                        },
                    },
                },
            ),
            Tool(
                name="list_prepayments",
                description="Retrieve a list of prepayments from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "Filter by prepayment status",
                        },
                        "invoiceNumbers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by a list of related invoice numbers",
                        },
                        "where": {
                            "type": "string",
                            "description": "Raw Xero where clause to apply",
                        },
                        "order": {
                            "type": "string",
                            "description": "Sort order expression accepted by Xero",
                        },
                        "page": {
                            "type": "integer",
                            "description": "Page number for pagination (starts at 1)",
                            "minimum": 1,
                        },
                        "pageSize": {
                            "type": "integer",
                            "description": "Number of records to retrieve per page",
                            "minimum": 1,
                            "maximum": 100,
                        },
                        "unitdp": {
                            "type": "integer",
                            "description": "Optional unit decimal places precision override",
                        },
                    },
                },
            ),
            Tool(
                name="list_manual_journals",
                description="Retrieve a list of manual journals from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "integer",
                            "description": "Page number for pagination (starts at 1)",
                            "minimum": 1,
                        },
                    },
                },
            ),
            Tool(
                name="list_tax_rates",
                description="Retrieve a list of tax rates from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="list_tracking_categories",
                description="Retrieve a list of tracking categories from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="list_contact_groups",
                description="Retrieve a list of contact groups from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="list_organisation_details",
                description="Retrieve details about the connected Xero organisation",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="list_profit_and_loss",
                description="Retrieve a profit and loss report from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "fromDate": {
                            "type": "string",
                            "description": "Start date for the report (YYYY-MM-DD)",
                        },
                        "toDate": {
                            "type": "string",
                            "description": "End date for the report (YYYY-MM-DD)",
                        },
                        "periods": {
                            "type": "integer",
                            "description": "Number of periods to compare",
                        },
                        "timeframe": {
                            "type": "string",
                            "description": "Period size (MONTH, QUARTER, YEAR)",
                            "enum": ["MONTH", "QUARTER", "YEAR"],
                        },
                    },
                },
            ),
            Tool(
                name="list_report_balance_sheet",
                description="Retrieve a balance sheet report from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Balance date for the report (YYYY-MM-DD)",
                        },
                        "periods": {
                            "type": "integer",
                            "description": "Number of periods to compare",
                        },
                        "timeframe": {
                            "type": "string",
                            "description": "Period size (MONTH, QUARTER, YEAR)",
                            "enum": ["MONTH", "QUARTER", "YEAR"],
                        },
                    },
                },
            ),
            Tool(
                name="list_trial_balance",
                description="Retrieve a trial balance report from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Date for the trial balance (YYYY-MM-DD)",
                        },
                    },
                },
            ),
            Tool(
                name="list_aged_receivables_by_contact",
                description="Retrieve aged receivables report for a specific contact",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contactId": {
                            "type": "string",
                            "description": "The contact ID to get aged receivables for",
                        },
                    },
                    "required": ["contactId"],
                },
            ),
            Tool(
                name="list_aged_payables_by_contact",
                description="Retrieve aged payables report for a specific contact",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contactId": {
                            "type": "string",
                            "description": "The contact ID to get aged payables for",
                        },
                    },
                    "required": ["contactId"],
                },
            ),
            Tool(
                name="list_payroll_employees",
                description="Retrieve a list of payroll employees from Xero (NZ/UK only)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "integer",
                            "description": "Page number for pagination (starts at 1)",
                            "minimum": 1,
                        },
                    },
                },
            ),
            Tool(
                name="list_payroll_employee_leave",
                description="Retrieve a payroll employee's leave records (NZ/UK only)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "employeeId": {
                            "type": "string",
                            "description": "The employee ID to get leave records for",
                        },
                    },
                    "required": ["employeeId"],
                },
            ),
            Tool(
                name="list_payroll_employee_leave_balances",
                description="Retrieve a payroll employee's leave balances (NZ/UK only)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "employeeId": {
                            "type": "string",
                            "description": "The employee ID to get leave balances for",
                        },
                    },
                    "required": ["employeeId"],
                },
            ),
            Tool(
                name="list_payroll_leave_types",
                description="Retrieve a list of all available leave types in Xero Payroll (NZ/UK only)",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="list_timesheets",
                description="Retrieve a list of payroll timesheets from Xero (NZ/UK only)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "integer",
                            "description": "Page number for pagination (starts at 1)",
                            "minimum": 1,
                        },
                    },
                },
            ),
            # ==================== CREATE OPERATIONS ====================
            Tool(
                name="create_contact",
                description="Create a new contact in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Contact name (required)",
                        },
                        "firstName": {
                            "type": "string",
                            "description": "First name of the contact",
                        },
                        "lastName": {
                            "type": "string",
                            "description": "Last name of the contact",
                        },
                        "email": {
                            "type": "string",
                            "description": "Email address of the contact",
                        },
                        "phone": {
                            "type": "string",
                            "description": "Phone number of the contact",
                        },
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="create_invoice",
                description="Create a new invoice in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contactId": {
                            "type": "string",
                            "description": "The contact ID for the invoice",
                        },
                        "type": {
                            "type": "string",
                            "description": "Invoice type: ACCREC (sales) or ACCPAY (bills)",
                            "enum": ["ACCREC", "ACCPAY"],
                        },
                        "lineItems": {
                            "type": "array",
                            "description": "Line items for the invoice",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {
                                        "type": "string",
                                        "description": "Description of the line item",
                                    },
                                    "quantity": {
                                        "type": "number",
                                        "description": "Quantity of the line item",
                                    },
                                    "unitAmount": {
                                        "type": "number",
                                        "description": "Unit price of the line item",
                                    },
                                    "accountCode": {
                                        "type": "string",
                                        "description": "Account code for the line item",
                                    },
                                    "taxType": {
                                        "type": "string",
                                        "description": "Tax type for the line item",
                                    },
                                    "itemCode": {
                                        "type": "string",
                                        "description": "Item code (optional)",
                                    },
                                    "tracking": {
                                        "type": "array",
                                        "description": "Tracking categories (max 2)",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "trackingCategoryID": {
                                                    "type": "string"
                                                },
                                                "trackingOptionID": {"type": "string"},
                                            },
                                        },
                                    },
                                },
                                "required": [
                                    "description",
                                    "quantity",
                                    "unitAmount",
                                    "accountCode",
                                ],
                            },
                        },
                        "date": {
                            "type": "string",
                            "description": "Invoice date (YYYY-MM-DD). Defaults to today.",
                        },
                        "dueDate": {
                            "type": "string",
                            "description": "Due date (YYYY-MM-DD). Defaults to 30 days from today.",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Reference number for the invoice",
                        },
                        "currencyCode": {
                            "type": "string",
                            "description": "Currency code (e.g., USD, NZD, GBP)",
                        },
                    },
                    "required": ["contactId", "type", "lineItems"],
                },
            ),
            Tool(
                name="create_item",
                description="Create a new item in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Unique code for the item",
                        },
                        "name": {
                            "type": "string",
                            "description": "Name of the item",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the item for sales",
                        },
                        "purchaseDescription": {
                            "type": "string",
                            "description": "Description of the item for purchases",
                        },
                        "purchaseUnitPrice": {
                            "type": "number",
                            "description": "Purchase unit price",
                        },
                        "purchaseAccountCode": {
                            "type": "string",
                            "description": "Account code for purchases",
                        },
                        "purchaseTaxType": {
                            "type": "string",
                            "description": "Tax type for purchases",
                        },
                        "salesUnitPrice": {
                            "type": "number",
                            "description": "Sales unit price",
                        },
                        "salesAccountCode": {
                            "type": "string",
                            "description": "Account code for sales",
                        },
                        "salesTaxType": {
                            "type": "string",
                            "description": "Tax type for sales",
                        },
                    },
                    "required": ["code", "name"],
                },
            ),
            Tool(
                name="create_payment",
                description="Create a new payment in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "invoiceId": {
                            "type": "string",
                            "description": "The invoice ID to apply the payment to",
                        },
                        "accountId": {
                            "type": "string",
                            "description": "The bank account ID for the payment",
                        },
                        "amount": {
                            "type": "number",
                            "description": "Payment amount",
                        },
                        "date": {
                            "type": "string",
                            "description": "Payment date (YYYY-MM-DD)",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Payment reference",
                        },
                    },
                    "required": ["invoiceId", "accountId", "amount", "date"],
                },
            ),
            Tool(
                name="create_quote",
                description="Create a new quote in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contactId": {
                            "type": "string",
                            "description": "The contact ID for the quote",
                        },
                        "lineItems": {
                            "type": "array",
                            "description": "Line items for the quote",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {
                                        "type": "string",
                                        "description": "Description of the line item",
                                    },
                                    "quantity": {
                                        "type": "number",
                                        "description": "Quantity",
                                    },
                                    "unitAmount": {
                                        "type": "number",
                                        "description": "Unit price",
                                    },
                                    "accountCode": {
                                        "type": "string",
                                        "description": "Account code",
                                    },
                                    "taxType": {
                                        "type": "string",
                                        "description": "Tax type",
                                    },
                                },
                                "required": [
                                    "description",
                                    "quantity",
                                    "unitAmount",
                                    "accountCode",
                                ],
                            },
                        },
                        "date": {
                            "type": "string",
                            "description": "Quote date (YYYY-MM-DD)",
                        },
                        "expiryDate": {
                            "type": "string",
                            "description": "Quote expiry date (YYYY-MM-DD)",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Reference for the quote",
                        },
                        "currencyCode": {
                            "type": "string",
                            "description": "Currency code (e.g., USD, NZD, GBP)",
                        },
                    },
                    "required": ["contactId", "lineItems"],
                },
            ),
            Tool(
                name="create_purchase_order",
                description="Create a new purchase order in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contactId": {
                            "type": "string",
                            "description": "The contact ID for the purchase order",
                        },
                        "lineItems": {
                            "type": "array",
                            "description": "Line items for the purchase order",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string"},
                                    "quantity": {"type": "number"},
                                    "unitAmount": {"type": "number"},
                                    "accountCode": {"type": "string"},
                                    "taxType": {"type": "string"},
                                    "itemCode": {"type": "string"},
                                    "tracking": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "trackingCategoryID": {
                                                    "type": "string"
                                                },
                                                "trackingOptionID": {"type": "string"},
                                            },
                                        },
                                    },
                                },
                                "required": [
                                    "description",
                                    "quantity",
                                    "unitAmount",
                                    "accountCode",
                                ],
                            },
                        },
                        "date": {
                            "type": "string",
                            "description": "Purchase order date (YYYY-MM-DD). Defaults to today.",
                        },
                        "deliveryDate": {
                            "type": "string",
                            "description": "Expected delivery date (YYYY-MM-DD)",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Reference for the purchase order",
                        },
                        "currencyCode": {
                            "type": "string",
                            "description": "Currency code (e.g., USD, NZD, GBP)",
                        },
                        "attentionTo": {
                            "type": "string",
                            "description": "Optional attention-to field for the purchase order",
                        },
                        "status": {
                            "type": "string",
                            "description": "Purchase order status. Defaults to DRAFT.",
                        },
                    },
                    "required": ["contactId", "lineItems"],
                },
            ),
            Tool(
                name="create_bank_transaction",
                description="Create a new bank transaction in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "description": "Transaction type: RECEIVE or SPEND",
                            "enum": ["RECEIVE", "SPEND"],
                        },
                        "contactId": {
                            "type": "string",
                            "description": "The contact ID for the transaction",
                        },
                        "bankAccountId": {
                            "type": "string",
                            "description": "The bank account ID for the transaction",
                        },
                        "lineItems": {
                            "type": "array",
                            "description": "Line items for the transaction",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {
                                        "type": "string",
                                        "description": "Description",
                                    },
                                    "quantity": {
                                        "type": "number",
                                        "description": "Quantity",
                                    },
                                    "unitAmount": {
                                        "type": "number",
                                        "description": "Unit price",
                                    },
                                    "accountCode": {
                                        "type": "string",
                                        "description": "Account code",
                                    },
                                    "taxType": {
                                        "type": "string",
                                        "description": "Tax type",
                                    },
                                },
                                "required": [
                                    "description",
                                    "quantity",
                                    "unitAmount",
                                    "accountCode",
                                ],
                            },
                        },
                        "date": {
                            "type": "string",
                            "description": "Transaction date (YYYY-MM-DD)",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Transaction reference",
                        },
                    },
                    "required": ["type", "contactId", "bankAccountId", "lineItems"],
                },
            ),
            Tool(
                name="create_credit_note",
                description="Create a new credit note in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contactId": {
                            "type": "string",
                            "description": "The contact ID for the credit note",
                        },
                        "type": {
                            "type": "string",
                            "description": "Credit note type: ACCRECCREDIT (sales) or ACCPAYCREDIT (bills)",
                            "enum": ["ACCRECCREDIT", "ACCPAYCREDIT"],
                        },
                        "lineItems": {
                            "type": "array",
                            "description": "Line items for the credit note",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string"},
                                    "quantity": {"type": "number"},
                                    "unitAmount": {"type": "number"},
                                    "accountCode": {"type": "string"},
                                    "taxType": {"type": "string"},
                                },
                                "required": [
                                    "description",
                                    "quantity",
                                    "unitAmount",
                                    "accountCode",
                                ],
                            },
                        },
                        "date": {
                            "type": "string",
                            "description": "Credit note date (YYYY-MM-DD)",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Reference for the credit note",
                        },
                    },
                    "required": ["contactId", "type", "lineItems"],
                },
            ),
            # ==================== TRANSFER & BATCH OPERATIONS ====================
            Tool(
                name="create_bank_transfer",
                description="Create a bank transfer between two bank accounts in Xero. Used for internal funds movement (e.g., transferring from Operating to Savings, or replenishing Petty Cash).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "fromAccountId": {
                            "type": "string",
                            "description": "The source bank account ID (AccountID of a BANK type account)",
                        },
                        "toAccountId": {
                            "type": "string",
                            "description": "The destination bank account ID (AccountID of a BANK type account)",
                        },
                        "amount": {
                            "type": "number",
                            "description": "Transfer amount (must be positive)",
                            "exclusiveMinimum": 0,
                        },
                        "date": {
                            "type": "string",
                            "description": "Transfer date (YYYY-MM-DD). Defaults to today if not provided.",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Optional reference for the transfer",
                        },
                    },
                    "required": ["fromAccountId", "toAccountId", "amount"],
                },
            ),
            Tool(
                name="create_batch_payment",
                description="Create a batch payment in Xero to pay multiple invoices in a single transaction. Used for reconciliation when one bank line matches multiple invoices.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "accountId": {
                            "type": "string",
                            "description": "The bank account ID the payment is made from/to",
                        },
                        "date": {
                            "type": "string",
                            "description": "Payment date (YYYY-MM-DD)",
                        },
                        "payments": {
                            "type": "array",
                            "description": "List of individual invoice payments within this batch",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "invoiceId": {
                                        "type": "string",
                                        "description": "The invoice ID to apply payment to",
                                    },
                                    "amount": {
                                        "type": "number",
                                        "description": "Payment amount for this invoice",
                                    },
                                },
                                "required": ["invoiceId", "amount"],
                            },
                        },
                        "reference": {
                            "type": "string",
                            "description": "Reference for the batch payment",
                        },
                        "narrative": {
                            "type": "string",
                            "description": "(UK Only) Shows on the statement line in Xero. Max length 18 characters.",
                            "maxLength": 18,
                        },
                        "details": {
                            "type": "string",
                            "description": "(Non-NZ Only) Bank reference for the batch payment. Shows in bank reconciliation Find & Match screen. Max length 18 characters.",
                            "maxLength": 18,
                        },
                    },
                    "required": ["accountId", "date", "payments"],
                },
            ),
            Tool(
                name="create_overpayment",
                description="Create an overpayment transaction in Xero. Used when a payment received or made exceeds the invoice balance. Creates a RECEIVE-OVERPAYMENT (customer overpaid) or SPEND-OVERPAYMENT (supplier overpaid) bank transaction.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "description": "Overpayment type: RECEIVE-OVERPAYMENT (customer overpaid us) or SPEND-OVERPAYMENT (we overpaid supplier)",
                            "enum": [
                                "RECEIVE-OVERPAYMENT",
                                "SPEND-OVERPAYMENT",
                            ],
                        },
                        "contactId": {
                            "type": "string",
                            "description": "The contact ID for the overpayment",
                        },
                        "bankAccountId": {
                            "type": "string",
                            "description": "The bank account ID for the overpayment",
                        },
                        "lineItems": {
                            "type": "array",
                            "description": "Line items describing the overpayment",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {
                                        "type": "string",
                                        "description": "Description of the overpayment",
                                    },
                                    "quantity": {
                                        "type": "number",
                                        "description": "Quantity (typically 1)",
                                    },
                                    "unitAmount": {
                                        "type": "number",
                                        "description": "Amount of the overpayment",
                                    },
                                    "accountCode": {
                                        "type": "string",
                                        "description": "Account code",
                                    },
                                    "taxType": {
                                        "type": "string",
                                        "description": "Tax type",
                                    },
                                },
                                "required": [
                                    "description",
                                    "quantity",
                                    "unitAmount",
                                    "accountCode",
                                ],
                            },
                        },
                        "date": {
                            "type": "string",
                            "description": "Transaction date (YYYY-MM-DD)",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Reference for the overpayment",
                        },
                    },
                    "required": [
                        "type",
                        "contactId",
                        "bankAccountId",
                        "lineItems",
                    ],
                },
            ),
            Tool(
                name="create_prepayment",
                description="Create a prepayment transaction in Xero. Used for advance payments before an invoice is raised. Creates a RECEIVE-PREPAYMENT (customer paid in advance) or SPEND-PREPAYMENT (we paid supplier in advance) bank transaction.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "description": "Prepayment type: RECEIVE-PREPAYMENT (customer prepaid) or SPEND-PREPAYMENT (we prepaid supplier)",
                            "enum": [
                                "RECEIVE-PREPAYMENT",
                                "SPEND-PREPAYMENT",
                            ],
                        },
                        "contactId": {
                            "type": "string",
                            "description": "The contact ID for the prepayment",
                        },
                        "bankAccountId": {
                            "type": "string",
                            "description": "The bank account ID for the prepayment",
                        },
                        "lineItems": {
                            "type": "array",
                            "description": "Line items describing the prepayment",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {
                                        "type": "string",
                                        "description": "Description of the prepayment",
                                    },
                                    "quantity": {
                                        "type": "number",
                                        "description": "Quantity (typically 1)",
                                    },
                                    "unitAmount": {
                                        "type": "number",
                                        "description": "Amount of the prepayment",
                                    },
                                    "accountCode": {
                                        "type": "string",
                                        "description": "Account code",
                                    },
                                    "taxType": {
                                        "type": "string",
                                        "description": "Tax type",
                                    },
                                },
                                "required": [
                                    "description",
                                    "quantity",
                                    "unitAmount",
                                    "accountCode",
                                ],
                            },
                        },
                        "date": {
                            "type": "string",
                            "description": "Transaction date (YYYY-MM-DD)",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Reference for the prepayment",
                        },
                    },
                    "required": [
                        "type",
                        "contactId",
                        "bankAccountId",
                        "lineItems",
                    ],
                },
            ),
            Tool(
                name="create_manual_journal",
                description="Create a new manual journal in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "narration": {
                            "type": "string",
                            "description": "Description/narration for the journal",
                        },
                        "journalLines": {
                            "type": "array",
                            "description": "Journal lines (must have at least 2 lines that balance to zero)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "lineAmount": {
                                        "type": "number",
                                        "description": "Amount (positive for debit, negative for credit)",
                                    },
                                    "accountCode": {
                                        "type": "string",
                                        "description": "Account code",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "Line description",
                                    },
                                    "taxType": {
                                        "type": "string",
                                        "description": "Tax type",
                                    },
                                    "tracking": {
                                        "type": "array",
                                        "description": "Tracking categories",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "trackingCategoryID": {
                                                    "type": "string"
                                                },
                                                "trackingOptionID": {"type": "string"},
                                            },
                                        },
                                    },
                                },
                                "required": ["lineAmount", "accountCode"],
                            },
                        },
                        "date": {
                            "type": "string",
                            "description": "Journal date (YYYY-MM-DD)",
                        },
                    },
                    "required": ["narration", "journalLines"],
                },
            ),
            Tool(
                name="create_payroll_timesheet",
                description="Create a new payroll timesheet in Xero (NZ/UK only)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "employeeId": {
                            "type": "string",
                            "description": "The employee ID for the timesheet",
                        },
                        "startDate": {
                            "type": "string",
                            "description": "Start date of the timesheet period (YYYY-MM-DD)",
                        },
                        "endDate": {
                            "type": "string",
                            "description": "End date of the timesheet period (YYYY-MM-DD)",
                        },
                        "timesheetLines": {
                            "type": "array",
                            "description": "Timesheet lines with hours",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "earningsRateID": {
                                        "type": "string",
                                        "description": "Earnings rate ID",
                                    },
                                    "numberOfUnits": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "description": "Hours for each day of the period",
                                    },
                                },
                                "required": ["earningsRateID", "numberOfUnits"],
                            },
                        },
                    },
                    "required": [
                        "employeeId",
                        "startDate",
                        "endDate",
                        "timesheetLines",
                    ],
                },
            ),
            Tool(
                name="create_tracking_category",
                description="Create a new tracking category in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the tracking category",
                        },
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="create_tracking_option",
                description="Create a new tracking option within a tracking category",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "trackingCategoryId": {
                            "type": "string",
                            "description": "The tracking category ID to add the option to",
                        },
                        "name": {
                            "type": "string",
                            "description": "Name of the tracking option",
                        },
                    },
                    "required": ["trackingCategoryId", "name"],
                },
            ),
            # ==================== UPDATE OPERATIONS ====================
            Tool(
                name="update_contact",
                description="Update an existing contact in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contactId": {
                            "type": "string",
                            "description": "The contact ID to update",
                        },
                        "name": {
                            "type": "string",
                            "description": "Updated contact name",
                        },
                        "firstName": {
                            "type": "string",
                            "description": "Updated first name",
                        },
                        "lastName": {
                            "type": "string",
                            "description": "Updated last name",
                        },
                        "email": {
                            "type": "string",
                            "description": "Updated email address",
                        },
                        "phone": {
                            "type": "string",
                            "description": "Updated phone number",
                        },
                        "address": {
                            "type": "object",
                            "description": "Updated address",
                            "properties": {
                                "addressLine1": {"type": "string"},
                                "addressLine2": {"type": "string"},
                                "city": {"type": "string"},
                                "region": {"type": "string"},
                                "postalCode": {"type": "string"},
                                "country": {"type": "string"},
                            },
                        },
                    },
                    "required": ["contactId"],
                },
            ),
            Tool(
                name="update_invoice",
                description="Update an existing draft invoice in Xero (only DRAFT invoices can be updated)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "invoiceId": {
                            "type": "string",
                            "description": "The invoice ID to update",
                        },
                        "date": {
                            "type": "string",
                            "description": "Updated invoice date (YYYY-MM-DD)",
                        },
                        "dueDate": {
                            "type": "string",
                            "description": "Updated due date (YYYY-MM-DD)",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Updated reference",
                        },
                        "lineItems": {
                            "type": "array",
                            "description": "Updated line items (replaces existing)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string"},
                                    "quantity": {"type": "number"},
                                    "unitAmount": {"type": "number"},
                                    "accountCode": {"type": "string"},
                                    "taxType": {"type": "string"},
                                    "itemCode": {"type": "string"},
                                },
                                "required": [
                                    "description",
                                    "quantity",
                                    "unitAmount",
                                    "accountCode",
                                ],
                            },
                        },
                        "status": {
                            "type": "string",
                            "description": "Updated invoice status. Use AUTHORISED to push the draft into the invoices section in Xero. Allowed transitions from DRAFT: SUBMITTED, AUTHORISED, DELETED.",
                            "enum": ["DRAFT", "SUBMITTED", "AUTHORISED", "DELETED"],
                        },
                    },
                    "required": ["invoiceId"],
                },
            ),
            Tool(
                name="update_item",
                description="Update an existing item in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "itemId": {
                            "type": "string",
                            "description": "The item ID to update",
                        },
                        "code": {
                            "type": "string",
                            "description": "Updated item code",
                        },
                        "name": {
                            "type": "string",
                            "description": "Updated item name",
                        },
                        "description": {
                            "type": "string",
                            "description": "Updated sales description",
                        },
                        "purchaseDescription": {
                            "type": "string",
                            "description": "Updated purchase description",
                        },
                        "purchaseUnitPrice": {
                            "type": "number",
                            "description": "Updated purchase unit price",
                        },
                        "purchaseAccountCode": {
                            "type": "string",
                            "description": "Updated purchase account code",
                        },
                        "salesUnitPrice": {
                            "type": "number",
                            "description": "Updated sales unit price",
                        },
                        "salesAccountCode": {
                            "type": "string",
                            "description": "Updated sales account code",
                        },
                    },
                    "required": ["itemId"],
                },
            ),
            Tool(
                name="update_quote",
                description="Update an existing draft quote in Xero (only DRAFT quotes can be updated)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "quoteId": {
                            "type": "string",
                            "description": "The quote ID to update",
                        },
                        "date": {
                            "type": "string",
                            "description": "Updated quote date (YYYY-MM-DD)",
                        },
                        "expiryDate": {
                            "type": "string",
                            "description": "Updated expiry date (YYYY-MM-DD)",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Updated reference",
                        },
                        "lineItems": {
                            "type": "array",
                            "description": "Updated line items",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string"},
                                    "quantity": {"type": "number"},
                                    "unitAmount": {"type": "number"},
                                    "accountCode": {"type": "string"},
                                    "taxType": {"type": "string"},
                                },
                                "required": [
                                    "description",
                                    "quantity",
                                    "unitAmount",
                                    "accountCode",
                                ],
                            },
                        },
                    },
                    "required": ["quoteId"],
                },
            ),
            Tool(
                name="update_purchase_order",
                description="Update an existing draft purchase order in Xero (only DRAFT purchase orders can be updated)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "purchaseOrderId": {
                            "type": "string",
                            "description": "The purchase order ID to update",
                        },
                        "date": {
                            "type": "string",
                            "description": "Updated purchase order date (YYYY-MM-DD)",
                        },
                        "deliveryDate": {
                            "type": "string",
                            "description": "Updated delivery date (YYYY-MM-DD)",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Updated reference",
                        },
                        "currencyCode": {
                            "type": "string",
                            "description": "Updated currency code",
                        },
                        "attentionTo": {
                            "type": "string",
                            "description": "Updated attention-to value",
                        },
                        "status": {
                            "type": "string",
                            "description": "Updated purchase order status",
                        },
                        "lineItems": {
                            "type": "array",
                            "description": "Updated line items",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string"},
                                    "quantity": {"type": "number"},
                                    "unitAmount": {"type": "number"},
                                    "accountCode": {"type": "string"},
                                    "taxType": {"type": "string"},
                                    "itemCode": {"type": "string"},
                                    "tracking": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "trackingCategoryID": {
                                                    "type": "string"
                                                },
                                                "trackingOptionID": {"type": "string"},
                                            },
                                        },
                                    },
                                },
                                "required": [
                                    "description",
                                    "quantity",
                                    "unitAmount",
                                    "accountCode",
                                ],
                            },
                        },
                    },
                    "required": ["purchaseOrderId"],
                },
            ),
            Tool(
                name="update_bank_transaction",
                description="Update an existing bank transaction in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "transactionId": {
                            "type": "string",
                            "description": "The bank transaction ID to update",
                        },
                        "date": {
                            "type": "string",
                            "description": "Updated transaction date (YYYY-MM-DD)",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Updated reference",
                        },
                        "lineItems": {
                            "type": "array",
                            "description": "Updated line items",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string"},
                                    "quantity": {"type": "number"},
                                    "unitAmount": {"type": "number"},
                                    "accountCode": {"type": "string"},
                                    "taxType": {"type": "string"},
                                },
                                "required": [
                                    "description",
                                    "quantity",
                                    "unitAmount",
                                    "accountCode",
                                ],
                            },
                        },
                    },
                    "required": ["transactionId"],
                },
            ),
            Tool(
                name="update_credit_note",
                description="Update an existing draft credit note in Xero (only DRAFT credit notes can be updated)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "creditNoteId": {
                            "type": "string",
                            "description": "The credit note ID to update",
                        },
                        "date": {
                            "type": "string",
                            "description": "Updated date (YYYY-MM-DD)",
                        },
                        "reference": {
                            "type": "string",
                            "description": "Updated reference",
                        },
                        "lineItems": {
                            "type": "array",
                            "description": "Updated line items",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string"},
                                    "quantity": {"type": "number"},
                                    "unitAmount": {"type": "number"},
                                    "accountCode": {"type": "string"},
                                    "taxType": {"type": "string"},
                                },
                                "required": [
                                    "description",
                                    "quantity",
                                    "unitAmount",
                                    "accountCode",
                                ],
                            },
                        },
                    },
                    "required": ["creditNoteId"],
                },
            ),
            Tool(
                name="update_manual_journal",
                description="Update an existing manual journal in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "manualJournalId": {
                            "type": "string",
                            "description": "The manual journal ID to update",
                        },
                        "narration": {
                            "type": "string",
                            "description": "Updated narration/description",
                        },
                        "journalLines": {
                            "type": "array",
                            "description": "Updated journal lines",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "lineAmount": {"type": "number"},
                                    "accountCode": {"type": "string"},
                                    "description": {"type": "string"},
                                    "taxType": {"type": "string"},
                                },
                                "required": ["lineAmount", "accountCode"],
                            },
                        },
                        "date": {
                            "type": "string",
                            "description": "Updated journal date (YYYY-MM-DD)",
                        },
                    },
                    "required": ["manualJournalId"],
                },
            ),
            Tool(
                name="update_tracking_category",
                description="Update an existing tracking category in Xero",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "trackingCategoryId": {
                            "type": "string",
                            "description": "The tracking category ID to update",
                        },
                        "name": {
                            "type": "string",
                            "description": "Updated name for the tracking category",
                        },
                    },
                    "required": ["trackingCategoryId", "name"],
                },
            ),
            Tool(
                name="update_tracking_options",
                description="Update tracking options within a tracking category",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "trackingCategoryId": {
                            "type": "string",
                            "description": "The tracking category ID",
                        },
                        "optionId": {
                            "type": "string",
                            "description": "The tracking option ID to update",
                        },
                        "name": {
                            "type": "string",
                            "description": "Updated name for the tracking option",
                        },
                    },
                    "required": ["trackingCategoryId", "optionId", "name"],
                },
            ),
            Tool(
                name="update_payroll_timesheet_line",
                description="Update a line on an existing payroll timesheet (NZ/UK only)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "timesheetId": {
                            "type": "string",
                            "description": "The timesheet ID to update",
                        },
                        "timesheetLines": {
                            "type": "array",
                            "description": "Updated timesheet lines",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "earningsRateID": {"type": "string"},
                                    "numberOfUnits": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                    },
                                },
                                "required": ["earningsRateID", "numberOfUnits"],
                            },
                        },
                    },
                    "required": ["timesheetId", "timesheetLines"],
                },
            ),
            Tool(
                name="add_payroll_timesheet_line",
                description="Add a new line to an existing payroll timesheet (NZ/UK only)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "timesheetId": {
                            "type": "string",
                            "description": "The timesheet ID to add lines to",
                        },
                        "timesheetLines": {
                            "type": "array",
                            "description": "New timesheet lines to add",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "earningsRateID": {"type": "string"},
                                    "numberOfUnits": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                    },
                                },
                                "required": ["earningsRateID", "numberOfUnits"],
                            },
                        },
                    },
                    "required": ["timesheetId", "timesheetLines"],
                },
            ),
            # ==================== OTHER OPERATIONS ====================
            Tool(
                name="approve_payroll_timesheet",
                description="Approve a payroll timesheet (NZ/UK only)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "timesheetId": {
                            "type": "string",
                            "description": "The timesheet ID to approve",
                        },
                    },
                    "required": ["timesheetId"],
                },
            ),
            Tool(
                name="revert_payroll_timesheet",
                description="Revert an approved payroll timesheet back to draft (NZ/UK only)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "timesheetId": {
                            "type": "string",
                            "description": "The timesheet ID to revert",
                        },
                    },
                    "required": ["timesheetId"],
                },
            ),
            Tool(
                name="delete_payroll_timesheet",
                description="Delete a payroll timesheet (NZ/UK only)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "timesheetId": {
                            "type": "string",
                            "description": "The timesheet ID to delete",
                        },
                    },
                    "required": ["timesheetId"],
                },
            ),
            Tool(
                name="get_payroll_timesheet",
                description="Retrieve a specific payroll timesheet by ID (NZ/UK only)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "timesheetId": {
                            "type": "string",
                            "description": "The timesheet ID to retrieve",
                        },
                    },
                    "required": ["timesheetId"],
                },
            ),
            # ==================== ATTACHMENT OPERATIONS ====================
            Tool(
                name="list_attachments",
                description="List all attachments for a Xero entity (invoice, credit note, contact, etc.)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entityType": {
                            "type": "string",
                            "description": "The type of Xero entity",
                            "enum": list(ATTACHMENT_ENTITY_TYPES.keys()),
                        },
                        "entityId": {
                            "type": "string",
                            "description": "The ID (GUID) of the entity to list attachments for",
                        },
                    },
                    "required": ["entityType", "entityId"],
                },
            ),
            Tool(
                name="get_attachment",
                description="Get a temporary download URL for a Xero attachment",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entityType": {
                            "type": "string",
                            "description": "The type of Xero entity the attachment belongs to",
                            "enum": list(ATTACHMENT_ENTITY_TYPES.keys()),
                        },
                        "entityId": {
                            "type": "string",
                            "description": "The ID (GUID) of the entity the attachment belongs to",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Filename of the attachment (from list_attachments results)",
                        },
                        "mime_type": {
                            "type": "string",
                            "description": "MIME type of the attachment (from list_attachments results)",
                        },
                    },
                    "required": ["entityType", "entityId", "filename"],
                },
            ),
            Tool(
                name="add_attachment",
                description="Create a new attachment on a supported Xero entity from base64-encoded file content",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entityType": {
                            "type": "string",
                            "description": "The type of Xero entity the attachment belongs to",
                            "enum": list(ATTACHMENT_ENTITY_TYPES.keys()),
                        },
                        "entityId": {
                            "type": "string",
                            "description": "The ID (GUID) of the entity the attachment belongs to",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Filename to create in Xero",
                        },
                        "contentBase64": {
                            "type": "string",
                            "description": "Base64-encoded file content",
                        },
                        "mimeType": {
                            "type": "string",
                            "description": "MIME type for the uploaded attachment",
                        },
                        "includeOnline": {
                            "type": "boolean",
                            "description": "For invoices only, whether the attachment should be included online",
                        },
                        "idempotencyKey": {
                            "type": "string",
                            "description": "Optional Xero idempotency key",
                        },
                    },
                    "required": ["entityType", "entityId", "filename", "contentBase64"],
                },
            ),
            Tool(
                name="upload_attachment",
                description="Update or overwrite an existing Xero attachment from base64-encoded file content",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entityType": {
                            "type": "string",
                            "description": "The type of Xero entity the attachment belongs to",
                            "enum": list(ATTACHMENT_ENTITY_TYPES.keys()),
                        },
                        "entityId": {
                            "type": "string",
                            "description": "The ID (GUID) of the entity the attachment belongs to",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Filename to update in Xero",
                        },
                        "contentBase64": {
                            "type": "string",
                            "description": "Base64-encoded file content",
                        },
                        "mimeType": {
                            "type": "string",
                            "description": "MIME type for the uploaded attachment",
                        },
                        "idempotencyKey": {
                            "type": "string",
                            "description": "Optional Xero idempotency key",
                        },
                    },
                    "required": ["entityType", "entityId", "filename", "contentBase64"],
                },
            ),
            Tool(
                name="get_invoice_pdf",
                description="Download the rendered PDF of a Xero invoice and return a temporary download URL",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "invoiceId": {
                            "type": "string",
                            "description": "The InvoiceID (GUID) or InvoiceNumber of the invoice",
                        },
                    },
                    "required": ["invoiceId"],
                },
            ),
            Tool(
                name="email_invoice",
                description="Send a copy of an invoice to its related contact via Xero email",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "invoiceId": {
                            "type": "string",
                            "description": "The InvoiceID (GUID) of the invoice to email",
                        },
                        "idempotencyKey": {
                            "type": "string",
                            "description": "Optional Xero idempotency key",
                        },
                    },
                    "required": ["invoiceId"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[TextContent | ImageContent | EmbeddedResource]:
        """
        Handle tool invocation from the MCP system.

        Args:
            name: The name of the tool being called.
            arguments: Parameters passed to the tool.

        Returns:
            List of content objects with tool execution results.
        """
        logger.info(
            f"User {server.user_id} calling tool: {name} with arguments: {arguments}"
        )

        if arguments is None:
            arguments = {}

        try:
            access_token, tenant_id = await get_xero_credentials(
                server.user_id, api_key=server.api_key
            )

            # ==================== LIST OPERATIONS ====================

            if name == "list_accounts":
                params = {}
                where_clauses = []
                if arguments.get("type"):
                    where_clauses.append(f'Type=="{arguments["type"]}"')
                if arguments.get("classType"):
                    where_clauses.append(f'Class=="{arguments["classType"]}"')
                if arguments.get("status"):
                    where_clauses.append(f'Status=="{arguments["status"]}"')
                if where_clauses:
                    params["where"] = " AND ".join(where_clauses)

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Accounts",
                    access_token,
                    tenant_id,
                    params=params if params else None,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_contacts":
                params = {}
                page = arguments.get("page")
                search_term = arguments.get("searchTerm")
                if page:
                    params["page"] = page
                if search_term:
                    params["where"] = f'Name.Contains("{search_term}")'
                params["order"] = "Name ASC"

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Contacts",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_invoices":
                params = {"order": "Date DESC", "pageSize": 10}
                page = arguments.get("page", 1)
                params["page"] = page

                contact_ids = arguments.get("contactIds")
                invoice_numbers = arguments.get("invoiceNumbers")
                if contact_ids:
                    params["ContactIDs"] = ",".join(contact_ids)
                if invoice_numbers:
                    params["InvoiceNumbers"] = ",".join(invoice_numbers)

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Invoices",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_items":
                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Items",
                    access_token,
                    tenant_id,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_payments":
                params = {"order": "Date DESC"}
                page = arguments.get("page")
                if page:
                    params["page"] = page

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Payments",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_quotes":
                params = {"order": "DateString DESC"}
                page = arguments.get("page")
                if page:
                    params["page"] = page

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Quotes",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_purchase_orders":
                params = {"order": arguments.get("order", "PurchaseOrderNumber ASC")}
                if arguments.get("status"):
                    params["status"] = arguments["status"]
                if arguments.get("dateFrom"):
                    params["dateFrom"] = arguments["dateFrom"]
                if arguments.get("dateTo"):
                    params["dateTo"] = arguments["dateTo"]
                if arguments.get("page"):
                    params["page"] = arguments["page"]
                if arguments.get("pageSize"):
                    params["pageSize"] = arguments["pageSize"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/PurchaseOrders",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_credit_notes":
                params = {"order": "Date DESC"}
                page = arguments.get("page")
                if page:
                    params["page"] = page

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/CreditNotes",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_bank_transactions":
                params = {"order": "Date DESC"}
                page = arguments.get("page")
                bank_account_id = arguments.get("bankAccountId")
                status = arguments.get("status")
                if page:
                    params["page"] = page

                where_clauses = []
                if bank_account_id:
                    where_clauses.append(
                        f'BankAccount.AccountID==Guid("{bank_account_id}")'
                    )
                if status:
                    where_clauses.append(f'Status=="{status}"')
                if where_clauses:
                    params["where"] = " AND ".join(where_clauses)

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/BankTransactions",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_bank_transfers":
                params = {"order": arguments.get("order", "Date DESC")}
                where_clauses = []
                if arguments.get("fromAccountId"):
                    where_clauses.append(
                        f'FromBankAccount.AccountID==Guid("{arguments["fromAccountId"]}")'
                    )
                if arguments.get("toAccountId"):
                    where_clauses.append(
                        f'ToBankAccount.AccountID==Guid("{arguments["toAccountId"]}")'
                    )
                if arguments.get("where"):
                    where_clauses.append(arguments["where"])
                if where_clauses:
                    params["where"] = " AND ".join(where_clauses)

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/BankTransfers",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_batch_payments":
                params = {"order": arguments.get("order", "Date DESC")}
                where_clauses = []
                if arguments.get("status"):
                    where_clauses.append(f'Status=="{arguments["status"]}"')
                if arguments.get("accountId"):
                    where_clauses.append(
                        f'Account.AccountID==Guid("{arguments["accountId"]}")'
                    )
                if arguments.get("where"):
                    where_clauses.append(arguments["where"])
                if where_clauses:
                    params["where"] = " AND ".join(where_clauses)

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/BatchPayments",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_overpayments":
                params = {"order": arguments.get("order", "Date DESC")}
                if arguments.get("status"):
                    params["where"] = f'Status=="{arguments["status"]}"'
                if arguments.get("where"):
                    params["where"] = arguments["where"]
                if arguments.get("page"):
                    params["page"] = arguments["page"]
                if arguments.get("pageSize"):
                    params["pageSize"] = arguments["pageSize"]
                if arguments.get("unitdp"):
                    params["unitdp"] = arguments["unitdp"]
                if arguments.get("references"):
                    params["References"] = ",".join(arguments["references"])

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Overpayments",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_prepayments":
                params = {"order": arguments.get("order", "Date DESC")}
                if arguments.get("status"):
                    params["where"] = f'Status=="{arguments["status"]}"'
                if arguments.get("where"):
                    params["where"] = arguments["where"]
                if arguments.get("page"):
                    params["page"] = arguments["page"]
                if arguments.get("pageSize"):
                    params["pageSize"] = arguments["pageSize"]
                if arguments.get("unitdp"):
                    params["unitdp"] = arguments["unitdp"]
                if arguments.get("invoiceNumbers"):
                    params["InvoiceNumbers"] = ",".join(arguments["invoiceNumbers"])

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Prepayments",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_manual_journals":
                params = {"order": "Date DESC"}
                page = arguments.get("page")
                if page:
                    params["page"] = page

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/ManualJournals",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_tax_rates":
                result = await call_xero_api(
                    f"{ACCOUNTING_API}/TaxRates",
                    access_token,
                    tenant_id,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_tracking_categories":
                result = await call_xero_api(
                    f"{ACCOUNTING_API}/TrackingCategories",
                    access_token,
                    tenant_id,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_contact_groups":
                result = await call_xero_api(
                    f"{ACCOUNTING_API}/ContactGroups",
                    access_token,
                    tenant_id,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_organisation_details":
                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Organisation",
                    access_token,
                    tenant_id,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_profit_and_loss":
                params = {}
                if arguments.get("fromDate"):
                    params["fromDate"] = arguments["fromDate"]
                if arguments.get("toDate"):
                    params["toDate"] = arguments["toDate"]
                if arguments.get("periods"):
                    params["periods"] = arguments["periods"]
                if arguments.get("timeframe"):
                    params["timeframe"] = arguments["timeframe"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Reports/ProfitAndLoss",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_report_balance_sheet":
                params = {}
                if arguments.get("date"):
                    params["date"] = arguments["date"]
                if arguments.get("periods"):
                    params["periods"] = arguments["periods"]
                if arguments.get("timeframe"):
                    params["timeframe"] = arguments["timeframe"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Reports/BalanceSheet",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_trial_balance":
                params = {}
                if arguments.get("date"):
                    params["date"] = arguments["date"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Reports/TrialBalance",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_aged_receivables_by_contact":
                contact_id = arguments.get("contactId")
                if not contact_id:
                    raise ValueError("contactId is required")

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Reports/AgedReceivablesByContact",
                    access_token,
                    tenant_id,
                    params={"contactId": contact_id},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_aged_payables_by_contact":
                contact_id = arguments.get("contactId")
                if not contact_id:
                    raise ValueError("contactId is required")

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Reports/AgedPayablesByContact",
                    access_token,
                    tenant_id,
                    params={"contactId": contact_id},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_payroll_employees":
                params = {}
                page = arguments.get("page")
                if page:
                    params["page"] = page

                result = await call_xero_api(
                    f"{PAYROLL_API}/Employees",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_payroll_employee_leave":
                employee_id = arguments.get("employeeId")
                if not employee_id:
                    raise ValueError("employeeId is required")

                result = await call_xero_api(
                    f"{PAYROLL_API}/Employees/{employee_id}/Leave",
                    access_token,
                    tenant_id,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_payroll_employee_leave_balances":
                employee_id = arguments.get("employeeId")
                if not employee_id:
                    raise ValueError("employeeId is required")

                result = await call_xero_api(
                    f"{PAYROLL_API}/Employees/{employee_id}/LeaveBalances",
                    access_token,
                    tenant_id,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_payroll_leave_types":
                result = await call_xero_api(
                    f"{PAYROLL_API}/LeaveTypes",
                    access_token,
                    tenant_id,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_timesheets":
                params = {}
                page = arguments.get("page")
                if page:
                    params["page"] = page

                result = await call_xero_api(
                    f"{PAYROLL_API}/Timesheets",
                    access_token,
                    tenant_id,
                    params=params,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            # ==================== CREATE OPERATIONS ====================

            elif name == "create_contact":
                contact_name = arguments.get("name")
                if not contact_name:
                    raise ValueError("name is required")

                contact = {"Name": contact_name}

                if arguments.get("firstName"):
                    contact["FirstName"] = arguments["firstName"]
                if arguments.get("lastName"):
                    contact["LastName"] = arguments["lastName"]
                if arguments.get("email"):
                    contact["EmailAddress"] = arguments["email"]
                if arguments.get("phone"):
                    contact["Phones"] = [
                        {
                            "PhoneNumber": arguments["phone"],
                            "PhoneType": "MOBILE",
                        }
                    ]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Contacts",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Contacts": [contact]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_invoice":
                contact_id = arguments.get("contactId")
                invoice_type = arguments.get("type")
                line_items_input = arguments.get("lineItems", [])

                if not contact_id or not invoice_type or not line_items_input:
                    raise ValueError("contactId, type, and lineItems are required")

                # Build line items
                line_items = []
                for item in line_items_input:
                    line_item = {
                        "Description": item.get("description", ""),
                        "Quantity": item.get("quantity", 1),
                        "UnitAmount": item.get("unitAmount", 0),
                        "AccountCode": item.get("accountCode", ""),
                    }
                    if item.get("taxType"):
                        line_item["TaxType"] = item["taxType"]
                    if item.get("itemCode"):
                        line_item["ItemCode"] = item["itemCode"]
                    if item.get("tracking"):
                        line_item["Tracking"] = [
                            {
                                "TrackingCategoryID": t.get("trackingCategoryID"),
                                "TrackingOptionID": t.get("trackingOptionID"),
                            }
                            for t in item["tracking"]
                        ]
                    line_items.append(line_item)

                today = datetime.now().strftime("%Y-%m-%d")
                due_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

                invoice = {
                    "Type": invoice_type,
                    "Contact": {"ContactID": contact_id},
                    "LineItems": line_items,
                    "Date": arguments.get("date", today),
                    "DueDate": arguments.get("dueDate", due_date),
                    "Status": "DRAFT",
                }

                if arguments.get("reference"):
                    invoice["Reference"] = arguments["reference"]
                if arguments.get("currencyCode"):
                    invoice["CurrencyCode"] = arguments["currencyCode"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Invoices",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Invoices": [invoice]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_item":
                code = arguments.get("code")
                item_name = arguments.get("name")
                if not code or not item_name:
                    raise ValueError("code and name are required")

                item = {"Code": code, "Name": item_name}

                # Sales details
                has_sales = any(
                    arguments.get(k)
                    for k in [
                        "description",
                        "salesUnitPrice",
                        "salesAccountCode",
                        "salesTaxType",
                    ]
                )
                if has_sales:
                    item["IsSold"] = True
                    if arguments.get("description"):
                        item["Description"] = arguments["description"]
                    sales_details = {}
                    if arguments.get("salesUnitPrice") is not None:
                        sales_details["UnitPrice"] = arguments["salesUnitPrice"]
                    if arguments.get("salesAccountCode"):
                        sales_details["AccountCode"] = arguments["salesAccountCode"]
                    if arguments.get("salesTaxType"):
                        sales_details["TaxType"] = arguments["salesTaxType"]
                    if sales_details:
                        item["SalesDetails"] = sales_details

                # Purchase details
                has_purchase = any(
                    arguments.get(k)
                    for k in [
                        "purchaseDescription",
                        "purchaseUnitPrice",
                        "purchaseAccountCode",
                        "purchaseTaxType",
                    ]
                )
                if has_purchase:
                    item["IsPurchased"] = True
                    if arguments.get("purchaseDescription"):
                        item["PurchaseDescription"] = arguments["purchaseDescription"]
                    purchase_details = {}
                    if arguments.get("purchaseUnitPrice") is not None:
                        purchase_details["UnitPrice"] = arguments["purchaseUnitPrice"]
                    if arguments.get("purchaseAccountCode"):
                        purchase_details["AccountCode"] = arguments[
                            "purchaseAccountCode"
                        ]
                    if arguments.get("purchaseTaxType"):
                        purchase_details["TaxType"] = arguments["purchaseTaxType"]
                    if purchase_details:
                        item["PurchaseDetails"] = purchase_details

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Items",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Items": [item]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_payment":
                invoice_id = arguments.get("invoiceId")
                account_id = arguments.get("accountId")
                amount = arguments.get("amount")
                date = arguments.get("date")

                if not all([invoice_id, account_id, amount, date]):
                    raise ValueError(
                        "invoiceId, accountId, amount, and date are required"
                    )

                payment = {
                    "Invoice": {"InvoiceID": invoice_id},
                    "Account": {"AccountID": account_id},
                    "Amount": amount,
                    "Date": date,
                }

                if arguments.get("reference"):
                    payment["Reference"] = arguments["reference"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Payments",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Payments": [payment]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_quote":
                contact_id = arguments.get("contactId")
                line_items_input = arguments.get("lineItems", [])

                if not contact_id or not line_items_input:
                    raise ValueError("contactId and lineItems are required")

                line_items = []
                for item in line_items_input:
                    line_item = {
                        "Description": item.get("description", ""),
                        "Quantity": item.get("quantity", 1),
                        "UnitAmount": item.get("unitAmount", 0),
                        "AccountCode": item.get("accountCode", ""),
                    }
                    if item.get("taxType"):
                        line_item["TaxType"] = item["taxType"]
                    line_items.append(line_item)

                today = datetime.now().strftime("%Y-%m-%d")
                expiry = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

                quote = {
                    "Contact": {"ContactID": contact_id},
                    "LineItems": line_items,
                    "Date": arguments.get("date", today),
                    "ExpiryDate": arguments.get("expiryDate", expiry),
                    "Status": "DRAFT",
                }

                if arguments.get("reference"):
                    quote["Reference"] = arguments["reference"]
                if arguments.get("currencyCode"):
                    quote["CurrencyCode"] = arguments["currencyCode"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Quotes",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Quotes": [quote]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_purchase_order":
                contact_id = arguments.get("contactId")
                line_items_input = arguments.get("lineItems", [])

                if not contact_id or not line_items_input:
                    raise ValueError("contactId and lineItems are required")

                purchase_order = {
                    "Contact": {"ContactID": contact_id},
                    "LineItems": build_line_items_payload(line_items_input),
                    "Date": arguments.get("date", datetime.now().strftime("%Y-%m-%d")),
                    "Status": arguments.get("status", "DRAFT"),
                }

                if arguments.get("deliveryDate"):
                    purchase_order["DeliveryDate"] = arguments["deliveryDate"]
                if arguments.get("reference"):
                    purchase_order["Reference"] = arguments["reference"]
                if arguments.get("currencyCode"):
                    purchase_order["CurrencyCode"] = arguments["currencyCode"]
                if arguments.get("attentionTo"):
                    purchase_order["AttentionTo"] = arguments["attentionTo"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/PurchaseOrders",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"PurchaseOrders": [purchase_order]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_bank_transaction":
                tx_type = arguments.get("type")
                contact_id = arguments.get("contactId")
                bank_account_id = arguments.get("bankAccountId")
                line_items_input = arguments.get("lineItems", [])

                if not all([tx_type, contact_id, bank_account_id, line_items_input]):
                    raise ValueError(
                        "type, contactId, bankAccountId, and lineItems are required"
                    )

                line_items = []
                for item in line_items_input:
                    line_item = {
                        "Description": item.get("description", ""),
                        "Quantity": item.get("quantity", 1),
                        "UnitAmount": item.get("unitAmount", 0),
                        "AccountCode": item.get("accountCode", ""),
                    }
                    if item.get("taxType"):
                        line_item["TaxType"] = item["taxType"]
                    line_items.append(line_item)

                transaction = {
                    "Type": tx_type,
                    "Contact": {"ContactID": contact_id},
                    "BankAccount": {"AccountID": bank_account_id},
                    "LineItems": line_items,
                }

                if arguments.get("date"):
                    transaction["Date"] = arguments["date"]
                if arguments.get("reference"):
                    transaction["Reference"] = arguments["reference"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/BankTransactions",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"BankTransactions": [transaction]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_credit_note":
                contact_id = arguments.get("contactId")
                cn_type = arguments.get("type")
                line_items_input = arguments.get("lineItems", [])

                if not all([contact_id, cn_type, line_items_input]):
                    raise ValueError("contactId, type, and lineItems are required")

                line_items = []
                for item in line_items_input:
                    line_item = {
                        "Description": item.get("description", ""),
                        "Quantity": item.get("quantity", 1),
                        "UnitAmount": item.get("unitAmount", 0),
                        "AccountCode": item.get("accountCode", ""),
                    }
                    if item.get("taxType"):
                        line_item["TaxType"] = item["taxType"]
                    line_items.append(line_item)

                credit_note = {
                    "Type": cn_type,
                    "Contact": {"ContactID": contact_id},
                    "LineItems": line_items,
                    "Status": "DRAFT",
                }

                if arguments.get("date"):
                    credit_note["Date"] = arguments["date"]
                if arguments.get("reference"):
                    credit_note["Reference"] = arguments["reference"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/CreditNotes",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"CreditNotes": [credit_note]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            # ==================== TRANSFER & BATCH OPERATIONS ====================

            elif name == "create_bank_transfer":
                from_account_id = arguments.get("fromAccountId")
                to_account_id = arguments.get("toAccountId")
                amount = arguments.get("amount")

                if not all([from_account_id, to_account_id, amount]):
                    raise ValueError(
                        "fromAccountId, toAccountId, and amount are required"
                    )

                if amount <= 0:
                    raise ValueError("Transfer amount must be positive")

                transfer = {
                    "FromBankAccount": {"AccountID": from_account_id},
                    "ToBankAccount": {"AccountID": to_account_id},
                    "Amount": amount,
                }

                if arguments.get("date"):
                    transfer["Date"] = arguments["date"]
                else:
                    transfer["Date"] = datetime.now().strftime("%Y-%m-%d")
                if arguments.get("reference"):
                    transfer["Reference"] = arguments["reference"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/BankTransfers",
                    access_token,
                    tenant_id,
                    method="PUT",
                    data={"BankTransfers": [transfer]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_batch_payment":
                account_id = arguments.get("accountId")
                date = arguments.get("date")
                payments_input = arguments.get("payments", [])

                if not all([account_id, date, payments_input]):
                    raise ValueError("accountId, date, and payments are required")

                payments = []
                for p in payments_input:
                    invoice_id = p.get("invoiceId")
                    amount = p.get("amount")
                    if not invoice_id or amount is None:
                        raise ValueError(
                            "Each payment must include invoiceId and amount"
                        )
                    payments.append(
                        {
                            "Invoice": {"InvoiceID": invoice_id},
                            "Amount": amount,
                        }
                    )

                batch_payment = {
                    "Account": {"AccountID": account_id},
                    "Date": date,
                    "Payments": payments,
                }

                if arguments.get("reference"):
                    batch_payment["Reference"] = arguments["reference"]
                if arguments.get("narrative"):
                    batch_payment["Narrative"] = arguments["narrative"]
                if arguments.get("details"):
                    batch_payment["Details"] = arguments["details"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/BatchPayments",
                    access_token,
                    tenant_id,
                    method="PUT",
                    data={"BatchPayments": [batch_payment]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_overpayment":
                op_type = arguments.get("type")
                contact_id = arguments.get("contactId")
                bank_account_id = arguments.get("bankAccountId")
                line_items_input = arguments.get("lineItems", [])

                if not all([op_type, contact_id, bank_account_id, line_items_input]):
                    raise ValueError(
                        "type, contactId, bankAccountId, and lineItems are required"
                    )

                line_items = []
                for item in line_items_input:
                    line_item = {
                        "Description": item.get("description", ""),
                        "Quantity": item.get("quantity", 1),
                        "UnitAmount": item.get("unitAmount", 0),
                        "AccountCode": item.get("accountCode", ""),
                    }
                    if item.get("taxType"):
                        line_item["TaxType"] = item["taxType"]
                    line_items.append(line_item)

                transaction = {
                    "Type": op_type,
                    "Contact": {"ContactID": contact_id},
                    "BankAccount": {"AccountID": bank_account_id},
                    "LineItems": line_items,
                }

                if arguments.get("date"):
                    transaction["Date"] = arguments["date"]
                if arguments.get("reference"):
                    transaction["Reference"] = arguments["reference"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/BankTransactions",
                    access_token,
                    tenant_id,
                    method="PUT",
                    data={"BankTransactions": [transaction]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_prepayment":
                pp_type = arguments.get("type")
                contact_id = arguments.get("contactId")
                bank_account_id = arguments.get("bankAccountId")
                line_items_input = arguments.get("lineItems", [])

                if not all([pp_type, contact_id, bank_account_id, line_items_input]):
                    raise ValueError(
                        "type, contactId, bankAccountId, and lineItems are required"
                    )

                line_items = []
                for item in line_items_input:
                    line_item = {
                        "Description": item.get("description", ""),
                        "Quantity": item.get("quantity", 1),
                        "UnitAmount": item.get("unitAmount", 0),
                        "AccountCode": item.get("accountCode", ""),
                    }
                    if item.get("taxType"):
                        line_item["TaxType"] = item["taxType"]
                    line_items.append(line_item)

                transaction = {
                    "Type": pp_type,
                    "Contact": {"ContactID": contact_id},
                    "BankAccount": {"AccountID": bank_account_id},
                    "LineItems": line_items,
                }

                if arguments.get("date"):
                    transaction["Date"] = arguments["date"]
                if arguments.get("reference"):
                    transaction["Reference"] = arguments["reference"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/BankTransactions",
                    access_token,
                    tenant_id,
                    method="PUT",
                    data={"BankTransactions": [transaction]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_manual_journal":
                narration = arguments.get("narration")
                journal_lines_input = arguments.get("journalLines", [])

                if not narration or not journal_lines_input:
                    raise ValueError("narration and journalLines are required")

                journal_lines = []
                for line in journal_lines_input:
                    journal_line = {
                        "LineAmount": line.get("lineAmount", 0),
                        "AccountCode": line.get("accountCode", ""),
                    }
                    if line.get("description"):
                        journal_line["Description"] = line["description"]
                    if line.get("taxType"):
                        journal_line["TaxType"] = line["taxType"]
                    if line.get("tracking"):
                        journal_line["Tracking"] = [
                            {
                                "TrackingCategoryID": t.get("trackingCategoryID"),
                                "TrackingOptionID": t.get("trackingOptionID"),
                            }
                            for t in line["tracking"]
                        ]
                    journal_lines.append(journal_line)

                journal = {
                    "Narration": narration,
                    "JournalLines": journal_lines,
                }

                if arguments.get("date"):
                    journal["Date"] = arguments["date"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/ManualJournals",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"ManualJournals": [journal]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_payroll_timesheet":
                employee_id = arguments.get("employeeId")
                start_date = arguments.get("startDate")
                end_date = arguments.get("endDate")
                timesheet_lines_input = arguments.get("timesheetLines", [])

                if not all([employee_id, start_date, end_date, timesheet_lines_input]):
                    raise ValueError(
                        "employeeId, startDate, endDate, and timesheetLines are required"
                    )

                timesheet_lines = []
                for line in timesheet_lines_input:
                    timesheet_lines.append(
                        {
                            "EarningsRateID": line.get("earningsRateID"),
                            "NumberOfUnits": line.get("numberOfUnits", []),
                        }
                    )

                timesheet = {
                    "EmployeeID": employee_id,
                    "StartDate": start_date,
                    "EndDate": end_date,
                    "TimesheetLines": timesheet_lines,
                }

                result = await call_xero_api(
                    f"{PAYROLL_API}/Timesheets",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Timesheets": [timesheet]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_tracking_category":
                category_name = arguments.get("name")
                if not category_name:
                    raise ValueError("name is required")

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/TrackingCategories",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Name": category_name},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_tracking_option":
                tracking_category_id = arguments.get("trackingCategoryId")
                option_name = arguments.get("name")
                if not tracking_category_id or not option_name:
                    raise ValueError("trackingCategoryId and name are required")

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/TrackingCategories/{tracking_category_id}/Options",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Name": option_name},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            # ==================== UPDATE OPERATIONS ====================

            elif name == "update_contact":
                contact_id = arguments.get("contactId")
                if not contact_id:
                    raise ValueError("contactId is required")

                contact = {"ContactID": contact_id}

                if arguments.get("name"):
                    contact["Name"] = arguments["name"]
                if arguments.get("firstName"):
                    contact["FirstName"] = arguments["firstName"]
                if arguments.get("lastName"):
                    contact["LastName"] = arguments["lastName"]
                if arguments.get("email"):
                    contact["EmailAddress"] = arguments["email"]
                if arguments.get("phone"):
                    contact["Phones"] = [
                        {
                            "PhoneNumber": arguments["phone"],
                            "PhoneType": "MOBILE",
                        }
                    ]
                if arguments.get("address"):
                    addr = arguments["address"]
                    address_obj = {"AddressType": "STREET"}
                    if addr.get("addressLine1"):
                        address_obj["AddressLine1"] = addr["addressLine1"]
                    if addr.get("addressLine2"):
                        address_obj["AddressLine2"] = addr["addressLine2"]
                    if addr.get("city"):
                        address_obj["City"] = addr["city"]
                    if addr.get("region"):
                        address_obj["Region"] = addr["region"]
                    if addr.get("postalCode"):
                        address_obj["PostalCode"] = addr["postalCode"]
                    if addr.get("country"):
                        address_obj["Country"] = addr["country"]
                    contact["Addresses"] = [address_obj]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Contacts/{contact_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Contacts": [contact]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "update_invoice":
                invoice_id = arguments.get("invoiceId")
                if not invoice_id:
                    raise ValueError("invoiceId is required")

                # First, verify the invoice is in DRAFT status
                existing = await call_xero_api(
                    f"{ACCOUNTING_API}/Invoices/{invoice_id}",
                    access_token,
                    tenant_id,
                )
                invoices = existing.get("Invoices", [])
                if invoices and invoices[0].get("Status") != "DRAFT":
                    raise ValueError(
                        f"Only DRAFT invoices can be updated. "
                        f"Current status: {invoices[0].get('Status')}"
                    )

                invoice = {"InvoiceID": invoice_id}

                if arguments.get("date"):
                    invoice["Date"] = arguments["date"]
                if arguments.get("dueDate"):
                    invoice["DueDate"] = arguments["dueDate"]
                if arguments.get("reference"):
                    invoice["Reference"] = arguments["reference"]
                if arguments.get("lineItems"):
                    line_items = []
                    for item in arguments["lineItems"]:
                        line_item = {
                            "Description": item.get("description", ""),
                            "Quantity": item.get("quantity", 1),
                            "UnitAmount": item.get("unitAmount", 0),
                            "AccountCode": item.get("accountCode", ""),
                        }
                        if item.get("taxType"):
                            line_item["TaxType"] = item["taxType"]
                        if item.get("itemCode"):
                            line_item["ItemCode"] = item["itemCode"]
                        line_items.append(line_item)
                    invoice["LineItems"] = line_items
                if arguments.get("status"):
                    invoice["Status"] = arguments["status"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Invoices/{invoice_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Invoices": [invoice]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "update_item":
                item_id = arguments.get("itemId")
                if not item_id:
                    raise ValueError("itemId is required")

                item = {"ItemID": item_id}

                if arguments.get("code"):
                    item["Code"] = arguments["code"]
                if arguments.get("name"):
                    item["Name"] = arguments["name"]
                if arguments.get("description"):
                    item["Description"] = arguments["description"]
                if arguments.get("purchaseDescription"):
                    item["PurchaseDescription"] = arguments["purchaseDescription"]

                # Sales details
                sales_details = {}
                if arguments.get("salesUnitPrice") is not None:
                    sales_details["UnitPrice"] = arguments["salesUnitPrice"]
                if arguments.get("salesAccountCode"):
                    sales_details["AccountCode"] = arguments["salesAccountCode"]
                if sales_details:
                    item["SalesDetails"] = sales_details

                # Purchase details
                purchase_details = {}
                if arguments.get("purchaseUnitPrice") is not None:
                    purchase_details["UnitPrice"] = arguments["purchaseUnitPrice"]
                if arguments.get("purchaseAccountCode"):
                    purchase_details["AccountCode"] = arguments["purchaseAccountCode"]
                if purchase_details:
                    item["PurchaseDetails"] = purchase_details

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Items/{item_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Items": [item]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "update_quote":
                quote_id = arguments.get("quoteId")
                if not quote_id:
                    raise ValueError("quoteId is required")

                # Verify DRAFT status
                existing = await call_xero_api(
                    f"{ACCOUNTING_API}/Quotes/{quote_id}",
                    access_token,
                    tenant_id,
                )
                quotes = existing.get("Quotes", [])
                if quotes and quotes[0].get("Status") != "DRAFT":
                    raise ValueError(
                        f"Only DRAFT quotes can be updated. "
                        f"Current status: {quotes[0].get('Status')}"
                    )

                quote = {"QuoteID": quote_id}

                if arguments.get("date"):
                    quote["Date"] = arguments["date"]
                if arguments.get("expiryDate"):
                    quote["ExpiryDate"] = arguments["expiryDate"]
                if arguments.get("reference"):
                    quote["Reference"] = arguments["reference"]
                if arguments.get("lineItems"):
                    line_items = []
                    for item in arguments["lineItems"]:
                        line_item = {
                            "Description": item.get("description", ""),
                            "Quantity": item.get("quantity", 1),
                            "UnitAmount": item.get("unitAmount", 0),
                            "AccountCode": item.get("accountCode", ""),
                        }
                        if item.get("taxType"):
                            line_item["TaxType"] = item["taxType"]
                        line_items.append(line_item)
                    quote["LineItems"] = line_items

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Quotes/{quote_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Quotes": [quote]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "update_purchase_order":
                purchase_order_id = arguments.get("purchaseOrderId")
                if not purchase_order_id:
                    raise ValueError("purchaseOrderId is required")

                existing = await call_xero_api(
                    f"{ACCOUNTING_API}/PurchaseOrders/{purchase_order_id}",
                    access_token,
                    tenant_id,
                )
                purchase_orders = existing.get("PurchaseOrders", [])
                if purchase_orders and purchase_orders[0].get("Status") != "DRAFT":
                    raise ValueError(
                        f"Only DRAFT purchase orders can be updated. "
                        f"Current status: {purchase_orders[0].get('Status')}"
                    )

                purchase_order = {"PurchaseOrderID": purchase_order_id}

                if arguments.get("date"):
                    purchase_order["Date"] = arguments["date"]
                if arguments.get("deliveryDate"):
                    purchase_order["DeliveryDate"] = arguments["deliveryDate"]
                if arguments.get("reference"):
                    purchase_order["Reference"] = arguments["reference"]
                if arguments.get("currencyCode"):
                    purchase_order["CurrencyCode"] = arguments["currencyCode"]
                if arguments.get("attentionTo"):
                    purchase_order["AttentionTo"] = arguments["attentionTo"]
                if arguments.get("status"):
                    purchase_order["Status"] = arguments["status"]
                if arguments.get("lineItems"):
                    purchase_order["LineItems"] = build_line_items_payload(
                        arguments["lineItems"]
                    )

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/PurchaseOrders/{purchase_order_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"PurchaseOrders": [purchase_order]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "update_bank_transaction":
                transaction_id = arguments.get("transactionId")
                if not transaction_id:
                    raise ValueError("transactionId is required")

                transaction = {"BankTransactionID": transaction_id}

                if arguments.get("date"):
                    transaction["Date"] = arguments["date"]
                if arguments.get("reference"):
                    transaction["Reference"] = arguments["reference"]
                if arguments.get("lineItems"):
                    line_items = []
                    for item in arguments["lineItems"]:
                        line_item = {
                            "Description": item.get("description", ""),
                            "Quantity": item.get("quantity", 1),
                            "UnitAmount": item.get("unitAmount", 0),
                            "AccountCode": item.get("accountCode", ""),
                        }
                        if item.get("taxType"):
                            line_item["TaxType"] = item["taxType"]
                        line_items.append(line_item)
                    transaction["LineItems"] = line_items

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/BankTransactions/{transaction_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"BankTransactions": [transaction]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "update_credit_note":
                credit_note_id = arguments.get("creditNoteId")
                if not credit_note_id:
                    raise ValueError("creditNoteId is required")

                # Verify DRAFT status
                existing = await call_xero_api(
                    f"{ACCOUNTING_API}/CreditNotes/{credit_note_id}",
                    access_token,
                    tenant_id,
                )
                notes = existing.get("CreditNotes", [])
                if notes and notes[0].get("Status") != "DRAFT":
                    raise ValueError(
                        f"Only DRAFT credit notes can be updated. "
                        f"Current status: {notes[0].get('Status')}"
                    )

                credit_note = {"CreditNoteID": credit_note_id}

                if arguments.get("date"):
                    credit_note["Date"] = arguments["date"]
                if arguments.get("reference"):
                    credit_note["Reference"] = arguments["reference"]
                if arguments.get("lineItems"):
                    line_items = []
                    for item in arguments["lineItems"]:
                        line_item = {
                            "Description": item.get("description", ""),
                            "Quantity": item.get("quantity", 1),
                            "UnitAmount": item.get("unitAmount", 0),
                            "AccountCode": item.get("accountCode", ""),
                        }
                        if item.get("taxType"):
                            line_item["TaxType"] = item["taxType"]
                        line_items.append(line_item)
                    credit_note["LineItems"] = line_items

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/CreditNotes/{credit_note_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"CreditNotes": [credit_note]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "update_manual_journal":
                manual_journal_id = arguments.get("manualJournalId")
                if not manual_journal_id:
                    raise ValueError("manualJournalId is required")

                journal = {"ManualJournalID": manual_journal_id}

                if arguments.get("narration"):
                    journal["Narration"] = arguments["narration"]
                if arguments.get("date"):
                    journal["Date"] = arguments["date"]
                if arguments.get("journalLines"):
                    journal_lines = []
                    for line in arguments["journalLines"]:
                        journal_line = {
                            "LineAmount": line.get("lineAmount", 0),
                            "AccountCode": line.get("accountCode", ""),
                        }
                        if line.get("description"):
                            journal_line["Description"] = line["description"]
                        if line.get("taxType"):
                            journal_line["TaxType"] = line["taxType"]
                        journal_lines.append(journal_line)
                    journal["JournalLines"] = journal_lines

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/ManualJournals/{manual_journal_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"ManualJournals": [journal]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "update_tracking_category":
                tracking_category_id = arguments.get("trackingCategoryId")
                category_name = arguments.get("name")
                if not tracking_category_id or not category_name:
                    raise ValueError("trackingCategoryId and name are required")

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/TrackingCategories/{tracking_category_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Name": category_name},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "update_tracking_options":
                tracking_category_id = arguments.get("trackingCategoryId")
                option_id = arguments.get("optionId")
                option_name = arguments.get("name")
                if not all([tracking_category_id, option_id, option_name]):
                    raise ValueError(
                        "trackingCategoryId, optionId, and name are required"
                    )

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/TrackingCategories/{tracking_category_id}/Options/{option_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Name": option_name},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "update_payroll_timesheet_line":
                timesheet_id = arguments.get("timesheetId")
                timesheet_lines_input = arguments.get("timesheetLines", [])
                if not timesheet_id or not timesheet_lines_input:
                    raise ValueError("timesheetId and timesheetLines are required")

                # Get existing timesheet to merge
                existing = await call_xero_api(
                    f"{PAYROLL_API}/Timesheets/{timesheet_id}",
                    access_token,
                    tenant_id,
                )

                timesheet_lines = []
                for line in timesheet_lines_input:
                    timesheet_lines.append(
                        {
                            "EarningsRateID": line.get("earningsRateID"),
                            "NumberOfUnits": line.get("numberOfUnits", []),
                        }
                    )

                timesheet = {
                    "TimesheetID": timesheet_id,
                    "TimesheetLines": timesheet_lines,
                }

                result = await call_xero_api(
                    f"{PAYROLL_API}/Timesheets/{timesheet_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Timesheets": [timesheet]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "add_payroll_timesheet_line":
                timesheet_id = arguments.get("timesheetId")
                timesheet_lines_input = arguments.get("timesheetLines", [])
                if not timesheet_id or not timesheet_lines_input:
                    raise ValueError("timesheetId and timesheetLines are required")

                # Get existing timesheet and append new lines
                existing = await call_xero_api(
                    f"{PAYROLL_API}/Timesheets/{timesheet_id}",
                    access_token,
                    tenant_id,
                )

                existing_lines = []
                timesheets = existing.get("Timesheets", [])
                if timesheets:
                    existing_lines = timesheets[0].get("TimesheetLines", [])

                new_lines = []
                for line in timesheet_lines_input:
                    new_lines.append(
                        {
                            "EarningsRateID": line.get("earningsRateID"),
                            "NumberOfUnits": line.get("numberOfUnits", []),
                        }
                    )

                all_lines = existing_lines + new_lines

                timesheet = {
                    "TimesheetID": timesheet_id,
                    "TimesheetLines": all_lines,
                }

                result = await call_xero_api(
                    f"{PAYROLL_API}/Timesheets/{timesheet_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Timesheets": [timesheet]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            # ==================== OTHER OPERATIONS ====================

            elif name == "approve_payroll_timesheet":
                timesheet_id = arguments.get("timesheetId")
                if not timesheet_id:
                    raise ValueError("timesheetId is required")

                # Get existing timesheet
                existing = await call_xero_api(
                    f"{PAYROLL_API}/Timesheets/{timesheet_id}",
                    access_token,
                    tenant_id,
                )

                timesheets = existing.get("Timesheets", [])
                if not timesheets:
                    raise ValueError(f"Timesheet {timesheet_id} not found")

                timesheet = timesheets[0]
                timesheet["Status"] = "Approved"

                result = await call_xero_api(
                    f"{PAYROLL_API}/Timesheets/{timesheet_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Timesheets": [timesheet]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "revert_payroll_timesheet":
                timesheet_id = arguments.get("timesheetId")
                if not timesheet_id:
                    raise ValueError("timesheetId is required")

                existing = await call_xero_api(
                    f"{PAYROLL_API}/Timesheets/{timesheet_id}",
                    access_token,
                    tenant_id,
                )

                timesheets = existing.get("Timesheets", [])
                if not timesheets:
                    raise ValueError(f"Timesheet {timesheet_id} not found")

                timesheet = timesheets[0]
                timesheet["Status"] = "Draft"

                result = await call_xero_api(
                    f"{PAYROLL_API}/Timesheets/{timesheet_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Timesheets": [timesheet]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "delete_payroll_timesheet":
                timesheet_id = arguments.get("timesheetId")
                if not timesheet_id:
                    raise ValueError("timesheetId is required")

                existing = await call_xero_api(
                    f"{PAYROLL_API}/Timesheets/{timesheet_id}",
                    access_token,
                    tenant_id,
                )

                timesheets = existing.get("Timesheets", [])
                if not timesheets:
                    raise ValueError(f"Timesheet {timesheet_id} not found")

                timesheet = timesheets[0]
                timesheet["Status"] = "Deleted"

                result = await call_xero_api(
                    f"{PAYROLL_API}/Timesheets/{timesheet_id}",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={"Timesheets": [timesheet]},
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_payroll_timesheet":
                timesheet_id = arguments.get("timesheetId")
                if not timesheet_id:
                    raise ValueError("timesheetId is required")

                result = await call_xero_api(
                    f"{PAYROLL_API}/Timesheets/{timesheet_id}",
                    access_token,
                    tenant_id,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            # ==================== ATTACHMENT OPERATIONS ====================

            elif name == "list_attachments":
                entity_type = arguments.get("entityType")
                entity_id = arguments.get("entityId")
                if not entity_type or not entity_id:
                    raise ValueError("entityType and entityId are required")

                if entity_type not in ATTACHMENT_ENTITY_TYPES:
                    raise ValueError(
                        f"Unsupported entity type: {entity_type}. "
                        f"Supported types: {', '.join(ATTACHMENT_ENTITY_TYPES.keys())}"
                    )

                endpoint = ATTACHMENT_ENTITY_TYPES[entity_type]
                result = await call_xero_api(
                    f"{ACCOUNTING_API}/{endpoint}/{entity_id}/Attachments",
                    access_token,
                    tenant_id,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_attachment":
                entity_type = arguments.get("entityType")
                entity_id = arguments.get("entityId")
                filename = arguments.get("filename")
                if not entity_type or not entity_id or not filename:
                    raise ValueError("entityType, entityId, and filename are required")

                if entity_type not in ATTACHMENT_ENTITY_TYPES:
                    raise ValueError(
                        f"Unsupported entity type: {entity_type}. "
                        f"Supported types: {', '.join(ATTACHMENT_ENTITY_TYPES.keys())}"
                    )

                mime_type = arguments.get("mime_type", "application/octet-stream")
                endpoint = ATTACHMENT_ENTITY_TYPES[entity_type]

                # Download the attachment binary data from Xero
                att_data = await download_xero_attachment(
                    endpoint, entity_id, filename, access_token, tenant_id
                )
                if not att_data:
                    return [
                        TextContent(
                            type="text",
                            text=(
                                f"Failed to download attachment '{filename}' "
                                f"from {entity_type}/{entity_id}."
                            ),
                        )
                    ]

                # Upload to storage and get signed URL
                storage = get_storage_service()
                download_url = storage.upload_temporary(
                    data=att_data,
                    filename=filename,
                    mime_type=mime_type,
                )

                size_kb = len(att_data) / 1024
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"Attachment: {filename}\n"
                            f"Type: {mime_type}\n"
                            f"Size: {size_kb:.1f} KB\n"
                            f"Download URL (expires in 1 hour): {download_url}"
                        ),
                    )
                ]

            elif name in {"add_attachment", "upload_attachment"}:
                from urllib.parse import quote

                entity_type = arguments.get("entityType")
                entity_id = arguments.get("entityId")
                filename = arguments.get("filename")
                content_base64 = arguments.get("contentBase64")
                if (
                    not entity_type
                    or not entity_id
                    or not filename
                    or not content_base64
                ):
                    raise ValueError(
                        "entityType, entityId, filename, and contentBase64 are required"
                    )

                if entity_type not in ATTACHMENT_ENTITY_TYPES:
                    raise ValueError(
                        f"Unsupported entity type: {entity_type}. "
                        f"Supported types: {', '.join(ATTACHMENT_ENTITY_TYPES.keys())}"
                    )

                endpoint = ATTACHMENT_ENTITY_TYPES[entity_type]
                mime_type = arguments.get("mimeType", "application/octet-stream")
                attachment_data = decode_base64_attachment(content_base64)
                params = None
                if name == "add_attachment" and entity_type == "Invoices":
                    include_online = arguments.get("includeOnline")
                    if include_online is not None:
                        params = {"includeOnline": include_online}

                extra_headers = {"Content-Type": mime_type}
                if arguments.get("idempotencyKey"):
                    extra_headers["Idempotency-Key"] = arguments["idempotencyKey"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/{endpoint}/{entity_id}/Attachments/{quote(filename, safe='')}",
                    access_token,
                    tenant_id,
                    method="POST" if name == "add_attachment" else "PUT",
                    params=params,
                    content=attachment_data,
                    extra_headers=extra_headers,
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_invoice_pdf":
                invoice_id = arguments.get("invoiceId")
                if not invoice_id:
                    raise ValueError("invoiceId is required")

                # Download the rendered invoice PDF from Xero
                pdf_data = await download_xero_invoice_pdf(
                    invoice_id, access_token, tenant_id
                )
                if not pdf_data:
                    return [
                        TextContent(
                            type="text",
                            text=f"Failed to download PDF for invoice {invoice_id}.",
                        )
                    ]

                # Use the invoice ID as the filename
                filename = f"{invoice_id}.pdf"

                # Upload to storage and get signed URL
                storage = get_storage_service()
                download_url = storage.upload_temporary(
                    data=pdf_data,
                    filename=filename,
                    mime_type="application/pdf",
                )

                size_kb = len(pdf_data) / 1024
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"Invoice PDF: {invoice_id}\n"
                            f"Size: {size_kb:.1f} KB\n"
                            f"Download URL (expires in 1 hour): {download_url}"
                        ),
                    )
                ]

            elif name == "email_invoice":
                invoice_id = arguments.get("invoiceId")
                if not invoice_id:
                    raise ValueError("invoiceId is required")

                extra_headers = {}
                if arguments.get("idempotencyKey"):
                    extra_headers["Idempotency-Key"] = arguments["idempotencyKey"]

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Invoices/{invoice_id}/Email",
                    access_token,
                    tenant_id,
                    method="POST",
                    data={},
                    extra_headers=extra_headers,
                )
                if not result:
                    result = {
                        "Success": True,
                        "InvoiceID": invoice_id,
                        "Message": "Invoice email request submitted to Xero.",
                    }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    return server


# Module-level exports for server discovery
server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """
    Define the initialization options for the Xero MCP server.

    Args:
        server_instance: The server instance to describe.

    Returns:
        InitializationOptions: MCP-compatible initialization configuration.
    """
    return InitializationOptions(
        server_name="xero-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() == "auth":
        print("Xero authentication is managed via Nango.")
        print("Please configure your Xero connection in your Nango dashboard")
        print("using the 'xero-oauth2-cc' provider.")
        print("See: https://nango.dev/docs/integrations/all/xero-oauth2-cc")
    else:
        print("Usage:")
        print("  python main.py auth - Show authentication setup instructions")
        print("Note: To run the server, use the pfMCP server framework.")
