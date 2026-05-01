import uuid
import pytest
from tests.utils.test_tools import get_test_id, run_tool_test, run_resources_test

# Shared context dictionary at module level
SHARED_CONTEXT = {}

TOOL_TESTS = [
    # ==================== READ-ONLY LIST OPERATIONS ====================
    {
        "name": "list_accounts",
        "args_template": "",
        "expected_keywords": ["Accounts"],
        "description": "list all accounts from Xero chart of accounts",
    },
    {
        "name": "list_tax_rates",
        "args_template": "",
        "expected_keywords": ["TaxRates"],
        "description": "list all tax rates from Xero",
    },
    {
        "name": "list_contacts",
        "args_template": "with page=1",
        "expected_keywords": ["Contacts"],
        "regex_extractors": {"contact_id": r'"ContactID":\s*"([^"]+)"'},
        "description": "list contacts from Xero and extract a contact ID",
    },
    {
        "name": "list_organisation_details",
        "args_template": "",
        "expected_keywords": ["Organisations"],
        "description": "retrieve organisation details from Xero",
    },
    {
        "name": "list_invoices",
        "args_template": "with page=1",
        "expected_keywords": ["Invoices"],
        "description": "list invoices from Xero",
    },
    {
        "name": "list_items",
        "args_template": "",
        "expected_keywords": ["Items"],
        "description": "list items from Xero",
    },
    {
        "name": "list_payments",
        "args_template": "with page=1",
        "expected_keywords": ["Payments"],
        "description": "list payments from Xero",
    },
    {
        "name": "list_tracking_categories",
        "args_template": "",
        "expected_keywords": ["TrackingCategories"],
        "description": "list tracking categories from Xero",
    },
    {
        "name": "list_contact_groups",
        "args_template": "",
        "expected_keywords": ["ContactGroups"],
        "description": "list contact groups from Xero",
    },
    # ==================== REPORT OPERATIONS ====================
    {
        "name": "list_profit_and_loss",
        "args_template": "",
        "expected_keywords": ["Reports"],
        "description": "retrieve profit and loss report from Xero",
    },
    {
        "name": "list_report_balance_sheet",
        "args_template": "",
        "expected_keywords": ["Reports"],
        "description": "retrieve balance sheet report from Xero",
    },
    {
        "name": "list_trial_balance",
        "args_template": "",
        "expected_keywords": ["Reports"],
        "description": "retrieve trial balance report from Xero",
    },
    # ==================== CREATE → UPDATE CHAIN ====================
    {
        "name": "create_contact",
        "args_template": 'with name="Test Contact {random_id}" email="test{random_id}@example.com" phone="+1234567890"',
        "expected_keywords": ["Contacts", "ContactID"],
        "regex_extractors": {"created_contact_id": r'"ContactID":\s*"([^"]+)"'},
        "description": "create a new contact in Xero and extract the contact ID",
        "setup": lambda context: {"random_id": str(uuid.uuid4())[:8]},
    },
    {
        "name": "update_contact",
        "args_template": 'with contactId="{created_contact_id}" firstName="Updated" lastName="Contact {random_id}"',
        "expected_keywords": ["Contacts", "ContactID"],
        "description": "update the previously created contact in Xero",
        "depends_on": ["created_contact_id"],
        "setup": lambda context: {"random_id": str(uuid.uuid4())[:8]},
    },
    {
        "name": "list_aged_receivables_by_contact",
        "args_template": 'with contactId="{created_contact_id}"',
        "expected_keywords": ["Reports"],
        "description": "retrieve aged receivables for the created contact",
        "depends_on": ["created_contact_id"],
    },
    {
        "name": "list_aged_payables_by_contact",
        "args_template": 'with contactId="{created_contact_id}"',
        "expected_keywords": ["Reports"],
        "description": "retrieve aged payables for the created contact",
        "depends_on": ["created_contact_id"],
    },
    # ==================== SEARCH CONTACTS ====================
    {
        "name": "list_contacts",
        "args_template": 'with searchTerm="Test Contact"',
        "expected_keywords": ["Contacts"],
        "description": "search for contacts by name in Xero",
    },
    # ==================== BANK TRANSACTIONS ====================
    {
        "name": "list_bank_transactions",
        "args_template": "with page=1",
        "expected_keywords": ["BankTransactions"],
        "description": "list bank transactions from Xero",
    },
    {
        "name": "list_bank_transactions",
        "args_template": 'with status="AUTHORISED" page=1',
        "expected_keywords": ["BankTransactions"],
        "description": "list bank transactions filtered by AUTHORISED status",
    },
    # ==================== ACCOUNTS WITH FILTERS ====================
    {
        "name": "list_accounts",
        "args_template": 'with type="BANK"',
        "expected_keywords": ["Accounts"],
        "description": "list accounts filtered by BANK type",
    },
    # ==================== CREDIT NOTES ====================
    {
        "name": "list_credit_notes",
        "args_template": "with page=1",
        "expected_keywords": ["CreditNotes"],
        "description": "list credit notes from Xero",
    },
    # ==================== MANUAL JOURNALS ====================
    {
        "name": "list_manual_journals",
        "args_template": "with page=1",
        "expected_keywords": ["ManualJournals"],
        "description": "list manual journals from Xero",
    },
    # ==================== QUOTES ====================
    {
        "name": "list_quotes",
        "args_template": "with page=1",
        "expected_keywords": ["Quotes"],
        "description": "list quotes from Xero",
    },
    {
        "name": "list_purchase_orders",
        "args_template": "with page=1",
        "expected_keywords": ["PurchaseOrders"],
        "description": "list purchase orders from Xero",
    },
    {
        "name": "list_bank_transfers",
        "args_template": "",
        "expected_keywords": ["BankTransfers"],
        "description": "list bank transfers from Xero",
    },
    {
        "name": "list_batch_payments",
        "args_template": "",
        "expected_keywords": ["BatchPayments"],
        "description": "list batch payments from Xero",
    },
    {
        "name": "list_overpayments",
        "args_template": "with page=1",
        "expected_keywords": ["Overpayments"],
        "description": "list overpayments from Xero",
    },
    {
        "name": "list_prepayments",
        "args_template": "with page=1",
        "expected_keywords": ["Prepayments"],
        "description": "list prepayments from Xero",
    },
]


@pytest.fixture(scope="module")
def context():
    return SHARED_CONTEXT


@pytest.mark.parametrize("test_config", TOOL_TESTS, ids=get_test_id)
@pytest.mark.asyncio
async def test_xero_tool(client, context, test_config):
    return await run_tool_test(client, context, test_config)


@pytest.mark.asyncio
async def test_resources(client, context):
    response = await run_resources_test(client)

    if response and hasattr(response, "resources") and len(response.resources) > 0:
        context["first_resource_uri"] = response.resources[0].uri

    return response
