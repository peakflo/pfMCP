# Google Analytics 4 (GA4) MCP Server

## Overview
MCP server for querying Google Analytics 4 data — traffic reports, user behavior, engagement metrics, and acquisition analysis using the GA4 Data API v1beta.

## Authentication
- **OAuth Scope:** `https://www.googleapis.com/auth/analytics.readonly`
- **Nango Integration ID:** `google-analytics`
- **Auth Type:** OAuth2 (Google)

## Tools

### list_properties
List all GA4 properties accessible to the authenticated user.

### run_report
Run a custom analytics report with configurable dimensions and metrics.

**Arguments:**
- `property_id` (required) — GA4 property ID (e.g., `properties/123456789`)
- `start_date` (required) — Start date (ISO format or relative like `30daysAgo`)
- `end_date` (required) — End date (ISO format or `today`)
- `metrics` (required) — List of metrics: `sessions`, `totalUsers`, `engagementRate`, `screenPageViews`, `averageSessionDuration`, etc.
- `dimensions` (optional) — List of dimensions: `pagePath`, `sessionSource`, `sessionMedium`, `date`, `country`, etc.
- `page_path_filter` (optional) — Filter by exact pagePath (e.g., `/blog/finance-automation-roi-guide-cfo`)
- `row_limit` (optional) — Max rows (default: 25, max: 100000)

**Returns:** Rows with requested metric values and dimension values.

### get_realtime_report
Get real-time analytics data for a GA4 property.

### get_metadata
Get the list of available dimensions and metrics for a property.

## Usage Example
```
Tool: run_report
Args: {
  "property_id": "properties/123456789",
  "start_date": "30daysAgo",
  "end_date": "today",
  "metrics": ["sessions", "totalUsers", "engagementRate"],
  "dimensions": ["pagePath", "sessionSource"],
  "page_path_filter": "/blog/finance-automation-roi-guide-cfo",
  "row_limit": 25
}
```

## URL Mapping Note
GA4 uses path-only format for `pagePath` (e.g., `/blog/finance-automation-roi-guide-cfo`).
When correlating with GSC data, prepend the scheme and host to construct the full URL.
