import os
import time
import asyncio
import logging
import requests
import httpx
import jwt
from typing import Optional, Dict, Any, Tuple, TypedDict
from requests.exceptions import ConnectionError, Timeout

from auth.constants import (
    SERVICE_NAME_MAP,
    AUTH_TYPE_OAUTH2,
    AUTH_TYPE_UNAUTHENTICATED,
    AUTH_TYPE_API_KEY,
    AUTH_TYPE_TBA,
)

from .BaseAuthClient import BaseAuthClient, CredentialsT
from auth import credential_errors as cred_err

logger = logging.getLogger("nango-auth-client")

# Retryable HTTP status codes
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


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

    # Class-level cache shared across all instances: {(service_name, connection_id): (timestamp, credentials_data)}
    _cache: Dict[Tuple[str, str], Tuple[float, Any]] = {}
    _cache_ttl: float = float(os.environ.get("NANGO_CACHE_TTL", "300"))  # 5 min default

    _REQUEST_TIMEOUT: int = 10  # seconds
    _MAX_RETRIES: int = 3
    _INITIAL_BACKOFF: float = 1.0

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

    def _resolve_jwt_from_metadata(
        self, response_json: dict, service_name: str, connection_id: str
    ) -> Optional[JWTTokenResponse]:
        """
        Try to build a JWT from connection metadata (tenantId, privateKey, accessToken).

        Used by both API_KEY (legacy fallback) and UNAUTHENTICATED auth types.
        Returns the JWT token dict on success, or None if required fields are missing.
        """
        metadata = response_json.get("metadata", {})
        tenant_id = metadata.get("tenantId")
        private_key = metadata.get("privateKey")
        access_token = metadata.get("accessToken")

        if not tenant_id or not private_key or not access_token:
            logger.error(
                f"Missing required metadata fields for {service_name} connection {connection_id}"
            )
            return None

        logger.info(
            f"[_resolve_jwt_from_metadata] generating JWT for tenant {tenant_id}"
        )
        return self._get_jwt_token(service_name, tenant_id, private_key, access_token)

    def _extract_connection_credentials(
        self,
        response_json: dict,
        auth_type: str,
        service_name: str,
        connection_id: str,
    ) -> Optional[dict]:
        """Return the credential payload needed by an MCP integration.

        Nango stores TBA secrets in ``credentials`` while connection-specific
        fields such as the NetSuite account ID live in ``connection_config``.
        Preserve both so the integration can construct a complete signer.
        """
        if auth_type == AUTH_TYPE_OAUTH2:
            credentials = dict(response_json.get("credentials") or {})
            credentials["metadata"] = response_json.get("metadata", {})
            return credentials

        if auth_type == AUTH_TYPE_TBA:
            credentials = dict(response_json.get("credentials") or {})
            credentials["connection_config"] = response_json.get(
                "connection_config", response_json.get("connectionConfig", {})
            )
            credentials["metadata"] = response_json.get("metadata", {})
            return credentials

        if auth_type == AUTH_TYPE_API_KEY:
            credentials = dict(response_json.get("credentials") or {})
            if credentials.get("apiKey"):
                return credentials
            # Fallback: legacy connection migrated from UNAUTHENTICATED.
            return (
                self._resolve_jwt_from_metadata(
                    response_json, service_name, connection_id
                )
                or credentials
            )

        if auth_type == AUTH_TYPE_UNAUTHENTICATED:
            return self._resolve_jwt_from_metadata(
                response_json, service_name, connection_id
            )

        logger.error(
            "Unsupported auth type %s for %s connection %s",
            auth_type,
            service_name,
            connection_id,
        )
        return None

    def _get_cached_credentials(
        self, service_name: str, connection_id: str
    ) -> Optional[CredentialsT]:
        """Return cached credentials if present and not expired."""
        cache_key = (service_name, connection_id)
        entry = NangoAuthClient._cache.get(cache_key)
        if entry is None:
            return None
        cached_at, credentials_data = entry
        if time.time() - cached_at > NangoAuthClient._cache_ttl:
            del NangoAuthClient._cache[cache_key]
            return None
        logger.info(
            f"[get_user_credentials] cache hit for {service_name} connection {connection_id}"
        )
        return credentials_data

    def _set_cached_credentials(
        self, service_name: str, connection_id: str, credentials_data: CredentialsT
    ) -> None:
        """Store credentials in the class-level cache."""
        NangoAuthClient._cache[(service_name, connection_id)] = (
            time.time(),
            credentials_data,
        )

    def _fetch_connection_with_retries(
        self, url: str, headers: Dict[str, str], service_name: str, connection_id: str
    ) -> Optional[requests.Response]:
        """
        Fetch connection details from Nango API with retries and exponential backoff.

        Returns the Response on success, or None for permanent failures (e.g. 404).
        Raises an exception if all retries are exhausted on transient errors.
        """
        delay = self._INITIAL_BACKOFF
        last_error = None

        for attempt in range(self._MAX_RETRIES):
            try:
                response = requests.get(
                    url, headers=headers, timeout=self._REQUEST_TIMEOUT
                )

                if response.status_code == 200:
                    return response

                if response.status_code == 404:
                    logger.info(
                        f"No connection found for {service_name} connection {connection_id}"
                    )
                    cred_err.record_failure(service_name, cred_err.MISSING)
                    return None

                if response.status_code in _RETRYABLE_STATUS_CODES:
                    last_error = f"HTTP {response.status_code}: {response.text}"
                    logger.warning(
                        f"[get_user_credentials] retryable error (attempt {attempt + 1}/{self._MAX_RETRIES}) "
                        f"for {service_name} connection {connection_id}: {last_error}"
                    )
                else:
                    # Non-retryable error (4xx other than 404/429)
                    logger.error(
                        f"Failed to get connection details for {service_name} connection {connection_id}: {response.text}"
                    )
                    reason = cred_err.classify_nango_failure(
                        response.status_code, response.text
                    )
                    if reason:
                        cred_err.record_failure(service_name, reason)
                    return None

            except (ConnectionError, Timeout) as e:
                last_error = str(e)
                logger.warning(
                    f"[get_user_credentials] network error (attempt {attempt + 1}/{self._MAX_RETRIES}) "
                    f"for {service_name} connection {connection_id}: {last_error}"
                )

            if attempt < self._MAX_RETRIES - 1:
                time.sleep(delay)
                delay *= 2

        logger.error(
            f"All {self._MAX_RETRIES} retries exhausted for {service_name} connection {connection_id}: {last_error}"
        )
        return None

    async def _async_fetch_connection_with_retries(
        self, url: str, headers: Dict[str, str], service_name: str, connection_id: str
    ) -> Optional[httpx.Response]:
        """
        Async version of _fetch_connection_with_retries.

        Uses httpx.AsyncClient and asyncio.sleep to avoid blocking the event loop.
        This prevents SSE stream stalls on the pf-mcp server when Nango is slow.
        """
        delay = self._INITIAL_BACKOFF
        last_error = None

        for attempt in range(self._MAX_RETRIES):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        url, headers=headers, timeout=self._REQUEST_TIMEOUT
                    )

                if response.status_code == 200:
                    return response

                if response.status_code == 404:
                    logger.info(
                        f"No connection found for {service_name} connection {connection_id}"
                    )
                    cred_err.record_failure(service_name, cred_err.MISSING)
                    return None

                if response.status_code in _RETRYABLE_STATUS_CODES:
                    last_error = f"HTTP {response.status_code}: {response.text}"
                    logger.warning(
                        f"[get_user_credentials] retryable error (attempt {attempt + 1}/{self._MAX_RETRIES}) "
                        f"for {service_name} connection {connection_id}: {last_error}"
                    )
                else:
                    # Non-retryable error (4xx other than 404/429)
                    logger.error(
                        f"Failed to get connection details for {service_name} connection {connection_id}: {response.text}"
                    )
                    reason = cred_err.classify_nango_failure(
                        response.status_code, response.text
                    )
                    if reason:
                        cred_err.record_failure(service_name, reason)
                    return None

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = str(e)
                logger.warning(
                    f"[get_user_credentials] network error (attempt {attempt + 1}/{self._MAX_RETRIES}) "
                    f"for {service_name} connection {connection_id}: {last_error}"
                )

            if attempt < self._MAX_RETRIES - 1:
                await asyncio.sleep(delay)
                delay *= 2

        logger.error(
            f"All {self._MAX_RETRIES} retries exhausted for {service_name} connection {connection_id}: {last_error}"
        )
        return None

    async def async_get_user_credentials(
        self, service_name: str, connection_id: str
    ) -> Optional[CredentialsT]:
        """
        Async version of get_user_credentials. Preferred in async contexts (MCP servers).

        Uses httpx.AsyncClient and asyncio.sleep instead of requests/time.sleep
        to avoid blocking the Python event loop, which would stall concurrent
        SSE streams and cause Cloud Run to truncate responses.
        """
        cred_err.clear_failure()
        if not self.secret_key:
            logger.error("Nango secret key is required to get user credentials")
            return None

        # Check cache first (cache operations are fast, no need for async)
        # BigQuery project allowlists live in Nango metadata. Fetch each time so
        # removing a project takes effect without waiting for the token cache TTL.
        cached = (
            self._get_cached_credentials(service_name, connection_id)
            if service_name != "bigquery"
            else None
        )
        if cached is not None:
            return cached

        try:
            nango_service_name = self._map_service_name(service_name)
            auth_type = SERVICE_NAME_MAP.get(service_name, {}).get(
                "auth_type", AUTH_TYPE_OAUTH2
            )
            url = f"{self.api_base_url}/connection/{connection_id}?provider_config_key={nango_service_name}"
            logger.info(f"[async_get_user_credentials] url: {url}")
            headers = {"Authorization": f"Bearer {self.secret_key}"}

            response = await self._async_fetch_connection_with_retries(
                url, headers, service_name, connection_id
            )

            if response is None:
                if cred_err.last_failure() is None:
                    cred_err.record_failure(service_name, cred_err.MISSING)
                return None

            result = self._extract_connection_credentials(
                response.json(), auth_type, service_name, connection_id
            )
            if auth_type == AUTH_TYPE_OAUTH2 and not (
                result and (result.get("access_token") or result.get("token"))
            ):
                # Nango answered, but holds no token for this connection.
                cred_err.record_failure(service_name, cred_err.MISSING)

            if result is not None and service_name != "bigquery":
                self._set_cached_credentials(service_name, connection_id, result)

            return result

        except Exception as e:
            logger.error(
                f"Error retrieving credentials for {service_name} connection {connection_id}: {str(e)}"
            )
            return None

    def get_user_credentials(
        self, service_name: str, connection_id: str
    ) -> Optional[CredentialsT]:
        """
        Get user credentials from Nango API with caching and retries.

        Args:
            service_name: Name of the service (e.g., "github", "slack", etc.)
            connection_id: Identifier for the connection

        Returns:
            Credentials object if found, None otherwise
        """
        cred_err.clear_failure()
        if not self.secret_key:
            logger.error("Nango secret key is required to get user credentials")
            return None

        # Check cache first
        cached = (
            self._get_cached_credentials(service_name, connection_id)
            if service_name != "bigquery"
            else None
        )
        if cached is not None:
            return cached

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

            response = self._fetch_connection_with_retries(
                url, headers, service_name, connection_id
            )

            if response is None:
                if cred_err.last_failure() is None:
                    cred_err.record_failure(service_name, cred_err.MISSING)
                return None

            result = self._extract_connection_credentials(
                response.json(), auth_type, service_name, connection_id
            )
            if auth_type == AUTH_TYPE_OAUTH2 and not (
                result and (result.get("access_token") or result.get("token"))
            ):
                # Nango answered, but holds no token for this connection.
                cred_err.record_failure(service_name, cred_err.MISSING)

            if result is not None and service_name != "bigquery":
                self._set_cached_credentials(service_name, connection_id, result)

            return result

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
