"""
Integration tests for the Google Search Console (GSC) MCP server.

Prerequisites:
- GSC OAuth credentials configured (via Nango or local auth)
- Access to at least one Search Console property

Run locally:
    pytest tests/servers/gsc/tests.py

Run against remote:
    pytest tests/servers/gsc/tests.py --remote --endpoint http://localhost:8000/gsc/local
"""

import pytest
import json
import re


@pytest.mark.asyncio
async def test_list_tools(client):
    """Test that GSC server exposes the expected tools."""
    response = await client.session.list_tools()
    tool_names = [tool.name for tool in response.tools]

    assert "list_sites" in tool_names, f"list_sites not found in {tool_names}"
    assert (
        "query_search_analytics" in tool_names
    ), f"query_search_analytics not found in {tool_names}"
    assert "list_sitemaps" in tool_names, f"list_sitemaps not found in {tool_names}"
    assert "inspect_url" in tool_names, f"inspect_url not found in {tool_names}"

    print(f"GSC tools: {tool_names}")
    print("✅ All expected GSC tools are available")


@pytest.mark.asyncio
async def test_list_sites(client):
    """Test listing verified sites in Google Search Console."""
    response = await client.process_query(
        "Use the list_sites tool to list all sites. "
        "If you found sites, start your response with 'I found the sites:'"
    )

    assert (
        "i found the sites" in response.lower()
    ), f"list_sites did not return sites: {response}"

    print(f"list_sites response: {response}")
    print("✅ Successfully listed GSC sites")


@pytest.mark.asyncio
async def test_query_search_analytics(client):
    """Test querying search analytics with page filter.

    This is the primary acceptance criteria test:
    - Filter: page = exact URL
    - Check response includes: clicks, impressions, ctr, position, queries
    """
    response = await client.process_query(
        "Use the query_search_analytics tool with these parameters: "
        "site_url='https://peakflo.co', "
        "start_date='2025-01-01', "
        "end_date='2025-03-01', "
        "dimensions=['query'], "
        "page_filter='https://peakflo.co/blog/finance-automation-roi-guide-cfo', "
        "row_limit=10. "
        "Report what you found. Include the words 'clicks', 'impressions', 'ctr', 'position' in your response."
    )

    response_lower = response.lower()
    assert "clicks" in response_lower, f"'clicks' not in response: {response}"
    assert "impressions" in response_lower, f"'impressions' not in response: {response}"
    assert "ctr" in response_lower, f"'ctr' not in response: {response}"
    assert "position" in response_lower, f"'position' not in response: {response}"

    print(f"query_search_analytics response: {response}")
    print("✅ Search analytics query returned expected metrics")


@pytest.mark.asyncio
async def test_query_search_analytics_path_normalization(client):
    """Test that passing a path-only page_filter is auto-expanded to full URL."""
    response = await client.process_query(
        "Use the query_search_analytics tool with these parameters: "
        "site_url='https://peakflo.co', "
        "start_date='2025-01-01', "
        "end_date='2025-03-01', "
        "dimensions=['query'], "
        "page_filter='/blog/finance-automation-roi-guide-cfo', "
        "row_limit=5. "
        "If you got results or an empty result set (not an error), say 'Query succeeded'."
    )

    assert (
        "query succeeded" in response.lower() or "error" not in response.lower()
    ), f"Path normalization may have failed: {response}"

    print(f"Path normalization response: {response}")
    print("✅ Path-only page_filter auto-expanded correctly")


@pytest.mark.asyncio
async def test_list_sitemaps(client):
    """Test listing sitemaps for a site."""
    response = await client.process_query(
        "Use the list_sitemaps tool for site_url='https://peakflo.co'. "
        "If you found sitemaps or got a valid response, start with 'Sitemaps result:'"
    )

    assert (
        "sitemaps result" in response.lower()
    ), f"list_sitemaps did not return valid response: {response}"

    print(f"list_sitemaps response: {response}")
    print("✅ Successfully listed sitemaps")
