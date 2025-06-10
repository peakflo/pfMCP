soa_email_input_schema = {
    "type": "object",
    "properties": {
        "operationType": {
            "type": "string",
            "description": "Type of operation to perform",
        },
        "customerExternalId": {
            "type": "string",
            "description": "External ID of the customer",
        },
        "userId": {
            "type": "string",
            "description": "ID of the user",
        },
        "message": {
            "type": "string",
            "description": "Message to send",
        },
        "contactIds": {
            "type": "array",
            "items": {
                "type": "string",
            },
            "minItems": 1,
        },
        "actionData": {
            "type": "object",
            "properties": {
                "actionId": {
                    "type": "string",
                    "description": "ID of the action",
                },
                "actionType": {
                    "type": "string",
                    "description": "Type of the action",
                },
                "channel": {
                    "type": "string",
                    "description": "Channel of the action",
                },
                "invoiceId": {
                    "type": "string",
                    "description": "ID of the invoice",
                },
                "actionName": {
                    "type": "string",
                    "description": "Name of the action",
                },
                "status": {
                    "type": "string",
                    "description": "Status of the action",
                },
                "from": {
                    "type": "string",
                    "description": "Email of the sender",
                },
                "fromName": {
                    "type": "string",
                    "description": "Name of the sender",
                },
                "subject": {
                    "type": "string",
                },
                "template": {
                    "type": "string",
                    "description": "Template of the action",
                },
                "emailObjectType": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "ID of the email object",
                        },
                        "type": {
                            "type": "string",
                            "description": "Type of the email object",
                        },
                    },
                    "required": ["id", "type"],
                },
            },
            "required": ["actionType", "channel", "invoiceId", "actionName", "status"],
        },
    },
    "required": [
        "operationType",
        "customerExternalId",
        "userId",
        "message",
        "contactIds",
        "actionData",
    ],
}

add_action_log_input_schema = {
    "type": "object",
    "properties": {
        "actionName": {
            "type": "string",
            "description": "Name of the action",
        },
        "note": {
            "type": "string",
            "description": "Note to add to the action log",
        },
        "objectType": {
            "type": "string",
            "description": "Type of the object",
        },
        "objectId": {
            "type": "string",
            "description": "ID of the object",
        },
        "entityId": {
            "type": "string",
            "description": "ID of the vendor or customer",
        },
    },
    "required": ["actionName", "note", "objectType", "objectId", "entityId"],
}

create_task_input_schema = {
    "type": "object",
    "properties": {
        "actionName": {
            "type": "string",
            "description": "Name of the action",
        },
        "actionInfo": {
            "type": "object",
            "description": "Description of the action, for example: Pay $100 to john@doe.com before 10th June 2025 will be converted to given object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Email of action creator, for example: john@doe.com",
                },
                "dueDate": {
                    "type": "string",
                    "description": "Due date of the action, format: iso string",
                },
                "details": {
                    "type": "string",
                    "description": "Details of the action, for example: Pay $100 to john@doe.com before 10th June 2025 will be converted to given object",
                },
                "amount": {
                    "type": "number",
                    "description": "Amount to pay, for example: 100",
                },
                "currency": {
                    "type": "string",
                    "description": "Currency of the amount to pay, for example: USD",
                },
            },
            "required": [
                "owner",
                "dueDate",
                "details",
                "amount",
            ],
        },
        "customerRef": {
            "type": "string",
            "description": "Firestore reference to the customer",
        },
    },
}
