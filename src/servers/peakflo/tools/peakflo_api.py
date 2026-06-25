from mcp.types import Tool
from servers.peakflo.schemas.vendor import create_vendor_schema, update_vendor_schema
from servers.peakflo.schemas.utility import (
    soa_email_input_schema,
    send_message_input_schema,
    create_task_input_schema,
    add_action_log_input_schema,
    run_bill_po_matching_input_schema,
    update_collection_workflow_input_schema,
    update_collection_workflow_action_input_schema,
    list_collection_workflows_input_schema,
    get_collection_workflow_input_schema,
)
from servers.peakflo.schemas.invoice import (
    create_invoice_schema,
    update_invoice_schema,
    raise_invoice_dispute_schema,
    add_invoice_attachment_schema,
)

vendor_tools = [
    Tool(
        name="read_vendor",
        description="Fetch vendor details by external ID from Peakflo API",
        inputSchema={
            "type": "object",
            "properties": {
                "externalId": {
                    "type": "string",
                    "description": "External ID of the vendor to fetch",
                },
                "tenantId": {
                    "type": "string",
                    "description": "Tenant ID",
                },
            },
            "required": ["externalId", "tenantId"],
        },
    ),
    Tool(
        name="create_vendor",
        description="Create a new vendor in Peakflo with comprehensive details including company information, addresses, contacts, bank details, and custom fields",
        inputSchema=create_vendor_schema,
    ),
    Tool(
        name="update_vendor",
        description="Update an existing vendor in Peakflo. Supports updating company information, addresses, contacts, bank details, custom fields, VAT settings, payment terms, and more. Only provided fields will be updated.",
        inputSchema=update_vendor_schema,
    ),
]


invoice_tools = [
    Tool(
        name="create_invoice",
        description="Create an invoice with comprehensive details including line items, customer information, and financial breakdown",
        inputSchema=create_invoice_schema,
    ),
    Tool(
        name="update_invoice",
        description="Update an invoice with comprehensive details including line items, customer information, and financial breakdown",
        inputSchema=update_invoice_schema,
    ),
    Tool(
        name="raise_invoice_dispute",
        description="Raise a dispute for an invoice",
        inputSchema=raise_invoice_dispute_schema,
    ),
    Tool(
        name="add_invoice_attachment",
        description="Add an attachment to an existing invoice. Accepts a signed file URL; the server downloads and base64-encodes it.",
        inputSchema=add_invoice_attachment_schema,
    ),
]


utility_tools = [
    Tool(
        name="soa_email",
        description="Send an SOA email to the vendor. Kept for backwards compat — for new agents use send_message which supports all channels (email/WhatsApp/SMS/Zalo/Line/call_log).",
        inputSchema=soa_email_input_schema,
    ),
    Tool(
        name="send_message",
        description=(
            "Send an ad-hoc message to a customer via email, WhatsApp, SMS, Zalo, "
            "Line, or log a call. Routes through /v2/messages/send. Use this when "
            "you need to communicate with a customer directly. For internal tasks "
            "(assigned to a teammate), use create_task instead."
        ),
        inputSchema=send_message_input_schema,
    ),
    Tool(
        name="create_task",
        description=(
            "Create an internal task assigned to a user (account manager, "
            "collector, etc.). Optionally link the task to an invoice "
            "via objectType + objectExternalId. Routes through /v1/tasks."
        ),
        inputSchema=create_task_input_schema,
    ),
    Tool(
        name="list_collection_workflows",
        description="List collection workflows for the authenticated tenant before choosing one to edit.",
        inputSchema=list_collection_workflows_input_schema,
    ),
    Tool(
        name="get_collection_workflow",
        description="Read a collection workflow and its action steps before editing it.",
        inputSchema=get_collection_workflow_input_schema,
    ),
    Tool(
        name="add_action_log",
        description="Add an action log to the vendor or customer, can be used for saving transcripts in action log",
        inputSchema=add_action_log_input_schema,
    ),
    Tool(
        name="run_bill_po_matching",
        description="Run Purchase Order (PO) matching on an existing bill. Updates line-level PO links and matching details (3-way matching). Use when re-running PO matching after a bill was created without POs, or when POs/bill data changed. Tenant is taken from the auth token. Provide at least one of billId, externalId, or sourceId to identify the bill.",
        inputSchema=run_bill_po_matching_input_schema,
    ),
    Tool(
        name="update_collection_workflow",
        description=(
            "Update top-level fields on a collection workflow (dunning cadence) — "
            "title, reply-to, sender name, contact-superior escalation, etc. Partial "
            "update: only the supplied fields are written. To edit individual "
            "steps in the cadence, use update_collection_workflow_action."
        ),
        inputSchema=update_collection_workflow_input_schema,
    ),
    Tool(
        name="update_collection_workflow_action",
        description=(
            "Update a single step inside a collection workflow — channel, "
            "message body, subject, or trigger timing. Useful for "
            "swapping a step from email to WhatsApp, rewriting the dunning "
            "copy on a specific step."
        ),
        inputSchema=update_collection_workflow_action_input_schema,
    ),
]
