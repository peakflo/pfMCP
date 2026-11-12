import os
import sys

import pytest
from jsonschema import Draft7Validator, ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src", "servers")
)

from servers.peakflo import main
from servers.peakflo.schemas.configuration import configuration_schemas
from servers.peakflo.factories.peakflo_api_factory import PeakfloApiToolFactory


def test_configuration_tools_are_registered():
    tools = {tool.name: tool for tool in PeakfloApiToolFactory.get_all_tools()}
    assert set(configuration_schemas) <= set(tools)
    for name, schema in configuration_schemas.items():
        Draft7Validator.check_schema(schema)
        assert tools[name].input_schema == schema


def test_configuration_inputs_need_ids_and_payloads():
    with pytest.raises(ValidationError):
        Draft7Validator(configuration_schemas["update_rule"]).validate({"id": "rule-1"})
    with pytest.raises(ValidationError):
        Draft7Validator(configuration_schemas["delete_custom_field"]).validate({})
    Draft7Validator(configuration_schemas["create_approval_policy"]).validate(
        {"payload": {"ranges": []}}
    )
    with pytest.raises(ValidationError):
        Draft7Validator(configuration_schemas["invite_user"]).validate(
            {"email": "new@example.com"}
        )
    with pytest.raises(ValidationError):
        Draft7Validator(configuration_schemas["create_chart_of_account"]).validate(
            {"account": {"name": "Office Supplies"}}
        )
    with pytest.raises(ValidationError):
        Draft7Validator(configuration_schemas["create_role"]).validate(
            {"payload": {"name": "Approver"}}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args,method,url,body",
    [
        (
            "list_rules",
            {"objectType": "bill"},
            "GET",
            "/field-rules?objectType=bill",
            None,
        ),
        ("get_approval_policy", {"id": "a/b"}, "GET", "/ap/policy/a%2Fb", None),
        (
            "update_custom_field",
            {"id": "cf-1", "payload": {"name": "Cost"}},
            "PUT",
            "/ap/customfields/cf-1",
            {"name": "Cost"},
        ),
        (
            "create_rule",
            {"payload": {"displayName": "Review"}},
            "POST",
            "/field-rules",
            {"displayName": "Review"},
        ),
        (
            "invite_user",
            {"email": "new@example.com", "displayName": "New User"},
            "POST",
            "/users/invitations",
            {"email": "new@example.com", "displayName": "New User"},
        ),
        (
            "list_chart_of_accounts",
            {"search": "office", "page": 1},
            "GET",
            "/chartOfAccounts?search=office&page=1",
            None,
        ),
        (
            "get_chart_of_account",
            {"id": "coa-1"},
            "GET",
            "/chartOfAccounts/coa-1",
            None,
        ),
        (
            "create_chart_of_account",
            {
                "account": {
                    "name": "Office",
                    "code": "6001",
                    "type": "expense",
                    "paymentAllowed": False,
                }
            },
            "POST",
            "/chartOfAccounts",
            {
                "name": "Office",
                "code": "6001",
                "type": "expense",
                "paymentAllowed": False,
            },
        ),
        (
            "update_chart_of_account",
            {
                "id": "coa-1",
                "account": {
                    "name": "Office",
                    "code": "6001",
                    "type": "expense",
                    "paymentAllowed": False,
                },
            },
            "PUT",
            "/chartOfAccounts/coa-1",
            {
                "name": "Office",
                "code": "6001",
                "type": "expense",
                "paymentAllowed": False,
            },
        ),
        (
            "delete_chart_of_account",
            {"id": "coa-1"},
            "DELETE",
            "/chartOfAccounts/coa-1",
            None,
        ),
        ("list_role_permissions", {}, "GET", "/roles/permissions", None),
        ("list_roles", {}, "GET", "/roles", None),
        ("get_role", {"id": "role-1"}, "GET", "/roles/role-1", None),
        (
            "create_role",
            {
                "payload": {
                    "name": "Approver",
                    "description": "Reviews bills",
                    "permissions": {"apViewer": True},
                }
            },
            "POST",
            "/roles",
            {
                "name": "Approver",
                "description": "Reviews bills",
                "permissions": {"apViewer": True},
            },
        ),
        (
            "update_role",
            {"id": "role-1", "payload": {"permissions": {"apViewer": False}}},
            "PATCH",
            "/roles/role-1",
            {"permissions": {"apViewer": False}},
        ),
        ("delete_role", {"id": "role-1"}, "DELETE", "/roles/role-1", None),
    ],
)
async def test_configuration_route_mapping(monkeypatch, name, args, method, url, body):
    calls = []

    class Response:
        status_code = 200
        content = b"{}"
        text = "{}"

        def json(self):
            return {}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def request(self, request_method, request_url, **kwargs):
            calls.append((request_method, request_url, kwargs))
            return Response()

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    monkeypatch.setattr(main, "PEAKFLO_V1_BASE_URL", "https://api.example/v1")
    result = await main.make_peakflo_request(name, args, "test-token")
    assert result["_status_code"] == 200
    assert calls[0][0] == method
    assert calls[0][1] == "https://api.example/v1" + url
    assert calls[0][2]["json"] == body
    assert calls[0][2]["headers"]["Authorization"] == "Bearer test-token"


@pytest.mark.asyncio
async def test_invite_queue_response_is_success(monkeypatch):
    class Response:
        status_code = 202
        content = b'{"status":"queued"}'
        text = '{"status":"queued"}'

        def json(self):
            return {"status": "queued"}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def request(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    monkeypatch.setattr(main, "PEAKFLO_V1_BASE_URL", "https://api.example/v1")
    result = await main.make_peakflo_request(
        "invite_user", {"email": "new@example.com", "displayName": "New User"}, "token"
    )
    assert result["_status_code"] == 202
    assert result["message"] == "Invite user succeeded"
