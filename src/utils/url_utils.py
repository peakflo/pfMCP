"""
URL normalization utilities for GSC ↔ GA4 URL mapping.

Google Search Console uses full URLs (e.g., https://peakflo.co/blog/finance-automation-roi-guide-cfo)
Google Analytics 4 uses path-only (e.g., /blog/finance-automation-roi-guide-cfo)

These utilities ensure both refer to the same page regardless of input format.
"""

from urllib.parse import urlparse, urlunparse


def url_to_path(url: str) -> str:
    """Extract the path component from a full URL.

    If the input is already a path (starts with /), returns it as-is.
    Strips trailing slashes (except for root path '/').

    Args:
        url: Full URL or path string.

    Returns:
        The path component (e.g., '/blog/finance-automation-roi-guide-cfo').

    Examples:
        >>> url_to_path('https://peakflo.co/blog/finance-automation-roi-guide-cfo')
        '/blog/finance-automation-roi-guide-cfo'
        >>> url_to_path('/blog/finance-automation-roi-guide-cfo')
        '/blog/finance-automation-roi-guide-cfo'
        >>> url_to_path('https://peakflo.co/')
        '/'
    """
    if not url:
        return "/"

    # Already a path
    if url.startswith("/"):
        path = url.rstrip("/") or "/"
        return path

    try:
        parsed = urlparse(url)
        path = parsed.path or "/"
        # Strip trailing slash except for root
        path = path.rstrip("/") or "/"
        return path
    except Exception:
        return url


def path_to_url(path: str, base_url: str) -> str:
    """Combine a path with a base URL to form a full URL.

    If the input is already a full URL (has scheme), returns it as-is.
    Strips trailing slashes from the result (except root).

    Args:
        path: Path string (e.g., '/blog/my-post') or full URL.
        base_url: Base URL including scheme and host (e.g., 'https://peakflo.co').

    Returns:
        Full URL string.

    Examples:
        >>> path_to_url('/blog/my-post', 'https://peakflo.co')
        'https://peakflo.co/blog/my-post'
        >>> path_to_url('https://peakflo.co/blog/my-post', 'https://peakflo.co')
        'https://peakflo.co/blog/my-post'
    """
    if not path:
        return base_url.rstrip("/")

    # Already a full URL
    if path.startswith("http://") or path.startswith("https://"):
        return path.rstrip("/") or path

    # Normalize base_url
    base = base_url.rstrip("/")

    # Ensure path starts with /
    if not path.startswith("/"):
        path = "/" + path

    result = base + path
    # Strip trailing slash except for root
    if result.endswith("/") and result != base + "/":
        result = result.rstrip("/")

    return result


def normalize_gsc_page_filter(page_filter: str, site_url: str = None) -> str:
    """Normalize a page filter value for GSC API.

    GSC expects full URLs for page dimension filtering.
    If a path-only value is provided and site_url is available,
    converts it to a full URL.

    Args:
        page_filter: Full URL or path to filter by.
        site_url: The GSC site URL (e.g., 'https://peakflo.co' or 'sc-domain:peakflo.co').

    Returns:
        Normalized full URL suitable for GSC page filter.
    """
    if not page_filter:
        return page_filter

    # Already a full URL
    if page_filter.startswith("http://") or page_filter.startswith("https://"):
        return page_filter

    # Path-only — need site_url to construct full URL
    if site_url and not site_url.startswith("sc-domain:"):
        return path_to_url(page_filter, site_url)

    # sc-domain property: construct URL from domain
    if site_url and site_url.startswith("sc-domain:"):
        domain = site_url.replace("sc-domain:", "")
        return path_to_url(page_filter, f"https://{domain}")

    # Can't determine full URL, return as-is
    return page_filter


def normalize_ga4_page_path(page_path: str) -> str:
    """Normalize a page path value for GA4 API.

    GA4 expects path-only values for pagePath dimension filtering.
    If a full URL is provided, extracts just the path component.

    Args:
        page_path: Full URL or path to filter by.

    Returns:
        Normalized path suitable for GA4 pagePath filter.

    Examples:
        >>> normalize_ga4_page_path('https://peakflo.co/blog/finance-automation-roi-guide-cfo')
        '/blog/finance-automation-roi-guide-cfo'
        >>> normalize_ga4_page_path('/blog/finance-automation-roi-guide-cfo')
        '/blog/finance-automation-roi-guide-cfo'
    """
    return url_to_path(page_path)


def urls_match(gsc_page: str, ga4_page_path: str) -> bool:
    """Check if a GSC page URL and GA4 pagePath refer to the same page.

    Args:
        gsc_page: Full URL from GSC (e.g., 'https://peakflo.co/blog/my-post').
        ga4_page_path: Path from GA4 (e.g., '/blog/my-post').

    Returns:
        True if both refer to the same page path.

    Examples:
        >>> urls_match('https://peakflo.co/blog/my-post', '/blog/my-post')
        True
        >>> urls_match('https://peakflo.co/blog/my-post/', '/blog/my-post')
        True
    """
    gsc_path = url_to_path(gsc_page)
    ga4_path = url_to_path(ga4_page_path)
    return gsc_path == ga4_path
