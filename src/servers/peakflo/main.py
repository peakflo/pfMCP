import os
import sys
import base64
import httpx
import logging
import json
from typing import Any
from urllib.parse import urlencode
from pathlib import Path

from servers.peakflo.factories.peakflo_api_factory import PeakfloApiToolFactory
from servers.peakflo.credential_broker import PeakfloCredentialBrokerClient

# Add project root and src directory to Python path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    ListToolsRequest,
    TextContent,
    Tool,
)
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from src.auth.factory import create_auth_client
from src.servers.xero import main as xero_main
from src.servers.netsuite import main as netsuite_main

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

SOURCE_SYSTEM_XERO = "xero"
SOURCE_SYSTEM_NETSUITE = "netsuite"
XERO_TOOL_PREFIX = "xero__"
NETSUITE_TOOL_PREFIX = "netsuite__"


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

    Tries two Nango provider config keys in order:
      1. "peakflo" — legacy connections (unauthenticated/metadata-based) and
         connections created via the original integration type.
      2. "peakflo-api-key" — new connections created via the native API_KEY
         integration type in Nango.

    New flow (API_KEY): Nango stores the API key natively.
        NangoAuthClient returns {apiKey: "pk_xxx"} → we use apiKey directly.

    Legacy flow (backward-compat): Old connections stored tenantId, privateKey,
        and accessToken in Nango metadata. NangoAuthClient detects this and
        generates a JWT internally, returning {access_token: "jwt_xxx", expires_at: ...}.
    """
    auth_client = create_auth_client(api_key=api_key)
    # Try both Nango provider config keys: legacy "peakflo" first, then
    # "peakflo-api-key" for connections created via the new integration type.
    # NangoAuthClient caches successful lookups, so subsequent calls are fast.
    credentials_data = None
    for service_name in ["peakflo", "peakflo-api-key"]:
        # Use async version to avoid blocking the event loop.
        # Sync requests.get() + time.sleep() in the non-async version would block
        # all concurrent SSE streams on this pf-mcp instance, causing Cloud Run
        # to truncate responses and workflow-api to hang indefinitely.
        if hasattr(auth_client, "async_get_user_credentials"):
            credentials_data = await auth_client.async_get_user_credentials(
                service_name, user_id
            )
        else:
            credentials_data = auth_client.get_user_credentials(service_name, user_id)

        if credentials_data:
            logger.info(
                f"[get_peakflo_credentials] resolved credentials via '{service_name}' for {user_id}"
            )
            break

    if not credentials_data:
        error_str = f"Peakflo API key not found for user {user_id}."
        if os.environ.get("ENVIRONMENT", "local") == "local":
            error_str += " Please run authentication first."
        raise ValueError(error_str)

    # New flow: native Nango API key
    token = credentials_data.get("apiKey")
    if token:
        return token

    # Legacy flow: NangoAuthClient already generated a JWT from metadata
    token = credentials_data.get("access_token")
    if token:
        return token

    raise ValueError(f"Peakflo token not found for user {user_id}.")


async def get_system_of_record_credentials(
    tenant_id: str, source_system: str, purpose: str = "workflow"
):
    """
    Resolve credentials for a Peakflo-connected system of record.

    This is for internal tool implementations that call Xero/NetSuite/etc.
    directly. Do not return this value from an MCP tool.
    """
    broker = PeakfloCredentialBrokerClient()
    return await broker.resolve_system_of_record_credentials(
        tenant_id=tenant_id,
        source_system=source_system,
        purpose=purpose,
    )


def _nested_data(payload: Any) -> dict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("data")
        return nested if isinstance(nested, dict) else data
    return payload


def _copy_tool(tool: Tool, *, name: str, description: str | None = None) -> Tool:
    updates = {
        "name": name,
        "description": description if description is not None else tool.description,
    }
    if hasattr(tool, "model_copy"):
        return tool.model_copy(update=updates)
    return tool.copy(update=updates)


async def _resolve_peakflo_tenant_context(token: str) -> dict:
    response = await make_peakflo_request("get_tenant", {}, token)
    status_code = response.get("_status_code", 0)
    if status_code < 200 or status_code >= 300:
        logger.warning(
            "[peakflo] failed to resolve tenant context",
            extra={"status_code": status_code},
        )
        return {}
    return _nested_data(response)


async def _resolve_source_system(token: str) -> str:
    """Return the lowercased sourceSystem the Peakflo tenant is connected to."""
    tenant_context = await _resolve_peakflo_tenant_context(token)
    return str(tenant_context.get("sourceSystem", "")).lower()


def _pick_credential(*sources: dict):
    """Return the first non-empty value found across the given key sequences.

    Called as _pick_credential(container, "keyA", "keyB", ...) — the first
    positional is the dict, the rest are candidate keys.
    """
    container, *keys = sources
    for key in keys:
        value = container.get(key)
        if value:
            return value
    return None


def _build_xero_credential_resolver(tenant_id: str, tool_name: str):
    """Return an async resolver yielding (access_token, xero_tenant_id) for Xero."""

    async def resolver(user_id: str = None, api_key: str = None) -> tuple:
        credentials = await get_system_of_record_credentials(
            tenant_id=tenant_id,
            source_system=SOURCE_SYSTEM_XERO,
            purpose=f"pfmcp:{tool_name}",
        )
        body = credentials.get("credentials") or {}
        access_token = (
            credentials.get("accessToken")
            or body.get("access_token")
            or body.get("accessToken")
        )
        xero_tenant_id = (
            credentials.get("providerTenantId")
            or body.get("tenantId")
            or body.get("xeroTenantId")
        )
        if not access_token or not xero_tenant_id:
            raise ValueError(
                "Peakflo Xero connection is missing accessToken or providerTenantId"
            )
        return access_token, xero_tenant_id

    return resolver


def _build_netsuite_credential_resolver(tenant_id: str, tool_name: str):
    """Return an async resolver yielding NetSuiteClient kwargs.

    Supports both auth shapes Peakflo may hold for a NetSuite connection:
      * OAuth 2.0 — accountId + accessToken
      * Token-Based Auth (OAuth 1.0a) — accountId + consumer/token key & secret
    """

    async def resolver(user_id: str = None, api_key: str = None) -> dict:
        credentials = await get_system_of_record_credentials(
            tenant_id=tenant_id,
            source_system=SOURCE_SYSTEM_NETSUITE,
            purpose=f"pfmcp:{tool_name}",
        )
        body = credentials.get("credentials") or {}

        def pick(*keys):
            return _pick_credential(credentials, *keys) or _pick_credential(body, *keys)

        account_id = pick(
            "accountId", "account_id", "providerAccountId", "realm", "providerTenantId"
        )
        access_token = pick("accessToken", "access_token")
        consumer_key = pick("consumerKey", "consumer_key")
        consumer_secret = pick("consumerSecret", "consumer_secret")
        token_id = pick("tokenId", "token_id", "tokenKey", "token_key")
        token_secret = pick("tokenSecret", "token_secret")

        if not account_id:
            raise ValueError("Peakflo NetSuite connection is missing accountId")

        has_tba = all([consumer_key, consumer_secret, token_id, token_secret])
        if not access_token and not has_tba:
            raise ValueError(
                "Peakflo NetSuite connection is missing an OAuth 2.0 access_token "
                "or the full Token-Based Auth credential set"
            )

        return {
            "account_id": account_id,
            "access_token": access_token,
            "consumer_key": consumer_key,
            "consumer_secret": consumer_secret,
            "token_id": token_id,
            "token_secret": token_secret,
        }

    return resolver


# Registry of Peakflo-connected systems of record whose native provider tools we
# surface through the Peakflo MCP server when the tenant is connected to them.
# Adding an accounting/ERP source here is all it takes to expose its tools.
SOURCE_SYSTEM_INTEGRATIONS = {
    SOURCE_SYSTEM_XERO: {
        "module": xero_main,
        "prefix": XERO_TOOL_PREFIX,
        "label": "Xero",
        "resolver_builder": _build_xero_credential_resolver,
    },
    SOURCE_SYSTEM_NETSUITE: {
        "module": netsuite_main,
        "prefix": NETSUITE_TOOL_PREFIX,
        "label": "NetSuite",
        "resolver_builder": _build_netsuite_credential_resolver,
    },
}


async def _get_prefixed_source_system_tools(source_system: str) -> list[Tool]:
    """List the provider's tools, prefixed/labelled, for the connected source system."""
    integration = SOURCE_SYSTEM_INTEGRATIONS.get(source_system)
    if not integration:
        return []
    inner_server = integration["module"].create_server("tool-discovery")
    list_handler = inner_server.request_handlers[ListToolsRequest]
    result = await list_handler(ListToolsRequest(method="tools/list"))
    prefix = integration["prefix"]
    label = integration["label"]
    return [
        _copy_tool(
            tool,
            name=f"{prefix}{tool.name}",
            description=f"[{label}] {tool.description or tool.name}",
        )
        for tool in result.root.tools
    ]


def _match_source_system_tool(name: str):
    """Return (source_system, integration) for a prefixed tool name, else (None, None)."""
    for source_system, integration in SOURCE_SYSTEM_INTEGRATIONS.items():
        if name.startswith(integration["prefix"]):
            return source_system, integration
    return None, None


async def _call_source_system_tool_via_peakflo_connection(
    server: Server,
    token: str,
    source_system: str,
    integration: dict,
    name: str,
    arguments: dict | None,
):
    tenant_context = await _resolve_peakflo_tenant_context(token)
    tenant_id = tenant_context.get("tenantId")
    tenant_source_system = str(tenant_context.get("sourceSystem", "")).lower()
    label = integration["label"]
    if not tenant_id or tenant_source_system != source_system:
        return [
            TextContent(
                type="text",
                text=(
                    f"{label} tools are only available for Peakflo tenants "
                    f"connected to {label}."
                ),
            )
        ]

    inner_tool_name = name[len(integration["prefix"]) :]
    credential_resolver = integration["resolver_builder"](tenant_id, inner_tool_name)

    inner_server = integration["module"].create_server(
        server.user_id,
        api_key=server.api_key,
        credential_resolver=credential_resolver,
    )
    call_handler = inner_server.request_handlers[CallToolRequest]
    result = await call_handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name=inner_tool_name,
                arguments=arguments or {},
            ),
        )
    )
    return result.root.content


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
    elif name == "create_collection_workflow_action":
        # Append a new action. actionExternalId stays in the body — it's
        # not used for URL routing on POST, only for downstream addressing
        # when subsequent update_collection_workflow_action calls reference
        # it.
        external_id = arguments.pop("externalId")
        method = "POST"
        url = f"{PEAKFLO_V1_BASE_URL}/collection-workflows/{external_id}/actions"
        message = "Collection workflow action created successfully"
    elif name == "delete_collection_workflow":
        external_id = arguments.pop("externalId")
        method = "DELETE"
        url = f"{PEAKFLO_V1_BASE_URL}/collection-workflows/{external_id}"
        message = "Collection workflow deleted successfully"
    elif name == "get_collection_workflow_action":
        external_id = arguments.pop("externalId")
        action_external_id = arguments.pop("actionExternalId")
        method = "GET"
        url = (
            f"{PEAKFLO_V1_BASE_URL}/collection-workflows/{external_id}"
            f"/actions/{action_external_id}"
        )
        message = "Collection workflow action fetched successfully"
    elif name == "delete_collection_workflow_action":
        external_id = arguments.pop("externalId")
        action_external_id = arguments.pop("actionExternalId")
        method = "DELETE"
        url = (
            f"{PEAKFLO_V1_BASE_URL}/collection-workflows/{external_id}"
            f"/actions/{action_external_id}"
        )
        message = "Collection workflow action deleted successfully"
    elif name == "get_tenant":
        method = "GET"
        url = f"{PEAKFLO_V1_BASE_URL}/tenant"
        message = "Tenant information fetched successfully"
    elif name == "create_collection_workflow":
        method = "POST"
        url = f"{PEAKFLO_V1_BASE_URL}/collection-workflows"
        message = "Collection workflow created successfully"
    elif name == "list_whatsapp_templates":
        method = "GET"
        url = f"{PEAKFLO_V1_BASE_URL}/whatsapp-templates"
        message = "WhatsApp templates listed successfully"
    elif name == "assign_customer_to_workflow":
        customer_external_id = arguments.pop("customerExternalId")
        method = "POST"
        url = (
            f"{PEAKFLO_V1_BASE_URL}/customers/"
            f"{customer_external_id}/assign-workflow"
        )
        message = "Customer workflow assigned successfully"
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
        try:
            token = await get_peakflo_credentials(server.user_id, server.api_key)
            source_system = await _resolve_source_system(token)
            if source_system in SOURCE_SYSTEM_INTEGRATIONS:
                return [
                    *tools,
                    *(await _get_prefixed_source_system_tools(source_system)),
                ]
        except Exception as e:
            logger.warning(f"[peakflo] unable to resolve source-system tools: {e}")
        return tools

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent]:
        token = await get_peakflo_credentials(server.user_id, server.api_key)

        source_system, integration = _match_source_system_tool(name)
        if integration:
            try:
                return await _call_source_system_tool_via_peakflo_connection(
                    server, token, source_system, integration, name, arguments
                )
            except Exception as e:
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"Unexpected error performing "
                            f"{integration['label']} request: {str(e)}"
                        ),
                    )
                ]

        if name not in tool_names:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

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
