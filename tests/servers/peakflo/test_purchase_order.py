"""
Network-free unit tests for the Peakflo update_purchase_order tool.

Covers the schema contract (required fields, replace semantics, shared
custom-field schema reuse) without requiring MCP or live credentials.
"""

import sys
import os

_SERVERS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "src", "servers"
)
sys.path.insert(0, _SERVERS_PATH)

from peakflo.schemas.purchase_order import (
    update_purchase_order_schema,
    po_item_schema,
    wht_schema,
    tax_schema,
    discount_schema,
)
from peakflo.schemas.common import custom_field_schema


def test_schema_required_fields_match_api_contract():
    required = set(update_purchase_order_schema["required"])
    # API vendorPurchaseOrderSchema required set (minus tenantId, which is
    # popped before the request body is sent).
    expected = {
        "externalId",
        "POAmount",
        "currency",
        "issueDate",
        "dueDate",
        "status",
        "items",
        "PONumber",
        "vendorId",
        "tenantId",
    }
    assert expected <= required
    assert "additionalProperties" not in update_purchase_order_schema or (
        update_purchase_order_schema["additionalProperties"] is False
    )


def test_item_schema_required_fields():
    required = set(po_item_schema["required"])
    assert {"sourceId", "name", "quantity", "unitPrice"} <= required


def test_custom_field_reuses_shared_schema():
    # PO-level customField must reuse the shared common.custom_field_schema items
    po_cf = update_purchase_order_schema["properties"]["customField"]
    assert po_cf["items"] == custom_field_schema["items"]

    # line-item-level customField must also reuse it
    line_cf = po_item_schema["properties"]["customField"]
    assert line_cf["items"] == custom_field_schema["items"]


def test_custom_field_required_keys():
    items = update_purchase_order_schema["properties"]["customField"]["items"]
    assert set(items.get("required", [])) >= {"customFieldNumber", "value"}


def test_status_restricted_to_api_po_status_values():
    status_enum = update_purchase_order_schema["properties"]["status"]["enum"]
    # Mirrors POStatus in peakflo-schema/src/schemas/ap/constants.ts
    assert status_enum == [
        "draft",
        "submitted",
        "approved",
        "billed",
        "deleted",
        "cancelled",
        "closed",
    ]


def test_items_requires_at_least_one():
    # Mirrors vendorPurchaseOrderSchema items.min(1)
    assert update_purchase_order_schema["properties"]["items"]["minItems"] == 1


def test_nested_financial_schemas_mirror_api():
    item_props = po_item_schema["properties"]

    # WHT mirrors whtInputSchema (id/code/displayName/amount, code required)
    assert item_props["wht"] == wht_schema
    assert set(wht_schema["required"]) == {"code", "displayName", "amount"}

    # Taxes mirror taxInputSchema (name/amount/amountType required)
    assert item_props["taxes"]["items"] == tax_schema
    assert set(tax_schema["required"]) == {"name", "amount", "amountType"}

    # Discounts mirror discountInputSchema (name/amount/amountType required)
    assert item_props["discounts"]["items"] == discount_schema
    assert set(discount_schema["required"]) == {"name", "amount", "amountType"}


def test_tax_amount_type_and_category_enums():
    assert tax_schema["properties"]["amountType"]["enum"] == [
        "Flat",
        "Fixed",
        "Percentage",
    ]
    assert tax_schema["properties"]["category"]["enum"] == [
        "VAT",
        "StampDuty",
        "Other",
    ]
