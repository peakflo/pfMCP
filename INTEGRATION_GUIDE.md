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
   import os
   from typing import Optional
   from src.auth.factory import create_auth_client
   from src.utils.oauth.util import run_oauth_flow, refresh_token_if_needed

   async def get_credentials(user_id: str, api_key: Optional[str] = None) -> str:
       """Get authenticated credentials for the service"""
       if api_key:
           return api_key
           
       auth_client = create_auth_client()
       credentials = auth_client.get_user_credentials("your-service-name", user_id)
       
       if not credentials:
           # Run OAuth flow if no credentials exist
           credentials = await run_oauth_flow("your-service-name", user_id)
           auth_client.save_user_credentials("your-service-name", user_id, credentials)
       
       # Refresh token if needed
       credentials = await refresh_token_if_needed("your-service-name", user_id, credentials)
       
       return credentials.get("access_token")
   ```

### For API Key Services

1. **Create utility module** (`src/utils/your-service-name/util.py`):
   ```python
   import os
   from typing import Optional
   from src.auth.factory import create_auth_client

   async def get_credentials(user_id: str, api_key: Optional[str] = None) -> str:
       """Get API key for the service"""
       if api_key:
           return api_key
           
       auth_client = create_auth_client()
       credentials = auth_client.get_user_credentials("your-service-name", user_id)
       
       if not credentials:
           raise ValueError("No credentials found. Please authenticate first.")
           
       return credentials.get("api_key")
   ```

## Step 3: Create API Client

Create an API client class in your main server file:

```python
import aiohttp
import asyncio
from typing import Optional, Dict, Any

class YourServiceApiClient:
    """API Client for Your Service"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.yourservice.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make a request to the API with retry logic"""
        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"{self.base_url}{endpoint}"
                    
                    async with session.request(
                        method=method, url=url, headers=self.headers, json=data, params=params
                    ) as response:
                        if response.status >= 400:
                            error_text = await response.text()
                            raise Exception(f"API request failed: {response.status} - {error_text}")

                        return await response.json()

            except Exception as e:
                if attempt == max_retries:
                    raise e
                await asyncio.sleep(retry_delay)
                retry_delay *= 2

    # Add your specific API methods here
    async def get_items(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get items from the service"""
        return await self.request("/items", params=params)

    async def create_item(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new item"""
        return await self.request("/items", method="POST", data=data)
```

## Step 4: Implement MCP Server

Create the main server implementation:

```python
import os
import sys
import logging
import json
from pathlib import Path
from typing import Optional, Dict, Any, List

# Add project paths
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from src.auth.factory import create_auth_client
from src.utils.your_service_name.util import get_credentials

# Configuration
SERVICE_NAME = Path(__file__).parent.name
logger = logging.getLogger(SERVICE_NAME)

# Create server instance
server = Server(SERVICE_NAME)

async def get_api_client(user_id: str, api_key: Optional[str] = None) -> YourServiceApiClient:
    """Get authenticated API client"""
    api_key = await get_credentials(user_id, api_key)
    return YourServiceApiClient(api_key)

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List all available tools"""
    return [
        types.Tool(
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
            outputSchema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Array of items from the service"
                    },
                    "total": {
                        "type": "integer",
                        "description": "Total number of items available"
                    }
                }
            }
        ),
        types.Tool(
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
            outputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Unique identifier of the created item"
                    },
                    "name": {
                        "type": "string",
                        "description": "Name of the created item"
                    },
                    "status": {
                        "type": "string",
                        "description": "Status of the created item"
                    }
                }
            }
        ),
    ]

@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None, user_id: str, api_key: str | None = None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls"""
    try:
        client = await get_api_client(user_id, api_key)

        if name == "get_items":
            params = {}
            if arguments:
                if arguments.get("limit"):
                    params["limit"] = arguments["limit"]
                if arguments.get("offset"):
                    params["offset"] = arguments["offset"]

            result = await client.get_items(params)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "create_item":
            if not arguments or not arguments.get("name"):
                raise ValueError("name is required")

            data = {
                "name": arguments["name"],
                "description": arguments.get("description", ""),
            }

            result = await client.create_item(data)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        logger.error(f"Error in tool {name}: {str(e)}")
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]

@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """List available resources"""
    return []

@server.read_resource()
async def handle_read_resource(
    uri: str, user_id: str, api_key: str | None = None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Read a resource"""
    raise ValueError(f"Unknown resource: {uri}")
```

## Step 5: Add Required Functions

Add the required functions for server discovery:

```python
def create_server(user_id: str, api_key: str | None = None) -> Server:
    """Create a server instance for the given user and API key"""
    return server

def get_initialization_options() -> InitializationOptions:
    """Get initialization options for the server"""
    return InitializationOptions(
        server_name=SERVICE_NAME,
        server_version="1.0.0",
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={}
        ),
    )

if __name__ == "__main__":
    import asyncio

    async def main():
        # Check if auth argument is provided
        if len(sys.argv) > 1 and sys.argv[1] == "auth":
            if len(sys.argv) < 3:
                print("Usage: python main.py auth <user_id>")
                sys.exit(1)

            user_id = sys.argv[2]
            
            # For OAuth services, run the OAuth flow
            from src.utils.your_service_name.util import get_credentials
            await get_credentials(user_id)
            print(f"Credentials saved for user {user_id}")
            return

        # Run the server
        await server.run()

    asyncio.run(main())
```

## Step 6: Create Tests

Create a test file (`tests/servers/your_service_name/test.py`):

```python
import pytest
from unittest.mock import AsyncMock, patch
from src.servers.your_service_name.main import server, get_api_client

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

# Resource Tests
RESOURCE_TESTS = [
    # Add resource tests if your service supports resources
]

@pytest.mark.asyncio
async def test_tools():
    """Test all tools with mocked API responses"""
    with patch('src.servers.your_service_name.main.get_api_client') as mock_get_client:
        # Mock the API client
        mock_client = AsyncMock()
        mock_client.get_items.return_value = MOCK_ITEMS
        mock_client.create_item.return_value = MOCK_CREATED_ITEM
        mock_get_client.return_value = mock_client

        for test in TOOL_TESTS:
            result = await server.call_tool(
                test["name"], 
                test["arguments"], 
                "test_user"
            )
            
            assert len(result) == 1
            assert result[0].type == "text"
            
            # Parse the JSON response
            import json
            response_data = json.loads(result[0].text)
            
            # Verify the response structure matches expected output
            if test["name"] == "get_items":
                assert "items" in response_data
                assert "total" in response_data
            elif test["name"] == "create_item":
                assert "id" in response_data
                assert "name" in response_data

@pytest.mark.asyncio
async def test_authentication():
    """Test authentication flow"""
    with patch('src.utils.your_service_name.util.get_credentials') as mock_get_creds:
        mock_get_creds.return_value = "test_api_key"
        
        client = await get_api_client("test_user")
        assert client.api_key == "test_api_key"

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
   python src/servers/your_service_name/main.py auth test_user
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

For services that support refresh tokens:

```python
async def get_credentials(user_id: str, api_key: Optional[str] = None) -> str:
    """Get credentials with automatic token refresh"""
    if api_key:
        return api_key
        
    auth_client = create_auth_client()
    credentials = auth_client.get_user_credentials("your-service-name", user_id)
    
    if not credentials:
        credentials = await run_oauth_flow("your-service-name", user_id)
        auth_client.save_user_credentials("your-service-name", user_id, credentials)
    
    # Check if token needs refresh
    if credentials.get("expires_at") and credentials["expires_at"] < time.time():
        credentials = await refresh_token_if_needed("your-service-name", user_id, credentials)
        auth_client.save_user_credentials("your-service-name", user_id, credentials)
    
    return credentials.get("access_token")
```

### Pagination Support

For APIs that support pagination:

```python
async def get_items_paginated(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """Get items with pagination support"""
    params = {"limit": limit, "offset": offset}
    return await self.request("/items", params=params)
```

### Error Handling with Retries

```python
async def request_with_retry(self, endpoint: str, max_retries: int = 3) -> Dict[str, Any]:
    """Make request with exponential backoff retry"""
    for attempt in range(max_retries + 1):
        try:
            return await self.request(endpoint)
        except Exception as e:
            if attempt == max_retries:
                raise e
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
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
