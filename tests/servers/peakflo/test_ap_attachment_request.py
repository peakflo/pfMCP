"""
Offline handler-level tests for the bill / expense-report / bill-payment
attach tools in the Peakflo server (make_peakflo_request).

Mocks the file download and the Peakflo HTTP call, so no network or
credentials are needed. Verifies the URL routing, the forwarded payload
shape (matches api ApAttachmentInput), fileType coercion, customFieldType
normalization and the customFieldFile guard.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for _p in (os.path.join(_ROOT, "src", "servers"), os.path.join(_ROOT, "src"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.servers.peakflo import main as peakflo_main  # noqa: E402

BASE = "https://api.example.test/v1"

CF_DETAILS = {
    "customFieldId": "cf-1",
    "customFieldNumber": "10",
    "customFieldName": "Journal Entry",
    "customFieldType": "MUltifile",
}


def _response(status=200, body=None):
    resp = MagicMock()
    resp.status_code = status
    resp.content = b"{}"
    resp.text = "{}"
    resp.json.return_value = body or {"id": "att-1"}
    return resp


async def _call(name, arguments):
    client = MagicMock()
    client.request = AsyncMock(return_value=_response())
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=client)
    client_cm.__aexit__ = AsyncMock(return_value=False)
    with patch.object(peakflo_main, "PEAKFLO_V1_BASE_URL", BASE), patch.object(
        peakflo_main,
        "_download_and_encode",
        AsyncMock(return_value=("aGVsbG8=", 5)),
    ), patch.object(peakflo_main.httpx, "AsyncClient", return_value=client_cm):
        await peakflo_main.make_peakflo_request(name, arguments, "token")
    method, url = client.request.call_args.args[:2]
    return method, url, client.request.call_args.kwargs["json"]


def _args(id_field, **extra):
    args = {
        id_field: "doc-1",
        "tenantId": "tenant-1",
        "id": "att-1",
        "name": "file.pdf",
        "contentType": "application/pdf",
        "fileType": "invoice",
        "file_url": "https://example.com/signed.pdf",
    }
    args.update(extra)
    return args


@pytest.mark.parametrize(
    "tool, id_field, path",
    [
        ("add_bill_attachment", "billExternalId", "/bill/doc-1/attachments"),
        (
            "add_expense_report_attachment",
            "externalId",
            "/expense-report/doc-1/attachments",
        ),
        (
            "add_bill_payment_attachment",
            "externalId",
            "/bill-payment/doc-1/attachments",
        ),
    ],
)
async def test_routes_and_forwards_cf_payload(tool, id_field, path):
    caller_details = dict(CF_DETAILS)
    method, url, body = await _call(
        tool, _args(id_field, customFieldDetails=caller_details)
    )
    assert method == "PUT"
    assert url == BASE + path
    # Only api ApAttachmentInput keys are forwarded.
    assert set(body) == {
        "id",
        "name",
        "contentType",
        "fileType",
        "fileSize",
        "base64",
        "customFieldDetails",
    }
    assert body["fileType"] == "customFieldFile"
    assert body["fileSize"] == 5
    assert body["base64"] == "data:application/pdf;base64,aGVsbG8="
    assert body["customFieldDetails"]["customFieldType"] == "multiFile"
    # The caller's nested dict is not mutated.
    assert caller_details["customFieldType"] == "MUltifile"


async def test_single_file_bill_attach_unchanged():
    _, url, body = await _call(
        "add_bill_attachment",
        _args("billExternalId", file_url=None, base64="aGVsbG8=", fileSize=5),
    )
    assert url == BASE + "/bill/doc-1/attachments"
    assert body["fileType"] == "invoice"
    assert "customFieldDetails" not in body
    assert body["base64"] == "data:application/pdf;base64,aGVsbG8="


async def test_custom_field_file_without_details_is_rejected():
    with pytest.raises(ValueError, match="customFieldDetails is required"):
        await _call(
            "add_bill_payment_attachment",
            _args("externalId", fileType="customFieldFile"),
        )


async def test_direct_base64_size_uses_decoded_length():
    # Caller under-declares fileSize; the real decoded size exceeds 10MB.
    big = peakflo_main.base64.b64encode(
        b"x" * (peakflo_main.MAX_ATTACHMENT_BYTES + 1)
    ).decode()
    with pytest.raises(ValueError, match="exceeds"):
        await _call(
            "add_bill_attachment",
            _args("billExternalId", file_url=None, base64=big, fileSize=5),
        )


async def test_direct_base64_invalid_content_is_rejected():
    with pytest.raises(ValueError, match="Invalid base64"):
        await _call(
            "add_bill_attachment",
            _args("billExternalId", file_url=None, base64="abc", fileSize=3),
        )


@pytest.mark.parametrize(
    "tool, id_field",
    [
        ("add_bill_attachment", "billExternalId"),
        ("add_expense_report_attachment", "externalId"),
        ("add_bill_payment_attachment", "externalId"),
    ],
)
async def test_number_only_details_forwarded_unchanged(tool, id_field):
    _, _, body = await _call(
        tool, _args(id_field, customFieldDetails={"customFieldNumber": "10"})
    )
    # No other keys are invented (customFieldType is omitted, not defaulted).
    assert body["customFieldDetails"] == {"customFieldNumber": "10"}
    assert body["fileType"] == "customFieldFile"


@pytest.mark.parametrize(
    "details",
    [
        {},
        {"customFieldId": "cf-1", "customFieldType": "multiFile"},
        {"customFieldNumber": ""},
        {"customFieldNumber": "   "},
        {"customFieldNumber": None},
        {"customFieldNumber": 10},
    ],
)
async def test_missing_custom_field_number_is_rejected(details):
    with pytest.raises(ValueError, match="customFieldNumber is required"):
        await _call(
            "add_bill_attachment",
            _args("billExternalId", customFieldDetails=details),
        )


async def test_empty_optional_values_are_dropped():
    caller_details = {
        "customFieldNumber": "10",
        "customFieldId": "",
        "customFieldName": None,
        "customFieldType": "  ",
        "customFieldSourceId": "",
    }
    _, _, body = await _call(
        "add_expense_report_attachment",
        _args("externalId", customFieldDetails=caller_details),
    )
    assert body["customFieldDetails"] == {"customFieldNumber": "10"}
    assert body["fileType"] == "customFieldFile"
    # Caller input is not mutated.
    assert caller_details["customFieldId"] == ""


async def test_full_details_payload_still_forwarded():
    full = dict(CF_DETAILS, customFieldSourceId="src-1")
    _, _, body = await _call(
        "add_bill_payment_attachment",
        _args("externalId", customFieldDetails=full),
    )
    assert body["customFieldDetails"] == {
        "customFieldNumber": "10",
        "customFieldId": "cf-1",
        "customFieldName": "Journal Entry",
        "customFieldType": "multiFile",
        "customFieldSourceId": "src-1",
    }
    assert body["fileType"] == "customFieldFile"
