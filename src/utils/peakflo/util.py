import logging
from typing import Dict, List, Any

from src.utils.oauth.util import run_oauth_flow, refresh_token_if_needed

logger = logging.getLogger(__name__)


def process_peakflo_token_response(token_response: Dict[str, Any]) -> Dict[str, Any]:
    """Process Slack token response."""
    if not token_response.get("ok"):
        raise ValueError(
            f"Token exchange failed: {token_response.get('error', 'Unknown error')}"
        )

    # Extract and prepare credentials
    access_token = token_response.get("access_token")

    # Store only what we need
    return {
        "access_token": access_token,
        "token_type": "Bearer",
    }


def authenticate_and_save_credentials(
    user_id: str, service_name: str
) -> Dict[str, Any]:
    """Authenticate with Slack and save credentials"""
    return run_oauth_flow(
        service_name=service_name,
        user_id=user_id,
        scopes=[],
        auth_url_base="",
        token_url="",
        auth_params_builder="",
        token_data_builder="",
        process_token_response=process_peakflo_token_response,
    )


async def get_credentials(user_id: str, service_name: str, api_key: str = None) -> str:
    """Get Slack credentials"""
    return await refresh_token_if_needed(
        user_id=user_id,
        service_name=service_name,
        token_url="",
        token_data_builder=lambda *args: {},  # Slack doesn't use refresh tokens
        api_key=api_key,
    )
