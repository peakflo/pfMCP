from servers.peakflo.schemas.common import address_schema, contact_schema

create_customer_schema = {
    "type": "object",
    "properties": {
        "tenantId": {
            "type": "string",
            "description": "Tenant ID for the customer. Removed before the API call.",
        },
        "externalId": {
            "type": "string",
            "description": "External ID of the customer",
        },
        "externalRefNumber": {
            "type": "array",
            "description": "Additional IDs for the customer",
            "items": {"type": "string"},
        },
        "companyName": {
            "type": "string",
            "description": "Legal name of the customer",
        },
        "currency": {
            "type": "string",
            "description": "Customer currency. Must be an ISO 4217 code",
        },
        "accountManagerEmail": {
            "type": "string",
            "description": "Account manager email",
        },
        "registrationNumber": {
            "type": "string",
            "description": "Company registration number",
        },
        "taxNumber": {
            "type": "string",
            "description": "Customer tax number, such as an ABN",
        },
        "notes": {
            "type": "string",
            "description": "Notes about the customer",
        },
        "pauseWorkflow": {
            "type": "boolean",
            "description": "Whether collection workflow is paused for this customer",
        },
        "contacts": {
            "type": "array",
            "description": "Customer contacts",
            "items": contact_schema,
        },
        "addresses": {
            "type": "array",
            "description": "Customer addresses",
            "items": address_schema,
        },
    },
    "required": ["externalId", "companyName", "currency", "tenantId"],
}


update_customer_schema = {
    "type": "object",
    "properties": {
        **create_customer_schema["properties"],
    },
    "required": ["externalId", "tenantId"],
}
