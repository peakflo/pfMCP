import logging
from typing import Dict, List, Any

from src.auth.factory import create_auth_client

logger = logging.getLogger(__name__)


def authenticate_and_save_credentials(
    user_id: str, service_name: str, scopes: List[str]
) -> Dict[str, Any]:
    """Authenticate with TLDV and save credentials"""
    # For TLDV, we use API key authentication instead of OAuth
    api_key = input("Enter your TLDV API key: ").strip()

    if not api_key:
        raise ValueError("API key is required")

    # Save credentials
    auth_client = create_auth_client()
    credentials = {"api_key": api_key}
    auth_client.save_user_credentials(service_name, user_id, credentials)

    return credentials


async def get_credentials(user_id: str, service_name: str, api_key: str = None) -> str:
    """Get TLDV credentials (API key)."""
    # If API key is provided directly, use it
    if api_key:
        return api_key

    # Otherwise, try to get from stored credentials
    auth_client = create_auth_client()
    credentials_data = auth_client.get_user_credentials(service_name, user_id)

    if not credentials_data:
        err = f"TLDV credentials not found for user {user_id}."
        err += " Please run with 'auth' argument first or provide an API key."
        logger.error(err)
        raise ValueError(err)
    logger.info("credentials_data", credentials_data)
    stored_api_key = credentials_data.get("apiKey")
    if not stored_api_key:
        err = f"TLDV API key not found in credentials for user {user_id}."
        logger.error(err)
        raise ValueError(err)

    return stored_api_key
