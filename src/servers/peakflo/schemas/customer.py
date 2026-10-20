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

# PUT /v1/customers/{customerExternalId}/attachments. The body matches the
# invoice attachment route: raw base64 in `data`, not a data URI.
add_customer_attachment_schema = {
    "type": "object",
    "properties": {
        "tenantId": {
            "type": "string",
            "description": "Peakflo tenant id. Used to select the API credential; it is not sent in the body.",
        },
        "customerExternalId": {
            "type": "string",
            "description": (
                "Customer external id, the same value passed to create_customer. "
                "This is not the internal companies document id."
            ),
        },
        "externalId": {
            "type": "string",
            "description": "External id for this file. Repeating it for the same customer is rejected.",
        },
        "name": {
            "type": "string",
            "description": "File name shown on the Files tab, including the extension",
        },
        "contentType": {
            "type": "string",
            "description": "MIME type of the file (e.g. application/pdf). It must match the file name.",
        },
        "fileType": {
            "type": "string",
            "enum": ["invoice", "transaction", "other"],
            "description": "Optional. Stored as other when omitted.",
        },
        "dateCreated": {
            "type": "string",
            "description": "Optional ISO 8601 timestamp for when the file was created",
        },
        "file_url": {
            "type": "string",
            "description": (
                "Signed URL of the file. The server downloads it and sends raw "
                "base64 in data. Use this or base64, not both."
            ),
        },
        "base64": {
            "type": "string",
            "description": "Raw base64 or a data URI. Use this or file_url, not both. fileSize is required with base64.",
        },
        "fileSize": {
            "type": "integer",
            "description": "Decoded byte size. Required when base64 is sent. Not forwarded to the API.",
        },
    },
    "required": [
        "tenantId",
        "customerExternalId",
        "externalId",
        "name",
        "contentType",
    ],
}
