from peakflo.schemas.common import (
    contact_schema,
    address_schema,
    bank_detail_schema,
)


read_vendor_output = {
    "type": "object",
    "properties": {
        "companyName": {
            "type": "string",
            "description": "Name of the vendor company",
        },
        "companyId": {
            "type": "string",
            "description": "Unique identifier for the company",
        },
        "defaultCurrency": {
            "type": "string",
            "description": "Default currency for the vendor (e.g., USD, SGD)",
        },
        "addresses": {
            "type": "array",
            "description": "Array of vendor addresses",
            "items": address_schema,
        },
        "contacts": {
            "type": "array",
            "description": "Array of vendor contacts",
            "items": contact_schema,
        },
        "taxNumber": {
            "type": "string",
            "description": "Vendor's tax identification number",
        },
        "notes": {
            "type": "string",
            "description": "Additional notes about the vendor",
        },
        "bankDetails": {
            "type": "array",
            "description": "Array of bank account details",
            "items": bank_detail_schema,
        },
        "entityType": {
            "type": "string",
            "description": "Type of entity (e.g., vendor)",
        },
        "beneficiaryCountry": {
            "type": "string",
            "description": "Country code of the beneficiary",
        },
        "vendorFirstName": {
            "type": "string",
            "description": "First name of the vendor",
        },
        "vendorLastName": {
            "type": "string",
            "description": "Last name of the vendor",
        },
        "paymentTerms": {
            "type": "integer",
            "description": "Payment terms in days",
        },
        "customField": {
            "type": "array",
            "description": "Array of custom fields",
            "items": {
                "type": "object",
                "properties": {
                    "customFieldNumber": {
                        "type": "string",
                        "description": "Custom field identifier",
                    },
                    "name": {
                        "type": "string",
                        "description": "Name of the custom field",
                    },
                    "value": {
                        "type": "string",
                        "description": "Value of the custom field",
                    },
                },
            },
        },
        "vatApplicable": {
            "type": "boolean",
            "description": "Whether VAT is applicable",
        },
    },
}
