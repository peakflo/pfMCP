import os
import sys
import time
import base64
import httpx
import logging
import json
import jwt
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

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


def _generate_legacy_jwt(tenant_id, private_key, access_token):
    """
    Generate a JWT token from legacy Nango unauthenticated metadata.

    Backward-compatible with connections created before the API key migration.
    These connections store tenantId, privateKey, and accessToken in Nango
    metadata instead of using native API key auth.
    """
    expires_at = time.time() + 3600
    payload = {
        "iss": SERVICE_NAME,
        "aud": SERVICE_NAME,
        "acc": access_token,
        "sub": tenant_id,
        "iat": time.time(),
        "exp": expires_at,
    }
    return jwt.encode(payload, private_key)


def authenticate_and_save_peakflo_key(user_id):
    auth_client = create_auth_client()

    api_key = input("Please enter your Peakflo API key: ").strip()
    if not api_key:
        raise ValueError("API key cannot be empty")

    auth_client.save_user_credentials("peakflo", user_id, {"apiKey": api_key})
    return api_key


async def get_peakflo_credentials(user_id, api_key=None):
    """
    Get Peakflo credentials, supporting both new and legacy auth flows.

    New flow (API_KEY): Nango stores the API key natively.
        credentials = {apiKey: "pk_xxx", metadata: {}}

    Legacy flow (backward-compat): Old connections stored tenantId, privateKey,
        and accessToken in Nango metadata. We generate a JWT on-the-fly.
        credentials = {metadata: {tenantId: ..., privateKey: ..., accessToken: ...}}
    """
    # If API key is provided directly (e.g. for local testing), use it
    if api_key:
        return api_key

    auth_client = create_auth_client()
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

    # New flow: native Nango API key
    token = credentials_data.get("apiKey")
    if token:
        logger.info(f"[get_peakflo_credentials] Using native API key for user {user_id}")
        return token

    # Legacy flow: generate JWT from metadata (backward-compat for old connections)
    metadata = credentials_data.get("metadata", {})
    tenant_id = metadata.get("tenantId")
    private_key = metadata.get("privateKey")
    access_token = metadata.get("accessToken")

    if tenant_id and private_key and access_token:
        logger.info(
            f"[get_peakflo_credentials] Using legacy JWT flow for user {user_id} "
            f"(tenant {tenant_id}). Consider migrating to API key auth."
        )
        return _generate_legacy_jwt(tenant_id, private_key, access_token)

    raise ValueError(
        f"Peakflo credentials not found for user {user_id}. "
        "Expected either an API key or legacy metadata (tenantId, privateKey, accessToken)."
    )


async def make_peakflo_request(name, arguments, token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
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
    elif name == "create_task":
        method = "POST"
        url = f"{PEAKFLO_V1_BASE_URL}/addAction"
        message = "Task created successfully"
    elif name == "add_action_log":
        method = "POST"
        url = f"{PEAKFLO_V1_BASE_URL}/addActionLog"
        message = "Action log added successfully"
    elif name == "run_bill_po_matching":
        method = "POST"
        url = f"{PEAKFLO_V1_BASE_URL}/runBillPoMatching"
        message = "Bill PO matching completed successfully"
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

            return {
                "_status_code": status_code,
                "message": (status_code == 200 or status_code == 201)
                and message
                or f"Error: {response.text or 'Unknown error'}",
                "data": arguments if method != "GET" else response.json(),
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
