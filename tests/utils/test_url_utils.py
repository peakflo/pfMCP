"""
Unit tests for URL normalization utilities used in GSC ↔ GA4 URL mapping.

These tests verify that:
- Full URLs are correctly converted to paths (for GA4)
- Paths are correctly expanded to full URLs (for GSC)
- GSC page URLs and GA4 pagePaths map to the same page
- Edge cases (trailing slashes, query params, fragments) are handled
"""

import pytest
import sys
import os

# Add project root to path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

from src.utils.url_utils import (
    url_to_path,
    path_to_url,
    normalize_gsc_page_filter,
    normalize_ga4_page_path,
    urls_match,
)

# --- url_to_path ---


class TestUrlToPath:
    def test_full_url_to_path(self):
        assert (
            url_to_path("https://peakflo.co/blog/finance-automation-roi-guide-cfo")
            == "/blog/finance-automation-roi-guide-cfo"
        )

    def test_full_url_with_trailing_slash(self):
        assert (
            url_to_path("https://peakflo.co/blog/finance-automation-roi-guide-cfo/")
            == "/blog/finance-automation-roi-guide-cfo"
        )

    def test_root_url(self):
        assert url_to_path("https://peakflo.co/") == "/"
        assert url_to_path("https://peakflo.co") == "/"

    def test_path_passthrough(self):
        assert (
            url_to_path("/blog/finance-automation-roi-guide-cfo")
            == "/blog/finance-automation-roi-guide-cfo"
        )

    def test_path_with_trailing_slash(self):
        assert url_to_path("/blog/my-post/") == "/blog/my-post"

    def test_root_path(self):
        assert url_to_path("/") == "/"

    def test_empty_string(self):
        assert url_to_path("") == "/"

    def test_url_with_query_params(self):
        result = url_to_path("https://peakflo.co/blog/my-post?utm_source=google")
        assert result == "/blog/my-post"

    def test_url_with_fragment(self):
        result = url_to_path("https://peakflo.co/blog/my-post#section-1")
        assert result == "/blog/my-post"

    def test_http_url(self):
        assert url_to_path("http://peakflo.co/blog/my-post") == "/blog/my-post"

    def test_deep_path(self):
        assert (
            url_to_path("https://peakflo.co/blog/category/subcategory/my-post")
            == "/blog/category/subcategory/my-post"
        )


# --- path_to_url ---


class TestPathToUrl:
    def test_path_to_url(self):
        assert (
            path_to_url("/blog/my-post", "https://peakflo.co")
            == "https://peakflo.co/blog/my-post"
        )

    def test_full_url_passthrough(self):
        assert (
            path_to_url("https://peakflo.co/blog/my-post", "https://peakflo.co")
            == "https://peakflo.co/blog/my-post"
        )

    def test_base_url_trailing_slash(self):
        assert (
            path_to_url("/blog/my-post", "https://peakflo.co/")
            == "https://peakflo.co/blog/my-post"
        )

    def test_path_without_leading_slash(self):
        assert (
            path_to_url("blog/my-post", "https://peakflo.co")
            == "https://peakflo.co/blog/my-post"
        )

    def test_empty_path(self):
        assert path_to_url("", "https://peakflo.co") == "https://peakflo.co"

    def test_root_path(self):
        assert path_to_url("/", "https://peakflo.co") == "https://peakflo.co/"


# --- normalize_gsc_page_filter ---


class TestNormalizeGscPageFilter:
    def test_full_url_passthrough(self):
        assert (
            normalize_gsc_page_filter(
                "https://peakflo.co/blog/my-post", "https://peakflo.co"
            )
            == "https://peakflo.co/blog/my-post"
        )

    def test_path_expanded_with_site_url(self):
        assert (
            normalize_gsc_page_filter("/blog/my-post", "https://peakflo.co")
            == "https://peakflo.co/blog/my-post"
        )

    def test_path_expanded_with_sc_domain(self):
        assert (
            normalize_gsc_page_filter("/blog/my-post", "sc-domain:peakflo.co")
            == "https://peakflo.co/blog/my-post"
        )

    def test_none_passthrough(self):
        assert normalize_gsc_page_filter(None, "https://peakflo.co") is None

    def test_empty_passthrough(self):
        assert normalize_gsc_page_filter("", "https://peakflo.co") == ""

    def test_path_without_site_url(self):
        # Can't expand, returns as-is
        assert normalize_gsc_page_filter("/blog/my-post", None) == "/blog/my-post"


# --- normalize_ga4_page_path ---


class TestNormalizeGa4PagePath:
    def test_full_url_to_path(self):
        assert (
            normalize_ga4_page_path(
                "https://peakflo.co/blog/finance-automation-roi-guide-cfo"
            )
            == "/blog/finance-automation-roi-guide-cfo"
        )

    def test_path_passthrough(self):
        assert (
            normalize_ga4_page_path("/blog/finance-automation-roi-guide-cfo")
            == "/blog/finance-automation-roi-guide-cfo"
        )

    def test_url_with_trailing_slash(self):
        assert (
            normalize_ga4_page_path("https://peakflo.co/blog/my-post/")
            == "/blog/my-post"
        )


# --- urls_match ---


class TestUrlsMatch:
    def test_matching_url_and_path(self):
        assert urls_match(
            "https://peakflo.co/blog/finance-automation-roi-guide-cfo",
            "/blog/finance-automation-roi-guide-cfo",
        )

    def test_matching_with_trailing_slash(self):
        assert urls_match(
            "https://peakflo.co/blog/my-post/",
            "/blog/my-post",
        )

    def test_non_matching(self):
        assert not urls_match(
            "https://peakflo.co/blog/post-a",
            "/blog/post-b",
        )

    def test_root_match(self):
        assert urls_match("https://peakflo.co/", "/")

    def test_both_full_urls(self):
        assert urls_match(
            "https://peakflo.co/blog/my-post",
            "https://peakflo.co/blog/my-post",
        )

    def test_different_domains_same_path(self):
        # urls_match only compares paths, so different domains with same path match
        assert urls_match(
            "https://example.com/blog/my-post",
            "https://different.com/blog/my-post",
        )


# --- Acceptance criteria: specific test case ---


class TestAcceptanceCriteria:
    """Tests matching the exact acceptance criteria from the task specification."""

    BLOG_URL = "https://peakflo.co/blog/finance-automation-roi-guide-cfo"
    EXPECTED_PATH = "/blog/finance-automation-roi-guide-cfo"
    SITE_URL = "https://peakflo.co"

    def test_gsc_page_filter_from_full_url(self):
        """GSC should use the full URL as page filter."""
        result = normalize_gsc_page_filter(self.BLOG_URL, self.SITE_URL)
        assert result == self.BLOG_URL

    def test_ga4_page_path_from_full_url(self):
        """GA4 should extract path from full URL."""
        result = normalize_ga4_page_path(self.BLOG_URL)
        assert result == self.EXPECTED_PATH

    def test_gsc_page_equals_ga4_page_path(self):
        """GSC page and GA4 pagePath must map to the same page."""
        gsc_page = normalize_gsc_page_filter(self.BLOG_URL, self.SITE_URL)
        ga4_path = normalize_ga4_page_path(self.BLOG_URL)
        assert urls_match(gsc_page, ga4_path)

    def test_url_mapping_from_path_input(self):
        """If user provides only a path, both should still map correctly."""
        gsc_page = normalize_gsc_page_filter(self.EXPECTED_PATH, self.SITE_URL)
        ga4_path = normalize_ga4_page_path(self.EXPECTED_PATH)
        assert gsc_page == self.BLOG_URL
        assert ga4_path == self.EXPECTED_PATH
        assert urls_match(gsc_page, ga4_path)

    def test_url_mapping_with_sc_domain(self):
        """sc-domain: style site URLs should also work."""
        gsc_page = normalize_gsc_page_filter(self.EXPECTED_PATH, "sc-domain:peakflo.co")
        ga4_path = normalize_ga4_page_path(self.BLOG_URL)
        assert gsc_page == self.BLOG_URL
        assert urls_match(gsc_page, ga4_path)
