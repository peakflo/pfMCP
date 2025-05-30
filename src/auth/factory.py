import os
import logging
from typing import Optional, TypeVar, Type
from dotenv import load_dotenv

from auth.constants import SERVICE_NAME_MAP
from .clients.BaseAuthClient import BaseAuthClient

logger = logging.getLogger("auth-factory")

T = TypeVar("T", bound=BaseAuthClient)

load_dotenv()


def create_auth_client(
    client_type: Optional[Type[T]] = None, api_key: Optional[str] = None
) -> BaseAuthClient:
    """
    Factory function to create the appropriate auth client based on environment

    Args:
        client_type: Optional specific client class to instantiate
        api_key: Optional API key for authentication

    Returns:
        An instance of the appropriate BaseAuthClient implementation
    """
    # If client_type is specified, use it directly
    if client_type:
        return client_type()

    # Otherwise, determine from environment
    environment = os.environ.get("ENVIRONMENT", "local").lower()

    if environment == "gumloop":
        from .clients.GumloopAuthClient import GumloopAuthClient

        return GumloopAuthClient(api_key=api_key)

    if environment == "nango":
        from .clients.NangoAuthClient import NangoAuthClient

        # Get Nango-specific configuration
        secret_key = os.environ.get("NANGO_SECRET_KEY")
        host = os.environ.get("NANGO_HOST")

        return NangoAuthClient(secret_key=secret_key, host=host)

    # Default to local file auth client
    from .clients.LocalAuthClient import LocalAuthClient

    return LocalAuthClient()

def get_auth_type(service_name: str) -> str:
    """
    Map MCP service name to Nango auth type

    Args:
        service_name: MCP service name

    Returns:
        Nango auth type. If the service name is not in the mapping,
        "oauth2" is returned.
    """
    return SERVICE_NAME_MAP.get(service_name, {}).get("auth_type", "oauth2")