import os
import sys
import httpx
import logging
import json
from pathlib import Path

# Add project root and src directory to Python path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

from mcp.types import (
    TextContent,
    Tool,
)
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from src.auth.factory import create_auth_client


SERVICE_NAME = Path(__file__).parent.name
PEAKFLO_BASE_URL = "https://stage-api.peakflo.co/v1"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


def authenticate_and_save_peakflo_key(user_id):
    auth_client = create_auth_client()

    api_key = input("Please enter your SerpAPI API key: ").strip()
    if not api_key:
        raise ValueError("API key cannot be empty")

    auth_client.save_user_credentials("serpapi", user_id, {"api_key": api_key})
    return api_key


async def get_peakflo_credentials(user_id, api_key=None):
    auth_client = create_auth_client(api_key=api_key)
    credentials_data = auth_client.get_user_credentials("peakflo", user_id)

    if not credentials_data:
        error_str = f"Peakflo API key not found for user {user_id}."
        if os.environ.get("ENVIRONMENT", "local") == "local":
            error_str += " Please run authentication first."
        raise ValueError(error_str)

    token = credentials_data.get("access_token")
    if not token:
        raise ValueError(f"Peakflo token not found for user {user_id}.")

    return token


async def make_peakflo_request(name, arguments, token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if name == "create_invoice":
        method = "POST"
        url = f"{PEAKFLO_BASE_URL}/invoices"
        message = "Invoice created successfully"
    elif name == "update_invoice":
        method = "PUT"
        url = f"{PEAKFLO_BASE_URL}/invoices/{arguments['externalId']}"
        message = "Invoice updated successfully"
    elif name == "read_vendor":
        method = "GET"
        url = f"{PEAKFLO_BASE_URL}/vendors/{arguments['externalId']}"
        message = "Vendor fetched successfully"

    logger.info(
        f"[make_peakflo_request] method: {method}, url: {url}, arguments: {arguments}"
    )
    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method, url, json=arguments, headers=headers, timeout=60.0
            )
            status_code = response.status_code
            logger.info(
                f"[make_peakflo_request] status_code: {status_code} response: {response.text}"
            )

            return {
                "_status_code": status_code,
                "message": status_code == 200
                and message
                or f"Error: {response.text or 'Unknown error'}",
                "data": arguments,
            }
    except httpx.HTTPStatusError as e:
        logger.error(
            f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
        )
        return {
            "message": f"Peakflo error: {e.response.status_code} - {e.response.text}",
            "_status_code": e.response.status_code,
        }
    except Exception as e:
        logger.error(f"Error making request to Peakflo: {str(e)}")
        return {
            "message": f"Error communicating with Peakflo: {str(e)}",
            "_status_code": 500,
        }


def create_server(user_id, api_key=None):
    server = Server(f"{SERVICE_NAME}-server")
    server.user_id = user_id
    server.api_key = api_key
    tool_names = ["read_vendor", "create_invoice", "update_invoice"]

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return [
            Tool(
                name="read_vendor",
                description="Fetch vendor details by external ID from Peakflo API",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "externalId": {
                            "type": "string",
                            "description": "External ID of the vendor to fetch",
                        }
                    },
                    "required": ["externalId"],
                },
                outputSchema={
                    "type": "object",
                    "properties": {
                        "companyName": {
                            "type": "string",
                            "description": "Name of the vendor company",
                        },
                        "companyId": {
                            "type": "string",
                            "description": "Unique identifier for the company",
                        },
                        "defaultCurrency": {
                            "type": "string",
                            "description": "Default currency for the vendor (e.g., USD, SGD)",
                        },
                        "addresses": {
                            "type": "array",
                            "description": "Array of vendor addresses",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "description": "Type of address (e.g., billing, shipping)",
                                    },
                                    "line1": {
                                        "type": "string",
                                        "description": "Primary address line",
                                    },
                                    "city": {
                                        "type": "string",
                                        "description": "City name",
                                    },
                                    "country": {
                                        "type": "string",
                                        "description": "Country code",
                                    },
                                    "postalCode": {
                                        "type": "string",
                                        "description": "Postal/ZIP code",
                                    },
                                },
                            },
                        },
                        "contacts": {
                            "type": "array",
                            "description": "Array of vendor contacts",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "externalId": {
                                        "type": "string",
                                        "description": "External reference ID for the contact",
                                    },
                                    "firstName": {
                                        "type": "string",
                                        "description": "Contact's first name",
                                    },
                                    "lastName": {
                                        "type": "string",
                                        "description": "Contact's last name",
                                    },
                                    "phone": {
                                        "type": "string",
                                        "description": "Contact's phone number",
                                    },
                                    "email": {
                                        "type": "string",
                                        "description": "Contact's email address",
                                    },
                                    "isMainContact": {
                                        "type": "boolean",
                                        "description": "Whether this is the main contact",
                                    },
                                },
                            },
                        },
                        "taxNumber": {
                            "type": "string",
                            "description": "Vendor's tax identification number",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Additional notes about the vendor",
                        },
                        "bankDetails": {
                            "type": "array",
                            "description": "Array of bank account details",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {
                                        "type": "string",
                                        "description": "Bank account identifier",
                                    },
                                    "bankName": {
                                        "type": "string",
                                        "description": "Name of the bank",
                                    },
                                    "bankCode": {
                                        "type": "string",
                                        "description": "Bank code",
                                    },
                                    "bankCountry": {
                                        "type": "string",
                                        "description": "Country code of the bank",
                                    },
                                    "accountNumber": {
                                        "type": "string",
                                        "description": "Bank account number",
                                    },
                                    "accountHolder": {
                                        "type": "string",
                                        "description": "Name of the account holder",
                                    },
                                    "currency": {
                                        "type": "string",
                                        "description": "Currency of the bank account",
                                    },
                                    "bankAccountType": {
                                        "type": "string",
                                        "description": "Type of bank account",
                                    },
                                    "isDefault": {
                                        "type": "boolean",
                                        "description": "Whether this is the default bank account",
                                    },
                                },
                            },
                        },
                        "entityType": {
                            "type": "string",
                            "description": "Type of entity (e.g., vendor)",
                        },
                        "beneficiaryCountry": {
                            "type": "string",
                            "description": "Country code of the beneficiary",
                        },
                        "vendorFirstName": {
                            "type": "string",
                            "description": "First name of the vendor",
                        },
                        "vendorLastName": {
                            "type": "string",
                            "description": "Last name of the vendor",
                        },
                        "paymentTerms": {
                            "type": "integer",
                            "description": "Payment terms in days",
                        },
                        "customField": {
                            "type": "array",
                            "description": "Array of custom fields",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "customFieldNumber": {
                                        "type": "string",
                                        "description": "Custom field identifier",
                                    },
                                    "name": {
                                        "type": "string",
                                        "description": "Name of the custom field",
                                    },
                                    "value": {
                                        "type": "string",
                                        "description": "Value of the custom field",
                                    },
                                },
                            },
                        },
                        "vatApplicable": {
                            "type": "boolean",
                            "description": "Whether VAT is applicable",
                        },
                    },
                },
            ),
            Tool(
                name="create_invoice",
                description="Create an invoice with comprehensive details including line items, customer information, and financial breakdown",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "externalId": {
                            "type": "string",
                            "description": "External reference ID for the invoice",
                        },
                        "customerRef": {
                            "type": "string",
                            "description": "Customer reference identifier",
                        },
                        "issueDate": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Invoice issue date in ISO format",
                        },
                        "dueDate": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Invoice due date in ISO format",
                        },
                        "currency": {
                            "type": "string",
                            "description": "Currency code (e.g., SGD, USD)",
                        },
                        "lineItems": {
                            "type": "array",
                            "description": "Array of line items for the invoice",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {
                                        "type": "string",
                                        "description": "Item description",
                                    },
                                    "unitAmount": {
                                        "type": "number",
                                        "description": "Unit price of the item",
                                    },
                                    "quantity": {
                                        "type": "number",
                                        "description": "Quantity of the item",
                                    },
                                    "discountAmount": {
                                        "type": "number",
                                        "description": "Discount amount for the item",
                                    },
                                    "subTotal": {
                                        "type": "number",
                                        "description": "Subtotal for the item",
                                    },
                                    "taxAmount": {
                                        "type": "number",
                                        "description": "Tax amount for the item",
                                    },
                                    "totalAmount": {
                                        "type": "number",
                                        "description": "Total amount for the item",
                                    },
                                    "itemRef": {
                                        "type": "string",
                                        "description": "Item reference identifier",
                                    },
                                },
                                "required": ["description", "unitAmount", "quantity"],
                            },
                        },
                        "totalAmount": {
                            "type": "number",
                            "description": "Total invoice amount",
                        },
                        "totalDiscount": {
                            "type": "number",
                            "description": "Total discount amount",
                        },
                        "totalTaxAmount": {
                            "type": "number",
                            "description": "Total tax amount",
                        },
                        "amountDue": {
                            "type": "number",
                            "description": "Amount due for the invoice",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["draft", "sent", "paid", "overdue", "cancelled"],
                            "description": "Invoice status",
                        },
                        "note": {
                            "type": "string",
                            "description": "Additional notes for the invoice",
                        },
                        "subTotal": {
                            "type": "number",
                            "description": "Subtotal before taxes and discounts",
                        },
                        "invoiceNumber": {
                            "type": "string",
                            "description": "Invoice number identifier",
                        },
                    },
                    "required": [
                        "externalId",
                        "customerRef",
                        "issueDate",
                        "dueDate",
                        "currency",
                        "lineItems",
                        "totalAmount",
                        "amountDue",
                        "status",
                        "invoiceNumber",
                    ],
                },
            ),
            Tool(
                name="update_invoice",
                description="Update an invoice with comprehensive details including line items, customer information, and financial breakdown",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "externalId": {
                            "type": "string",
                            "description": "External reference ID for the invoice",
                        },
                        "customerRef": {
                            "type": "string",
                            "description": "Customer reference identifier",
                        },
                        "issueDate": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Invoice issue date in ISO format",
                        },
                        "dueDate": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Invoice due date in ISO format",
                        },
                        "currency": {
                            "type": "string",
                            "description": "Currency code (e.g., SGD, USD)",
                        },
                        "lineItems": {
                            "type": "array",
                            "description": "Array of line items for the invoice",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {
                                        "type": "string",
                                        "description": "Item description",
                                    },
                                    "unitAmount": {
                                        "type": "number",
                                        "description": "Unit price of the item",
                                    },
                                    "quantity": {
                                        "type": "number",
                                        "description": "Quantity of the item",
                                    },
                                    "discountAmount": {
                                        "type": "number",
                                        "description": "Discount amount for the item",
                                    },
                                    "subTotal": {
                                        "type": "number",
                                        "description": "Subtotal for the item",
                                    },
                                    "taxAmount": {
                                        "type": "number",
                                        "description": "Tax amount for the item",
                                    },
                                    "totalAmount": {
                                        "type": "number",
                                        "description": "Total amount for the item",
                                    },
                                    "itemRef": {
                                        "type": "string",
                                        "description": "Item reference identifier",
                                    },
                                },
                                "required": ["description", "unitAmount", "quantity"],
                            },
                        },
                        "totalAmount": {
                            "type": "number",
                            "description": "Total invoice amount",
                        },
                        "totalDiscount": {
                            "type": "number",
                            "description": "Total discount amount",
                        },
                        "totalTaxAmount": {
                            "type": "number",
                            "description": "Total tax amount",
                        },
                        "amountDue": {
                            "type": "number",
                            "description": "Amount due for the invoice",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["draft", "sent", "paid", "overdue", "cancelled"],
                            "description": "Invoice status",
                        },
                        "note": {
                            "type": "string",
                            "description": "Additional notes for the invoice",
                        },
                        "subTotal": {
                            "type": "number",
                            "description": "Subtotal before taxes and discounts",
                        },
                        "invoiceNumber": {
                            "type": "string",
                            "description": "Invoice number identifier",
                        },
                    },
                    "required": [
                        "externalId",
                        "customerRef",
                        "issueDate",
                        "dueDate",
                        "currency",
                        "lineItems",
                        "totalAmount",
                        "amountDue",
                        "status",
                        "invoiceNumber",
                    ],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent]:
        if name not in tool_names:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        token = await get_peakflo_credentials(server.user_id, server.api_key)

        try:
            response = await make_peakflo_request(name, arguments, token)

            # Check response status code
            status_code = response.get("_status_code", 0)
            if status_code < 200 or status_code >= 300:
                return [
                    TextContent(
                        type="text",
                        text=f"Error performing request (Status {status_code}): {response.get('message', 'Unknown error')}",
                    )
                ]

            return [TextContent(type="text", text=json.dumps(response, indent=2))]

        except Exception as e:
            return [
                TextContent(
                    type="text", text=f"Unexpected error performing search: {str(e)}"
                )
            ]

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    return InitializationOptions(
        server_name=f"{SERVICE_NAME}-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() == "auth":
        user_id = "local"
        authenticate_and_save_peakflo_key(user_id)
    else:
        print("Usage:")
        print("  python main.py auth - Run authentication flow for a user")
        print("Note: To run the server normally, use the guMCP server framework.")
