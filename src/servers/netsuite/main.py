import json
import os
import logging
import sys
from pathlib import Path
from typing import Dict, Any, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
    """NetSuite REST API client"""

    def __init__(
        self,
        account_id: str,
        consumer_key: str,
        consumer_secret: str,
        token_id: str,
        token_secret: str,
    ):
        self.account_id = account_id
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.token_id = token_id
        self.token_secret = token_secret
        self.base_url = (
            f"https://{account_id}.restlets.api.netsuite.com/rest/platform/v1"
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

    def _get_headers(self) -> Dict[str, str]:
        """Get authentication headers for NetSuite API"""
        # Note: This is a simplified implementation
        # In production, you'd want to implement proper OAuth 1.0a signature
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.consumer_key}",
            "X-NetSuite-Account": self.account_id,
        }

    def create_record(self, record_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new record in NetSuite"""
        url = f"{self.base_url}/record/{record_type}"
        headers = self._get_headers()

        try:
            response = self.session.post(url, json=data, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error creating {record_type} record: {e}")
            raise Exception(f"Failed to create {record_type} record: {str(e)}")

    def update_record(
        self, record_type: str, record_id: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update an existing record in NetSuite"""
        url = f"{self.base_url}/record/{record_type}/{record_id}"
        headers = self._get_headers()

        try:
            response = self.session.patch(url, json=data, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error updating {record_type} record {record_id}: {e}")
            raise Exception(
                f"Failed to update {record_type} record {record_id}: {str(e)}"
            )

    def search_vendor_by_email(self, email: str) -> Dict[str, Any]:
        """Search for a vendor by email address"""
        url = f"{self.base_url}/search"
        headers = self._get_headers()

        search_query = {
            "type": "vendor",
            "filters": [{"field": "email", "operator": "is", "value": email}],
        }

        try:
            response = self.session.post(url, json=search_query, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error searching vendor by email {email}: {e}")
            raise Exception(f"Failed to search vendor by email {email}: {str(e)}")

    def search_vendor_by_name(self, vendor_name: str) -> Dict[str, Any]:
        """Search for a vendor by name"""
        url = f"{self.base_url}/search"
        headers = self._get_headers()

        search_query = {
            "type": "vendor",
            "filters": [
                {"field": "entityid", "operator": "contains", "value": vendor_name}
            ],
        }

        try:
            response = self.session.post(url, json=search_query, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error searching vendor by name {vendor_name}: {e}")
            raise Exception(f"Failed to search vendor by name {vendor_name}: {str(e)}")

    def execute_suiteql(self, query: str) -> Dict[str, Any]:
        """Execute a SuiteQL query"""
        url = f"{self.base_url}/query"
        headers = self._get_headers()

        query_data = {"q": query}

        try:
            response = self.session.post(url, json=query_data, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error executing SuiteQL query: {e}")
            raise Exception(f"Failed to execute SuiteQL query: {str(e)}")


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


def create_server(user_id: str, api_key: Optional[str] = None):
    """
    Initializes and configures a NetSuite MCP server instance.

    Args:
        user_id (str): The unique user identifier for session context.
        api_key (Optional[str]): Optional API key for user auth context.

    Returns:
        Server: Configured server instance with all NetSuite tools registered.
    """
    server = Server("netsuite-server")
    server.user_id = user_id
    server.api_key = api_key

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
            # Get NetSuite credentials
            credentials = await get_netsuite_credentials(user_id, api_key)
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
