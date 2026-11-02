"""Network-free proof that the MCP customer contact contract matches the API.

Set PEAKFLO_UPLOAD_FUNCTIONS_DIR to an upload-functions checkout and
PEAKFLO_API_FUNCTIONS_DIR to an api/functions checkout, with Node dependencies
installed. Unconfigured backends are skipped; no network or credentials are used.
A contact the API rejects for a missing required field must be rejected by the
MCP tool schema for the same field, and a contact the API accepts must pass.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft7Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src" / "servers"))
from peakflo.schemas.customer import create_customer_schema, update_customer_schema

BASE = {
    "externalId": "cust-1",
    "companyName": "Acme",
    "currency": "USD",
    "status": "active",
}
CONTACT = {
    "externalId": "contact-1",
    "firstName": "Alice",
    "email": "alice@example.com",
}
CASES = {
    "no_contacts": BASE,
    "complete_contact": {**BASE, "contacts": [CONTACT]},
    **{
        missing: {
            **BASE,
            "contacts": [
                {key: value for key, value in CONTACT.items() if key != missing}
            ],
        }
        for missing in CONTACT
    },
}


@pytest.fixture(
    scope="module",
    params=[
        ("PEAKFLO_UPLOAD_FUNCTIONS_DIR", "./src/api/schemas/customer"),
        ("PEAKFLO_API_FUNCTIONS_DIR", "./src/schemas/customer"),
    ],
    ids=["upload", "api"],
)
def api_results(request):
    env_var, schema_path = request.param
    root = os.environ.get(env_var)
    if not root:
        pytest.skip(f"Set {env_var} to run this cross-repo contract proof")
    script = """
require('ts-node').register({transpileOnly: true});
const {customerInputSchema} = require(process.argv[1]);
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(Object.fromEntries(Object.entries(cases).map(([name, body]) => {
  const {error} = customerInputSchema.validate(body);
  return [name, error ? error.details.map(({path, type}) => ({path, type})) : []];
}))));
"""
    result = subprocess.run(
        ["node", "-e", script, schema_path],
        cwd=root,
        input=json.dumps(CASES),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "schema", [create_customer_schema, update_customer_schema], ids=["create", "update"]
)
@pytest.mark.parametrize("case", CASES)
def test_customer_contact_contract(schema, case, api_results):
    # tenantId belongs to MCP and is removed before forwarding to the API.
    mcp_errors = list(
        Draft7Validator(schema).iter_errors({**CASES[case], "tenantId": "tenant-1"})
    )
    if case in CONTACT:
        assert [list(e.absolute_path) for e in mcp_errors] == [["contacts", 0]]
        assert mcp_errors[0].message == f"'{case}' is a required property"
        assert api_results[case] == [
            {"path": ["contacts", 0, case], "type": "any.required"}
        ]
    else:
        assert mcp_errors == []
        assert api_results[case] == []
