from mcp.types import Tool
from servers.peakflo.schemas.vendor import read_vendor_output
from servers.peakflo.schemas.utility import (
    soa_email_input_schema,
    create_task_input_schema,
    add_action_log_input_schema,
)
from servers.peakflo.schemas.invoice import (
    create_invoice_schema,
    update_invoice_schema,
    raise_invoice_dispute_schema,
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
                }
            },
            "required": ["externalId"],
        },
        outputSchema=read_vendor_output,
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
]


utility_tools = [
    Tool(
        name="soa_email",
        description="Send an SOA email to the vendor",
        inputSchema=soa_email_input_schema,
    ),
    Tool(
        name="create_task",
        description="Add an action to the vendor or customer, can be used to create a pay task",
        inputSchema=create_task_input_schema,
    ),
    Tool(
        name="add_action_log",
        description="Add an action log to the vendor or customer, can be used for saving transcripts in action log",
        inputSchema=add_action_log_input_schema,
    ),
]
