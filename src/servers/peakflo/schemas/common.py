contact_schema = {
    "type": "object",
    "properties": {
        "externalId": {
            "type": "string",
            "description": "External reference ID for the contact",
        },
        "firstName": {
            "type": "string",
            "description": "Contact's first name",
        },
        "lastName": {
            "type": "string",
            "description": "Contact's last name",
        },
        "phone": {
            "type": "string",
            "description": "Contact's phone number",
        },
        "email": {
            "type": "string",
            "description": "Contact's email address",
        },
        "isMainContact": {
            "type": "boolean",
            "description": "Whether this is the main contact",
        },
    },
}


address_schema = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "description": "Type of address (e.g., billing, delivery, other)",
            "enum": ["billing", "delivery", "other"],
        },
        "line1": {
            "type": "string",
            "description": "Primary address line",
        },
        "line2": {
            "type": "string",
            "description": "Secondary address line",
        },
        "city": {
            "type": "string",
            "description": "City name",
        },
        "region": {
            "type": "string",
            "description": "Region or state",
        },
        "country": {
            "type": "string",
            "description": "Country code in ALPHA-2 format (e.g., IN, US, SG)",
        },
        "postalCode": {
            "type": "string",
            "description": "Postal/ZIP code",
        },
    },
}


bank_detail_schema = {
    "type": "object",
    "properties": {
        "id": {
            "type": "string",
            "description": "Bank account identifier",
        },
        "bankName": {
            "type": "string",
            "description": "Name of the bank",
        },
        "bankCode": {
            "type": "string",
            "description": "Bank code",
        },
        "bankCountry": {
            "type": "string",
            "description": "Country code of the bank",
        },
        "accountNumber": {
            "type": "string",
            "description": "Bank account number",
        },
        "accountHolder": {
            "type": "string",
            "description": "Name of the account holder",
        },
        "currency": {
            "type": "string",
            "description": "Currency of the bank account",
        },
        "bankAccountType": {
            "type": "string",
            "description": "Type of bank account",
        },
        "isDefault": {
            "type": "boolean",
            "description": "Whether this is the default bank account",
        },
    },
    "additionalProperties": True,
}

line_item_schema = {
    "type": "array",
    "description": "Array of line items for the invoice",
    "items": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Item description",
            },
            "unitAmount": {
                "type": "number",
                "description": "Unit price of the item",
            },
            "quantity": {
                "type": "number",
                "description": "Quantity of the item",
            },
            "discountAmount": {
                "type": "number",
                "description": "Discount amount for the item",
            },
            "subTotal": {
                "type": "number",
                "description": "Subtotal for the item",
            },
            "taxAmount": {
                "type": "number",
                "description": "Tax amount for the item",
            },
            "totalAmount": {
                "type": "number",
                "description": "Total amount for the item",
            },
            "itemRef": {
                "type": "string",
                "description": "Item reference identifier",
            },
        },
        "required": ["description", "unitAmount", "quantity"],
    },
}
