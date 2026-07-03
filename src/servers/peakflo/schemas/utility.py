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
            # owner is optional on the API side — when omitted the
            # handler assigns the task to the customer's account manager.
            "required": [
                "dueDate",
                "amount",
            ],
        },
        "customerRef": {
            "type": "string",
            "description": "Firestore reference to the customer",
        },
        "objectType": {
            "type": "string",
            "enum": ["invoice"],
            "description": "Optional invoice link. When set, objectExternalId must also be set.",
        },
        "objectExternalId": {
            "type": "string",
            "description": "Optional external ID of the invoice the task is about. Pair with objectType.",
        },
    },
    "required": ["actionInfo", "customerRef"],
}


# send_message — replaces soa_email. Targets POST /v2/messages/send.
# Channel-first, source-IDs only, sensible defaults. The underlying API
# (peakflo-api) supports more fields (cc, bcc, attachments, templateId,
# specific contact lists); MCP intentionally exposes a minimal surface so
# agents don't get confused. Add fields as agent use cases need them.
# Recipient-spec for /v2/messages/send. Different from the workflow-action
# recipient spec because send_message IS customer-scoped — so type='specific'
# with a list of contact externalIds makes sense here. Maps 1:1 to the
# RecipientSpec the API accepts.
_send_message_recipient_schema = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["main_contacts", "all", "specific"],
            "description": (
                "How to resolve recipients on the customer:\n"
                "  main_contacts — every contact flagged isMainContact "
                "(default for the 'to' field).\n"
                "  all — every contact on the customer.\n"
                "  specific — only the contacts in contactExternalIds."
            ),
        },
        "contactExternalIds": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Required when type='specific'.",
        },
    },
    "required": ["type"],
}


send_message_input_schema = {
    "type": "object",
    "properties": {
        "channel": {
            "type": "string",
            "enum": ["email", "whatsapp", "sms", "zalo", "line", "call_log"],
            "description": "Delivery channel. 'call_log' records a manual call against the customer without sending anything.",
        },
        "companyExternalId": {
            "type": "string",
            "description": "External (source) ID of the company to message.",
        },
        "messageBody": {
            "type": "string",
            "description": (
                "Plain-text message body. Template placeholders are rendered "
                "server-side. Common ones: {{customerCompanyName}} (payer "
                "name), {{recipientName}} (contact first name), {{myOrgName}} "
                "(issuer name), {{invoiceNumber}}, {{invoiceAmountDue}}, "
                "{{totalOutstanding}}, {{totalAmountOverdue}}, and "
                "triple-brace HTML links like {{{customerPortalLink}}}. "
                "Do NOT use {{firstName}} or {{amount}} — those aren't real "
                "placeholders and won't be substituted."
            ),
        },
        "subject": {
            "type": "string",
            "description": "Email subject. Email channel only; non-email requests are rejected.",
        },
        "recipients": {
            **_send_message_recipient_schema,
            "description": (
                "Primary recipients ('to'). If omitted, defaults to "
                "{type: 'main_contacts'} — every contact flagged "
                "isMainContact on the customer."
            ),
        },
        "cc": {
            **_send_message_recipient_schema,
            "description": (
                "Optional CC recipients. Email channel only; non-email requests are rejected."
            ),
        },
        "bcc": {
            **_send_message_recipient_schema,
            "description": (
                "Optional BCC recipients. Email channel only; non-email requests are rejected."
            ),
        },
        "invoiceExternalId": {
            "type": "string",
            "description": "Optional. External ID of the invoice this message is about. Used as objectExternalId on the action so the message shows up on the invoice's history.",
        },
        "actionName": {
            "type": "string",
            "description": "Optional display name shown in action logs / dashboards. Defaults to 'Ad-hoc <channel>' if omitted.",
        },
        "messageTemplateId": {
            "type": "string",
            "description": (
                "WhatsApp channel only, REQUIRED for channel='whatsapp'. "
                "External ID of a Meta-approved WhatsApp template — fetch "
                "the tenant's approved templates first via "
                "list_whatsapp_templates, then pass the chosen template's "
                "externalId here. WhatsApp Business API rejects free-form "
                "text outside a 24h reply window, so cold outreach must "
                "always reference an approved template. Rejected on "
                "non-whatsapp channels."
            ),
        },
        "messageTemplateText": {
            "type": "string",
            "description": (
                "WhatsApp channel only. The template's raw text shape with "
                "{{1}}, {{2}}, … placeholders — the same 'text' field "
                "returned by list_whatsapp_templates. Optional; kept on the "
                "action for downstream tracking."
            ),
        },
        "variableValues": {
            "type": "object",
            "additionalProperties": True,
            "description": (
                "WhatsApp channel only. Slot-value map for the chosen "
                "template's {{1}}, {{2}}, … placeholders. Keys mirror the "
                "template's variableMapping (returned by "
                "list_whatsapp_templates); values are the strings that fill "
                "each slot. Optional but usually required by the template."
            ),
        },
    },
    "required": ["channel", "companyExternalId", "messageBody"],
}


# list_whatsapp_templates — list Meta-approved WhatsApp templates for the
# authenticated tenant. Callers use this to build a template picker before
# dispatching a WhatsApp send via send_message. WhatsApp Business API
# rejects free-form text outside a 24h reply window, so a cold outreach must
# always reference an approved template — this tool is the only way for an
# agent to discover which template IDs are valid to pass as
# send_message.messageTemplateId.
list_whatsapp_templates_input_schema = {
    "type": "object",
    "properties": {},
}


# update_collection_workflow — partial update of a dunning cadence.
# Backs PUT /v1/collection-workflows/:externalId. Agents use this to change
# the cadence's sender, reply-to, or rename it. Action steps are edited via
# the sibling update_collection_workflow_action tool — keeping them
# separate keeps each tool's surface small.
update_collection_workflow_input_schema = {
    "type": "object",
    "properties": {
        "externalId": {
            "type": "string",
            "description": "External ID of the workflow to update.",
        },
        "contactSuperior": {
            "type": "boolean",
            "description": "Whether the cadence escalates to a superior customer contact when applicable.",
        },
        "title": {
            "type": "string",
            "description": "Display name of the cadence.",
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
    "minProperties": 2,
}


# Recipient-spec sub-schema for workflow templates. Templates target
# recipient TYPES (mainContacts, all, accountManager, …), not specific
# contacts — a template is reusable across customers so binding to a
# specific contactId doesn't make sense. The API rejects `type='contact'`
# for that reason.
_recipient_spec_schema = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": [
                "mainContacts",
                "notMainContacts",
                "all",
                "accountManager",
                "user",
            ],
            "description": (
                "Recipient resolution strategy (peakflo-schema "
                "RecipientType):\n"
                "  mainContacts — every contact flagged isMainContact=true "
                "on the customer the cadence runs against.\n"
                "  notMainContacts — every contact NOT flagged main.\n"
                "  all — every contact on the customer.\n"
                "  accountManager — the assigned account manager.\n"
                "  user — a specific Peakflo user (pair with userId)."
            ),
        },
        "userId": {
            "type": "string",
            "description": "Required when type='user'.",
        },
    },
    "required": ["type"],
}


# update_collection_workflow_action — partial update of a single step
# inside a cadence. Backs PUT
# /v1/collection-workflows/:externalId/actions/:actionExternalId.
#
# Every field is sourced from peakflo-schema:
#   actionType ⊂ BaseActionType (workflow template subset, peakflo-web's
#     ActionTemplateEditDialog dispatcher is the source of truth)
#   triggerType = ActionTriggerType (8 values)
#   paymentLink = ActionInfoPaymentLinkType (enum — NOT a URL)
#   recipients/cc/bcc = ActionRecipient[]
#
# The opaque Firestore `actionInfo` jsonb is NOT exposed — the API maps
# these flat fields into it server-side (Dmitry: "API for MCP should be
# almost impossible to break").
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
            "description": "Display name of the step (shown in the cadence UI and action logs).",
        },
        "actionType": {
            "type": "string",
            "enum": [
                "automaticEmail",
                "lod",
                "automaticWA",
                "automaticSMS",
                "automaticZalo",
                "automaticLine",
                "manualEmail",
                "manualWhatsapp",
                "manualLegal",
                "manualCall",
                "manualVisit",
                "manualReminder",
            ],
            "description": (
                "Pipeline action type. The prefix encodes BOTH the channel "
                "AND whether the step fires automatically — there is no "
                "separate channel field.\n"
                "Automatic (fires on trigger and dispatches):\n"
                "  automaticEmail — sends an email.\n"
                "  lod — letter-of-demand variant of automaticEmail "
                "(same template, different pipeline label).\n"
                "  automaticWA — sends a WhatsApp message.\n"
                "  automaticSMS — sends an SMS.\n"
                "  automaticZalo — sends a Zalo message (VN).\n"
                "  automaticLine — sends a Line message (TH/JP).\n"
                "Manual (suggested action on the timeline for a human):\n"
                "  manualEmail — drafted email queued for human review.\n"
                "  manualWhatsapp — drafted WhatsApp message.\n"
                "  manualLegal — escalation task to legal.\n"
                "  manualCall — phone-call task.\n"
                "  manualVisit — in-person visit task.\n"
                "  manualReminder — generic reminder task.\n"
                "Pick the type that matches BOTH the desired channel AND "
                "whether the step should fire automatically. Changing "
                "only the message body? Keep the same actionType. "
                "Switching from auto-email to a human follow-up? Change "
                "to manualCall."
            ),
        },
        "triggerType": {
            "type": "string",
            "enum": [
                "afterIssueDate",
                "beforeDueDate",
                "afterDueDate",
                "dayOfMonth",
                "dayOfTheWeek",
                "beforePromiseToPay",
                "afterPromiseToPay",
                "none",
            ],
            "description": (
                "When the step fires. Combined with triggerTimePeriod:\n"
                "  afterIssueDate — N days after the invoice's issue "
                "date (e.g. day 0 = at issue, day 5 = 5 days after).\n"
                "  beforeDueDate — N days before the due date.\n"
                "  afterDueDate — N days after the due date (overdue "
                "reminders, escalations).\n"
                "  dayOfMonth — fires on a fixed calendar day; "
                "triggerTimePeriod is the day number (1-31).\n"
                "  dayOfTheWeek — fires on a fixed weekday; "
                "triggerTimePeriod is the weekday number (0=Sunday).\n"
                "  beforePromiseToPay — N days before a recorded "
                "promise-to-pay date.\n"
                "  afterPromiseToPay — N days after a recorded "
                "promise-to-pay date.\n"
                "  none — manual cadence; runs only when a user "
                "explicitly triggers it. Pair with manual* actionTypes."
            ),
        },
        "triggerTimePeriod": {
            "type": "integer",
            "description": (
                "Offset for the trigger. Days for the *Date / "
                "*PromiseToPay triggers; calendar day 1-31 for "
                "dayOfMonth; weekday number 0-6 for dayOfTheWeek. "
                "Ignored when triggerType='none'."
            ),
        },
        "triggerTimePeriodUntil": {
            "type": "integer",
            "description": (
                "Optional upper bound for repeating triggers — the step "
                "fires from triggerTimePeriod to triggerTimePeriodUntil "
                "days past the anchor (e.g. overdue reminder fires every "
                "day from day 7 to day 30 past due)."
            ),
        },
        "subject": {
            "type": "string",
            "description": (
                "Email subject line. Email actionTypes only "
                "(automaticEmail / lod / manualEmail). Requests using this "
                "field for a non-email action are rejected. Supports template "
                "placeholders, e.g. 'Reminder: {{invoiceNumber}} due in "
                "3 days'."
            ),
        },
        "messageBody": {
            "type": "string",
            "description": (
                "Plain-text message body. Template placeholders are "
                "rendered server-side. Common ones: "
                "{{customerCompanyName}} (payer name), {{recipientName}} "
                "(contact first name), {{myOrgName}} (issuer name), "
                "{{invoiceNumber}}, {{invoiceAmountDue}}, "
                "{{totalOutstanding}}, {{totalAmountOverdue}}, and "
                "triple-brace HTML links like {{{customerPortalLink}}}. "
                "Don't use {{firstName}} or {{amount}} — those aren't "
                "real placeholders and won't be substituted."
            ),
        },
        "paymentLink": {
            "type": "string",
            "enum": [
                "customerPortalLink",
                "currencyPaymentLink",
                "invoicePaymentLink",
                "directInvPaymentLink",
                "directPaymentLink",
            ],
            "description": (
                "Selector for which Peakflo-managed payment link to render "
                "in the message — NOT a free-form URL. The actual link is "
                "generated server-side per customer/invoice. "
                "(peakflo-schema ActionInfoPaymentLinkType):\n"
                "  customerPortalLink — link to the customer portal "
                "home.\n"
                "  invoicePaymentLink — direct link to pay this specific "
                "invoice.\n"
                "  currencyPaymentLink — currency-scoped payment landing.\n"
                "  directPaymentLink / directInvPaymentLink — bypass-portal "
                "direct payment links."
            ),
        },
        "recipients": {
            "type": "array",
            "items": _recipient_spec_schema,
            "description": (
                "Primary recipients. Most cadences use "
                "[{type: 'mainContacts'}] or [{type: 'all'}]. If omitted, "
                "the existing recipients on the step are kept; to clear, "
                "pass an empty array."
            ),
        },
        "cc": {
            "type": "array",
            "items": _recipient_spec_schema,
            "description": (
                "Email CC list. Email actionTypes only; non-email requests are rejected."
            ),
        },
        "bcc": {
            "type": "array",
            "items": _recipient_spec_schema,
            "description": (
                "Email BCC list. Email actionTypes only; non-email requests are rejected."
            ),
        },
    },
    "required": ["externalId", "actionExternalId"],
    "minProperties": 3,
}


# create_collection_workflow_action — append a new step to an existing
# cadence. Backs POST /v1/collection-workflows/:externalId/actions.
# Same payload shape as the update schema, but the cadence triplet
# (actionExternalId / actionName / actionType / triggerType /
# triggerTimePeriod) is required so the new step is fully addressable
# and schedulable from the moment it lands.
create_collection_workflow_action_input_schema = {
    "type": "object",
    "properties": {
        "externalId": {
            "type": "string",
            "description": "External ID of the parent workflow.",
        },
        "actionExternalId": {
            "type": "string",
            "description": (
                "Caller-assigned external ID for the new step. Reuse the same "
                "value on subsequent update_collection_workflow_action calls. "
                "Must be unique within the workflow — duplicates are rejected "
                "with 409."
            ),
        },
        "actionName": update_collection_workflow_action_input_schema["properties"][
            "actionName"
        ],
        "actionType": update_collection_workflow_action_input_schema["properties"][
            "actionType"
        ],
        "triggerType": update_collection_workflow_action_input_schema["properties"][
            "triggerType"
        ],
        "triggerTimePeriod": update_collection_workflow_action_input_schema[
            "properties"
        ]["triggerTimePeriod"],
        "triggerTimePeriodUntil": update_collection_workflow_action_input_schema[
            "properties"
        ]["triggerTimePeriodUntil"],
        "subject": update_collection_workflow_action_input_schema["properties"][
            "subject"
        ],
        "messageBody": update_collection_workflow_action_input_schema["properties"][
            "messageBody"
        ],
        "paymentLink": update_collection_workflow_action_input_schema["properties"][
            "paymentLink"
        ],
        "recipients": update_collection_workflow_action_input_schema["properties"][
            "recipients"
        ],
        "cc": update_collection_workflow_action_input_schema["properties"]["cc"],
        "bcc": update_collection_workflow_action_input_schema["properties"]["bcc"],
    },
    "required": [
        "externalId",
        "actionExternalId",
        "actionName",
        "actionType",
        "triggerType",
        "triggerTimePeriod",
    ],
}


list_collection_workflows_input_schema = {
    "type": "object",
    "properties": {
        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
        "startAfter": {
            "type": "string",
            "description": "Cursor returned by a previous list call.",
        },
    },
}


get_collection_workflow_input_schema = {
    "type": "object",
    "properties": {
        "externalId": {
            "type": "string",
            "description": "External ID of the workflow to read.",
        },
    },
    "required": ["externalId"],
}


delete_collection_workflow_input_schema = {
    "type": "object",
    "properties": {
        "externalId": {
            "type": "string",
            "description": (
                "External ID of the workflow to delete. Removes the template "
                "and every action under it; customers assigned to this "
                "workflow stop receiving its cadence."
            ),
        },
    },
    "required": ["externalId"],
}


get_collection_workflow_action_input_schema = {
    "type": "object",
    "properties": {
        "externalId": {
            "type": "string",
            "description": "External ID of the parent workflow.",
        },
        "actionExternalId": {
            "type": "string",
            "description": "External ID of the action step to read.",
        },
    },
    "required": ["externalId", "actionExternalId"],
}


delete_collection_workflow_action_input_schema = {
    "type": "object",
    "properties": {
        "externalId": {
            "type": "string",
            "description": "External ID of the parent workflow.",
        },
        "actionExternalId": {
            "type": "string",
            "description": (
                "External ID of the action step to delete. The rest of the "
                "cadence keeps firing — only this step is removed."
            ),
        },
    },
    "required": ["externalId", "actionExternalId"],
}
