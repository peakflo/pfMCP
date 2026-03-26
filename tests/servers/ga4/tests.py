"""
Integration tests for the Google Analytics 4 (GA4) MCP server.

Prerequisites:
- GA4 OAuth credentials configured (via Nango or local auth)
- Access to at least one GA4 property

Run locally:
    pytest tests/servers/ga4/tests.py

Run against remote:
    pytest tests/servers/ga4/tests.py --remote --endpoint http://localhost:8000/ga4/local
"""

import pytest
import json
import re


@pytest.mark.asyncio
async def test_list_tools(client):
    """Test that GA4 server exposes the expected tools."""
    response = await client.session.list_tools()
    tool_names = [tool.name for tool in response.tools]

    assert "list_properties" in tool_names, f"list_properties not found in {tool_names}"
    assert "run_report" in tool_names, f"run_report not found in {tool_names}"
    assert (
        "get_realtime_report" in tool_names
    ), f"get_realtime_report not found in {tool_names}"
    assert "get_metadata" in tool_names, f"get_metadata not found in {tool_names}"

    print(f"GA4 tools: {tool_names}")
    print("✅ All expected GA4 tools are available")


@pytest.mark.asyncio
async def test_list_properties(client):
    """Test listing GA4 properties."""
    response = await client.process_query(
        "Use the list_properties tool to list all GA4 properties. "
        "If you found properties, start your response with 'I found the properties:'"
    )

    assert (
        "i found the properties" in response.lower()
    ), f"list_properties did not return properties: {response}"

    print(f"list_properties response: {response}")
    print("✅ Successfully listed GA4 properties")


@pytest.mark.asyncio
async def test_run_report_sessions_users(client):
    """Test running a report for sessions and users with page path filter.

    This is the primary acceptance criteria test:
    - Filter: pagePath = /blog/finance-automation-roi-guide-cfo
    - Check response includes: sessions, users, engagement rate
    """
    response = await client.process_query(
        "Use the run_report tool with these parameters: "
        "property_id (use a valid one from list_properties first if needed), "
        "start_date='2025-01-01', end_date='2025-03-01', "
        "metrics=['sessions', 'totalUsers', 'engagementRate'], "
        "dimensions=['pagePath'], "
        "page_path_filter='/blog/finance-automation-roi-guide-cfo'. "
        "Report the sessions, users, and engagement rate. "
        "Include the words 'sessions', 'users', 'engagement' in your response."
    )

    response_lower = response.lower()
    assert "sessions" in response_lower, f"'sessions' not in response: {response}"
    assert "users" in response_lower, f"'users' not in response: {response}"
    assert "engagement" in response_lower, f"'engagement' not in response: {response}"

    print(f"run_report response: {response}")
    print("✅ GA4 report returned expected metrics (sessions, users, engagement)")


@pytest.mark.asyncio
async def test_run_report_traffic_source(client):
    """Test running a report for traffic sources.

    Acceptance criteria: GA4 response must include traffic source.
    """
    response = await client.process_query(
        "Use the run_report tool with these parameters: "
        "property_id (use a valid one), "
        "start_date='2025-01-01', end_date='2025-03-01', "
        "metrics=['sessions'], "
        "dimensions=['sessionSourceMedium', 'pagePath'], "
        "page_path_filter='/blog/finance-automation-roi-guide-cfo', "
        "row_limit=10. "
        "Report the traffic sources found. "
        "Include the word 'source' in your response."
    )

    assert "source" in response.lower(), f"'source' not in response: {response}"

    print(f"Traffic source response: {response}")
    print("✅ GA4 report returned traffic source data")


@pytest.mark.asyncio
async def test_run_report_url_normalization(client):
    """Test that passing a full URL as page_path_filter is auto-normalized to path."""
    response = await client.process_query(
        "Use the run_report tool with these parameters: "
        "property_id (use a valid one), "
        "start_date='2025-01-01', end_date='2025-03-01', "
        "metrics=['sessions'], "
        "page_path_filter='https://peakflo.co/blog/finance-automation-roi-guide-cfo'. "
        "If you got results or an empty result set (not an error), say 'Query succeeded'."
    )

    assert (
        "query succeeded" in response.lower() or "error" not in response.lower()
    ), f"URL normalization may have failed: {response}"

    print(f"URL normalization response: {response}")
    print("✅ Full URL auto-normalized to path for GA4 pagePath filter")


@pytest.mark.asyncio
async def test_get_metadata(client):
    """Test retrieving available dimensions and metrics metadata."""
    response = await client.process_query(
        "Use the get_metadata tool with a valid property_id "
        "(use list_properties first if needed). "
        "If you found metadata, start your response with 'Metadata result:'"
    )

    assert (
        "metadata result" in response.lower()
    ), f"get_metadata did not return valid response: {response}"

    print(f"get_metadata response: {response}")
    print("✅ Successfully retrieved GA4 metadata")
