"""
Offline tests for add_customer_attachment.

The tool must download the file, write it to the Peakflo storage bucket at
{tenant}/private/{uuid}/{name}, and POST the billing /files body the customer
Files tab uses. It must not send the bytes to the public Peakflo API.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jsonschema import Draft7Validator

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for _p in (os.path.join(_ROOT, "src", "servers"), os.path.join(_ROOT, "src"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.servers.peakflo import main as peakflo_main  # noqa: E402
from peakflo.schemas.customer import add_customer_attachment_schema  # noqa: E402
from peakflo.factories.peakflo_api_factory import PeakfloApiToolFactory  # noqa: E402

BILLING = "https://billing.example.test/v1"
BUCKET = "peakflo.appspot.com"
_RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_KEY = _RSA_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
PUBLIC_KEY = _RSA_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)


def _response(status=201, body=None):
    resp = MagicMock()
    resp.status_code = status
    resp.content = b"{}"
    resp.text = "{}"
    resp.json.return_value = body or {"id": "file-1"}
    return resp


def _args(**extra):
    args = {
        "tenantId": "0demoFileSG",
        "customerId": "iR99JgPYXStqvvwEHYh7",
        "name": "274.pdf",
        "contentType": "application/pdf",
        "file_url": "https://storage.example/signed.pdf",
    }
    args.update(extra)
    return args


async def _call(arguments, upload_error=None, private_key=PRIVATE_KEY):
    client = MagicMock()
    client.post = AsyncMock(return_value=_response())
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=client)
    client_cm.__aexit__ = AsyncMock(return_value=False)
    upload = (
        MagicMock(side_effect=upload_error)
        if upload_error
        else MagicMock(return_value=BUCKET)
    )
    env = {
        "PEAKFLO_BILLING_API_BASE_URL": BILLING,
        "PEAKFLO_STORAGE_BUCKET": BUCKET,
        "PEAKFLO_BILLING_JWT_PRIVATE_KEY": private_key,
    }
    with patch.dict(os.environ, env, clear=False), patch.object(
        peakflo_main,
        "_download_and_encode",
        AsyncMock(return_value=("aGVsbG8=", 5)),
    ), patch.object(peakflo_main, "_upload_customer_file", upload), patch.object(
        peakflo_main.httpx, "AsyncClient", return_value=client_cm
    ):
        result = await peakflo_main.make_peakflo_request(
            "add_customer_attachment", arguments, "token"
        )
    return result, client, upload


def test_tool_is_registered():
    names = [tool.name for tool in PeakfloApiToolFactory.get_all_tools()]
    assert "add_customer_attachment" in names


def test_schema_requires_internal_customer_id():
    Draft7Validator(add_customer_attachment_schema).validate(_args())
    assert "customerId" in add_customer_attachment_schema["required"]
    assert "externalId" not in add_customer_attachment_schema["properties"]


async def test_uploads_to_peakflo_bucket_and_posts_files_tab_body():
    result, client, upload = await _call(_args())

    assert result["_status_code"] == 201
    assert result["message"] == "Customer file added"
    upload.assert_called_once()
    data, object_path, content_type = upload.call_args.args
    assert data == b"hello"
    assert object_path.startswith("0demoFileSG/private/")
    assert object_path.endswith("/274.pdf")
    assert content_type == "application/pdf"

    client.post.assert_awaited_once()
    url = client.post.call_args.args[0]
    body = client.post.call_args.kwargs["json"]
    assert url == BILLING + "/files"
    assert body["parentCompanyId"] == "0demoFileSG"
    assert body["elementType"] == "companies"
    assert body["elementId"] == "iR99JgPYXStqvvwEHYh7"
    assert body["fileType"] == "other"
    assert body["file"] == {
        "name": "274.pdf",
        "mimeType": "application/pdf",
        "size": 5,
        "path": object_path,
    }
    assert "base64" not in body
    assert "file_url" not in body
    authorization = client.post.call_args.kwargs["headers"]["Authorization"]
    assert authorization != "Bearer token"
    claims = jwt.decode(
        authorization.removeprefix("Bearer "),
        PUBLIC_KEY,
        algorithms=["RS256"],
        audience="peakflo",
        issuer="peakflo",
    )
    assert claims["sub"] == "0demoFileSG"
    assert claims["uid"] == "workflow"
    assert claims["sourceSystem"] == "billing-api"
    assert authorization.count(".") == 2


async def test_rejects_a_missing_file_before_upload():
    result, client, upload = await _call(
        {
            "tenantId": "0demoFileSG",
            "customerId": "cust-1",
            "name": "274.pdf",
            "contentType": "application/pdf",
        }
    )
    assert result["_status_code"] == 400
    assert "file_url or base64" in result["message"]
    upload.assert_not_called()
    client.post.assert_not_called()


async def test_rejects_both_file_sources():
    result, client, upload = await _call(_args(base64="aGVsbG8=", fileSize=5))
    assert result["_status_code"] == 400
    assert "not both" in result["message"]
    upload.assert_not_called()
    client.post.assert_not_called()


async def test_does_not_upload_when_billing_url_is_missing():
    upload = MagicMock()
    env = {
        "PEAKFLO_STORAGE_BUCKET": BUCKET,
        "PEAKFLO_BILLING_API_BASE_URL": "",
    }
    with patch.dict(os.environ, env, clear=False), patch.object(
        peakflo_main, "_upload_customer_file", upload
    ):
        result = await peakflo_main.make_peakflo_request(
            "add_customer_attachment", _args(), "token"
        )
    assert result["_status_code"] == 400
    assert "PEAKFLO_BILLING_API_BASE_URL" in result["message"]
    upload.assert_not_called()


async def test_signs_with_a_private_key_stored_as_escaped_newlines():
    result, client, _upload = await _call(
        _args(), private_key=PRIVATE_KEY.replace("\n", "\\n")
    )
    assert result["_status_code"] == 201
    authorization = client.post.call_args.kwargs["headers"]["Authorization"]
    claims = jwt.decode(
        authorization.removeprefix("Bearer "),
        PUBLIC_KEY,
        algorithms=["RS256"],
        audience="peakflo",
    )
    assert claims["sub"] == "0demoFileSG"


async def test_does_not_upload_when_billing_private_key_is_missing():
    upload = MagicMock()
    env = {
        "PEAKFLO_BILLING_API_BASE_URL": BILLING,
        "PEAKFLO_STORAGE_BUCKET": BUCKET,
        "PEAKFLO_BILLING_JWT_PRIVATE_KEY": "",
    }
    with patch.dict(os.environ, env, clear=False), patch.object(
        peakflo_main, "_upload_customer_file", upload
    ), patch.object(
        peakflo_main, "_download_and_encode", AsyncMock(return_value=("aGVsbG8=", 5))
    ):
        result = await peakflo_main.make_peakflo_request(
            "add_customer_attachment", _args(), "peakflo-api-key"
        )
    assert result["_status_code"] == 400
    assert "PEAKFLO_BILLING_JWT_PRIVATE_KEY" in result["message"]
    upload.assert_not_called()
