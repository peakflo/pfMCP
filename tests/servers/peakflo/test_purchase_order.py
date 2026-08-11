"""
Network-free unit tests for the Peakflo purchase-order tools
(update_purchase_order, add_purchase_order_attachment).

Covers the schema contract (required fields, replace semantics, shared
custom-field schema reuse, file-source exclusivity) without requiring MCP
or live credentials.
"""

import sys
import os

import pytest
from jsonschema import Draft7Validator, ValidationError

_SERVERS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "src", "servers"
)
sys.path.insert(0, _SERVERS_PATH)

from peakflo.schemas.purchase_order import (
    update_purchase_order_schema,
    add_purchase_order_attachment_schema,
    ap_attachment_file_types,
    to_data_uri,
    po_item_schema,
    wht_schema,
    tax_schema,
    discount_schema,
)
from peakflo.schemas.common import custom_field_schema


def _validate_item(item):
    payload = {
        "externalId": "po-1",
        "tenantId": "tenant-1",
        "POAmount": 10,
        "currency": "USD",
        "issueDate": "2026-08-01",
        "dueDate": "2026-08-31",
        "status": "draft",
        "items": [item],
        "PONumber": "PO-1",
        "vendorId": "vendor-1",
    }
    Draft7Validator(update_purchase_order_schema).validate(payload)


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

    # Default API configuration also requires externalId.
    assert item_props["discounts"]["items"] == discount_schema
    assert set(discount_schema["required"]) == {
        "externalId",
        "name",
        "amount",
        "amountType",
    }


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


def test_discounts_require_external_id():
    with pytest.raises(ValidationError):
        _validate_item(
            {
                "sourceId": "line-1",
                "name": "Line item",
                "quantity": 1,
                "unitPrice": 10,
                "taxes": [],
                "discounts": [
                    {
                        "name": "Promo",
                        "amount": 1,
                        "amountType": "Flat",
                    }
                ],
            }
        )


def test_nested_discount_duration_remains_supported():
    _validate_item(
        {
            "sourceId": "line-1",
            "name": "Line item",
            "quantity": 1,
            "unitPrice": 10,
            "taxes": [],
            "discounts": [
                {
                    "externalId": "discount-1",
                    "name": "Promo",
                    "amount": 1,
                    "amountType": "Flat",
                    "duration": {
                        "duration": "First N days",
                        "durationNumber": 3,
                    },
                }
            ],
        }
    )


def _valid_attachment():
    return {
        "poExternalId": "po-1",
        "tenantId": "tenant-1",
        "id": "att-1",
        "name": "ENOVA-ACCLIVIS-170326-1.pdf",
        "contentType": "application/pdf",
        "fileType": "invoice",
        "file_url": "https://example.com/signed.pdf",
    }


def test_attachment_schema_required_fields_match_api_contract():
    required = set(add_purchase_order_attachment_schema["required"])
    # URL-routing + body-initial fields handled by the MCP server.
    assert {
        "poExternalId",
        "id",
        "name",
        "contentType",
        "fileType",
    } <= required
    assert add_purchase_order_attachment_schema["additionalProperties"] is False


def test_attachment_schema_accepts_file_url_or_base64():
    schema = add_purchase_order_attachment_schema

    # Nothing beyond the initial required set is mandated, so a file_url-only
    # payload is valid and the server derives base64/fileSize at runtime.
    Draft7Validator(schema).validate(_valid_attachment())

    # base64 path is accepted too (fileSize left to the caller/server).
    payload = _valid_attachment()
    payload.pop("file_url")
    payload["base64"] = "aGVsbG8="
    payload["fileSize"] = 5
    Draft7Validator(schema).validate(payload)


def test_attachment_file_type_enum_mirrors_ap_attachment_type():
    enum_values = add_purchase_order_attachment_schema["properties"]["fileType"]["enum"]
    # Mirrors ApAttachmentType in peakflo-schema/src/schemas/ap/constants.ts
    assert enum_values == [
        "transaction",
        "statement",
        "cabinet",
        "invoice",
        "other",
        "paymentProof",
        "incomingFile",
        "customFieldFile",
        "fakturPajak",
        "payerReceipt",
        "whtFile",
        "eStampFile",
        "shippingList",
        "dscSigned",
    ]
    assert enum_values == ap_attachment_file_types


def test_attachment_rejects_unknown_keys():
    payload = _valid_attachment()
    payload["unknownKey"] = "nope"
    with pytest.raises(ValidationError):
        Draft7Validator(add_purchase_order_attachment_schema).validate(payload)


def test_attachment_rejects_invalid_file_type():
    payload = _valid_attachment()
    payload["fileType"] = "garbage"
    with pytest.raises(ValidationError):
        Draft7Validator(add_purchase_order_attachment_schema).validate(payload)


def test_attachment_requires_file_source():
    schema = add_purchase_order_attachment_schema

    # Neither file_url nor base64 supplied -> invalid (mirrors the API
    # contract that base64 + fileSize are always required in the body).
    payload = _valid_attachment()
    payload.pop("file_url")
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(payload)


def test_attachment_base64_requires_file_size():
    schema = add_purchase_order_attachment_schema

    # base64 without fileSize -> invalid; the API body always requires both.
    payload = _valid_attachment()
    payload.pop("file_url")
    payload["base64"] = "aGVsbG8="
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(payload)


def test_attachment_rejects_file_url_and_base64_together():
    # Providing both file_url and base64 is ambiguous -> rejected by oneOf.
    payload = _valid_attachment()
    payload["base64"] = "aGVsbG8="
    payload["fileSize"] = 5
    with pytest.raises(ValidationError):
        Draft7Validator(add_purchase_order_attachment_schema).validate(payload)


def test_to_data_uri_wraps_raw_base64():
    assert to_data_uri("aGVsbG8=", "application/pdf") == (
        "data:application/pdf;base64,aGVsbG8="
    )


def test_to_data_uri_leaves_existing_data_uri_untouched():
    data_uri = "data:application/pdf;base64,aGVsbG8="
    assert to_data_uri(data_uri, "application/pdf") == data_uri


def test_attachment_rejects_api_ignored_fields():
    # includeWhenSent / dateCreated are ignored by the downstream API
    # (api/functions/src/utils/attachment.ts hardcodes includeWhenSent=false
    # and dateCreated=now), so they must not be advertised or accepted.
    for field in ("includeWhenSent", "dateCreated"):
        payload = _valid_attachment()
        payload[field] = True if field == "includeWhenSent" else "2026-08-11T00:00:00Z"
        with pytest.raises(ValidationError):
            Draft7Validator(add_purchase_order_attachment_schema).validate(payload)


def test_attachment_rejects_file_url_and_base64_without_file_size():
    # file_url + base64 together, with fileSize omitted, used to slip
    # through: the file_url branch of oneOf matched (only requires
    # file_url) while the base64 branch failed (missing fileSize), so
    # oneOf saw exactly one match and passed. The "not" constraints on
    # each branch make the two sources mutually exclusive regardless of
    # which other fields are present.
    payload = _valid_attachment()
    payload["base64"] = "aGVsbG8="
    with pytest.raises(ValidationError):
        Draft7Validator(add_purchase_order_attachment_schema).validate(payload)
