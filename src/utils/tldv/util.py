import logging
from typing import Optional

from src.auth.factory import create_auth_client

logger = logging.getLogger(__name__)


async def get_credentials(user_id: str, api_key: Optional[str] = None) -> str:
    """
    Retrieves the API key for a specific TLDV user.

    Args:
        user_id (str): The identifier of the user.
        api_key (Optional[str]): Optional API key passed during server creation.

    Returns:
        str: The API key to authenticate with the TLDV API.

    Raises:
        ValueError: If credentials are missing or invalid.
    """
    # If API key is provided directly, use it
    if api_key:
        return api_key

    # Otherwise, try to get from stored credentials
    auth_client = create_auth_client()
    credentials_data = auth_client.get_user_credentials("tldv", user_id)

    if not credentials_data:
        err = f"TLDV credentials not found for user {user_id}."
        if not api_key:
            err += " Please run with 'auth' argument first or provide an API key."
        logger.error(err)
        raise ValueError(err)

    stored_api_key = credentials_data.get("api_key")
    if not stored_api_key:
        err = f"TLDV API key not found in credentials for user {user_id}."
        logger.error(err)
        raise ValueError(err)

    return stored_api_key
