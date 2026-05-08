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

### query_search_analytics
Query search performance data with flexible dimensions and filters.

**Arguments:**
- `site_url` (required) — The site URL (e.g., `https://peakflo.co` or `sc-domain:peakflo.co`)
- `start_date` (required) — Start date in ISO format (YYYY-MM-DD)
- `end_date` (required) — End date in ISO format (YYYY-MM-DD)
- `dimensions` (optional) — List of dimensions: `query`, `page`, `date`, `country`, `device`, `searchAppearance`
- `page_filter` (optional) — Filter by page URL. Accepts full URL (`https://peakflo.co/blog/...`) or path-only (`/blog/...`) — paths are auto-expanded to full URLs using `site_url`
- `query_filter` (optional) — Filter by search query (contains match)
- `row_limit` (optional) — Max rows to return (default: 25, max: 25000)

**Returns:** Rows with `clicks`, `impressions`, `ctr`, `position`, and dimension keys.

### list_sitemaps
List all sitemaps submitted for a given site.

**Arguments:**
- `site_url` (required) — The site URL

### inspect_url
Request Google's URL inspection data for a specific URL. Returns indexing status, crawl info, and mobile usability.

**Arguments:**
- `site_url` (required) — The site URL (property)
- `inspection_url` (required) — The fully-qualified URL to inspect

## Usage Examples

### Query search analytics for a specific page
```
Tool: query_search_analytics
Args: {
  "site_url": "https://peakflo.co",
  "start_date": "2025-01-01",
  "end_date": "2025-03-01",
  "dimensions": ["query"],
  "page_filter": "https://peakflo.co/blog/finance-automation-roi-guide-cfo",
  "row_limit": 10
}
```

### Using path-only filter (auto-expanded)
```
Tool: query_search_analytics
Args: {
  "site_url": "https://peakflo.co",
  "start_date": "2025-01-01",
  "end_date": "2025-03-01",
  "dimensions": ["query"],
  "page_filter": "/blog/finance-automation-roi-guide-cfo",
  "row_limit": 10
}
```
The path `/blog/finance-automation-roi-guide-cfo` is auto-expanded to `https://peakflo.co/blog/finance-automation-roi-guide-cfo` using the `site_url`.

## URL Mapping with GA4
GSC uses full URLs for the `page` dimension (e.g., `https://peakflo.co/blog/...`).
GA4 uses path-only for `pagePath` (e.g., `/blog/...`).

Both servers auto-normalize inputs, so you can pass either format to either tool:
- **GSC:** path-only input is auto-expanded to full URL using `site_url`
- **GA4:** full URL input is auto-normalized to path-only

The shared `url_utils` module (`src/utils/url_utils.py`) handles this normalization.

## Running

### Local (stdio)
```bash
python src/servers/local.py --server gsc
```

### Remote (HTTP)
Automatically discovered by `remote.py` — no registration needed.

## Testing
```bash
# Unit tests (URL normalization)
pytest tests/utils/test_url_utils.py -v

# Integration tests (requires OAuth credentials)
pytest tests/servers/gsc/tests.py -v
```
