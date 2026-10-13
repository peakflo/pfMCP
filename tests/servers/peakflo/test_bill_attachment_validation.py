import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jsonschema import Draft7Validator, ValidationError

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for path in (os.path.join(ROOT, "src", "servers"), os.path.join(ROOT, "src"), ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from src.servers.peakflo import main as peakflo_main  # noqa: E402
from peakflo.schemas.bill import (  # noqa: E402
    update_ap_attachment_validation_schema,
    update_bill_attachment_validation_schema,
)
from peakflo.factories.peakflo_api_factory import PeakfloApiToolFactory  # noqa: E402

PAYLOAD = {
    "billExternalId": "bill-1",
    "attachmentId": "attachment-1",
    "tenantId": "tenant-1",
    "validationDetails": {
        "status": "warning",
        "ruleStatuses": {"tax": "warning", "line-amount": "passed"},
        "errors": [],
        "warnings": [{"ruleId": "tax", "code": "MISMATCH", "message": "Check tax"}],
    },
    "suggestedFieldOverwrites": [
        {
            "id": "line-total",
            "ruleId": "line-amount",
            "target": {"scope": "lineItem", "lineIndex": 7, "fieldPath": "total"},
            "currentValue": 100,
            "suggestedValue": 125,
            "optional": True,
            "overridable": False,
        }
    ],
}


def test_tool_exposes_backend_contract():
    tool = next(
        tool
        for tool in PeakfloApiToolFactory.get_all_tools()
        if tool.name == "update_bill_attachment_validation"
    )
    input_schema = getattr(tool, "inputSchema", None) or tool.input_schema
    assert input_schema == update_bill_attachment_validation_schema
    Draft7Validator(input_schema).validate(PAYLOAD)


def test_tool_requires_object_issue_details_from_backend_contract():
    payload = {
        **PAYLOAD,
        "validationDetails": {
            "status": "warning",
            "ruleStatuses": {"tax": "warning", "line-amount": "passed"},
            "errors": [],
            "warnings": [
                {
                    "ruleId": "tax",
                    "code": "MISMATCH",
                    "message": "Check tax",
                    "details": {"capturedValue": "captured value"},
                }
            ],
        },
    }
    Draft7Validator(update_bill_attachment_validation_schema).validate(payload)
    payload["validationDetails"]["warnings"][0]["details"] = "scalar"
    with pytest.raises(ValidationError):
        Draft7Validator(update_bill_attachment_validation_schema).validate(payload)


def test_tool_can_mark_a_rule_passed_to_clear_its_prior_result():
    payload = {
        "billExternalId": "bill-1",
        "attachmentId": "attachment-1",
        "validationDetails": {
            "status": "passed",
            "ruleStatuses": {"tax": "passed"},
            "errors": [],
            "warnings": [],
        },
        "suggestedFieldOverwrites": [],
    }
    Draft7Validator(update_bill_attachment_validation_schema).validate(payload)
    del payload["validationDetails"]["ruleStatuses"]
    with pytest.raises(ValidationError):
        Draft7Validator(update_bill_attachment_validation_schema).validate(payload)


def test_tool_accepts_generic_success_and_skipped_checks_with_evidence():
    payload = {
        "billExternalId": "bill-1",
        "attachmentId": "attachment-1",
        "validationDetails": {
            "status": "passed",
            "ruleStatuses": {"bir": "passed"},
            "checks": [
                {
                    "ruleId": "bir",
                    "code": "TIN",
                    "message": "TIN matches",
                    "outcome": "success",
                    "details": {"extractedTin": "123"},
                },
                {
                    "ruleId": "bir",
                    "code": "LOW_VALUE",
                    "message": "Below threshold",
                    "outcome": "skipped",
                    "details": {"threshold": 500},
                },
            ],
        },
    }
    Draft7Validator(update_bill_attachment_validation_schema).validate(payload)
    payload["validationDetails"]["checks"][0]["details"] = "scalar"
    with pytest.raises(ValidationError):
        Draft7Validator(update_bill_attachment_validation_schema).validate(payload)


@pytest.mark.parametrize(
    "invalid_target",
    [
        {"scope": "lineItem", "id": "line-id", "fieldPath": "total"},
        {"scope": "lineItem", "lineIndex": 0, "fieldPath": "total"},
        {"scope": "lineItem", "lineIndex": 1.5, "fieldPath": "total"},
    ],
)
def test_tool_rejects_non_contract_line_identity(invalid_target):
    payload = {
        **PAYLOAD,
        "suggestedFieldOverwrites": [
            {**PAYLOAD["suggestedFieldOverwrites"][0], "target": invalid_target}
        ],
    }
    with pytest.raises(ValidationError):
        Draft7Validator(update_bill_attachment_validation_schema).validate(payload)


def test_tool_requires_current_value():
    suggestion = {**PAYLOAD["suggestedFieldOverwrites"][0]}
    suggestion.pop("currentValue")
    with pytest.raises(ValidationError):
        Draft7Validator(update_bill_attachment_validation_schema).validate(
            {**PAYLOAD, "suggestedFieldOverwrites": [suggestion]}
        )


def test_generic_tool_exposes_ap_types_and_tr_line_suggestions():
    tool = next(
        item
        for item in PeakfloApiToolFactory.get_all_tools()
        if item.name == "update_ap_attachment_validation"
    )
    schema = getattr(tool, "inputSchema", None) or tool.input_schema
    assert schema == update_ap_attachment_validation_schema
    for object_type in (
        "bill",
        "po",
        "tr",
        "pq",
        "pr",
        "rn",
        "billPayment",
        "apCreditNote",
    ):
        payload = {
            "objectType": object_type,
            "objectId": "507f1f77bcf86cd799439011",
            "attachmentId": "attachment-1",
            "validationDetails": PAYLOAD["validationDetails"],
        }
        Draft7Validator(schema).validate(payload)
        Draft7Validator(schema).validate(
            {**payload, "suggestedFieldOverwrites": PAYLOAD["suggestedFieldOverwrites"]}
        )

    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(
            {
                "objectType": "bill",
                "objectId": "507f1f77bcf86cd799439011",
                "attachmentId": "attachment-1",
                "validationDetails": PAYLOAD["validationDetails"],
                "suggestedFieldOverwrites": [
                    {
                        **PAYLOAD["suggestedFieldOverwrites"][0],
                        "target": {"scope": "bill", "fieldPath": "totalAmount"},
                    }
                ],
            }
        )

    tr_payload = {
        "objectType": "tr",
        "objectId": "507f1f77bcf86cd799439011",
        "lineIndex": 7,
        "attachmentId": "voucher-1",
        "validationDetails": PAYLOAD["validationDetails"],
        "suggestedFieldOverwrites": PAYLOAD["suggestedFieldOverwrites"],
    }
    Draft7Validator(schema).validate(tr_payload)
    for invalid in (
        {**tr_payload, "lineIndex": 0},
        {**tr_payload, "objectType": "po"},
    ):
        with pytest.raises(ValidationError):
            Draft7Validator(schema).validate(invalid)


@pytest.mark.asyncio
async def test_generic_tool_routes_issue_update_without_tenant_hint():
    response = MagicMock()
    response.status_code = 200
    response.content = b"{}"
    response.text = "{}"
    response.json.return_value = {"attachmentId": "attachment-1"}
    client = MagicMock()
    client.request = AsyncMock(return_value=response)
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=client)
    client_cm.__aexit__ = AsyncMock(return_value=False)
    arguments = {
        "objectType": "rn",
        "objectId": "507f1f77bcf86cd799439011",
        "attachmentId": "attachment?1",
        "tenantId": "tenant-1",
        "validationDetails": PAYLOAD["validationDetails"],
    }
    with patch.object(
        peakflo_main, "PEAKFLO_V1_BASE_URL", "https://api.example.test/v1"
    ), patch.object(peakflo_main.httpx, "AsyncClient", return_value=client_cm):
        result = await peakflo_main.make_peakflo_request(
            "update_ap_attachment_validation", arguments, "token"
        )

    assert result["_status_code"] == 200
    method, url = client.request.call_args.args[:2]
    assert method == "PUT"
    assert url == (
        "https://api.example.test/v1/ap/rn/507f1f77bcf86cd799439011/"
        "attachments/attachment%3F1/validation"
    )
    assert client.request.call_args.kwargs["json"] == {
        "validationDetails": PAYLOAD["validationDetails"],
    }


@pytest.mark.asyncio
async def test_generic_tool_routes_tr_line_voucher_by_stable_index():
    response = MagicMock()
    response.status_code = 200
    response.content = b"{}"
    response.text = "{}"
    response.json.return_value = {"attachmentId": "voucher-1"}
    client = MagicMock()
    client.request = AsyncMock(return_value=response)
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=client)
    client_cm.__aexit__ = AsyncMock(return_value=False)
    arguments = {
        "objectType": "tr",
        "objectId": "507f1f77bcf86cd799439011",
        "lineIndex": 7,
        "attachmentId": "voucher-1",
        "validationDetails": PAYLOAD["validationDetails"],
        "suggestedFieldOverwrites": PAYLOAD["suggestedFieldOverwrites"],
    }
    with patch.object(
        peakflo_main, "PEAKFLO_V1_BASE_URL", "https://api.example.test/v1"
    ), patch.object(peakflo_main.httpx, "AsyncClient", return_value=client_cm):
        await peakflo_main.make_peakflo_request(
            "update_ap_attachment_validation", arguments, "token"
        )
    method, url = client.request.call_args.args[:2]
    assert method == "PUT"
    assert url == (
        "https://api.example.test/v1/ap/tr/507f1f77bcf86cd799439011/"
        "lines/7/attachments/voucher-1/validation"
    )
    assert "lineIndex" not in client.request.call_args.kwargs["json"]


@pytest.mark.asyncio
async def test_tool_routes_contract_without_tenant_hint_or_path_injection():
    response = MagicMock()
    response.status_code = 200
    response.content = b"{}"
    response.text = "{}"
    response.json.return_value = {"attachmentId": "attachment-1"}
    client = MagicMock()
    client.request = AsyncMock(return_value=response)
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=client)
    client_cm.__aexit__ = AsyncMock(return_value=False)
    arguments = {
        **PAYLOAD,
        "billExternalId": "bill/1",
        "attachmentId": "attachment?1",
    }
    with patch.object(
        peakflo_main, "PEAKFLO_V1_BASE_URL", "https://api.example.test/v1"
    ), patch.object(peakflo_main.httpx, "AsyncClient", return_value=client_cm):
        result = await peakflo_main.make_peakflo_request(
            "update_bill_attachment_validation", arguments, "token"
        )

    assert result["_status_code"] == 200
    method, url = client.request.call_args.args[:2]
    assert method == "PUT"
    assert url == (
        "https://api.example.test/v1/bill/bill%2F1/"
        "attachments/attachment%3F1/validation"
    )
    assert client.request.call_args.kwargs["json"] == {
        "validationDetails": PAYLOAD["validationDetails"],
        "suggestedFieldOverwrites": PAYLOAD["suggestedFieldOverwrites"],
    }
    assert arguments["tenantId"] == "tenant-1"
