# Peakflo Server

pfMCP server implementation for interacting with the Peakflo API (invoices, vendors, bills, actions, and more).

### Prerequisites

- Python 3.11+
- Signed up in Peakflo
- API access token set up

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
| **create_task** | Create an internal task assigned to a user (account manager, collector). Optionally link to an invoice/bill/PO via `objectType` + `objectExternalId`. Routes through `/v1/tasks`. |
| **add_action_log** | Add an action log entry (e.g. save transcripts). |
| **run_bill_po_matching** | Run Purchase Order (PO) matching on an existing bill. Updates line-level PO links and 3-way matching details. Use when re-running matching after a bill was created without POs or when POs/bill data changed. Tenant is taken from the auth token; provide at least one of `billId`, `externalId`, or `sourceId` to identify the bill. |
| **update_collection_workflow** | Update top-level fields on a collection workflow (dunning cadence) — title, default template, reply-to, etc. Partial update; only supplied fields are written. Routes through `PUT /v1/collection-workflows/:externalId`. |
| **update_collection_workflow_action** | Update a single step inside a collection workflow — channel, message body, trigger timing, enabled flag. Routes through `PUT /v1/collection-workflows/:externalId/actions/:actionExternalId`. |

### Run

#### Local Development

```bash
python src/servers/local.py --server peakflo --user-id local
```
