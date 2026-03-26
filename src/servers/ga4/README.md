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
- `property_id` (required) — GA4 property ID (numeric, e.g., `123456789`). Do NOT include `properties/` prefix.
- `start_date` (required) — Start date (YYYY-MM-DD or relative like `30daysAgo`, `7daysAgo`)
- `end_date` (required) — End date (YYYY-MM-DD or `today`, `yesterday`)
- `metrics` (required) — List of metrics: `sessions`, `totalUsers`, `newUsers`, `engagementRate`, `screenPageViews`, `averageSessionDuration`, `bounceRate`, `conversions`, etc.
- `dimensions` (optional) — List of dimensions: `pagePath`, `sessionSource`, `sessionMedium`, `sessionSourceMedium`, `date`, `country`, `city`, `deviceCategory`, etc.
- `page_path_filter` (optional) — Filter by pagePath. Accepts path (`/blog/...`) or full URL (`https://peakflo.co/blog/...`) — full URLs are auto-normalized to path-only
- `row_limit` (optional) — Max rows to return (default: 25, max: 100000)

**Returns:** Rows with requested metric values and dimension values, plus totals if available.

### get_realtime_report
Get real-time analytics data for a GA4 property (active users, page views, etc.).

**Arguments:**
- `property_id` (required) — GA4 property ID (numeric)
- `metrics` (required) — Real-time metrics: `activeUsers`, `screenPageViews`, `conversions`, `eventCount`, etc.
- `dimensions` (optional) — Real-time dimensions: `unifiedScreenName`, `country`, `city`, `deviceCategory`, etc.

### get_metadata
Get the list of available dimensions and metrics for a GA4 property. Useful for discovering what can be used in reports.

**Arguments:**
- `property_id` (required) — GA4 property ID (numeric)

## Usage Examples

### Sessions, users, and engagement for a blog page
```
Tool: run_report
Args: {
  "property_id": "123456789",
  "start_date": "30daysAgo",
  "end_date": "today",
  "metrics": ["sessions", "totalUsers", "engagementRate"],
  "dimensions": ["pagePath"],
  "page_path_filter": "/blog/finance-automation-roi-guide-cfo"
}
```

### Traffic sources for a page
```
Tool: run_report
Args: {
  "property_id": "123456789",
  "start_date": "30daysAgo",
  "end_date": "today",
  "metrics": ["sessions"],
  "dimensions": ["sessionSourceMedium", "pagePath"],
  "page_path_filter": "/blog/finance-automation-roi-guide-cfo",
  "row_limit": 10
}
```

### Using full URL (auto-normalized)
```
Tool: run_report
Args: {
  "property_id": "123456789",
  "start_date": "30daysAgo",
  "end_date": "today",
  "metrics": ["sessions", "totalUsers"],
  "page_path_filter": "https://peakflo.co/blog/finance-automation-roi-guide-cfo"
}
```
The full URL is auto-normalized to `/blog/finance-automation-roi-guide-cfo`.

## URL Mapping with GSC
GA4 uses path-only for `pagePath` (e.g., `/blog/...`).
GSC uses full URLs for the `page` dimension (e.g., `https://peakflo.co/blog/...`).

Both servers auto-normalize inputs, so you can pass either format to either tool:
- **GA4:** full URL input is auto-normalized to path-only
- **GSC:** path-only input is auto-expanded to full URL using `site_url`

The shared `url_utils` module (`src/utils/url_utils.py`) handles this normalization.

## Running

### Local (stdio)
```bash
python src/servers/local.py --server ga4
```

### Remote (HTTP)
Automatically discovered by `remote.py` — no registration needed.

## Testing
```bash
# Unit tests (URL normalization)
pytest tests/utils/test_url_utils.py -v

# Integration tests (requires OAuth credentials)
pytest tests/servers/ga4/tests.py -v
```
