import os
import logging

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from src.auth.credential_errors import credential_error_from_last
from src.auth.factory import create_auth_client


def authenticate_and_save_credentials(user_id, service_name, scopes):
    """Authenticate with Google and save credentials"""
    logger = logging.getLogger(service_name)

    logger.info(f"Launching auth flow for user {user_id}...")

    # Get auth client
    auth_client = create_auth_client()

    # Get OAuth config
    oauth_config = auth_client.get_oauth_config(service_name)

    # Create and run flow
    flow = InstalledAppFlow.from_client_config(oauth_config, scopes)
    credentials = flow.run_local_server(
        port=8080, prompt="consent", access_type="offline", open_browser=True
    )

    # Save credentials using auth client
    auth_client.save_user_credentials(service_name, user_id, credentials)

    logger.info(f"Credentials saved for user {user_id}. You can now run the server.")
    return credentials


async def get_credentials(user_id, service_name, api_key=None):
    """Get credentials for the specified user"""
    logger = logging.getLogger(service_name)

    # Get auth client
    auth_client = create_auth_client(api_key=api_key)

    # Get credentials for this user
    credentials_data = auth_client.get_user_credentials(service_name, user_id)

    def handle_missing_credentials():
        # Say exactly which case it is. The message holds no connection id.
        error = credential_error_from_last(service_name)
        if os.environ.get("ENVIRONMENT", "local") == "local":
            logging.error("%s Please run with 'auth' argument first.", error)
        else:
            logging.error("%s", error)
        raise error

    if not credentials_data:
        handle_missing_credentials()

    token = credentials_data.get("token")
    if token:
        return Credentials.from_authorized_user_info(credentials_data)

    # If the auth client doesn't return key 'token', but instead returns 'access_token', assume that refreshing is taken care of on the auth client side
    token = credentials_data.get("access_token")
    if token:
        return Credentials(token=token)

    handle_missing_credentials()
