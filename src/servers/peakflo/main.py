import os
import sys
import httpx
import logging
import json
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
PEAKFLO_V1_BASE_URL = f"https://stage-api.peakflo.co/v1"
PEAKFLO_V2_BASE_URL = f"https://stage-api.peakflo.co/v2"

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
        url = f"{PEAKFLO_V1_BASE_URL}/invoices"
        message = "Invoice created successfully"
    elif name == "update_invoice":
        method = "PUT"
        url = f"{PEAKFLO_V1_BASE_URL}/invoices/{arguments['externalId']}"
        message = "Invoice updated successfully"
    elif name == "read_vendor":
        method = "GET"
        url = f"{PEAKFLO_V1_BASE_URL}/vendors/{arguments['externalId']}"
        message = "Vendor fetched successfully"
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
                "message": status_code == 200
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
