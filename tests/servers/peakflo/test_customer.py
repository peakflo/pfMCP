"""
Network-free unit tests for the Peakflo customer tools
(create_customer, update_customer).

Covers the schema contract (required fields, payment terms bounds,
shared custom-field schema reuse) and tool registration without requiring
MCP or live credentials.
"""

import sys
import os

import pytest
from jsonschema import Draft7Validator, ValidationError

_SERVERS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "src", "servers"
)
sys.path.insert(0, _SERVERS_PATH)

from peakflo.schemas.customer import (
    create_customer_schema,
    update_customer_schema,
)
from peakflo.schemas.common import custom_field_schema

_BASE = {
    "externalId": "cust-1",
    "tenantId": "tenant-1",
    "companyName": "Acme",
    "currency": "USD",
    "status": "active",
}


def _validate(schema, **overrides):
    Draft7Validator(schema).validate({**_BASE, **overrides})


@pytest.mark.parametrize("schema", [create_customer_schema, update_customer_schema])
def test_required_fields_match_api_contract(schema):
    # API customerInputSchema requires externalId, companyName, currency, status;
    # tenantId is popped before the request body is sent.
    assert set(schema["required"]) == {
        "externalId",
        "companyName",
        "currency",
        "status",
        "tenantId",
    }


@pytest.mark.parametrize("schema", [create_customer_schema, update_customer_schema])
def test_minimal_payload_is_valid(schema):
    _validate(schema)


@pytest.mark.parametrize("missing", ["externalId", "companyName", "currency", "status"])
def test_missing_required_field_is_rejected(missing):
    payload = {k: v for k, v in _BASE.items() if k != missing}
    with pytest.raises(ValidationError):
        Draft7Validator(create_customer_schema).validate(payload)


def test_status_must_be_a_known_value():
    _validate(create_customer_schema, status="archived")
    with pytest.raises(ValidationError):
        _validate(create_customer_schema, status="paused")


@pytest.mark.parametrize("value", [0, 30, 3650])
def test_payment_terms_accepts_whole_days_in_range(value):
    _validate(create_customer_schema, paymentTerms=value)


@pytest.mark.parametrize("value", [-1, 14.5, "14", 3651])
def test_payment_terms_rejects_out_of_contract_values(value):
    with pytest.raises(ValidationError):
        _validate(create_customer_schema, paymentTerms=value)


def test_custom_field_reuses_shared_schema():
    assert create_customer_schema["properties"]["customField"] is custom_field_schema
    assert update_customer_schema["properties"]["customField"] is custom_field_schema
    _validate(
        create_customer_schema,
        customField=[{"customFieldNumber": "cf1", "value": "Gold"}],
    )
    with pytest.raises(ValidationError):
        _validate(create_customer_schema, customField=[{"value": "Gold"}])


def test_tools_are_registered():
    # the tools module imports via the `servers.` package root, so add `src` too
    sys.path.insert(0, os.path.join(_SERVERS_PATH, ".."))
    from servers.peakflo.tools.peakflo_api import customer_tools
    from servers.peakflo.factories.peakflo_api_factory import PeakfloApiToolFactory

    names = {tool.name for tool in customer_tools}
    assert names == {"create_customer", "update_customer"}
    by_name = {tool.name: tool for tool in customer_tools}
    # same module loaded under a different package root, so compare by value
    assert by_name["create_customer"].input_schema == create_customer_schema
    assert by_name["update_customer"].input_schema == update_customer_schema
    all_names = {tool.name for tool in PeakfloApiToolFactory.get_all_tools()}
    assert names <= all_names
