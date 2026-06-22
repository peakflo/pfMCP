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

run_bill_po_matching_input_schema = {
    "type": "object",
    "properties": {
        "tenantId": {
            "type": "string",
            "description": "Optional. Normally derived from the auth token; only set when calling in a context where tenant is not from the token (e.g. admin).",
        },
        "billId": {
            "type": "string",
            "description": "Peakflo internal bill ID. Use when you have the bill's ID from Peakflo; takes precedence over externalId/sourceId if provided.",
        },
        "externalId": {
            "type": "string",
            "description": "ID from your external system that was stored as sourceId on the bill. Use to look up the bill when you don't have the Peakflo billId.",
        },
        "sourceId": {
            "type": "string",
            "description": "Alias for externalId; same lookup as externalId (bill is found by sourceId).",
        },
    },
    "required": [],
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
        "objectType": {
            "type": "string",
            "enum": ["invoice", "bill", "po"],
            "description": "Optional document type to link the task to. When set, objectExternalId must also be set.",
        },
        "objectExternalId": {
            "type": "string",
            "description": "Optional external ID of the document (invoice/bill/PO) the task is about. Pair with objectType.",
        },
    },
}


# send_message — replaces soa_email. Targets POST /v2/messages/send.
# Channel-first, source-IDs only, sensible defaults. The underlying API
# (peakflo-api) supports more fields (cc, bcc, attachments, templateId,
# specific contact lists); MCP intentionally exposes a minimal surface so
# agents don't get confused. Add fields as agent use cases need them.
send_message_input_schema = {
    "type": "object",
    "properties": {
        "channel": {
            "type": "string",
            "enum": ["email", "whatsapp", "sms", "zalo", "line", "call_log"],
            "description": "Delivery channel. 'call_log' records a manual call against the customer without sending anything.",
        },
        "customerExternalId": {
            "type": "string",
            "description": "External (source) ID of the customer to message.",
        },
        "messageBody": {
            "type": "string",
            "description": "Plain-text message body. Supports {{firstName}}, {{invoiceNumber}}, {{amount}} placeholders rendered server-side.",
        },
        "subject": {
            "type": "string",
            "description": "Email subject. Email channel only — ignored on other channels.",
        },
        "invoiceExternalId": {
            "type": "string",
            "description": "Optional. External ID of the invoice this message is about. Used as objectExternalId on the action so the message shows up on the invoice's history.",
        },
        "billExternalId": {
            "type": "string",
            "description": "Optional. External ID of the bill this message is about. Mutually exclusive with invoiceExternalId.",
        },
        "actionName": {
            "type": "string",
            "description": "Optional display name shown in action logs / dashboards. Defaults to 'Ad-hoc <channel>' if omitted.",
        },
    },
    "required": ["channel", "customerExternalId", "messageBody"],
}


# update_collection_workflow — partial update of a dunning cadence.
# Backs PUT /v1/collection-workflows/:externalId. Agents use this to flip a
# customer's workflow to a different default template, change the reply-to,
# or rename the cadence. Action steps are edited via the sibling
# update_collection_workflow_action tool — keeping them separate keeps each
# tool's surface small.
update_collection_workflow_input_schema = {
    "type": "object",
    "properties": {
        "externalId": {
            "type": "string",
            "description": "External ID of the workflow to update.",
        },
        "title": {
            "type": "string",
            "description": "Display name of the cadence.",
        },
        "defaultEmailTemplateId": {
            "type": "string",
            "description": "Default email template applied to action steps that don't set their own.",
        },
        "sendFromAddress": {
            "type": "string",
            "description": "Sender email address used for outbound mail from this cadence.",
        },
        "emailName": {
            "type": "string",
            "description": "Friendly From-name shown to recipients (e.g., 'Acme Collections').",
        },
        "minimumContactDelay": {
            "type": "integer",
            "description": "Minimum days between automated contacts on this cadence.",
        },
        "replyToAddress": {
            "type": "string",
            "description": "Reply-To header for outbound mail from this cadence.",
        },
    },
    "required": ["externalId"],
}


# update_collection_workflow_action — partial update of a single step inside
# a cadence. Backs PUT /v1/collection-workflows/:externalId/actions/:actionExternalId.
# Useful for "swap step 3 from email to whatsapp" or "rewrite the dunning body
# on the day-30 step" — the agent can edit one step without rewriting the
# whole cadence.
update_collection_workflow_action_input_schema = {
    "type": "object",
    "properties": {
        "externalId": {
            "type": "string",
            "description": "External ID of the parent workflow.",
        },
        "actionExternalId": {
            "type": "string",
            "description": "External ID of the action step to update.",
        },
        "actionName": {
            "type": "string",
            "description": "Display name of the step.",
        },
        "channel": {
            "type": "string",
            "enum": ["email", "whatsapp", "sms", "zalo", "line", "call_log"],
            "description": "Delivery channel for this step.",
        },
        "messageBody": {
            "type": "string",
            "description": "Message body. Supports template placeholders rendered server-side.",
        },
        "subject": {
            "type": "string",
            "description": "Email subject. Email channel only.",
        },
        "emailTemplateId": {
            "type": "string",
            "description": "Pre-built email template to use instead of inline messageBody/subject.",
        },
        "triggerType": {
            "type": "string",
            "enum": [
                "afterIssueDate",
                "beforeDueDate",
                "afterDueDate",
                "dayOfMonth",
                "none",
            ],
            "description": "When this step fires relative to the invoice's lifecycle.",
        },
        "triggerDays": {
            "type": "integer",
            "description": "Offset in days for the trigger (e.g., 7 with 'afterDueDate' = fires 7 days after the due date).",
        },
        "enabled": {
            "type": "boolean",
            "description": "Whether the step is active. Disabled steps stay configured but don't fire.",
        },
    },
    "required": ["externalId", "actionExternalId"],
}
