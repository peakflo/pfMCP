# How to Create New Integrations for pfMCP

This guide provides step-by-step instructions for creating new MCP server integrations in pfMCP. Whether you're adding a new API service, implementing OAuth authentication, or creating custom tools, this guide will walk you through the entire process.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Project Structure](#project-structure)
3. [Step 1: Create Server Directory](#step-1-create-server-directory)
4. [Step 2: Implement Authentication](#step-2-implement-authentication)
5. [Step 3: Create API Client](#step-3-create-api-client)
6. [Step 4: Implement MCP Server](#step-4-implement-mcp-server)
7. [Step 5: Add Required Functions](#step-5-add-required-functions)
8. [Step 6: Create Tests](#step-6-create-tests)
9. [Step 7: Update Documentation](#step-7-update-documentation)
10. [Step 8: Test Your Integration](#step-8-test-your-integration)
11. [Common Patterns and Examples](#common-patterns-and-examples)
12. [Troubleshooting](#troubleshooting)

## Prerequisites

Before starting, ensure you have:

- Python 3.11+
- Basic understanding of the MCP (Model Context Protocol) specification
- Familiarity with the service's API you want to integrate
- Access to the service's API documentation and credentials

## Project Structure

Understanding the project structure is crucial:

```
src/
├── auth/                    # Authentication components
│   ├── clients/            # Auth client implementations
│   └── factory.py          # Auth client factory
├── servers/                # Server implementations
│   ├── your-service/       # Your new integration
│   │   ├── main.py         # Main server implementation
│   │   └── README.md       # Service-specific documentation
│   └── ...
├── utils/                  # Utility modules
│   ├── oauth/              # OAuth utilities
│   └── your-service/       # Service-specific utilities
│       └── util.py         # Credential management
└── ...
```

## Step 1: Create Server Directory

1. **Create the server directory**:
   ```bash
   mkdir src/servers/your-service-name
   ```

2. **Create the main server file**:
   ```bash
   touch src/servers/your-service-name/main.py
   ```

3. **Create a README for your service**:
   ```bash
   touch src/servers/your-service-name/README.md
   ```

## Step 2: Implement Authentication

### For OAuth 2.0 Services

1. **Create OAuth configuration**:
   ```bash
   mkdir -p local_auth/oauth_configs/your-service-name
   ```

2. **Create OAuth config file** (`local_auth/oauth_configs/your-service-name/oauth.json`):
   ```json
   {
     "client_id": "your_client_id",
     "client_secret": "your_client_secret",
     "redirect_uri": "http://localhost:8080",
     "auth_url": "https://api.service.com/oauth/authorize",
     "token_url": "https://api.service.com/oauth/token",
     "scopes": ["read", "write"]
   }
   ```

3. **Create utility module** (`src/utils/your-service-name/util.py`):
   ```python
   import logging
   from typing import Dict, List, Any

   from src.utils.oauth.util import run_oauth_flow, refresh_token_if_needed

   # Service OAuth endpoints
   SERVICE_OAUTH_AUTHORIZE_URL = "https://api.service.com/oauth/authorize"
   SERVICE_OAUTH_TOKEN_URL = "https://api.service.com/oauth/token"

   logger = logging.getLogger(__name__)

   def build_service_auth_params(
       oauth_config: Dict[str, Any], redirect_uri: str, scopes: List[str]
   ) -> Dict[str, str]:
       """Build the authorization parameters for service OAuth."""
       return {
           "response_type": "code",
           "client_id": oauth_config.get("client_id"),
           "scope": " ".join(scopes),
           "redirect_uri": redirect_uri,
       }

   def build_service_token_data(
       oauth_config: Dict[str, Any], redirect_uri: str, scopes: List[str], auth_code: str
   ) -> Dict[str, str]:
       """Build the token request data for service OAuth."""
       return {
           "grant_type": "authorization_code",
           "client_id": oauth_config.get("client_id"),
           "client_secret": oauth_config.get("client_secret"),
           "code": auth_code,
           "redirect_uri": redirect_uri,
       }

   def process_service_token_response(token_response: Dict[str, Any]) -> Dict[str, Any]:
       """Process the OAuth token response returned from service."""
       if "access_token" not in token_response:
           raise ValueError(f"Token exchange failed: {token_response}")

       return {
           "access_token": token_response.get("access_token"),
           "refresh_token": token_response.get("refresh_token"),
           "scope": token_response.get("scope"),
           "token_type": token_response.get("token_type"),
       }

   def authenticate_and_save_credentials(
       user_id: str, service_name: str, scopes: List[str]
   ) -> Dict[str, Any]:
       """Authenticate with service and save credentials"""
       return run_oauth_flow(
           service_name=service_name,
           user_id=user_id,
           scopes=scopes,
           auth_url_base=SERVICE_OAUTH_AUTHORIZE_URL,
           token_url=SERVICE_OAUTH_TOKEN_URL,
           auth_params_builder=build_service_auth_params,
           token_data_builder=build_service_token_data,
           process_token_response=process_service_token_response,
       )

   async def get_credentials(user_id: str, service_name: str, api_key: str = None) -> str:
       """Get service credentials (access token)."""
       return await refresh_token_if_needed(
           user_id=user_id,
           service_name=service_name,
           token_url=SERVICE_OAUTH_TOKEN_URL,
           token_data_builder=lambda oauth_config, refresh_token, credentials: {
               "grant_type": "refresh_token",
               "refresh_token": refresh_token,
               "client_secret": oauth_config.get("client_secret"),
           },
           process_token_response=process_service_token_response,
           api_key=api_key,
       )
   ```

### For API Key Services

1. **Create utility module** (`src/utils/your-service-name/util.py`):
   ```python
   import logging
   from typing import Dict, List, Any

   from src.auth.factory import create_auth_client

   logger = logging.getLogger(__name__)

   def authenticate_and_save_credentials(
       user_id: str, service_name: str, scopes: List[str]
   ) -> Dict[str, Any]:
       """Authenticate with service and save credentials"""
       # For API key services, we prompt for the API key
       api_key = input("Enter your API key: ").strip()
       
       if not api_key:
           raise ValueError("API key is required")
       
       # Save credentials
       auth_client = create_auth_client()
       credentials = {"api_key": api_key}
       auth_client.save_user_credentials(service_name, user_id, credentials)
       
       return credentials

   async def get_credentials(user_id: str, service_name: str, api_key: str = None) -> str:
       """Get service credentials (API key)."""
       # If API key is provided directly, use it
       if api_key:
           return api_key

       # Otherwise, try to get from stored credentials
       auth_client = create_auth_client()
       credentials_data = auth_client.get_user_credentials(service_name, user_id)

       if not credentials_data:
           err = f"Service credentials not found for user {user_id}."
           err += " Please run with 'auth' argument first or provide an API key."
           logger.error(err)
           raise ValueError(err)

       stored_api_key = credentials_data.get("api_key")
       if not stored_api_key:
           err = f"Service API key not found in credentials for user {user_id}."
           logger.error(err)
           raise ValueError(err)

       return stored_api_key
   ```

## Step 3: Create API Client Function

Create an API client function in your main server file (this is now integrated into the server implementation):

## Step 4: Implement MCP Server

Create the main server implementation:

```python
import os
import sys
from typing import Optional, Iterable

# Add project paths
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import logging
from pathlib import Path

import aiohttp
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

from src.utils.your_service_name.util import authenticate_and_save_credentials, get_credentials

# Configuration
SERVICE_NAME = Path(__file__).parent.name
BASE_URL = "https://api.yourservice.com/v1"

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)

async def create_api_client(user_id, api_key=None):
    """
    Create a new API client instance using the stored credentials.

    Args:
        user_id (str): The user ID associated with the credentials.
        api_key (str, optional): Optional override for authentication.

    Returns:
        dict: API client configuration with credentials initialized.
    """
    token = await get_credentials(user_id, SERVICE_NAME, api_key=api_key)
    return {
        "api_key": token,
        "base_url": BASE_URL,
        "headers": {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    }

def create_server(user_id, api_key=None):
    """
    Initialize and configure the Your Service MCP server.

    Args:
        user_id (str): The user ID associated with the current session.
        api_key (str, optional): Optional API key override.

    Returns:
        Server: Configured MCP server instance with registered tools.
    """
    server = Server("your-service-server")

    server.user_id = user_id
    server.api_key = api_key

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """
        Return a list of available tools.

        Returns:
            list[Tool]: List of tool definitions supported by this server.
        """
        return [
            Tool(
                name="get_items",
                description="Retrieve items from the service",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of items to retrieve",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 50,
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Number of items to skip",
                            "minimum": 0,
                            "default": 0,
                        },
                    },
                },
            ),
            Tool(
                name="create_item",
                description="Create a new item in the service",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the item to create",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the item",
                        },
                    },
                    "required": ["name"],
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
            name (str): The name of the tool being called.
            arguments (dict | None): Parameters passed to the tool.

        Returns:
            list[Union[TextContent, ImageContent, EmbeddedResource]]:
                Output content from tool execution.
        """
        logger.info(
            f"User {server.user_id} calling tool: {name} with arguments: {arguments}"
        )

        if arguments is None:
            arguments = {}

        client_config = await create_api_client(server.user_id, api_key=server.api_key)

        try:
            async with aiohttp.ClientSession() as session:
                if name == "get_items":
                    url = f"{client_config['base_url']}/items"
                    params = {}
                    if arguments.get("limit"):
                        params["limit"] = arguments["limit"]
                    if arguments.get("offset"):
                        params["offset"] = arguments["offset"]
                    
                    async with session.get(url, headers=client_config['headers'], params=params) as response:
                        if response.status >= 400:
                            error_text = await response.text()
                            raise Exception(f"API request failed: {response.status} - {error_text}")
                        result = await response.json()

                elif name == "create_item":
                    if not arguments.get("name"):
                        raise ValueError("name is required")
                    
                    url = f"{client_config['base_url']}/items"
                    data = {
                        "name": arguments["name"],
                        "description": arguments.get("description", ""),
                    }
                    
                    async with session.post(url, headers=client_config['headers'], json=data) as response:
                        if response.status >= 400:
                            error_text = await response.text()
                            raise Exception(f"API request failed: {response.status} - {error_text}")
                        result = await response.json()

                else:
                    return [TextContent(type="text", text=f"Unknown tool: {name}")]

            return [TextContent(type="text", text=str(result))]

        except Exception as e:
            logger.error(f"API error: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    return server
```

## Step 5: Add Required Functions

Add the required functions for server discovery:

```python
server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """
    Define the initialization options for the MCP server.

    Args:
        server_instance (Server): The server instance to describe.

    Returns:
        InitializationOptions: MCP-compatible initialization configuration.
    """
    return InitializationOptions(
        server_name="your-service-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


if __name__ == "__main__":
    if sys.argv[1].lower() == "auth":
        user_id = "local"
        authenticate_and_save_credentials(user_id, SERVICE_NAME, [])
    else:
        print("Usage:")
        print("  python main.py auth - Run authentication flow for a user")
        print("Note: To run the server normally, use the guMCP server framework.")
```

## Step 6: Create Tests

Create a test file (`tests/servers/your_service_name/test.py`):

```python
import pytest
from unittest.mock import AsyncMock, patch
from src.servers.your_service_name.main import create_server

# Test data
MOCK_ITEMS = {
    "items": [
        {"id": "1", "name": "Test Item 1", "description": "Test Description 1"},
        {"id": "2", "name": "Test Item 2", "description": "Test Description 2"},
    ],
    "total": 2
}

MOCK_CREATED_ITEM = {
    "id": "3",
    "name": "New Item",
    "status": "created"
}

# Tool Tests
TOOL_TESTS = [
    {
        "name": "get_items",
        "description": "Test retrieving items with default parameters",
        "arguments": {},
        "expected_output": MOCK_ITEMS,
    },
    {
        "name": "get_items",
        "description": "Test retrieving items with limit",
        "arguments": {"limit": 10},
        "expected_output": MOCK_ITEMS,
    },
    {
        "name": "create_item",
        "description": "Test creating a new item",
        "arguments": {"name": "New Item", "description": "New Description"},
        "expected_output": MOCK_CREATED_ITEM,
    },
]

@pytest.mark.asyncio
async def test_tools():
    """Test all tools with mocked API responses"""
    with patch('src.servers.your_service_name.main.create_api_client') as mock_get_client:
        # Mock the API client config
        mock_client_config = {
            "api_key": "test_key",
            "base_url": "https://api.test.com/v1",
            "headers": {"Authorization": "Bearer test_key", "Content-Type": "application/json"}
        }
        mock_get_client.return_value = mock_client_config

        # Create server instance
        server = create_server("test_user")
        
        for test in TOOL_TESTS:
            result = await server.call_tool(
                test["name"], 
                test["arguments"]
            )
            
            assert len(result) == 1
            assert result[0].type == "text"

@pytest.mark.asyncio
async def test_authentication():
    """Test authentication flow"""
    with patch('src.utils.your_service_name.util.get_credentials') as mock_get_creds:
        mock_get_creds.return_value = "test_api_key"
        
        from src.servers.your_service_name.main import create_api_client
        client_config = await create_api_client("test_user")
        assert client_config["api_key"] == "test_api_key"

if __name__ == "__main__":
    pytest.main([__file__])
```

## Step 7: Update Documentation

Create a comprehensive README for your service (`src/servers/your_service_name/README.md`):

```markdown
# Your Service Name Integration

This MCP server provides integration with [Your Service Name], allowing you to interact with [service functionality] through the Model Context Protocol.

## Features

- **Get Items**: Retrieve items from your service
- **Create Items**: Create new items in your service
- **Authentication**: Secure OAuth 2.0 / API key authentication

## Authentication

### OAuth 2.0 (Recommended)

1. Register your application with [Your Service Name]
2. Configure OAuth settings in `local_auth/oauth_configs/your-service-name/oauth.json`
3. Run authentication:
   ```bash
   python src/servers/your_service_name/main.py auth <user_id>
   ```

### API Key

1. Get your API key from [Your Service Name] dashboard
2. Run authentication:
   ```bash
   python src/servers/your_service_name/main.py auth <user_id>
   # Enter your API key when prompted
   ```

## Available Tools

### get_items

Retrieve items from your service with optional filtering.

**Parameters:**
- `limit` (optional): Number of items to retrieve (1-100, default: 50)
- `offset` (optional): Number of items to skip (default: 0)

**Example:**
```json
{
  "limit": 10,
  "offset": 0
}
```

### create_item

Create a new item in your service.

**Parameters:**
- `name` (required): Name of the item
- `description` (optional): Description of the item

**Example:**
```json
{
  "name": "My New Item",
  "description": "This is a new item"
}
```

## Testing

Run the test suite:

```bash
# Run specific tests
python tests/servers/your_service_name/test.py

# Run with test runner
python tests/servers/test_runner.py --server=your-service-name
```

## Error Handling

The server includes comprehensive error handling for:
- Authentication failures
- API rate limits
- Network connectivity issues
- Invalid parameters

All errors are returned as human-readable messages to help with debugging.
```

## Step 8: Test Your Integration

1. **Test server loading**:
   ```bash
   python -c "
   import sys
   sys.path.insert(0, 'src')
   from servers.your_service_name import main
   print('✓ Server loads successfully')
   print('✓ create_server function exists:', hasattr(main, 'create_server'))
   print('✓ get_initialization_options function exists:', hasattr(main, 'get_initialization_options'))
   "
   ```

2. **Test authentication**:
   ```bash
   python src/servers/your_service_name/main.py auth
   ```

3. **Run tests**:
   ```bash
   python tests/servers/your_service_name/test.py
   ```

4. **Test with SSE server**:
   ```bash
   # Start the SSE server
   ./start_sse_dev_server.sh
   
   # Test your server
   python tests/clients/RemoteMCPTestClient.py --endpoint=http://localhost:8000/your-service-name/test_user
   ```

## Common Patterns and Examples

### OAuth with Refresh Tokens

For services that support refresh tokens, use the `refresh_token_if_needed` utility:

```python
async def get_credentials(user_id: str, service_name: str, api_key: str = None) -> str:
    """Get service credentials with automatic token refresh."""
    return await refresh_token_if_needed(
        user_id=user_id,
        service_name=service_name,
        token_url=SERVICE_OAUTH_TOKEN_URL,
        token_data_builder=lambda oauth_config, refresh_token, credentials: {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_secret": oauth_config.get("client_secret"),
        },
        process_token_response=process_service_token_response,
        api_key=api_key,
    )
```

### API Key Authentication

For services that use API keys:

```python
def authenticate_and_save_credentials(
    user_id: str, service_name: str, scopes: List[str]
) -> Dict[str, Any]:
    """Authenticate with service and save credentials"""
    api_key = input("Enter your API key: ").strip()
    
    if not api_key:
        raise ValueError("API key is required")
    
    auth_client = create_auth_client()
    credentials = {"api_key": api_key}
    auth_client.save_user_credentials(service_name, user_id, credentials)
    
    return credentials
```

### Error Handling in Tool Implementation

```python
try:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=client_config['headers']) as response:
            if response.status >= 400:
                error_text = await response.text()
                raise Exception(f"API request failed: {response.status} - {error_text}")
            result = await response.json()
except Exception as e:
    logger.error(f"API error: {e}")
    return [TextContent(type="text", text=f"Error: {str(e)}")]
```

## Troubleshooting

### Common Issues

1. **"Server does not have required create_server or get_initialization_options"**
   - Ensure you've added both functions to your main.py file
   - Check that the functions are properly defined and return the correct types

2. **Authentication failures**
   - Verify your OAuth configuration is correct
   - Check that API keys are valid and have proper permissions
   - Ensure the redirect URI matches your OAuth app settings

3. **Import errors**
   - Make sure all required dependencies are installed
   - Check that your Python path includes the project root and src directory

4. **API rate limiting**
   - Implement proper retry logic with exponential backoff
   - Consider adding rate limiting to your API client

### Getting Help

- Check existing server implementations for reference
- Review the [CONTRIBUTING.md](CONTRIBUTING.MD) for additional guidelines
- Open an issue in the GitHub repository for specific problems
- Join the community discussions for general questions

## Next Steps

After creating your integration:

1. **Submit a Pull Request** with your implementation
2. **Add to the main README** by updating the supported servers table
3. **Create comprehensive tests** to ensure reliability
4. **Document any special requirements** or limitations
5. **Consider adding resources** if your service supports them

Congratulations! You've successfully created a new MCP integration for pfMCP. Your contribution helps build the largest collection of open-source MCP servers.
