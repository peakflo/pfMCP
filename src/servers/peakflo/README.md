# Peakflo Server

pfMCP server implementation for interacting with the Peakflo API (invoices, vendors, bills, actions, and more).

### Prerequisites

- Python 3.11+
- Signed up in Peakflo
- API access token set up
- `PEAKFLO_API_GATEWAY_KEY` configured for `send_message`

To set up and verify authentication, run:

```bash
python src/servers/peakflo/main.py auth
```

### Tools

| Tool | Description |
|------|-------------|
| **read_vendor** | Fetch vendor details by external ID. |
| **create_vendor** | Create a new vendor with company info, addresses, contacts, bank details, and custom fields. |
| **create_invoice** | Create an invoice with line items, customer info, and financial breakdown. |
| **update_invoice** | Update an existing invoice. |
| **raise_invoice_dispute** | Raise a dispute for an invoice. |
| **soa_email** | Send an SOA (statement of account) email to the vendor. Kept for backwards compat — prefer `send_message` for new use cases. |
| **send_message** | Send an ad-hoc message to a customer via email/WhatsApp/SMS/Zalo/Line, or log a manual call. Channel-first; routes through `/v2/messages/send`. |
| **create_task** | Create an internal task assigned to a user (account manager, collector). Optionally link it to an invoice via `objectType` + `objectExternalId`. Routes through `/v1/tasks`. |
| **list_collection_workflows** | List workflows before selecting one to edit. |
| **get_collection_workflow** | Read a workflow and its action steps before editing it. |
| **add_action_log** | Add an action log entry (e.g. save transcripts). |
| **run_bill_po_matching** | Run Purchase Order (PO) matching on an existing bill. Updates line-level PO links and 3-way matching details. Use when re-running matching after a bill was created without POs or when POs/bill data changed. Tenant is taken from the auth token; provide at least one of `billId`, `externalId`, or `sourceId` to identify the bill. |
| **update_collection_workflow** | Update top-level fields on a collection workflow (dunning cadence) — title, default template, reply-to, etc. Partial update; only supplied fields are written. Routes through `PUT /v1/collection-workflows/:externalId`. |
| **update_collection_workflow_action** | Update a single step inside a collection workflow — channel, message body, trigger timing, enabled flag. Routes through `PUT /v1/collection-workflows/:externalId/actions/:actionExternalId`. |
| **create_collection_workflow_action** | Append a new step (cadence action) to an existing collection workflow — e.g. add a −3-day pre-due nudge or a Day-3 overdue email. `actionExternalId` is caller-assigned and must be unique within the workflow. Routes through `POST /v1/collection-workflows/:externalId/actions`. |
| **delete_collection_workflow** | Delete a workflow template and every action under it. Customers assigned to this workflow stop receiving its cadence. Routes through `DELETE /v1/collection-workflows/:externalId`. |
| **get_collection_workflow_action** | Read one step of a workflow. The parent `get_collection_workflow` already returns nested actions; use this when you already know the `actionExternalId` (e.g. to verify a PATCH landed). Routes through `GET /v1/collection-workflows/:externalId/actions/:actionExternalId`. |
| **delete_collection_workflow_action** | Delete one step from a workflow's cadence. The rest keeps firing. Routes through `DELETE /v1/collection-workflows/:externalId/actions/:actionExternalId`. |
| **list_whatsapp_templates** | List Meta-approved WhatsApp templates registered for the tenant. Call this before dispatching a WhatsApp message via `send_message` — the WhatsApp Business API rejects free-form text outside a 24h reply window, so every cold outreach must reference an approved template. Returns an empty list if the tenant has none configured. Routes through `GET /v1/whatsapp-templates`. |
| **assign_customer_to_workflow** | Reassign a customer's default collection workflow to a specific template. Used to apply an AR Golden Workflow recommendation — e.g. "shift this Large-Doubtful account onto the call-led golden workflow." Discover valid `workflowExternalId` values via `list_collection_workflows`. Only affects NEW invoices for the customer; existing open invoices keep whatever workflow they were created with. Routes through `POST /v1/customers/:customerExternalId/assign-workflow`. |

### Run

#### Local Development

```bash
python src/servers/local.py --server peakflo --user-id local
```
