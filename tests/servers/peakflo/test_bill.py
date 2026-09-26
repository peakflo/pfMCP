"""
Network-free unit tests for the Peakflo add_bill_attachment tool schema.

Covers the schema contract (required fields, file-type enum,
file-source exclusivity) without requiring MCP or live credentials.
"""

import sys
import os

import pytest
from jsonschema import Draft7Validator, ValidationError

_SERVERS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "src", "servers"
)
sys.path.insert(0, _SERVERS_PATH)

from peakflo.schemas.bill import (
    add_bill_attachment_schema,
    add_expense_report_attachment_schema,
    add_bill_payment_attachment_schema,
    normalize_multifile_custom_field_type,
)
from peakflo.schemas.purchase_order import ap_attachment_file_types, to_data_uri


def _valid_attachment():
    return {
        "billExternalId": "bill-1",
        "tenantId": "tenant-1",
        "id": "att-1",
        "name": "ENOVA-ACCLIVIS-170326-1.pdf",
        "contentType": "application/pdf",
        "fileType": "invoice",
        "file_url": "https://example.com/signed.pdf",
    }


def test_attachment_schema_required_fields_match_api_contract():
    required = set(add_bill_attachment_schema["required"])
    # URL-routing + body-initial fields handled by the MCP server.
    assert {
        "billExternalId",
        "id",
        "name",
        "contentType",
        "fileType",
    } <= required
    assert add_bill_attachment_schema["additionalProperties"] is False


def test_attachment_schema_accepts_file_url_or_base64():
    schema = add_bill_attachment_schema

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
    enum_values = add_bill_attachment_schema["properties"]["fileType"]["enum"]
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
        Draft7Validator(add_bill_attachment_schema).validate(payload)


def test_attachment_rejects_invalid_file_type():
    payload = _valid_attachment()
    payload["fileType"] = "garbage"
    with pytest.raises(ValidationError):
        Draft7Validator(add_bill_attachment_schema).validate(payload)


def test_attachment_requires_file_source():
    schema = add_bill_attachment_schema

    # Neither file_url nor base64 supplied -> invalid (mirrors the API
    # contract that base64 + fileSize are always required in the body).
    payload = _valid_attachment()
    payload.pop("file_url")
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(payload)


def test_attachment_base64_requires_file_size():
    schema = add_bill_attachment_schema

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
        Draft7Validator(add_bill_attachment_schema).validate(payload)


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
            Draft7Validator(add_bill_attachment_schema).validate(payload)


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
        Draft7Validator(add_bill_attachment_schema).validate(payload)


def test_attachment_accepts_custom_field_details():
    payload = _valid_attachment()
    payload["fileType"] = "customFieldFile"
    payload["customFieldDetails"] = {
        "customFieldId": "cf-1",
        "customFieldNumber": "10",
        "customFieldName": "Journal Entry",
        "customFieldType": "multiFile",
    }
    Draft7Validator(add_bill_attachment_schema).validate(payload)


def test_attachment_rejects_incomplete_custom_field_details():
    payload = _valid_attachment()
    payload["customFieldDetails"] = {
        "customFieldId": "cf-1",
        # missing required number / name / type
    }
    with pytest.raises(ValidationError):
        Draft7Validator(add_bill_attachment_schema).validate(payload)


def test_expense_report_and_payment_schemas_share_cf_contract():
    for schema, id_field in (
        (add_expense_report_attachment_schema, "externalId"),
        (add_bill_payment_attachment_schema, "externalId"),
    ):
        assert id_field in schema["required"]
        assert "customFieldDetails" in schema["properties"]
        assert schema["additionalProperties"] is False
        payload = {
            id_field: "doc-1",
            "tenantId": "tenant-1",
            "id": "att-1",
            "name": "file.xlsx",
            "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "fileType": "customFieldFile",
            "file_url": "https://example.com/signed.xlsx",
            "customFieldDetails": {
                "customFieldId": "cf-1",
                "customFieldNumber": "10",
                "customFieldName": "DV",
                "customFieldType": "multiFile",
            },
        }
        Draft7Validator(schema).validate(payload)


def test_normalize_multifile_custom_field_type_returns_canonical_value():
    # Canonical CustomFieldType.MultiFile value per the real peakflo-schema
    # package; the api repo's mocked "MUltifile" value and other casing
    # variants are normalized so the API persists a value that strict
    # downstream consumers recognize.
    assert normalize_multifile_custom_field_type("multiFile") == "multiFile"
    assert normalize_multifile_custom_field_type("MUltifile") == "multiFile"
    assert normalize_multifile_custom_field_type("MultiFile") == "multiFile"
    assert normalize_multifile_custom_field_type("MULTIFILE") == "multiFile"
    assert normalize_multifile_custom_field_type(" multifile ") == "multiFile"


def test_normalize_multifile_custom_field_type_passes_others_through():
    assert normalize_multifile_custom_field_type("") == ""
    assert normalize_multifile_custom_field_type("Text") == "Text"
    assert normalize_multifile_custom_field_type("not-a-multifile") == "not-a-multifile"
