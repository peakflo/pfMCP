from peakflo.schemas.common import line_item_schema


create_invoice_schema = {
    "type": "object",
    "properties": {
        "externalId": {
            "type": "string",
            "description": "External reference ID for the invoice",
        },
        "customerRef": {
            "type": "string",
            "description": "Customer reference identifier",
        },
        "issueDate": {
            "type": "string",
            "format": "date-time",
            "description": "Invoice issue date in ISO format",
        },
        "dueDate": {
            "type": "string",
            "format": "date-time",
            "description": "Invoice due date in ISO format",
        },
        "currency": {
            "type": "string",
            "description": "Currency code (e.g., SGD, USD)",
        },
        "lineItems": line_item_schema,
        "totalAmount": {
            "type": "number",
            "description": "Total invoice amount",
        },
        "totalDiscount": {
            "type": "number",
            "description": "Total discount amount",
        },
        "totalTaxAmount": {
            "type": "number",
            "description": "Total tax amount",
        },
        "amountDue": {
            "type": "number",
            "description": "Amount due for the invoice",
        },
        "status": {
            "type": "string",
            "enum": ["draft", "sent", "paid", "overdue", "cancelled"],
            "description": "Invoice status",
        },
        "note": {
            "type": "string",
            "description": "Additional notes for the invoice",
        },
        "subTotal": {
            "type": "number",
            "description": "Subtotal before taxes and discounts",
        },
        "invoiceNumber": {
            "type": "string",
            "description": "Invoice number identifier",
        },
    },
    "required": [
        "externalId",
        "customerRef",
        "issueDate",
        "dueDate",
        "currency",
        "lineItems",
        "totalAmount",
        "amountDue",
        "status",
        "invoiceNumber",
    ],
}

update_invoice_schema = {
    "type": "object",
    "properties": {
        "externalId": {
            "type": "string",
            "description": "External reference ID for the invoice",
        },
        "tenantId": {
            "type": "string",
            "description": "Tenant ID",
        },
        "customerRef": {
            "type": "string",
            "description": "Customer reference identifier",
        },
        "issueDate": {
            "type": "string",
            "format": "date-time",
            "description": "Invoice issue date in ISO format",
        },
        "dueDate": {
            "type": "string",
            "format": "date-time",
            "description": "Invoice due date in ISO format",
        },
        "currency": {
            "type": "string",
            "description": "Currency code (e.g., SGD, USD)",
        },
        "lineItems": line_item_schema,
        "totalAmount": {
            "type": "number",
            "description": "Total invoice amount",
        },
        "totalDiscount": {
            "type": "number",
            "description": "Total discount amount",
        },
        "totalTaxAmount": {
            "type": "number",
            "description": "Total tax amount",
        },
        "amountDue": {
            "type": "number",
            "description": "Amount due for the invoice",
        },
        "status": {
            "type": "string",
            "enum": ["draft", "sent", "paid", "overdue", "cancelled"],
            "description": "Invoice status",
        },
        "note": {
            "type": "string",
            "description": "Additional notes for the invoice",
        },
        "subTotal": {
            "type": "number",
            "description": "Subtotal before taxes and discounts",
        },
        "invoiceNumber": {
            "type": "string",
            "description": "Invoice number identifier",
        },
    },
    "required": [
        "externalId",
        "tenantId",
        "customerRef",
        "issueDate",
        "dueDate",
        "currency",
        "lineItems",
        "totalAmount",
        "amountDue",
        "status",
        "invoiceNumber",
    ],
}

raise_invoice_dispute_schema = {
    "type": "object",
    "properties": {
        "externalId": {
            "type": "string",
            "description": "External reference ID for the dispute",
        },
        "description": {
            "type": "string",
            "description": "Description of the dispute",
        },
        "amount": {
            "type": "number",
            "description": "Amount of the dispute",
        },
        "currencyCode": {
            "type": "string",
            "description": "Currency code of the dispute",
        },
        "date": {
            "type": "string",
            "description": "Date of the dispute",
        },
        "status": {
            "type": "string",
            "description": "Status of the dispute",
        },
        "referenceDocumentType": {
            "type": "string",
            "description": "Type of the reference document",
        },
        "referenceDocumentId": {
            "type": "string",
            "description": "ID of the reference document",
        },
        "vendorId": {
            "type": "string",
            "description": "ID of the vendor",
        },
        "attachments": {
            "type": "array",
            "description": "Attachments of the dispute",
        },
        "metadata": {
            "type": "object",
            "description": "Metadata of the dispute",
        },
    },
}
