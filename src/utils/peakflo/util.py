import os
import logging
from src.auth.factory import create_auth_client

logger = logging.getLogger(__name__)


def authenticate_and_save_credentials(user_id: str, service_name: str):
    """Authenticate with Peakflo and save credentials"""
    auth_client = create_auth_client()

    access_token = input("Please enter your Peakflo access token: ").strip()
    if not access_token:
        raise ValueError("Access token cannot be empty")

    api_key = input(
        "Please enter your Peakflo API key (x-api-key, press Enter to skip): "
    ).strip()
    client_id = input(
        "Please enter your Peakflo client ID (x-client-id, press Enter to skip): "
    ).strip()

    credentials = {"access_token": access_token}
    if api_key:
        credentials["api_key"] = api_key
    if client_id:
        credentials["client_id"] = client_id

    auth_client.save_user_credentials(service_name, user_id, credentials)
    logger.info("Peakflo credentials saved for user %s.", user_id)
    return credentials


async def get_credentials(user_id: str, service_name: str, api_key: str = None):
    """Get Peakflo credentials for the specified user"""
    auth_client = create_auth_client(api_key=api_key)
    credentials_data = auth_client.get_user_credentials(service_name, user_id)

    if not credentials_data:
        error_str = f"Peakflo credentials not found for user {user_id}."
        if os.environ.get("ENVIRONMENT", "local") == "local":
            error_str += " Please run authentication first."
        raise ValueError(error_str)

    if not credentials_data.get("access_token"):
        raise ValueError(f"Peakflo access token not found for user {user_id}.")

    return credentials_data
