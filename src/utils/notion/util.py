import base64
import logging
import re
from typing import Dict, List, Any
from urllib.parse import parse_qs, urlparse

from src.utils.oauth.util import (
    run_oauth_flow,
    refresh_token_if_needed,
)

logger = logging.getLogger(__name__)

NOTION_OAUTH_AUTHORIZE_URL = "https://api.notion.com/v1/oauth/authorize"
NOTION_OAUTH_TOKEN_URL = "https://api.notion.com/v1/oauth/token"


def build_notion_auth_params(
    oauth_config: Dict[str, Any], redirect_uri: str, scopes: List[str]
) -> Dict[str, str]:
    """
    Build the authorization parameters for Notion OAuth.

    Args:
        oauth_config: OAuth configuration dictionary with client_id, redirect_uri, etc.
        redirect_uri: Redirect URI configured for the Notion integration.
        scopes: List of scopes (Notion currently ignores them).

    Returns:
        Dictionary of query params for the OAuth URL.
    """
    return {
        "client_id": oauth_config.get("client_id"),
        "response_type": "code",
        "owner": "user",
        "redirect_uri": redirect_uri,
    }


def build_notion_token_data(
    oauth_config: Dict[str, Any], redirect_uri: str, scopes: List[str], auth_code: str
) -> Dict[str, str]:
    """
    Build the token request body for exchanging code with access token.

    Args:
        oauth_config: OAuth configuration dictionary.
        redirect_uri: Redirect URI used in the flow.
        scopes: Scopes list (not used in Notion).
        auth_code: The authorization code returned from Notion.

    Returns:
        POST body dictionary for token exchange.
    """
    return {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": redirect_uri,
    }


def build_notion_token_headers(oauth_config: Dict[str, Any]) -> Dict[str, str]:
    """
    Build the token request headers for Notion OAuth.

    Uses Basic Auth header with base64 encoded client_id:client_secret.

    Args:
        oauth_config: OAuth configuration dictionary.

    Returns:
        Dictionary of headers.
    """
    credentials = f'{oauth_config["client_id"]}:{oauth_config["client_secret"]}'
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    return {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    }


def process_notion_token_response(token_response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process Notion's token response.

    Args:
        token_response: Raw token response JSON from Notion.

    Returns:
        Cleaned-up and standardized credentials dictionary.

    Raises:
        ValueError: If response is missing required access token.
    """
    if "access_token" not in token_response:
        raise ValueError(
            f"Token exchange failed: {token_response.get('error', 'Unknown error')}"
        )

    return {
        "access_token": token_response.get("access_token"),
        "workspace_id": token_response.get("workspace_id"),
        "bot_id": token_response.get("bot_id"),
        "duplicated_template_id": token_response.get("duplicated_template_id"),
    }


def authenticate_and_save_credentials(
    user_id: str, service_name: str, scopes: List[str]
) -> Dict[str, Any]:
    """
    Authenticate with Notion and save credentials securely.

    Args:
        user_id: ID of the user being authenticated.
        service_name: Service identifier (e.g., 'notion').
        scopes: List of scopes (Notion ignores this for now).

    Returns:
        Dictionary containing final credentials (e.g., access_token).
    """
    return run_oauth_flow(
        service_name=service_name,
        user_id=user_id,
        scopes=scopes,
        auth_url_base=NOTION_OAUTH_AUTHORIZE_URL,
        token_url=NOTION_OAUTH_TOKEN_URL,
        auth_params_builder=build_notion_auth_params,
        token_data_builder=build_notion_token_data,
        token_header_builder=build_notion_token_headers,
        process_token_response=process_notion_token_response,
    )


async def get_credentials(user_id: str, service_name: str, api_key: str = None) -> str:
    """
    Retrieve (or refresh if needed) the access token for Notion.

    Args:
        user_id: ID of the user.
        service_name: Name of the service (notion).
        api_key: Optional API key (used by auth client abstraction).

    Returns:
        A valid access token string.
    """
    return await refresh_token_if_needed(
        user_id=user_id,
        service_name=service_name,
        token_url=NOTION_OAUTH_TOKEN_URL,
        token_data_builder=lambda *args: {},  # Notion doesn’t support refresh tokens
        token_header_builder=build_notion_token_headers,
        api_key=api_key,
    )


_NOTION_ID_PATTERN = re.compile(
    r"^(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)
_TRAILING_NOTION_ID_PATTERN = re.compile(
    r"(?:^|-)([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32})$"
)


def validate_notion_id(value: Any, field_name: str = "id") -> str:
    """
    Validate that a Notion resource ID is a 32-character hex or hyphenated UUID.

    Args:
        value (Any): Candidate Notion ID.
        field_name (str): Parameter name used in error messages.

    Returns:
        str: Canonical lowercase Notion UUID string.

    Raises:
        ValueError: If value is not a valid Notion UUID.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a valid Notion UUID")
    normalized = value.strip()
    if not _NOTION_ID_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"{field_name} must be a valid Notion UUID (32 hex characters or hyphenated UUID)"
        )
    return normalized.lower()


def extract_page_id_from_url(url: str) -> str:
    """
    Extracts the page ID from a Notion URL.

    Prefers the ``p`` query parameter on database/parent peek URLs (e.g.
    ``?v=<view_id>&p=<page_id>``); otherwise extracts the trailing UUID/32-hex
    page ID from the URL path only (ignoring ``?v=`` and ``#block_id`` fragments).

    Args:
        url (str): A Notion page URL (with or without scheme).

    Returns:
        str: The validated page ID extracted from the URL.

    Raises:
        ValueError: If the URL doesn't contain a valid page ID.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Could not extract page ID from the provided URL")

    candidate = url.strip()
    if not re.match(r"^https?://", candidate, re.IGNORECASE):
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    if "p" in query_params:
        peek_values = [value.strip() for value in query_params["p"] if value.strip()]
        if not peek_values:
            raise ValueError("Invalid page ID in 'p' query parameter")
        return validate_notion_id(peek_values[0], "page")

    path = parsed.path.rstrip("/")
    last_segment = path.rsplit("/", 1)[-1] if path else ""
    match = _TRAILING_NOTION_ID_PATTERN.search(last_segment)
    if match:
        return validate_notion_id(match.group(1), "page")

    raise ValueError("Could not extract page ID from the provided URL")
