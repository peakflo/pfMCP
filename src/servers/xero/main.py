import os
import sys
from typing import Optional, Dict, Any, List
import json

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

    async with httpx.AsyncClient() as client:
        if method.upper() == "GET":
            response = await client.get(url, headers=headers, params=params)
        elif method.upper() == "POST":
            response = await client.post(url, headers=headers, json=data)
        elif method.upper() == "PUT":
            response = await client.put(url, headers=headers, json=data)
        elif method.upper() == "DELETE":
            response = await client.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        if response.status_code >= 400:
            error_text = response.text
            raise Exception(format_xero_error(response.status_code, error_text))

        return response.json()


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
                description="Retrieve a list of accounts (chart of accounts) from Xero",
                inputSchema={
                    "type": "object",
                    "properties": {},
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
                description="Retrieve a list of bank account transactions from Xero",
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
                result = await call_xero_api(
                    f"{ACCOUNTING_API}/Accounts",
                    access_token,
                    tenant_id,
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
                if page:
                    params["page"] = page
                if bank_account_id:
                    params["where"] = (
                        f'BankAccount.AccountID==Guid("{bank_account_id}")'
                    )

                result = await call_xero_api(
                    f"{ACCOUNTING_API}/BankTransactions",
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
