import os
import time
import logging
import requests
import jwt
from typing import Optional, Dict, Any, TypeVar, Generic, TypedDict

from auth.constants import (
    SERVICE_NAME_MAP,
    AUTH_TYPE_OAUTH2,
    AUTH_TYPE_UNAUTHENTICATED,
    AUTH_TYPE_API_KEY,
)

from .BaseAuthClient import BaseAuthClient, CredentialsT

logger = logging.getLogger("nango-auth-client")


class JWTTokenResponse(TypedDict):
    access_token: str
    expires_at: float


class NangoUnauthenticatedConnectionMetadata(TypedDict):
    tenantId: str
    privateKey: str
    accessToken: str


class NangoStandardConnectionCredentials(TypedDict):
    access_token: str
    expires_at: float
    refresh_token: Optional[str]


class NangoApiKeyConnectionCredentials(TypedDict):
    apiKey: str


class NangoAuthClient(BaseAuthClient[CredentialsT]):
    """
    Implementation of BaseAuthClient that uses Nango's infrastructure.

    Can work with any type of credentials that can be managed through Nango.
    """

    def __init__(self, secret_key: Optional[str] = None, host: Optional[str] = None):
        """
        Initialize the Nango auth client

        Args:
            secret_key: Nango secret key for service authentication
            host: Nango API host URL (defaults to Nango Cloud)
        """
        self.secret_key = secret_key or os.environ.get("NANGO_SECRET_KEY")
        self.host = host or os.environ.get("NANGO_HOST", "https://api.nango.dev")
        self.api_base_url = f"{self.host}"

        if not self.secret_key:
            logger.warning(
                "Missing Nango secret key. Some functionality may be limited."
            )

    def _map_service_name(self, service_name: str) -> str:
        """
        Map MCP service name to Nango service name

        Args:
            service_name: MCP service name

        Returns:
            Nango service name. If the service name is not in the mapping,
            the original service name is returned unchanged.
        """
        # If the service name is in our mapping, use the mapped value
        # Otherwise, use the original service name as is
        return SERVICE_NAME_MAP.get(service_name, {}).get(
            "nango_service_name", service_name
        )

    def _get_jwt_token(
        self, service_name: str, tenant_id: str, private_key: str, access_token: str
    ) -> JWTTokenResponse:
        """
        Get JWT token from Nango API
        """
        # Generate JWT token
        expires_at = time.time() + 3600
        payload = {
            "iss": service_name,
            "aud": service_name,
            "acc": access_token,
            "sub": tenant_id,
            "iat": time.time(),
            "exp": expires_at,
        }
        jwt_token = jwt.encode(
            payload,
            private_key,
            # algorithm="RS256"
        )
        return {"access_token": jwt_token, "expires_at": expires_at}

    def get_user_credentials(
        self, service_name: str, connection_id: str
    ) -> Optional[CredentialsT]:
        """
        Get user credentials from Nango API

        Args:
            service_name: Name of the service (e.g., "github", "slack", etc.)
            connection_id: Identifier for the connection

        Returns:
            Credentials object if found, None otherwise
        """
        if not self.secret_key:
            logger.error("Nango secret key is required to get user credentials")
            return None

        try:
            # Map the service name to Nango's service name
            nango_service_name = self._map_service_name(service_name)
            auth_type = SERVICE_NAME_MAP.get(service_name, {}).get(
                "auth_type", AUTH_TYPE_OAUTH2
            )
            # Use the Nango API to get connection details
            url = f"{self.api_base_url}/connection/{connection_id}?provider_config_key={nango_service_name}"
            logger.info(f"[get_user_credentials] url: {url}")
            headers = {"Authorization": f"Bearer {self.secret_key}"}

            response = requests.get(url, headers=headers)

            if response.status_code == 404:
                logger.info(
                    f"No connection found for {service_name} connection {connection_id}"
                )
                return None

            if response.status_code != 200:
                logger.error(
                    f"Failed to get connection details for {service_name} connection {connection_id}: {response.text}"
                )
                return None

            if auth_type == AUTH_TYPE_OAUTH2:
                # Return the credentials data as a dictionary
                # The caller is responsible for converting to the appropriate credentials type
                credentials: NangoStandardConnectionCredentials = response.json().get(
                    "credentials"
                )
                metadata = response.json().get("metadata", {})
                credentials["metadata"] = metadata
                return credentials
            elif auth_type == AUTH_TYPE_API_KEY:
                # Return the credentials data as a dictionary
                # The caller is responsible for converting to the appropriate credentials type
                credentials: NangoApiKeyConnectionCredentials = response.json().get(
                    "credentials"
                )
                return credentials
            elif auth_type == AUTH_TYPE_UNAUTHENTICATED:
                # Return the JWT token data
                connection_data = response.json()
                metadata: NangoUnauthenticatedConnectionMetadata = connection_data.get(
                    "metadata", {}
                )
                logger.info(
                    f"[get_user_credentials] metadata fetched for tenant {metadata.get('tenantId')}"
                )
                # check if metadata has all the required fields
                if (
                    not metadata.get("tenantId")
                    or not metadata.get("privateKey")
                    or not metadata.get("accessToken")
                ):
                    logger.error(
                        f"Missing required fields in metadata for {service_name} connection {connection_id}"
                    )
                    return None

                jwt_token_data = self._get_jwt_token(
                    service_name,
                    metadata.get("tenantId"),
                    metadata.get("privateKey"),
                    metadata.get("accessToken"),
                )
                return jwt_token_data

        except Exception as e:
            logger.error(
                f"Error retrieving credentials for {service_name} connection {connection_id}: {str(e)}"
            )
            return None

    def get_oauth_config(self, service_name: str) -> Dict[str, Any]:
        """
        Retrieves OAuth configuration for a specific service from Nango

        Args:
            service_name: Name of the service (e.g., "github", "slack", etc.)

        Returns:
            Dict containing OAuth configuration
        """
        if not self.secret_key:
            logger.error("Nango secret key is required to get OAuth config")
            raise ValueError("Nango secret key is required")

        try:
            # Map the service name to Nango's service name
            nango_service_name = self._map_service_name(service_name)

            # Get provider information from Nango
            url = f"{self.api_base_url}/provider/{nango_service_name}"
            logger.info(f"[get_oauth_config] url: {url}")
            headers = {"Authorization": f"Bearer {self.secret_key}"}

            response = requests.get(url, headers=headers)

            if response.status_code != 200:
                logger.error(
                    f"Failed to get provider info for {service_name}: {response.text}"
                )
                raise ValueError(f"Failed to get provider info for {service_name}")

            provider_data = response.json()

            # Extract OAuth configuration from provider data
            oauth_config = {
                "client_id": provider_data.get("oauth_client_id"),
                "client_secret": provider_data.get("oauth_client_secret"),
                "auth_url": provider_data.get("auth_url"),
                "token_url": provider_data.get("token_url"),
                "scopes": provider_data.get("oauth_scopes", "").split(","),
            }

            return oauth_config
        except Exception as e:
            logger.error(f"Error retrieving OAuth config for {service_name}: {str(e)}")
            raise

    def save_user_credentials(
        self, service_name: str, connection_id: str, credentials: CredentialsT
    ) -> None:
        """
        Saves user credentials to Nango

        Args:
            service_name: Name of the service (e.g., "github", "slack", etc.)
            connection_id: Identifier for the connection
            credentials: Credentials object to save
        """
        if not self.secret_key:
            logger.error("Nango secret key is required to save user credentials")
            return

        try:
            # Map the service name to Nango's service name
            nango_service_name = self._map_service_name(service_name)

            # Use the Nango API to update connection credentials
            url = f"{self.api_base_url}/connection/{nango_service_name}/{connection_id}"
            logger.info(f"[save_user_credentials] url: {url}")
            headers = {
                "Authorization": f"Bearer {self.secret_key}",
                "Content-Type": "application/json",
            }

            # Convert credentials to JSON if needed
            if hasattr(credentials, "to_json"):
                credentials_data = credentials.to_json()
            elif isinstance(credentials, dict):
                credentials_data = credentials
            else:
                # Try to serialize the object directly
                credentials_data = credentials

            response = requests.put(url, headers=headers, json=credentials_data)

            if response.status_code != 200:
                logger.error(
                    f"Failed to save credentials for {service_name} connection {connection_id}: {response.text}"
                )
                return

            logger.info(
                f"Successfully saved credentials for {service_name} connection {connection_id}"
            )
        except Exception as e:
            logger.error(
                f"Error saving credentials for {service_name} connection {connection_id}: {str(e)}"
            )
