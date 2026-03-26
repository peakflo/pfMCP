"""
Google Search Console (GSC) MCP Server

Exposes tools for:
- Listing verified sites/properties
- Querying search analytics (clicks, impressions, CTR, position, queries)
- Listing sitemaps
- URL inspection
"""

import os
import sys
import logging
import json
from pathlib import Path

# Add project root and src directory to Python path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.auth.factory import create_auth_client
from src.utils.url_utils import normalize_gsc_page_filter

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("gsc-server")

SERVICE_NAME = Path(__file__).parent.name  # "gsc"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


async def get_credentials(user_id, api_key=None):
    """Get Google OAuth2 credentials for the specified user.

    Args:
        user_id (str): The identifier of the user whose credentials are needed.
        api_key (Optional[str]): Optional API key for different environments.

    Returns:
        Credentials: The Google OAuth2 credentials for the specified user.

    Raises:
        ValueError: If no valid credentials can be found.
    """
    auth_client = create_auth_client(api_key=api_key)
    credentials_data = auth_client.get_user_credentials(SERVICE_NAME, user_id)

    if not credentials_data:
        error_str = f"Credentials not found for user {user_id}."
        if os.environ.get("ENVIRONMENT", "local") == "local":
            error_str += " Please run with 'auth' argument first."
        logger.error(error_str)
        raise ValueError(error_str)

    # Handle both token formats (local vs Nango)
    token = credentials_data.get("token")
    if token:
        return Credentials.from_authorized_user_info(credentials_data)

    token = credentials_data.get("access_token")
    if token:
        return Credentials(token=token)

    raise ValueError(f"No valid token in credentials for user {user_id}")


async def create_searchconsole_service(user_id, api_key=None):
    """Create a new Search Console API service instance.

    Args:
        user_id (str): The identifier of the user.
        api_key (Optional[str]): Optional API key.

    Returns:
        googleapiclient.discovery.Resource: Authorized Search Console API client.
    """
    credentials = await get_credentials(user_id, api_key=api_key)
    return build("searchconsole", "v1", credentials=credentials)


def create_server(user_id, api_key=None):
    """Create a new MCP server instance for Google Search Console.

    Args:
        user_id (str): The identifier of the user.
        api_key (Optional[str]): Optional API key.

    Returns:
        Server: Configured MCP server with GSC tools.
    """
    server = Server("gsc-server")
    server.user_id = user_id
    server.api_key = api_key

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """List available GSC tools."""
        return [
            types.Tool(
                name="list_sites",
                description="List all sites/properties the user has access to in Google Search Console",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            types.Tool(
                name="query_search_analytics",
                description="Query search analytics data (clicks, impressions, CTR, position, queries) for a site, optionally filtered by page URL",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "site_url": {
                            "type": "string",
                            "description": "The site URL, e.g., https://peakflo.co or sc-domain:peakflo.co",
                        },
                        "start_date": {
                            "type": "string",
                            "description": "Start date in ISO format (YYYY-MM-DD)",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date in ISO format (YYYY-MM-DD)",
                        },
                        "dimensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Dimensions to group by: query, page, date, country, device, searchAppearance",
                        },
                        "page_filter": {
                            "type": "string",
                            "description": "Optional page URL to filter results. Accepts full URL (https://peakflo.co/blog/...) or path-only (/blog/...) — paths are auto-expanded using site_url.",
                        },
                        "query_filter": {
                            "type": "string",
                            "description": "Optional search query filter (contains match)",
                        },
                        "row_limit": {
                            "type": "integer",
                            "description": "Max rows to return (default: 25, max: 25000)",
                        },
                    },
                    "required": ["site_url", "start_date", "end_date"],
                },
            ),
            types.Tool(
                name="list_sitemaps",
                description="List all sitemaps submitted for a site",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "site_url": {
                            "type": "string",
                            "description": "The site URL",
                        },
                    },
                    "required": ["site_url"],
                },
            ),
            types.Tool(
                name="inspect_url",
                description="Request URL inspection data for a specific URL in a site property. Returns indexing status, crawl info, and mobile usability.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "site_url": {
                            "type": "string",
                            "description": "The site URL (property), e.g., https://peakflo.co or sc-domain:peakflo.co",
                        },
                        "inspection_url": {
                            "type": "string",
                            "description": "The fully-qualified URL to inspect (must be under the site_url property)",
                        },
                    },
                    "required": ["site_url", "inspection_url"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Dispatch and handle tool execution."""
        logger.info(
            f"User {server.user_id} calling tool: {name} with arguments: {arguments}"
        )

        try:
            service = await create_searchconsole_service(server.user_id, server.api_key)

            if name == "list_sites":
                return await _list_sites(service)
            elif name == "query_search_analytics":
                return await _query_search_analytics(service, arguments)
            elif name == "list_sitemaps":
                return await _list_sitemaps(service, arguments)
            elif name == "inspect_url":
                return await _inspect_url(service, arguments)
            else:
                raise ValueError(f"Unknown tool: {name}")

        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}")
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": str(e)}),
                )
            ]

    return server


async def _list_sites(service) -> list[types.TextContent]:
    """List all verified sites in Google Search Console."""
    result = service.sites().list().execute()
    sites = result.get("siteEntry", [])

    site_list = []
    for site in sites:
        site_list.append(
            {
                "siteUrl": site.get("siteUrl"),
                "permissionLevel": site.get("permissionLevel"),
            }
        )

    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {"sites": site_list, "totalSites": len(site_list)}, indent=2
            ),
        )
    ]


async def _query_search_analytics(service, arguments: dict) -> list[types.TextContent]:
    """Query search analytics data with optional page/query filters."""
    site_url = arguments["site_url"]
    start_date = arguments["start_date"]
    end_date = arguments["end_date"]
    dimensions = arguments.get("dimensions", ["query", "page"])
    page_filter = arguments.get("page_filter")
    query_filter = arguments.get("query_filter")
    row_limit = arguments.get("row_limit", 25)

    # Auto-normalize page_filter: if user passes a path like /blog/..., convert to full URL
    if page_filter:
        page_filter = normalize_gsc_page_filter(page_filter, site_url)

    # Clamp row_limit
    row_limit = max(1, min(row_limit, 25000))

    # Build the request body
    request_body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions,
        "rowLimit": row_limit,
    }

    # Build dimension filters
    dimension_filter_groups = []
    filters = []

    if page_filter:
        filters.append(
            {
                "dimension": "page",
                "operator": "equals",
                "expression": page_filter,
            }
        )

    if query_filter:
        filters.append(
            {
                "dimension": "query",
                "operator": "contains",
                "expression": query_filter,
            }
        )

    if filters:
        dimension_filter_groups.append({"filters": filters})
        request_body["dimensionFilterGroups"] = dimension_filter_groups

    response = (
        service.searchanalytics().query(siteUrl=site_url, body=request_body).execute()
    )

    rows = response.get("rows", [])

    # Format the response
    formatted_rows = []
    for row in rows:
        formatted_row = {
            "keys": row.get("keys", []),
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": round(row.get("ctr", 0), 4),
            "position": round(row.get("position", 0), 2),
        }
        formatted_rows.append(formatted_row)

    result = {
        "siteUrl": site_url,
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions,
        "rows": formatted_rows,
        "totalRows": len(formatted_rows),
    }

    if page_filter:
        result["pageFilter"] = page_filter
    if query_filter:
        result["queryFilter"] = query_filter

    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, indent=2),
        )
    ]


async def _list_sitemaps(service, arguments: dict) -> list[types.TextContent]:
    """List all sitemaps for a site."""
    site_url = arguments["site_url"]

    result = service.sitemaps().list(siteUrl=site_url).execute()
    sitemaps = result.get("sitemap", [])

    sitemap_list = []
    for sitemap in sitemaps:
        sitemap_list.append(
            {
                "path": sitemap.get("path"),
                "lastSubmitted": sitemap.get("lastSubmitted"),
                "isPending": sitemap.get("isPending"),
                "isSitemapsIndex": sitemap.get("isSitemapsIndex"),
                "lastDownloaded": sitemap.get("lastDownloaded"),
                "warnings": sitemap.get("warnings", 0),
                "errors": sitemap.get("errors", 0),
            }
        )

    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {
                    "siteUrl": site_url,
                    "sitemaps": sitemap_list,
                    "totalSitemaps": len(sitemap_list),
                },
                indent=2,
            ),
        )
    ]


async def _inspect_url(service, arguments: dict) -> list[types.TextContent]:
    """Inspect a URL for indexing status, crawl info, and mobile usability."""
    site_url = arguments["site_url"]
    inspection_url = arguments["inspection_url"]

    request_body = {
        "inspectionUrl": inspection_url,
        "siteUrl": site_url,
    }

    response = service.urlInspection().index().inspect(body=request_body).execute()
    inspection_result = response.get("inspectionResult", {})

    # Extract key information
    index_status = inspection_result.get("indexStatusResult", {})
    crawl_result = index_status.get("crawlTimeSecs")
    mobile_usability = inspection_result.get("mobileUsabilityResult", {})
    rich_results = inspection_result.get("richResultsResult", {})

    result = {
        "inspectionUrl": inspection_url,
        "siteUrl": site_url,
        "indexStatus": {
            "verdict": index_status.get("verdict"),
            "coverageState": index_status.get("coverageState"),
            "robotsTxtState": index_status.get("robotsTxtState"),
            "indexingState": index_status.get("indexingState"),
            "lastCrawlTime": index_status.get("lastCrawlTime"),
            "pageFetchState": index_status.get("pageFetchState"),
            "crawlTimeSecs": crawl_result,
            "crawledAs": index_status.get("crawledAs"),
            "referringUrls": index_status.get("referringUrls", []),
        },
        "mobileUsability": {
            "verdict": mobile_usability.get("verdict"),
            "issues": mobile_usability.get("issues", []),
        },
        "richResults": {
            "verdict": rich_results.get("verdict"),
            "detectedItems": rich_results.get("detectedItems", []),
        },
    }

    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, indent=2),
        )
    ]


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """Get MCP initialization options for this server."""
    return InitializationOptions(
        server_name="gsc",
        server_version="0.1.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


# Export for auto-discovery by remote.py
server = create_server

if __name__ == "__main__":
    import asyncio
    from src.servers.local import run_local_server

    asyncio.run(run_local_server(create_server, get_initialization_options))
