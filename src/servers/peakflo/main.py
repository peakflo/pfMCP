import os
import sys
import base64
import httpx
import logging
import json
from urllib.parse import urlencode
from pathlib import Path

from servers.peakflo.factories.peakflo_api_factory import PeakfloApiToolFactory

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
PEAKFLO_V1_BASE_URL = os.environ.get("PEAKFLO_API_BASE_URL")
# v2 base derived from v1; falls back to None if v1 is unset so the existing
# v1 error path stays unchanged.
PEAKFLO_V2_BASE_URL = (
    PEAKFLO_V1_BASE_URL.replace("/v1", "/v2") if PEAKFLO_V1_BASE_URL else None
)

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
    # Use async version to avoid blocking the event loop.
    # Sync requests.get() + time.sleep() in the non-async version would block
    # all concurrent SSE streams on this pf-mcp instance, causing Cloud Run
    # to truncate responses and workflow-api to hang indefinitely.
    if hasattr(auth_client, "async_get_user_credentials"):
        credentials_data = await auth_client.async_get_user_credentials(
            "peakflo", user_id
        )
    else:
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
    arguments = dict(arguments or {})
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    gateway_key = os.environ.get("PEAKFLO_API_GATEWAY_KEY")
    if gateway_key:
        headers["x-api-key"] = gateway_key
    tenantId = arguments.get("tenantId")
    # remove tenantId from arguments if present, as it may appear in the payload (to handle vendor portal cases) but not expected by API
    if "tenantId" in arguments:
        arguments.pop("tenantId")
    if name == "create_invoice":
        method = "POST"
        url = f"{PEAKFLO_V1_BASE_URL}/invoices"
        message = "Invoice created successfully"
    elif name == "update_invoice":
        method = "PUT"
        url = f"{PEAKFLO_V1_BASE_URL}/internal/invoices/{arguments['externalId']}/{tenantId}"
        message = "Invoice updated successfully"
    elif name == "read_vendor":
        method = "GET"
        url = f"{PEAKFLO_V1_BASE_URL}/vendors/{arguments['externalId']}"
        message = "Vendor fetched successfully"
    elif name == "create_vendor":
        method = "POST"
        url = f"{PEAKFLO_V1_BASE_URL}/vendors"
        message = "Vendor created successfully"
    elif name == "update_vendor":
        external_id = arguments.pop("externalId")
        method = "PUT"
        url = f"{PEAKFLO_V1_BASE_URL}/vendors/{external_id}"
        message = "Vendor updated successfully"
    elif name == "add_invoice_attachment":
        invoice_external_id = arguments.pop("invoiceExternalId")
        file_url = arguments.pop("file_url", None)
        if file_url:
            try:
                async with httpx.AsyncClient() as dl_client:
                    dl_response = await dl_client.get(file_url, timeout=60.0)
                    dl_response.raise_for_status()
                    arguments["data"] = base64.b64encode(dl_response.content).decode(
                        "utf-8"
                    )
                    logger.info(
                        f"[add_invoice_attachment] Downloaded file from URL "
                        f"({len(dl_response.content)} bytes) and base64-encoded"
                    )
            except Exception as dl_err:
                raise ValueError(
                    f"Failed to download file from file_url: {dl_err}"
                ) from dl_err
        elif "data" not in arguments:
            raise ValueError(
                "Either file_url or data (base64) is required for add_invoice_attachment"
            )
        method = "PUT"
        url = f"{PEAKFLO_V1_BASE_URL}/invoices/{invoice_external_id}/attachments"
        message = "Attachment added to invoice successfully"
    elif name == "raise_invoice_dispute":
        method = "POST"
        url = f"{PEAKFLO_V1_BASE_URL}/upload-dispute"
        message = "Dispute raised successfully"
    elif name == "soa_email":
        method = "POST"
        url = f"{PEAKFLO_V1_BASE_URL}/upload-soa-email"
        message = "SOA email sent successfully"
    elif name == "send_message":
        # MCP exposes invoiceExternalId as agent-friendly sugar; the API
        # contract uses objectType + objectExternalId and rejects unknown
        # keys (allowUnknown:false). Translate before forwarding. Other
        # fields (recipients/cc/bcc as RecipientSpec, messageBody, subject,
        # …) map 1:1 to the API contract.
        invoice_external_id = arguments.pop("invoiceExternalId", None)
        if invoice_external_id:
            arguments["objectType"] = "invoice"
            arguments["objectExternalId"] = invoice_external_id

        method = "POST"
        url = f"{PEAKFLO_V2_BASE_URL}/messages/send"
        message = "Message sent successfully"
    elif name == "create_task":
        method = "POST"
        url = f"{PEAKFLO_V1_BASE_URL}/tasks"
        message = "Task created successfully"
    elif name == "list_collection_workflows":
        method = "GET"
        query = urlencode(arguments)
        url = f"{PEAKFLO_V1_BASE_URL}/collection-workflows" + (
            f"?{query}" if query else ""
        )
        message = "Collection workflows fetched successfully"
    elif name == "get_collection_workflow":
        external_id = arguments.pop("externalId")
        method = "GET"
        url = f"{PEAKFLO_V1_BASE_URL}/collection-workflows/{external_id}"
        message = "Collection workflow fetched successfully"
    elif name == "add_action_log":
        method = "POST"
        url = f"{PEAKFLO_V1_BASE_URL}/addActionLog"
        message = "Action log added successfully"
    elif name == "run_bill_po_matching":
        method = "POST"
        url = f"{PEAKFLO_V1_BASE_URL}/runBillPoMatching"
        message = "Bill PO matching completed successfully"
    elif name == "update_collection_workflow":
        external_id = arguments.pop("externalId")
        method = "PUT"
        url = f"{PEAKFLO_V1_BASE_URL}/collection-workflows/{external_id}"
        message = "Collection workflow updated successfully"
    elif name == "update_collection_workflow_action":
        # MCP field names mirror the API contract 1:1 (recipients, cc,
        # bcc, subject, messageBody, paymentLink, actionType, triggerType,
        # …). No translation needed.
        external_id = arguments.pop("externalId")
        action_external_id = arguments.pop("actionExternalId")
        method = "PUT"
        url = (
            f"{PEAKFLO_V1_BASE_URL}/collection-workflows/{external_id}"
            f"/actions/{action_external_id}"
        )
        message = "Collection workflow action updated successfully"
    else:
        raise ValueError(f"Unknown tool call: {name}")

    logger.info(
        f"[make_peakflo_request] method: {method}, url: {url}, arguments: {arguments}"
    )
    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method,
                url,
                json=arguments if method != "GET" else None,
                headers=headers,
                timeout=60.0,
            )
            status_code = response.status_code
            logger.info(
                f"[make_peakflo_request] status_code: {status_code} response: {response.text}"
            )

            try:
                response_data = response.json() if response.content else None
            except ValueError:
                response_data = response.text
            return {
                "_status_code": status_code,
                "message": (status_code == 200 or status_code == 201)
                and message
                or f"Error: {response.text or 'Unknown error'}",
                "data": response_data,
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

    tools = PeakfloApiToolFactory.get_all_tools()
    tool_names = [tool.name for tool in tools]

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return tools

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
