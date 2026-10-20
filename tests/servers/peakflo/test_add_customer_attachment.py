"""
Offline tests for add_customer_attachment.

The tool calls PUT /v1/customers/:customerExternalId/attachments with the same
Peakflo API key as create_customer. The body matches the invoice attachment
route: raw base64 in `data`.
"""

import base64
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

from jsonschema import Draft7Validator, ValidationError
import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for _p in (os.path.join(_ROOT, "src", "servers"), os.path.join(_ROOT, "src"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.servers.peakflo import main as peakflo_main  # noqa: E402
from peakflo.schemas.customer import add_customer_attachment_schema  # noqa: E402
from peakflo.factories.peakflo_api_factory import PeakfloApiToolFactory  # noqa: E402

BASE = "https://api.example.test/v1"


def _response(status=201, body=None):
    resp = MagicMock()
    resp.status_code = status
    resp.content = b"{}"
    resp.text = "{}"
    resp.json.return_value = body or {
        "externalId": "letter-1",
        "name": "274.pdf",
        "fileSize": 5,
    }
    return resp


def _args(**extra):
    args = {
        "tenantId": "0demoFileSG",
        "customerExternalId": "cust-ext",
        "externalId": "letter-1",
        "name": "274.pdf",
        "contentType": "application/pdf",
        "file_url": "https://storage.example/signed.pdf",
    }
    args.update(extra)
    return args


async def _call(arguments, download=None):
    client = MagicMock()
    client.request = AsyncMock(return_value=_response())
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=client)
    client_cm.__aexit__ = AsyncMock(return_value=False)
    with patch.object(peakflo_main, "PEAKFLO_V1_BASE_URL", BASE), patch.object(
        peakflo_main,
        "_download_and_encode",
        download or AsyncMock(return_value=("aGVsbG8=", 5)),
    ), patch.object(peakflo_main.httpx, "AsyncClient", return_value=client_cm):
        result = await peakflo_main.make_peakflo_request(
            "add_customer_attachment", arguments, "peakflo-api-key"
        )
    return result, client


def test_tool_is_registered():
    names = [tool.name for tool in PeakfloApiToolFactory.get_all_tools()]
    assert "add_customer_attachment" in names


def test_schema_uses_the_customer_external_id():
    Draft7Validator(add_customer_attachment_schema).validate(_args())
    required = add_customer_attachment_schema["required"]
    assert "customerExternalId" in required
    assert "externalId" in required
    assert "customerId" not in add_customer_attachment_schema["properties"]
    Draft7Validator(add_customer_attachment_schema).validate(
        _args(fileType="transaction")
    )
    with pytest.raises(ValidationError):
        Draft7Validator(add_customer_attachment_schema).validate(
            _args(fileType="statement")
        )


async def test_puts_raw_base64_on_the_customer_attachment_route():
    result, client = await _call(_args(fileType="other", dateCreated="2026-01-02"))

    assert result["_status_code"] == 201
    assert result["message"] == "Customer attachment added successfully"
    client.request.assert_awaited_once()
    method, url = client.request.call_args.args[:2]
    body = client.request.call_args.kwargs["json"]
    headers = client.request.call_args.kwargs["headers"]
    assert method == "PUT"
    assert url == BASE + "/customers/cust-ext/attachments"
    assert body == {
        "externalId": "letter-1",
        "name": "274.pdf",
        "contentType": "application/pdf",
        "data": "aGVsbG8=",
        "fileType": "other",
        "dateCreated": "2026-01-02",
    }
    assert headers["Authorization"] == "Bearer peakflo-api-key"
    assert "tenantId" not in body
    assert "file_url" not in body
    assert "base64" not in body
    assert "path" not in body
    assert "customerId" not in body


async def test_omits_file_type_when_the_caller_does_not_send_one():
    _result, client = await _call(_args())
    body = client.request.call_args.kwargs["json"]
    assert "fileType" not in body


async def test_strips_a_data_uri_before_sending_base64():
    arguments = _args()
    arguments.pop("file_url")
    arguments["base64"] = "data:application/pdf;base64,aGVsbG8="
    arguments["fileSize"] = 5
    _result, client = await _call(arguments)
    body = client.request.call_args.kwargs["json"]
    assert body["data"] == "aGVsbG8="
    assert "fileSize" not in body


async def test_rejects_a_missing_file_before_the_api_call():
    arguments = _args()
    arguments.pop("file_url")
    result, client = await _call(arguments)
    assert result["_status_code"] == 400
    assert "file_url or base64" in result["message"]
    client.request.assert_not_called()


async def test_rejects_both_file_sources():
    result, client = await _call(_args(base64="aGVsbG8=", fileSize=5))
    assert result["_status_code"] == 400
    assert "not both" in result["message"]
    client.request.assert_not_called()


async def test_rejects_an_oversized_base64_file():
    arguments = _args()
    arguments.pop("file_url")
    arguments["base64"] = "aGVsbG8="
    arguments["fileSize"] = peakflo_main.MAX_ATTACHMENT_BYTES + 1
    result, client = await _call(arguments)
    assert result["_status_code"] == 400
    assert "10MB" in result["message"]
    client.request.assert_not_called()


async def test_uses_the_file_name_without_a_directory():
    _result, client = await _call(_args(name="nested/274.pdf"))
    body = client.request.call_args.kwargs["json"]
    assert body["name"] == "274.pdf"


async def test_pads_unpadded_base64_before_sending():
    arguments = _args()
    arguments.pop("file_url")
    arguments["base64"] = "aGVsbG8"
    arguments["fileSize"] = 5
    _result, client = await _call(arguments)
    body = client.request.call_args.kwargs["json"]
    assert body["data"] == "aGVsbG8="


async def test_converts_url_safe_base64_to_the_standard_alphabet():
    raw = b"\xfb\xff\xef"
    arguments = _args()
    arguments.pop("file_url")
    arguments["base64"] = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    arguments["fileSize"] = len(raw)
    _result, client = await _call(arguments)
    body = client.request.call_args.kwargs["json"]
    assert body["data"] == base64.b64encode(raw).decode()


async def test_strips_ids_before_the_request():
    _result, client = await _call(
        _args(customerExternalId=" cust-ext ", externalId=" letter-1 ")
    )
    _method, url = client.request.call_args.args[:2]
    body = client.request.call_args.kwargs["json"]
    assert url == BASE + "/customers/cust-ext/attachments"
    assert body["externalId"] == "letter-1"


async def test_sends_a_file_name_the_invoice_rule_rejects():
    for name in ("Invoice (1).pdf", "Invoice #123.pdf"):
        _result, client = await _call(_args(name=name))
        body = client.request.call_args.kwargs["json"]
        assert body["name"] == name


async def test_rejects_a_file_name_with_no_letter_or_digit():
    result, client = await _call(_args(name="###.pdf"))
    assert result["_status_code"] == 400
    assert "invalid file name" in result["message"]
    client.request.assert_not_called()


async def test_rejects_a_content_type_that_does_not_match_the_extension():
    result, client = await _call(_args(contentType="application/octet-stream"))
    assert result["_status_code"] == 400
    assert "contentType must be application/pdf" in result["message"]
    client.request.assert_not_called()


async def test_rejects_a_date_that_is_not_iso_8601():
    result, client = await _call(_args(dateCreated="01/02/2026"))
    assert result["_status_code"] == 400
    assert "ISO 8601" in result["message"]
    client.request.assert_not_called()


async def test_sends_an_iso_timestamp():
    _result, client = await _call(_args(dateCreated=" 2026-01-02T00:00:00.000Z "))
    body = client.request.call_args.kwargs["json"]
    assert body["dateCreated"] == "2026-01-02T00:00:00.000Z"
