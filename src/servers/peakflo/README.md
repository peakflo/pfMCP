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

Tenant configuration tools use the tenant in the API token. Read a record before you update it. The `payload` input is the complete billing API body. The API checks policy levels, rule access, and custom field data.

| Resource | Tools | API route |
|----------|-------|-----------|
| AP approval policies | `list_approval_policies`, `get_approval_policy`, `create_approval_policy`, `update_approval_policy`, `delete_approval_policy` | `/v1/ap/policy` |
| Rules Engine rules | `list_rules`, `get_rule`, `create_rule`, `update_rule`, `delete_rule` | `/v1/field-rules` |
| AP custom fields | `list_custom_fields`, `create_custom_field`, `update_custom_field`, `delete_custom_field` | `/v1/ap/customfields` |
| Users | `invite_user` | `/v1/users/invitations` |
| Chart of accounts | `list_chart_of_accounts`, `get_chart_of_account`, `create_chart_of_account`, `update_chart_of_account`, `delete_chart_of_account` | `/v1/chartOfAccounts` |
| Roles and permissions | `list_role_permissions`, `list_roles`, `get_role`, `create_role`, `update_role`, `delete_role` | `/v1/roles` |

Approval rule deletion archives the rule. The API rejects deletion while an active policy uses it. Other rule deletion removes the rule. Custom field list results use the API page and limit controls.

`invite_user` requires `email` and `displayName`. The API uses the tenant's default user role unless a user token with role management authority supplies another role. Tenant API credentials can invite users with the default role only. The API queues user creation; the existing user management worker sends the email unless `skipUserInvite` is set for the tenant.

COA create and update need `name`, `code`, `type`, and `paymentAllowed`. The API checks the same `enableCoaCreation` flag, `createCOA` user permission, and duplicate account number as the Settings page. An API credential can write when the tenant flag is on. Update and delete work only for accounts created in Settings.

Read `list_role_permissions` before changing role flags. Role writes accept only the permission keys used by the web role editor. A user token needs `createRoles` or `editRoles` and cannot grant a permission the user does not hold. The tenant API credential is checked against the tenant's configured access token. System roles cannot be changed. A role cannot be deleted if it is assigned to a user or set as the default user role.

| Tool | Description |
|------|-------------|
| **read_vendor** | Fetch vendor details by external ID. |
| **create_vendor** | Create a new vendor with company info, addresses, contacts, bank details, and custom fields. |
| **create_customer** | Create a new customer (`POST /v1/customers`) with company info, status, currency, contacts, addresses, payment terms, and custom fields. |
| **update_customer** | Update an existing customer by its external ID (`PUT /v1/customers/:externalId`). `externalId`, `companyName`, `currency` and `status` are required by the API on every update; omitted optional fields stay unchanged; a non-empty `customField` list replaces the stored custom fields. |
| **add_customer_attachment** | Add a file to a customer's Files tab (`PUT /v1/customers/:customerExternalId/attachments`). `customerExternalId` is the same external id used by `create_customer`, and `externalId` identifies the file. A previous caller may still send `customerId` (the internal companies document id) and omit `externalId`; that call registers the file through billing. Supply the file via a signed `file_url` or via `base64` with `fileSize` — not both. The API receives standard padded base64 in `data`. `name` may include letters, numbers, spaces, dots, hyphens, underscores, parentheses, `#`, apostrophes, ampersands, plus, commas, and brackets. It must contain a letter or digit and an extension, and `contentType` must match that extension. `dateCreated`, when set, must be ISO 8601. `fileType` is optional and defaults to `other`. Files over 10MB are rejected. |
| **create_invoice** | Create an invoice with line items, customer info, and financial breakdown. |
| **update_invoice** | Update an existing invoice. |
| **update_purchase_order** | Update an existing purchase order by its external ID (`PUT /v1/purchase-order/:externalId`). Full-object update — supply the complete field set; `customField` replaces the existing custom-field array (no merge); `status` is carried for validation but does not transition the PO. |
| **add_purchase_order_attachment** | Add an attachment to an existing purchase order by its external ID (`PUT /v1/purchase-order/:externalId/attachments`). Supply the file via a signed `file_url` (server downloads, base64-encodes, and computes `fileSize`) or directly via `base64` (with `fileSize`) — not both. Supports AP attachment file types (invoice, statement, cabinet, paymentProof, fakturPajak, whtFile, etc.). Files over 10MB are rejected. |
| **add_bill_attachment** | Add an attachment to an existing bill by its external ID (`PUT /v1/bill/:billExternalId/attachments`). Supply the file via a signed `file_url` (server downloads, base64-encodes, and computes `fileSize`) or directly via `base64` (with `fileSize`) — not both. Optional `customFieldDetails` targets a Pixel multi-file CF (`fileType` coerced to `customFieldFile`): `customFieldNumber` is required; `customFieldId`, `customFieldName`, `customFieldType`, `customFieldSourceId` are optional and are forwarded only when non-empty (`customFieldType` normalized to `multiFile` when given, omitted otherwise). Files over 10MB are rejected. |
| **update_bill_attachment_validation** | Save `validationDetails` and optional `suggestedFieldOverwrites` on an existing bill attachment (`PUT /v1/bill/:billExternalId/attachments/:attachmentId/validation`). Each suggestion needs `id`, `ruleId`, `currentValue`, `suggestedValue`, `optional`, `overridable`, and a bill or line target. A line target uses persistent 1-based `lineIndex`. This tool does not apply changes to the bill; the separate user decision route records approval or rejection. |
| **update_ap_attachment_validation** | Save validation checks and optional proposed field changes by `objectType`, Mongo `objectId`, and `attachmentId`. Supports standalone My Expenses (`expense`), bill (including Expense Reports), PO, PQ, PR, RN, Travel Reports (`tr`), bill payment, and AP credit note. A TR line voucher uses the same `PUT /v1/ap/tr/:objectId/attachments/:attachmentId/validation` route with its persistent 1-based `lineIndex` in the body. A verified user reviews proposals separately. |
| **add_expense_report_attachment** | Add an attachment to an expense report by external ID (`PUT /v1/expense-report/:externalId/attachments`). Same file source + optional `customFieldDetails` contract as bill attach. |
| **add_bill_payment_attachment** | Add an attachment to an AP / TnE payment by external ID (`PUT /v1/bill-payment/:externalId/attachments`). Same file source + optional `customFieldDetails` contract as bill attach. |
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
| **create_collection_workflow** | Create a new collection workflow (dunning cadence) from scratch — the workflow shell only (title, sender identity, cadence settings). Add steps afterwards with `create_collection_workflow_action`, one call per step. `externalId` is caller-assigned and must be unique per tenant (409 on collision). Routes through `POST /v1/collection-workflows`. |
| **assign_customer_to_workflow** | Reassign a customer's default collection workflow to a specific template. Used to apply an AR Golden Workflow recommendation — e.g. "shift this Large-Doubtful account onto the call-led golden workflow." Discover valid `workflowExternalId` values via `list_collection_workflows`. Only affects NEW invoices for the customer; existing open invoices keep whatever workflow they were created with. Routes through `POST /v1/customers/:customerExternalId/assign-workflow`. |

### Run

#### Local Development

```bash
python src/servers/local.py --server peakflo --user-id local
```

Standalone expense suggestions support only `apObject.note`. Merchant, dates, money, mileage/per-diem and line-item targets are rejected by the API; apply OCR amounts through the reviewed normal expense editor save. The tool never approves proposals.
