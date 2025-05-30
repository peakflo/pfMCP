# Service name mapping from MCP to Nango
# This maps the service names used in MCP to their equivalents in Nango

AUTH_TYPE_OAUTH2 = "oauth2"
AUTH_TYPE_UNAUTHENTICATED = "unauthenticated"

SERVICE_NAME_MAP = {
    # Google services
    "gsheets": {
        "nango_service_name": "google-sheet",
        "auth_type": AUTH_TYPE_OAUTH2
    },
    "gmail": {
        "nango_service_name": "google-mail",
        "auth_type": AUTH_TYPE_OAUTH2
    },
    "gdocs": {
        "nango_service_name": "google-docs",
        "auth_type": AUTH_TYPE_OAUTH2
    },
    "gdrive": {
        "nango_service_name": "google-drive",
        "auth_type": AUTH_TYPE_OAUTH2
    },
    "gmaps": {
        "nango_service_name": "google",
        "auth_type": AUTH_TYPE_OAUTH2
    },
    "gmeet": {
        "nango_service_name": "google",
        "auth_type": AUTH_TYPE_OAUTH2
    },
    "peakflo": {
        "nango_service_name": "peakflo",
        "auth_type": AUTH_TYPE_UNAUTHENTICATED
    },
    # # Add more mappings as needed
} 