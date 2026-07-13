import pytest
from tests.utils.test_tools import get_test_id, run_tool_test

# Shared context dictionary at module level
SHARED_CONTEXT = {}

# Live integration tests. These exercise the NetSuite server against a real
# connection (env-var TBA credentials or a Peakflo-brokered connection) and are
# skipped by the harness when no connection is configured.
TOOL_TESTS = [
    {
        "name": "execute_suiteql",
        "args_template": "with query='SELECT id, entityid FROM vendor WHERE isinactive = \\'F\\' FETCH FIRST 1 ROWS ONLY'",
        "expected_keywords": ["items"],
        "description": "run a read-only SuiteQL query against NetSuite",
    },
    {
        "name": "search_vendor_by_name",
        "args_template": "with vendor_name='a'",
        "expected_keywords": ["items"],
        "description": "search vendors by partial name via SuiteQL",
    },
]


@pytest.fixture(scope="module")
def context():
    return SHARED_CONTEXT


@pytest.mark.parametrize("test_config", TOOL_TESTS, ids=get_test_id)
@pytest.mark.asyncio
async def test_netsuite_tool(client, context, test_config):
    return await run_tool_test(client, context, test_config)
