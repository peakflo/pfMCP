"""Offline tests: send_email and forward_email refuse an empty, placeholder or
malformed recipient before any mail is built or sent."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

from src.servers.gmail.main import create_server, validate_recipients


@pytest.mark.parametrize(
    "value",
    [
        "a@b.co",
        "Name <a@b.co>",
        "a@b.co, Other <c@d.org>",
        None,
    ],
)
def test_valid_recipients_pass(value):
    validate_recipients("to", value)


@pytest.mark.parametrize(
    "value", ["", "   ", "[EMAIL]", "me", "no-at-sign", "a@b", "a@b.co, [EMAIL]"]
)
def test_bad_recipients_are_refused(value):
    with pytest.raises(ValueError) as caught:
        validate_recipients("to", value)
    assert "Ask the person" in str(caught.value)


def _service():
    service = MagicMock()
    send = service.users.return_value.messages.return_value.send
    return service, send


def _call(name, arguments, service):
    with patch(
        "src.servers.gmail.main.create_gmail_service",
        new_callable=AsyncMock,
        return_value=service,
    ):
        server = create_server("conn", api_key="k")
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=arguments),
        )
        return asyncio.run(server.dispatch(request))


@pytest.mark.parametrize("to", ["", "[EMAIL]"])
def test_forward_with_bad_recipient_sends_nothing(to):
    service, send = _service()
    result = _call(
        "forward_email",
        {"email_id": "e1", "to": to, "include_attachments": False},
        service,
    )
    assert result.is_error
    assert "Ask the person" in result.content[0].text
    send.assert_not_called()
    # The original email is not even fetched.
    service.users.return_value.messages.return_value.get.assert_not_called()


@pytest.mark.parametrize("field", ["to", "cc", "bcc"])
def test_send_with_bad_recipient_sends_nothing(field):
    service, send = _service()
    arguments = {"to": "ok@example.com", "subject": "s", "body": "b"}
    arguments[field] = "[EMAIL]"
    result = _call("send_email", arguments, service)
    assert result.is_error
    send.assert_not_called()
