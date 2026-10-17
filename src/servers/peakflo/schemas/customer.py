from peakflo.schemas.common import (
    contact_schema,
    address_schema,
    custom_field_schema,
)

# Mirrors the Peakflo API customer schema (POST /v1/customers, PUT /v1/customers/{externalId}).
# tenantId is popped before the request body is sent.
_customer_properties = {
    "tenantId": {
        "type": "string",
        "description": "Tenant ID for the customer",
    },
    "externalId": {
        "type": "string",
        "description": "External ID of the customer (also used in the URL path on update)",
    },
    "externalRefNumber": {
        "type": "array",
        "description": "Additional reference IDs for the customer",
        "items": {"type": "string"},
    },
    "companyName": {
        "type": "string",
        "description": "Name of the customer company",
    },
    "currency": {
        "type": "string",
        "description": "Customer currency as an ISO 4217 code (e.g., USD, SGD)",
    },
    "status": {
        "type": "string",
        "description": "Customer status",
        "enum": ["active", "archived", "deleted", "unknown"],
    },
    "accountManagerEmail": {
        "type": "string",
        "description": "Email of the Peakflo user who manages this customer",
    },
    "registrationNumber": {
        "type": "string",
        "description": "Company registration number",
    },
    "taxNumber": {
        "type": "string",
        "description": "Customer's tax identification number",
    },
    "notes": {
        "type": "string",
        "description": "Additional notes about the customer",
    },
    "pauseWorkflow": {
        "type": "boolean",
        "description": "Pause the collection workflow for this customer",
    },
    "statementFile": {
        "type": "string",
        "description": "URL of the customer's statement of account file",
    },
    "contacts": {
        "type": "array",
        "description": "Array of customer contacts",
        "items": contact_schema,
    },
    "addresses": {
        "type": "array",
        "description": "Array of customer addresses",
        "items": address_schema,
    },
    "paymentTerms": {
        "type": "integer",
        "minimum": 0,
        "maximum": 3650,
        "description": (
            "Payment terms in days from the invoice issue date (whole number, 0 to 3650). "
            "Omit it to leave the stored value unchanged."
        ),
    },
    "customField": custom_field_schema,
}

# The API requires the same fields on create and update.
_customer_required = ["externalId", "companyName", "currency", "status", "tenantId"]

create_customer_schema = {
    "type": "object",
    "properties": _customer_properties,
    "required": _customer_required,
}

update_customer_schema = {
    "type": "object",
    "properties": _customer_properties,
    "required": _customer_required,
}
