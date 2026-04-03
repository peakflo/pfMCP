"""Unit tests for read_emails with output_format='structured'.

These tests mock the Gmail API to verify structured JSON output format,
filtering, and edge cases without requiring real credentials.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from base64 import urlsafe_b64encode

from mcp.types import CallToolRequest, CallToolRequestParams

# Default structured arguments — query is required for read_emails
_STRUCTURED_DEFAULTS = {"query": "in:inbox", "output_format": "structured"}


def _make_gmail_message(
    msg_id="msg_001",
    thread_id="thread_001",
    history_id="12345",
    subject="Test Subject",
    sender="alice@example.com",
    to="bob@example.com",
    cc="",
    bcc="",
    date="Mon, 31 Mar 2026 10:00:00 +0000",
    message_id_header="<abc123@mail.gmail.com>",
    labels=None,
    body_text="Hello world",
    body_html="",
    snippet="Hello world snippet",
    attachments=None,
):
    """Build a fake Gmail API message response."""
    if labels is None:
        labels = ["INBOX", "UNREAD"]

    headers = [
        {"name": "From", "value": sender},
        {"name": "To", "value": to},
        {"name": "Subject", "value": subject},
        {"name": "Date", "value": date},
        {"name": "Message-ID", "value": message_id_header},
    ]
    if cc:
        headers.append({"name": "Cc", "value": cc})
    if bcc:
        headers.append({"name": "Bcc", "value": bcc})

    parts = []
    if body_text:
        encoded = urlsafe_b64encode(body_text.encode()).decode()
        parts.append(
            {
                "mimeType": "text/plain",
                "body": {"data": encoded, "size": len(body_text)},
            }
        )
    if body_html:
        encoded = urlsafe_b64encode(body_html.encode()).decode()
        parts.append(
            {
                "mimeType": "text/html",
                "body": {"data": encoded, "size": len(body_html)},
            }
        )

    if attachments:
        for att in attachments:
            parts.append(
                {
                    "filename": att["filename"],
                    "mimeType": att.get("mimeType", "application/octet-stream"),
                    "body": {
                        "size": att.get("size", 1024),
                        "attachmentId": att.get("attachmentId", "att_001"),
                    },
                }
            )

    payload = {"headers": headers, "mimeType": "multipart/mixed", "parts": parts}

    return {
        "id": msg_id,
        "threadId": thread_id,
        "historyId": history_id,
        "labelIds": labels,
        "snippet": snippet,
        "payload": payload,
    }


def _build_mock_gmail_service(messages_list_response, message_get_responses):
    """Build a mock Gmail service with list and get responses."""
    mock_service = MagicMock()

    mock_list = MagicMock()
    mock_list.execute.return_value = messages_list_response

    mock_messages = MagicMock()
    mock_messages.list.return_value = mock_list

    mock_get = MagicMock()
    if isinstance(message_get_responses, list):
        mock_get.execute.side_effect = message_get_responses
    else:
        mock_get.execute.return_value = message_get_responses
    mock_messages.get.return_value = mock_get

    mock_users = MagicMock()
    mock_users.messages.return_value = mock_messages
    mock_service.users.return_value = mock_users

    return mock_service


@pytest.fixture
def single_email_service():
    """Gmail service mock returning one email."""
    msg = _make_gmail_message()
    return _build_mock_gmail_service(
        messages_list_response={"messages": [{"id": "msg_001"}]},
        message_get_responses=msg,
    )


@pytest.fixture
def multi_email_service():
    """Gmail service mock returning two emails."""
    msg1 = _make_gmail_message(
        msg_id="msg_001",
        subject="First Email",
        sender="alice@example.com",
        labels=["INBOX", "UNREAD"],
    )
    msg2 = _make_gmail_message(
        msg_id="msg_002",
        thread_id="thread_002",
        subject="Second Email",
        sender="charlie@example.com",
        labels=["INBOX"],
        body_text="Second body",
        snippet="Second snippet",
    )
    return _build_mock_gmail_service(
        messages_list_response={"messages": [{"id": "msg_001"}, {"id": "msg_002"}]},
        message_get_responses=[msg1, msg2],
    )


@pytest.fixture
def empty_service():
    """Gmail service mock returning no emails."""
    return _build_mock_gmail_service(
        messages_list_response={"messages": []},
        message_get_responses=None,
    )


@pytest.fixture
def email_with_attachments_service():
    """Gmail service mock returning an email with attachments."""
    msg = _make_gmail_message(
        msg_id="msg_att",
        subject="Email with Attachment",
        attachments=[
            {
                "filename": "report.pdf",
                "mimeType": "application/pdf",
                "size": 2048,
                "attachmentId": "att_pdf_001",
            },
            {
                "filename": "photo.png",
                "mimeType": "image/png",
                "size": 4096,
                "attachmentId": "att_png_001",
            },
        ],
    )
    return _build_mock_gmail_service(
        messages_list_response={"messages": [{"id": "msg_att"}]},
        message_get_responses=msg,
    )


async def _invoke_tool(mock_service, arguments=None):
    """Call read_emails with output_format=structured and return parsed JSON."""
    # Merge caller args on top of structured defaults
    merged = {**_STRUCTURED_DEFAULTS, **(arguments or {})}

    with patch(
        "src.servers.gmail.main.create_gmail_service",
        new_callable=AsyncMock,
        return_value=mock_service,
    ):
        from src.servers.gmail.main import create_server

        server_instance = create_server("test_user", api_key="test_key")
        handler = server_instance.request_handlers[CallToolRequest]

        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="read_emails",
                arguments=merged,
            ),
        )
        result = await handler(request)
        text = result.root.content[0].text
        return json.loads(text)


async def _invoke_tool_raw(mock_service, arguments=None):
    """Call read_emails and return the raw text (for testing text vs structured)."""
    merged = {**(arguments or {})}
    if "query" not in merged:
        merged["query"] = "in:inbox"

    with patch(
        "src.servers.gmail.main.create_gmail_service",
        new_callable=AsyncMock,
        return_value=mock_service,
    ):
        from src.servers.gmail.main import create_server

        server_instance = create_server("test_user", api_key="test_key")
        handler = server_instance.request_handlers[CallToolRequest]

        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="read_emails",
                arguments=merged,
            ),
        )
        result = await handler(request)
        return result.root.content[0].text


@pytest.mark.asyncio
async def test_basic_structured_output(single_email_service):
    """Structured output contains expected top-level keys and email fields."""
    data = await _invoke_tool(single_email_service)

    assert "emails" in data
    assert "resultCount" in data
    assert "query" in data
    assert data["resultCount"] == 1
    assert data["query"] == "in:inbox"

    email = data["emails"][0]
    assert email["id"] == "msg_001"
    assert email["threadId"] == "thread_001"
    assert email["from"] == "alice@example.com"
    assert email["to"] == "bob@example.com"
    assert email["subject"] == "Test Subject"
    assert email["isUnread"] is True
    assert "INBOX" in email["labels"]
    assert email["snippet"] == "Hello world snippet"
    assert email["messageId"] == "<abc123@mail.gmail.com>"


@pytest.mark.asyncio
async def test_empty_result(empty_service):
    """Returns empty list when no emails match."""
    data = await _invoke_tool(empty_service)

    assert data["emails"] == []
    assert data["resultCount"] == 0


@pytest.mark.asyncio
async def test_multiple_emails(multi_email_service):
    """Returns multiple emails in order."""
    data = await _invoke_tool(multi_email_service)

    assert data["resultCount"] == 2
    assert data["emails"][0]["subject"] == "First Email"
    assert data["emails"][0]["isUnread"] is True
    assert data["emails"][1]["subject"] == "Second Email"
    assert data["emails"][1]["isUnread"] is False


@pytest.mark.asyncio
async def test_body_included_by_default(single_email_service):
    """Email body is included when include_body is not specified (default true)."""
    data = await _invoke_tool(single_email_service)

    email = data["emails"][0]
    assert "body" in email
    assert email["body"]["text"] == "Hello world"


@pytest.mark.asyncio
async def test_body_excluded_when_disabled(single_email_service):
    """Email body is excluded when include_body is false."""
    data = await _invoke_tool(single_email_service, {"include_body": False})

    email = data["emails"][0]
    assert "body" not in email


@pytest.mark.asyncio
async def test_attachments_included(email_with_attachments_service):
    """Attachment metadata is returned in structured format."""
    data = await _invoke_tool(email_with_attachments_service)

    email = data["emails"][0]
    assert "attachments" in email
    assert len(email["attachments"]) == 2

    pdf = email["attachments"][0]
    assert pdf["filename"] == "report.pdf"
    assert pdf["mimeType"] == "application/pdf"
    assert pdf["size"] == 2048
    assert pdf["attachmentId"] == "att_pdf_001"

    png = email["attachments"][1]
    assert png["filename"] == "photo.png"


@pytest.mark.asyncio
async def test_attachments_excluded_when_disabled(
    email_with_attachments_service,
):
    """Attachments are excluded when include_attachments_info is false."""
    data = await _invoke_tool(
        email_with_attachments_service,
        {"include_attachments_info": False},
    )

    email = data["emails"][0]
    assert "attachments" not in email


@pytest.mark.asyncio
async def test_custom_query(single_email_service):
    """Custom query parameter is passed to Gmail API and reflected in response."""
    data = await _invoke_tool(single_email_service, {"query": "from:alice@example.com"})

    assert data["query"] == "from:alice@example.com"

    # Verify the query was passed to the API
    mock_messages = single_email_service.users().messages()
    mock_messages.list.assert_called_with(
        userId="me", q="from:alice@example.com", maxResults=10
    )


@pytest.mark.asyncio
async def test_label_ids_filter(single_email_service):
    """label_ids parameter is passed to Gmail API list call."""
    await _invoke_tool(
        single_email_service,
        {"label_ids": ["INBOX", "UNREAD"]},
    )

    mock_messages = single_email_service.users().messages()
    mock_messages.list.assert_called_with(
        userId="me",
        q="in:inbox",
        maxResults=10,
        labelIds=["INBOX", "UNREAD"],
    )


@pytest.mark.asyncio
async def test_max_results_capped_at_100(single_email_service):
    """max_results is capped at 100 even if caller requests more."""
    await _invoke_tool(single_email_service, {"max_results": 500})

    mock_messages = single_email_service.users().messages()
    call_kwargs = mock_messages.list.call_args
    assert call_kwargs.kwargs.get("maxResults", call_kwargs[1].get("maxResults")) == 100


@pytest.mark.asyncio
async def test_extra_headers(single_email_service):
    """Extra headers requested via include_headers appear in extraHeaders."""
    msg = single_email_service.users().messages().get().execute()
    msg["payload"]["headers"].append({"name": "Reply-To", "value": "reply@example.com"})
    single_email_service.users().messages().get().execute.return_value = msg
    single_email_service.users().messages().get.return_value.execute.return_value = msg

    data = await _invoke_tool(
        single_email_service,
        {"include_headers": ["Reply-To"]},
    )

    email = data["emails"][0]
    assert "extraHeaders" in email
    assert email["extraHeaders"]["Reply-To"] == "reply@example.com"


@pytest.mark.asyncio
async def test_output_is_valid_json(single_email_service):
    """Tool output is valid JSON string that can be parsed back to dict."""
    with patch(
        "src.servers.gmail.main.create_gmail_service",
        new_callable=AsyncMock,
        return_value=single_email_service,
    ):
        from src.servers.gmail.main import create_server

        server_instance = create_server("test_user", api_key="test_key")
        handler = server_instance.request_handlers[CallToolRequest]

        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="read_emails",
                arguments={"query": "in:inbox", "output_format": "structured"},
            ),
        )
        result = await handler(request)
        raw_text = result.root.content[0].text
        parsed = json.loads(raw_text)
        assert isinstance(parsed, dict)
        assert isinstance(parsed["emails"], list)


@pytest.mark.asyncio
async def test_text_format_is_default(single_email_service):
    """Without output_format, read_emails returns human-readable text (not JSON)."""
    raw = await _invoke_tool_raw(single_email_service)

    # Text format starts with "Found N emails:"
    assert raw.startswith("Found 1 emails:")
    # Should NOT be valid JSON
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)


@pytest.mark.asyncio
async def test_text_format_explicit(single_email_service):
    """output_format='text' returns human-readable text."""
    raw = await _invoke_tool_raw(single_email_service, {"output_format": "text"})
    assert "Found 1 emails:" in raw
    assert "From: alice@example.com" in raw
