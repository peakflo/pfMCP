import os
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("peakflo-credential-broker")


class PeakfloCredentialBrokerClient:
    """
    Client for Peakflo's internal system-of-record credential broker.

    This is intentionally separate from normal Peakflo public API auth. It uses a
    service-to-service secret and must never expose returned credentials as MCP
    tool output.
    """

    def __init__(
        self,
        api_base_url: Optional[str] = None,
        broker_secret: Optional[str] = None,
    ):
        self.api_base_url = (
            api_base_url
            or os.environ.get("PEAKFLO_INTERNAL_API_BASE_URL")
            or os.environ.get("PEAKFLO_API_BASE_URL", "").replace("/v1", "")
        ).rstrip("/")
        self.broker_secret = broker_secret or os.environ.get(
            "PF_MCP_CREDENTIAL_BROKER_SECRET"
        )

        if not self.api_base_url:
            raise ValueError(
                "PEAKFLO_INTERNAL_API_BASE_URL or PEAKFLO_API_BASE_URL is required"
            )
        if not self.broker_secret:
            raise ValueError("PF_MCP_CREDENTIAL_BROKER_SECRET is required")

    async def resolve_system_of_record_credentials(
        self,
        tenant_id: str,
        source_system: str,
        purpose: str = "workflow",
    ) -> Dict[str, Any]:
        """
        Resolve short-lived credentials for a tenant's connected system of record.

        The Peakflo API owns refresh-token storage and refresh. pfMCP receives
        only what it needs to call the provider API directly.
        """
        url = f"{self.api_base_url}/internal/credentials/system-of-record/resolve"
        payload = {
            "tenantId": tenant_id,
            "sourceSystem": source_system,
            "purpose": purpose,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.broker_secret}",
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )

        if response.status_code < 200 or response.status_code >= 300:
            logger.warning(
                "[PeakfloCredentialBrokerClient] credential resolution failed",
                extra={
                    "status_code": response.status_code,
                    "tenant_id": tenant_id,
                    "source_system": source_system,
                },
            )
            raise ValueError(
                f"Peakflo credential broker returned {response.status_code}: {response.text}"
            )

        return response.json()
