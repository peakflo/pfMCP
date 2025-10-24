# Service name mapping from MCP to Nango
# This maps the service names used in MCP to their equivalents in Nango

AUTH_TYPE_OAUTH2 = "oauth2"
AUTH_TYPE_API_KEY = "API_KEY"
AUTH_TYPE_TBA = "tba"
AUTH_TYPE_UNAUTHENTICATED = "unauthenticated"

SERVICE_NAME_MAP = {
    # Google services
    "gsheets": {"nango_service_name": "google-sheet", "auth_type": AUTH_TYPE_OAUTH2},
    "gcalendar": {
        "nango_service_name": "google-calendar",
        "auth_type": AUTH_TYPE_OAUTH2,
    },
    "gmail": {"nango_service_name": "google-mail", "auth_type": AUTH_TYPE_OAUTH2},
    "gdocs": {"nango_service_name": "google-docs", "auth_type": AUTH_TYPE_OAUTH2},
    "gdrive": {"nango_service_name": "google-drive", "auth_type": AUTH_TYPE_OAUTH2},
    "gmaps": {"nango_service_name": "google", "auth_type": AUTH_TYPE_OAUTH2},
    "gmeet": {"nango_service_name": "google", "auth_type": AUTH_TYPE_OAUTH2},
    "firestore": {"nango_service_name": "google-firestore", "auth_type": AUTH_TYPE_OAUTH2},
    "notion": {"nango_service_name": "notion", "auth_type": AUTH_TYPE_OAUTH2},
    "tldv": {"nango_service_name": "tldv", "auth_type": AUTH_TYPE_API_KEY},
    "peakflo": {
        "nango_service_name": "peakflo",
        "auth_type": AUTH_TYPE_UNAUTHENTICATED,
    },
    "netsuite": {
        "nango_service_name": "netsuite-tba",
        "auth_type": AUTH_TYPE_TBA,
    },
    # # Add more mappings as needed
}
