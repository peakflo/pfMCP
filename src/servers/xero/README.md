# Xero Integration

This MCP server provides integration with [Xero](https://www.xero.com/), allowing you to interact with Xero's accounting, invoicing, contacts, and payroll features through the Model Context Protocol.

## Authentication

Xero authentication is managed via [Nango](https://nango.dev/) using the `xero-oauth2-cc` provider. No custom OAuth utility is needed.

### Setup

1. Configure a Xero connection in your Nango dashboard using the `xero-oauth2-cc` provider
2. Ensure the following OAuth scopes are granted:
   - `accounting.invoices` / `accounting.invoices.read`
   - `accounting.payments` / `accounting.payments.read`
   - `accounting.banktransactions` / `accounting.banktransactions.read`
   - `accounting.manualjournals` / `accounting.manualjournals.read`
   - `accounting.reports.aged.read`
   - `accounting.reports.balancesheet.read`
   - `accounting.reports.profitandloss.read`
   - `accounting.reports.trialbalance.read`
   - `accounting.contacts`
   - `accounting.settings`
   - `payroll.settings`
   - `payroll.employees`
   - `payroll.timesheets`
3. The Xero tenant ID is automatically retrieved from Nango connection metadata or via the Xero `/connections` endpoint

### Nango Documentation

- [Xero OAuth2 CC Integration](https://nango.dev/docs/integrations/all/xero-oauth2-cc)

## Available Tools

### List Operations

| Tool | Description |
|------|-------------|
| `list_accounts` | Retrieve chart of accounts |
| `list_contacts` | Retrieve contacts with optional search |
| `list_invoices` | Retrieve invoices with filtering |
| `list_items` | Retrieve items |
| `list_payments` | Retrieve payments |
| `list_quotes` | Retrieve quotes |
| `list_purchase_orders` | Retrieve purchase orders |
| `list_credit_notes` | Retrieve credit notes |
| `list_bank_transactions` | Retrieve bank transactions |
| `list_bank_transfers` | Retrieve bank transfers |
| `list_batch_payments` | Retrieve batch payments |
| `list_overpayments` | Retrieve overpayments |
| `list_prepayments` | Retrieve prepayments |
| `list_manual_journals` | Retrieve manual journals |
| `list_tax_rates` | Retrieve tax rates |
| `list_tracking_categories` | Retrieve tracking categories |
| `list_contact_groups` | Retrieve contact groups |
| `list_organisation_details` | Retrieve organisation details |
| `list_profit_and_loss` | Retrieve P&L report |
| `list_report_balance_sheet` | Retrieve balance sheet |
| `list_trial_balance` | Retrieve trial balance |
| `list_aged_receivables_by_contact` | Retrieve aged receivables for a contact |
| `list_aged_payables_by_contact` | Retrieve aged payables for a contact |
| `list_payroll_employees` | Retrieve payroll employees (NZ/UK) |
| `list_payroll_employee_leave` | Retrieve employee leave records (NZ/UK) |
| `list_payroll_employee_leave_balances` | Retrieve employee leave balances (NZ/UK) |
| `list_payroll_leave_types` | Retrieve leave types (NZ/UK) |
| `list_timesheets` | Retrieve timesheets (NZ/UK) |

### Create Operations

| Tool | Description |
|------|-------------|
| `create_contact` | Create a new contact |
| `create_invoice` | Create a new invoice (ACCREC/ACCPAY) |
| `create_item` | Create a new item |
| `create_payment` | Create a new payment |
| `create_quote` | Create a new quote |
| `create_purchase_order` | Create a new purchase order |
| `create_bank_transaction` | Create a bank transaction |
| `create_credit_note` | Create a credit note |
| `create_bank_transfer` | Create a bank transfer |
| `create_batch_payment` | Create a batch payment |
| `create_overpayment` | Create an overpayment |
| `create_prepayment` | Create a prepayment |
| `create_manual_journal` | Create a manual journal |
| `create_payroll_timesheet` | Create a timesheet (NZ/UK) |
| `create_tracking_category` | Create a tracking category |
| `create_tracking_option` | Create a tracking option |

### Update Operations

| Tool | Description |
|------|-------------|
| `update_contact` | Update a contact |
| `update_invoice` | Update a draft invoice |
| `update_item` | Update an item |
| `update_quote` | Update a draft quote |
| `update_purchase_order` | Update a draft purchase order |
| `update_bank_transaction` | Update a bank transaction |
| `update_credit_note` | Update a draft credit note |
| `update_manual_journal` | Update a manual journal |
| `update_tracking_category` | Update a tracking category |
| `update_tracking_options` | Update tracking options |
| `update_payroll_timesheet_line` | Update timesheet lines (NZ/UK) |
| `add_payroll_timesheet_line` | Add timesheet lines (NZ/UK) |

### Attachment Operations

| Tool | Description |
|------|-------------|
| `list_attachments` | List attachments on supported entities |
| `get_attachment` | Download an attachment via temporary URL |
| `add_attachment` | Create a new attachment from base64 content |
| `upload_attachment` | Update an existing attachment from base64 content |
| `get_invoice_pdf` | Download a rendered invoice PDF via temporary URL |

### Other Operations

| Tool | Description |
|------|-------------|
| `approve_payroll_timesheet` | Approve a timesheet (NZ/UK) |
| `revert_payroll_timesheet` | Revert an approved timesheet (NZ/UK) |
| `delete_payroll_timesheet` | Delete a timesheet (NZ/UK) |
| `get_payroll_timesheet` | Retrieve a specific timesheet (NZ/UK) |
| `email_invoice` | Send an invoice email through Xero |

## Xero API Notes

- **Pagination**: Most list endpoints use `page` parameter (1-based), returning ~10 items per page
- **Rate Limits**: Xero allows 60 API calls per minute per tenant
- **Date Format**: ISO 8601 `YYYY-MM-DD`
- **Tenant ID**: Required for every API call via the `xero-tenant-id` header
- **Draft Validation**: Update operations for invoices, quotes, and credit notes validate DRAFT status before updating
- **Payroll**: Payroll endpoints are only available for NZ and UK regions

## Testing

```bash
# Run tests
python tests/servers/test_runner.py --server=xero

# Run tests remotely
python tests/servers/test_runner.py --server=xero --remote
```

## Error Handling

The server provides clear error messages for:
- **401**: Authentication failures (expired token)
- **403**: Permission denied (missing scopes)
- **404**: Resource not found
- **429**: Rate limit exceeded
- **400**: Bad request (invalid parameters)
