# Implementation Plan: Xero Integration for pfMCP (TSK-15826)

## Overview

Add Xero accounting/invoicing/payroll integration to pfMCP, porting all 49 tools from the official [xero-mcp-server](https://github.com/XeroAPI/xero-mcp-server) TypeScript implementation into Python following pfMCP conventions.

**Key decision**: Nango handles Xero OAuth2 natively via `xero-oauth2-cc` provider — no custom `src/utils/xero/util.py` needed.

---

## Files to Create

| # | File | Purpose | Complexity |
|---|------|---------|------------|
| 1 | `src/servers/xero/main.py` | MCP server: 49 tool definitions + handlers | High (~1500–1800 lines) |
| 2 | `src/servers/xero/config.yaml` | Server metadata & tools list | Trivial (~60 lines) |
| 3 | `src/servers/xero/README.md` | Integration documentation | Low (~100 lines) |
| 4 | `tests/servers/xero/tests.py` | Tool tests | Medium (~150 lines) |

## Files to Modify

| File | Change |
|------|--------|
| `src/auth/constants.py` | Add `"xero"` → `{"nango_service_name": "xero-oauth2-cc", "auth_type": AUTH_TYPE_OAUTH2}` |
| `README.MD` (root) | Add Xero row to **Business Tools** section of the supported servers table |

---

## Step-by-Step Implementation

### Step 1: Add Xero to `SERVICE_NAME_MAP`

**File**: `src/auth/constants.py`

Add one entry:
```python
"xero": {"nango_service_name": "xero-oauth2-cc", "auth_type": AUTH_TYPE_OAUTH2},
```

Maps our internal `"xero"` service name to Nango's `"xero-oauth2-cc"` provider key so `NangoAuthClient` fetches the correct connection.

**Complexity**: Trivial (1 line)

---

### Step 2: Create Main Server — `src/servers/xero/main.py`

This is the bulk of the work. Structure:

#### 2A. Imports & Configuration (~30 lines)

- Standard path setup, logging, mcp imports
- `from src.auth.factory import create_auth_client` (Nango-managed, no custom util)
- Constants:
  - `SERVICE_NAME = Path(__file__).parent.name`
  - `XERO_API_BASE = "https://api.xero.com"`
  - `ACCOUNTING_API = "/api.xro/2.0"`
  - `PAYROLL_API = "/payroll.xro/1.0"`

#### 2B. Credential Extraction Helper (~25 lines)

```python
async def get_xero_credentials(user_id, api_key=None):
    """Get Xero access_token and tenant_id from Nango."""
    auth_client = create_auth_client(api_key=api_key)
    credentials = auth_client.get_user_credentials(SERVICE_NAME, user_id)

    access_token = credentials.get("access_token")
    # Tenant ID comes from Nango connection metadata
    tenant_id = credentials.get("metadata", {}).get("tenantId")

    if not tenant_id:
        # Fallback: call Xero /connections to discover tenant ID
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.xero.com/connections",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            connections = resp.json()
            if connections:
                tenant_id = connections[0].get("tenantId")

    if not access_token or not tenant_id:
        raise ValueError("Invalid Xero credentials: missing access_token or tenantId")

    return access_token, tenant_id
```

#### 2C. Centralized API Helper (~50 lines)

```python
async def call_xero_api(endpoint, access_token, tenant_id, method="GET", data=None, params=None):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "xero-tenant-id": tenant_id,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    # Uses httpx.AsyncClient for HTTP calls
    # Error handling: 401→auth, 403→permission, 404→not found, 429→rate limit
```

#### 2D. `create_server(user_id, api_key=None)` Factory

##### Tool Definitions (`@server.list_tools()`) — 49 tools:

**List Operations (22 tools):**
| Tool Name | Xero API Endpoint | Key Params |
|-----------|------------------|------------|
| `list_accounts` | `GET /api.xro/2.0/Accounts` | — |
| `list_contacts` | `GET /api.xro/2.0/Contacts` | `page`, `searchTerm` (via where clause) |
| `list_invoices` | `GET /api.xro/2.0/Invoices` | `page`, `contactIds[]`, `invoiceNumbers[]` |
| `list_items` | `GET /api.xro/2.0/Items` | — |
| `list_payments` | `GET /api.xro/2.0/Payments` | `page` |
| `list_quotes` | `GET /api.xro/2.0/Quotes` | `page` |
| `list_credit_notes` | `GET /api.xro/2.0/CreditNotes` | `page` |
| `list_bank_transactions` | `GET /api.xro/2.0/BankTransactions` | `page`, `bankAccountId` (via where clause) |
| `list_manual_journals` | `GET /api.xro/2.0/ManualJournals` | `page` |
| `list_tax_rates` | `GET /api.xro/2.0/TaxRates` | — |
| `list_tracking_categories` | `GET /api.xro/2.0/TrackingCategories` | — |
| `list_contact_groups` | `GET /api.xro/2.0/ContactGroups` | — |
| `list_organisation_details` | `GET /api.xro/2.0/Organisation` | — |
| `list_profit_and_loss` | `GET /api.xro/2.0/Reports/ProfitAndLoss` | `fromDate`, `toDate`, `periods`, `timeframe` |
| `list_report_balance_sheet` | `GET /api.xro/2.0/Reports/BalanceSheet` | `date`, `periods`, `timeframe` |
| `list_trial_balance` | `GET /api.xro/2.0/Reports/TrialBalance` | `date` |
| `list_aged_receivables_by_contact` | `GET /api.xro/2.0/Reports/AgedReceivablesByContact` | `contactId` (required) |
| `list_aged_payables_by_contact` | `GET /api.xro/2.0/Reports/AgedPayablesByContact` | `contactId` (required) |
| `list_payroll_employees` | `GET /payroll.xro/1.0/Employees` | `page` |
| `list_payroll_employee_leave` | `GET /payroll.xro/1.0/Employees/{employeeId}/Leave` | `employeeId` (required) |
| `list_payroll_employee_leave_balances` | `GET /payroll.xro/1.0/Employees/{employeeId}/LeaveBalances` | `employeeId` (required) |
| `list_payroll_leave_types` | `GET /payroll.xro/1.0/LeaveTypes` | — |
| `list_timesheets` | `GET /payroll.xro/1.0/Timesheets` | `page` |

**Create Operations (11 tools):**
| Tool Name | Xero API Endpoint | Required Fields |
|-----------|------------------|-----------------|
| `create_contact` | `POST /api.xro/2.0/Contacts` | `name`; optional: `email`, `phone` |
| `create_invoice` | `POST /api.xro/2.0/Invoices` | `contactId`, `lineItems[]` (description, quantity, unitAmount, accountCode), `type` (ACCREC/ACCPAY) |
| `create_item` | `POST /api.xro/2.0/Items` | `code`, `name`; optional: purchase/sales details |
| `create_payment` | `POST /api.xro/2.0/Payments` | `invoiceId`, `accountId`, `amount`, `date` |
| `create_quote` | `POST /api.xro/2.0/Quotes` | `contactId`, `lineItems[]` |
| `create_bank_transaction` | `POST /api.xro/2.0/BankTransactions` | `type`, `contactId`, `bankAccountId`, `lineItems[]` |
| `create_credit_note` | `POST /api.xro/2.0/CreditNotes` | `contactId`, `type`, `lineItems[]` |
| `create_manual_journal` | `POST /api.xro/2.0/ManualJournals` | `narration`, `journalLines[]` |
| `create_payroll_timesheet` | `POST /payroll.xro/1.0/Timesheets` | `employeeId`, `startDate`, `endDate`, `timesheetLines[]` |
| `create_tracking_category` | `POST /api.xro/2.0/TrackingCategories` | `name` |
| `create_tracking_option` | `POST /api.xro/2.0/TrackingCategories/{trackingCategoryId}/Options` | `trackingCategoryId`, `name` |

**Update Operations (11 tools):**
| Tool Name | Xero API Endpoint | Required Fields |
|-----------|------------------|-----------------|
| `update_contact` | `POST /api.xro/2.0/Contacts/{contactId}` | `contactId`; optional: name, email, phone, address |
| `update_invoice` | `POST /api.xro/2.0/Invoices/{invoiceId}` | `invoiceId`; validates DRAFT status first |
| `update_item` | `POST /api.xro/2.0/Items/{itemId}` | `itemId`; optional: code, name, purchase/sales details |
| `update_quote` | `POST /api.xro/2.0/Quotes/{quoteId}` | `quoteId`; validates DRAFT status |
| `update_bank_transaction` | `POST /api.xro/2.0/BankTransactions/{transactionId}` | `transactionId` |
| `update_credit_note` | `POST /api.xro/2.0/CreditNotes/{creditNoteId}` | `creditNoteId`; validates DRAFT status |
| `update_manual_journal` | `POST /api.xro/2.0/ManualJournals/{manualJournalId}` | `manualJournalId` |
| `update_tracking_category` | `POST /api.xro/2.0/TrackingCategories/{trackingCategoryId}` | `trackingCategoryId`, `name` |
| `update_tracking_options` | `POST /api.xro/2.0/TrackingCategories/{trackingCategoryId}/Options/{optionId}` | `trackingCategoryId`, `optionId`, `name` |
| `update_payroll_timesheet_line` | `POST /payroll.xro/1.0/Timesheets/{timesheetId}` | `timesheetId`, updated `timesheetLines[]` |
| `add_payroll_timesheet_line` | `POST /payroll.xro/1.0/Timesheets/{timesheetId}` | `timesheetId`, new `timesheetLines[]` |

**Other Operations (5 tools):**
| Tool Name | Xero API Endpoint | Description |
|-----------|------------------|-------------|
| `approve_payroll_timesheet` | `POST /payroll.xro/1.0/Timesheets/{timesheetId}` | Set status → Approved |
| `revert_payroll_timesheet` | `POST /payroll.xro/1.0/Timesheets/{timesheetId}` | Set status → Draft |
| `delete_payroll_timesheet` | `POST /payroll.xro/1.0/Timesheets/{timesheetId}` | Set status → Deleted |
| `get_payroll_timesheet` | `GET /payroll.xro/1.0/Timesheets/{timesheetId}` | Retrieve single timesheet |

##### Tool Handlers (`@server.call_tool()`)

Large if/elif chain. Each handler:
1. Extracts arguments
2. Calls `call_xero_api()` with the appropriate endpoint, method, and data
3. Returns `[TextContent(type="text", text=json.dumps(result, indent=2))]`

Handler patterns:
- **Simple list**: `GET /api.xro/2.0/{Resource}`, return JSON
- **Paginated list**: Add `page` query param
- **Filtered list**: Add `where` clause or ID arrays as query params
- **Report**: Pass date params (`fromDate`, `toDate`)
- **Create**: Build JSON body from args, `POST /api.xro/2.0/{Resource}`, wrap in container (`{"Contacts": [contact]}`)
- **Update**: Build JSON body, `POST /api.xro/2.0/{Resource}/{id}`
- **Payroll**: Use `/payroll.xro/1.0/` base path

#### 2E. Module Exports (~20 lines)

- `server = create_server`
- `get_initialization_options(server_instance)` function
- `if __name__ == "__main__":` with auth entry point (print message pointing to Nango)

---

### Step 3: Create Config — `src/servers/xero/config.yaml`

```yaml
name: "Xero guMCP Server"
icon: "assets/icon.png"
description: "Interact with Xero for accounting, invoicing, contacts, and payroll management"
documentation_path: "README.md"
tools:
  - name: "list_accounts"
    description: "Retrieve a list of accounts from Xero"
  # ... all 49 tools
```

**Complexity**: Trivial (~60 lines, mechanical)

---

### Step 4: Create README — `src/servers/xero/README.md`

Document:
- Overview of the integration
- Authentication setup via Nango (xero-oauth2-cc provider)
- Required Xero OAuth scopes
- Available tools grouped by category (List, Create, Update, Other)
- Xero-specific notes: tenant ID handling, pagination (page=10), rate limits (60/min)

**Complexity**: Low (~100 lines)

---

### Step 5: Create Tests — `tests/servers/xero/tests.py`

Follow existing test patterns with `TOOL_TESTS` array.

Suggested test flow:
1. Read-only: `list_accounts`, `list_tax_rates`, `list_contacts`, `list_organisation_details`
2. Create chain: `create_contact` → `update_contact` → `create_invoice` → `list_invoices`
3. Reports: `list_profit_and_loss`, `list_report_balance_sheet`

**Complexity**: Medium (~150 lines)

---

### Step 6: Update Root README

**File**: `README.MD`

Add Xero row in the **Business Tools** section (after QuickBooks line ~167):

```markdown
| Xero | ✅ Seamless with Nango auth | [Xero Docs](/src/servers/xero/README.md) |
```

**Complexity**: Trivial (1 line)

---

## Implementation Order

```
Step 1 (constants.py)  ──→  Step 2 (main.py)  ──→  Step 5 (tests.py)
                                  │
                            Step 3 (config.yaml)  [parallel]
                            Step 4 (README.md)    [parallel]
                                  │
                            Step 6 (root README)  [last]
```

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Auth approach | Nango-managed, no `util.py` | User requirement; Nango has native `xero-oauth2-cc` provider |
| Nango provider key | `xero-oauth2-cc` | Matches Nango's built-in Xero Client Credentials integration |
| Tenant ID source | Nango metadata → `/connections` fallback | Nango stores org metadata; fallback ensures robustness |
| Tool naming | Underscores (`list_accounts`) | pfMCP convention (vs hyphens in TypeScript original) |
| HTTP client | `httpx` | Async-compatible, matches QuickBooks pattern |
| File structure | Single `main.py` | Follows project convention |
| Tool count | All 49 tools | Per task requirement: "Copy each tool and mapping carefully" |

## Xero API Reference

- **Base URL**: `https://api.xero.com`
- **Accounting API**: `/api.xro/2.0/`
- **Payroll API**: `/payroll.xro/1.0/`
- **Required headers**: `Authorization: Bearer {token}`, `xero-tenant-id: {tenantId}`
- **Pagination**: `page` param (1-based), ~10 items per page
- **Rate limits**: 60 calls/minute per tenant
- **Date format**: ISO 8601 `YYYY-MM-DD`
- **Phone format**: `[{"PhoneNumber": "...", "PhoneType": "MOBILE"}]`
- **Address format**: `[{"AddressLine1": "...", ..., "AddressType": "STREET"}]`
- **Invoice line items**: `{"Description", "Quantity", "UnitAmount", "AccountCode", "TaxType", optional "ItemCode", "Tracking"}`

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Tenant ID not in Nango metadata | Fallback to `GET /connections` endpoint |
| Large file size (~1800 lines) | Centralized `call_xero_api()` helper keeps handlers compact (3-10 lines each) |
| Xero rate limits (60 calls/min) | Clear 429 error messages returned to user |
| Payroll API regional differences (NZ/UK only) | Document in README, handlers return clear API errors |
