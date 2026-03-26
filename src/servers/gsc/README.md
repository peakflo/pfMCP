# Google Search Console (GSC) MCP Server

## Overview
MCP server for querying Google Search Console data — search analytics (clicks, impressions, CTR, position), site management, sitemap listing, and URL inspection.

## Authentication
- **OAuth Scope:** `https://www.googleapis.com/auth/webmasters.readonly`
- **Nango Integration ID:** `google-search-console`
- **Auth Type:** OAuth2 (Google)

## Tools

### list_sites
List all sites/properties the user has access to in GSC.

### get_site_info
Get details for a specific site property.

### query_search_analytics
Query search performance data with flexible dimensions and filters.

**Arguments:**
- `site_url` (required) — The site URL (e.g., `https://peakflo.co`)
- `start_date` (required) — Start date (ISO format)
- `end_date` (required) — End date (ISO format)
- `dimensions` (optional) — List of dimensions: `query`, `page`, `date`, `country`, `device`
- `page_filter` (optional) — Filter by exact page URL
- `query_filter` (optional) — Filter by search query (contains)
- `row_limit` (optional) — Max rows to return (default: 25, max: 25000)

**Returns:** Rows with `clicks`, `impressions`, `ctr`, `position`, and dimension keys.

### list_sitemaps
List sitemaps for a given site.

### inspect_url
Request Google's URL inspection data for a specific URL.

## Usage Example
```
Tool: query_search_analytics
Args: {
  "site_url": "https://peakflo.co",
  "start_date": "2026-01-01",
  "end_date": "2026-03-26",
  "dimensions": ["query", "page"],
  "page_filter": "https://peakflo.co/blog/finance-automation-roi-guide-cfo",
  "row_limit": 10
}
```

## URL Mapping Note
GSC uses full URLs for the `page` dimension (e.g., `https://peakflo.co/blog/...`).
When correlating with GA4 data, strip the scheme and host to get the `pagePath`.
