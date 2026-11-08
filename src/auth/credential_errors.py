"""Exact, machine-readable credential errors.

Every message says WHICH case it is and carries a stable code. A message never
holds a token or a connection id.

Codes:
  credentials_missing   no connection, or no credentials stored for it
  credentials_expired   token expired and could not be refreshed
  credentials_revoked   the user or the provider revoked access
  setup_incomplete      a token exists but required setup is missing
"""

import re
from contextvars import ContextVar
from typing import Optional

MISSING = "credentials_missing"
EXPIRED = "credentials_expired"
REVOKED = "credentials_revoked"
SETUP_INCOMPLETE = "setup_incomplete"
CODES = (MISSING, EXPIRED, REVOKED, SETUP_INCOMPLETE)

_LABELS = {
    "gmail": "Gmail",
    "gdrive": "Google Drive",
    "gsheets": "Google Sheets",
    "gcalendar": "Google Calendar",
    "gdocs": "Google Docs",
    "gmeet": "Google Meet",
    "gmaps": "Google Maps",
    "xero": "Xero",
    "github": "GitHub",
    "hubspot": "HubSpot",
    "slack": "Slack",
    "notion": "Notion",
    "quickbooks": "QuickBooks",
}


def service_label(service_name: str) -> str:
    return (
        _LABELS.get(service_name)
        or service_name.replace("-", " ").replace("_", " ").title()
    )


# The reason recorded by the Nango client for the CURRENT request.
# The module can be imported as `auth.credential_errors` and as
# `src.auth.credential_errors`. Keep ONE variable for both copies.
import sys as _sys

if not hasattr(_sys, "_pfmcp_credential_failure"):
    _sys._pfmcp_credential_failure = ContextVar("credential_failure", default=None)
_last_failure: ContextVar[Optional[tuple]] = _sys._pfmcp_credential_failure


def record_failure(service_name: str, code: str) -> None:
    _last_failure.set((service_name, code))


def clear_failure() -> None:
    _last_failure.set(None)


def last_failure() -> Optional[tuple]:
    return _last_failure.get()


def message_for(service_name: str, code: str, detail: Optional[str] = None) -> str:
    name = service_label(service_name)
    if code == MISSING:
        return (
            f"{name} credentials are missing for this connection. Connect {name} again."
        )
    if code == REVOKED:
        return f"{name} access was revoked. Reconnect {name}."
    if code == SETUP_INCOMPLETE:
        return detail or f"{name} setup is incomplete. Reconnect {name}."
    return (
        f"{name} credentials have expired and could not be refreshed. Reconnect {name}."
    )


class CredentialError(ValueError):
    """A credential problem. `str(error)` is safe to show to a person."""

    def __init__(self, service_name: str, code: str, detail: Optional[str] = None):
        self.service_name = service_name
        self.code = code
        super().__init__(f"[{code}] {message_for(service_name, code, detail)}")


def credential_error_from_last(service_name: str) -> CredentialError:
    """Build the exact error for the failure the Nango client just recorded."""
    seen = last_failure()
    code = seen[1] if seen and seen[0] == service_name else MISSING
    return CredentialError(service_name, code)


_CREDENTIAL_TEXT = re.compile(
    r"credentials? (?:not found|missing)|no (?:valid )?\w* ?credentials found|"
    r"missing access_token|invalid_credentials|refresh limit",
    re.I,
)


def translate_exception(error: Exception) -> str:
    """Text for a tool error. Rewrites old, vague credential messages."""
    # Duck typing: the class can exist twice under two import paths.
    if getattr(error, "code", None) in CODES and hasattr(error, "service_name"):
        return str(error)
    seen = last_failure()
    if seen and _CREDENTIAL_TEXT.search(str(error)):
        return str(CredentialError(seen[0], seen[1]))
    return str(error)


def classify_nango_failure(status: int, body_text: str) -> Optional[str]:
    """Map a failed Nango answer to a code. None means 'not a credential case'."""
    text = (body_text or "").lower()
    if status == 404:
        return MISSING
    if "revoked" in text:
        return REVOKED
    if (
        "invalid_credentials" in text
        or "refresh limit" in text
        or "invalid_grant" in text
        or "expired" in text
        or status in (401, 403)
    ):
        return EXPIRED
    return None
