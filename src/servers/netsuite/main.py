import json
import os
import logging
import sys
from pathlib import Path
from typing import Dict, Any, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from requests_oauthlib import OAuth1
from oauthlib.oauth1 import SIGNATURE_HMAC_SHA256, SIGNATURE_TYPE_AUTH_HEADER

project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import mcp.types as types
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions

SERVICE_NAME = Path(__file__).parent.name

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


class NetSuiteClient:
    """
    NetSuite SuiteTalk REST API client.

    Supports the two authentication modes NetSuite exposes for REST:

    * Token-Based Authentication (OAuth 1.0a / TBA) — the default for
      integrations. Requires account_id + consumer_key/secret + token_id/secret
      and signs each request with HMAC-SHA256.
    * OAuth 2.0 Bearer — when Peakflo holds a short-lived OAuth 2.0 access token
      for the tenant's NetSuite connection. Requires account_id + access_token.

    The auth mode is selected automatically from whichever credentials are
    present, so the same client works for both the env-var (TBA) path and the
    Peakflo credential-broker path.
    """

    def __init__(
        self,
        account_id: str,
        consumer_key: Optional[str] = None,
        consumer_secret: Optional[str] = None,
        token_id: Optional[str] = None,
        token_secret: Optional[str] = None,
        access_token: Optional[str] = None,
    ):
        if not account_id:
            raise ValueError("NetSuite account_id is required")

        self.account_id = account_id
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.token_id = token_id
        self.token_secret = token_secret
        self.access_token = access_token

        # The SuiteTalk REST host uses the account id lowercased with '_' -> '-'
        # (e.g. account "1234567_SB1" -> host "1234567-sb1.suitetalk...").
        host_account = account_id.lower().replace("_", "-")
        self.base_url = (
            f"https://{host_account}.suitetalk.api.netsuite.com/services/rest"
        )

        # Set up retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _auth(self) -> Optional[OAuth1]:
        """
        Build the OAuth 1.0a (TBA) request signer, or None when using OAuth 2.0.
        """
        if self.access_token:
            return None
        if all(
            [self.consumer_key, self.consumer_secret, self.token_id, self.token_secret]
        ):
            return OAuth1(
                client_key=self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=self.token_id,
                resource_owner_secret=self.token_secret,
                signature_method=SIGNATURE_HMAC_SHA256,
                signature_type=SIGNATURE_TYPE_AUTH_HEADER,
                # NetSuite requires the account id (canonical upper form) as the
                # OAuth realm.
                realm=self.account_id.upper(),
            )
        raise ValueError(
            "NetSuite credentials are incomplete: provide an OAuth 2.0 access_token "
            "or the full TBA set (consumer_key, consumer_secret, token_id, token_secret)."
        )

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if extra:
            headers.update(extra)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(
                method,
                url,
                json=json_body,
                headers=self._headers(extra_headers),
                auth=self._auth(),
                timeout=60,
            )
            response.raise_for_status()
            if response.content:
                try:
                    return response.json()
                except ValueError:
                    return {"raw": response.text}
            return {}
        except requests.exceptions.RequestException as e:
            detail = ""
            if getattr(e, "response", None) is not None:
                detail = e.response.text
            logger.error(f"NetSuite {method} {path} failed: {e} {detail}")
            raise Exception(f"NetSuite {method} {path} failed: {e} {detail}")

    def create_record(self, record_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new record in NetSuite via the SuiteTalk REST record API."""
        return self._request("POST", f"/record/v1/{record_type}", json_body=data)

    def update_record(
        self, record_type: str, record_id: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update an existing record in NetSuite via the SuiteTalk REST record API."""
        return self._request(
            "PATCH", f"/record/v1/{record_type}/{record_id}", json_body=data
        )

    def execute_suiteql(
        self, query: str, limit: int = 1000, offset: int = 0
    ) -> Dict[str, Any]:
        """Execute a SuiteQL query via the SuiteTalk REST query API."""
        path = f"/query/v1/suiteql?limit={limit}&offset={offset}"
        # SuiteQL requires the "Prefer: transient" header.
        return self._request(
            "POST",
            path,
            json_body={"q": query},
            extra_headers={"Prefer": "transient"},
        )

    def search_vendor_by_email(self, email: str) -> Dict[str, Any]:
        """Search for a vendor by email address (implemented via SuiteQL)."""
        safe = email.replace("'", "''")
        query = (
            "SELECT id, entityid, companyname, email FROM vendor "
            f"WHERE email = '{safe}' AND isinactive = 'F'"
        )
        return self.execute_suiteql(query)

    def search_vendor_by_name(self, vendor_name: str) -> Dict[str, Any]:
        """Search for a vendor by name, partial match (implemented via SuiteQL)."""
        safe = vendor_name.replace("'", "''")
        query = (
            "SELECT id, entityid, companyname, email FROM vendor "
            f"WHERE UPPER(entityid) LIKE UPPER('%{safe}%') AND isinactive = 'F'"
        )
        return self.execute_suiteql(query)


async def get_netsuite_credentials(
    user_id: str, api_key: Optional[str] = None
) -> Dict[str, str]:
    """
    Get NetSuite credentials for a specific user.

    Args:
        user_id (str): The user identifier.
        api_key (Optional[str]): Optional API key.

    Returns:
        Dict[str, str]: Dictionary containing NetSuite credentials.
    """
    # In a real implementation, you would retrieve these from a secure credential store
    # For now, we'll use environment variables as a fallback
    credentials = {
        "account_id": os.getenv("NETSUITE_ACCOUNT_ID"),
        "consumer_key": os.getenv("NETSUITE_CONSUMER_KEY"),
        "consumer_secret": os.getenv("NETSUITE_CONSUMER_SECRET"),
        "token_id": os.getenv("NETSUITE_TOKEN_ID"),
        "token_secret": os.getenv("NETSUITE_TOKEN_SECRET"),
    }

    # Validate that all required credentials are present
    missing_credentials = [key for key, value in credentials.items() if not value]
    if missing_credentials:
        raise Exception(
            f"Missing NetSuite credentials: {', '.join(missing_credentials)}"
        )

    return credentials


def create_server(
    user_id: str, api_key: Optional[str] = None, credential_resolver=None
):
    """
    Initializes and configures a NetSuite MCP server instance.

    Args:
        user_id (str): The unique user identifier for session context.
        api_key (Optional[str]): Optional API key for user auth context.
        credential_resolver: Optional async callable used by wrapper servers
            (e.g. the Peakflo server) to resolve NetSuite credentials outside the
            default env-var path. It receives (user_id, api_key) and must return a
            dict of NetSuiteClient kwargs (account_id + TBA fields and/or
            access_token). Defaults to get_netsuite_credentials.

    Returns:
        Server: Configured server instance with all NetSuite tools registered.
    """
    server = Server("netsuite-server")
    server.user_id = user_id
    server.api_key = api_key
    server.credential_resolver = credential_resolver or get_netsuite_credentials

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """
        Lists all available tools for interacting with the NetSuite API.

        Returns:
            list[types.Tool]: A list of tool metadata with schema definitions.
        """
        logger.info(f"Listing tools for user: {user_id}")
        return [
            types.Tool(
                name="create_record",
                description="Creates a new record in NetSuite with the specified record type and data",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "record_type": {
                            "type": "string",
                            "description": "The NetSuite record type (e.g., 'customer', 'vendor', 'item', 'salesorder')",
                        },
                        "data": {
                            "type": "object",
                            "description": "The record data as key-value pairs",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["record_type", "data"],
                },
            ),
            types.Tool(
                name="update_record",
                description="Updates an existing record in NetSuite with the specified record type, ID, and data",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "record_type": {
                            "type": "string",
                            "description": "The NetSuite record type (e.g., 'customer', 'vendor', 'item', 'salesorder')",
                        },
                        "record_id": {
                            "type": "string",
                            "description": "The unique identifier of the record to update",
                        },
                        "data": {
                            "type": "object",
                            "description": "The updated record data as key-value pairs",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["record_type", "record_id", "data"],
                },
            ),
            types.Tool(
                name="search_vendor_by_email",
                description="Searches for a vendor in NetSuite by email address",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "The email address to search for",
                        },
                    },
                    "required": ["email"],
                },
            ),
            types.Tool(
                name="search_vendor_by_name",
                description="Searches for a vendor in NetSuite by vendor name",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "vendor_name": {
                            "type": "string",
                            "description": "The vendor name to search for (supports partial matches)",
                        },
                    },
                    "required": ["vendor_name"],
                },
            ),
            types.Tool(
                name="execute_suiteql",
                description="Executes a SuiteQL query string against the NetSuite database",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The SuiteQL query string to execute (e.g., 'SELECT id, entityid FROM vendor WHERE isinactive = F')",
                        },
                    },
                    "required": ["query"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """
        Handle tool execution requests.
        Tools can interact with NetSuite API and return responses.
        """
        logger.info(f"User {user_id} calling tool: {name} with arguments: {arguments}")

        if not arguments:
            raise ValueError("Missing arguments")

        try:
            # Get NetSuite credentials (env-var default, or broker-resolved when
            # invoked through the Peakflo server via credential_resolver).
            credentials = await server.credential_resolver(user_id, api_key)
            netsuite_client = NetSuiteClient(**credentials)

            if name == "create_record":
                record_type = arguments.get("record_type")
                data = arguments.get("data")

                if not record_type or not data:
                    raise ValueError("Missing record_type or data")

                result = netsuite_client.create_record(record_type, data)
                return [
                    types.TextContent(
                        type="text",
                        text=f"Successfully created {record_type} record: {json.dumps(result, indent=2)}",
                    )
                ]

            elif name == "update_record":
                record_type = arguments.get("record_type")
                record_id = arguments.get("record_id")
                data = arguments.get("data")

                if not record_type or not record_id or not data:
                    raise ValueError("Missing record_type, record_id, or data")

                result = netsuite_client.update_record(record_type, record_id, data)
                return [
                    types.TextContent(
                        type="text",
                        text=f"Successfully updated {record_type} record {record_id}: {json.dumps(result, indent=2)}",
                    )
                ]

            elif name == "search_vendor_by_email":
                email = arguments.get("email")

                if not email:
                    raise ValueError("Missing email")

                result = netsuite_client.search_vendor_by_email(email)
                return [
                    types.TextContent(
                        type="text",
                        text=f"Vendor search results for email {email}: {json.dumps(result, indent=2)}",
                    )
                ]

            elif name == "search_vendor_by_name":
                vendor_name = arguments.get("vendor_name")

                if not vendor_name:
                    raise ValueError("Missing vendor_name")

                result = netsuite_client.search_vendor_by_name(vendor_name)
                return [
                    types.TextContent(
                        type="text",
                        text=f"Vendor search results for name '{vendor_name}': {json.dumps(result, indent=2)}",
                    )
                ]

            elif name == "execute_suiteql":
                query = arguments.get("query")

                if not query:
                    raise ValueError("Missing query")

                result = netsuite_client.execute_suiteql(query)
                return [
                    types.TextContent(
                        type="text",
                        text=f"SuiteQL query executed successfully: {json.dumps(result, indent=2)}",
                    )
                ]

            else:
                raise ValueError(f"Unknown tool: {name}")

        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}")
            return [
                types.TextContent(
                    type="text",
                    text=f"Error executing {name}: {str(e)}",
                )
            ]

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """Get the initialization options for the server"""
    return InitializationOptions(
        server_name="netsuite-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )
