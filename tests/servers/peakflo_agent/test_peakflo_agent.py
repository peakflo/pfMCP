from unittest.mock import AsyncMock

import pytest

from servers.peakflo_agent import main


@pytest.mark.asyncio
async def test_list_tools_uses_signed_session_token_and_server_schemas(monkeypatch):
    request = AsyncMock(
        return_value={
            "tools": [
                {
                    "name": "approve",
                    "description": "Approve assigned bill",
                    "inputSchema": {
                        "type": "object",
                        "required": ["callId", "rationale"],
                    },
                }
            ]
        }
    )
    monkeypatch.setattr(main, "_runtime_request", request)

    tools = await main.list_scoped_tools("signed-session-token")

    assert [tool.name for tool in tools] == ["approve"]
    request.assert_awaited_once_with(
        "signed-session-token", "GET", "/v1/autonomous-agent-session/tools"
    )


@pytest.mark.asyncio
async def test_call_forwards_only_tool_arguments_under_session_bearer(monkeypatch):
    request = AsyncMock(return_value={"result": {"status": "approved"}})
    monkeypatch.setattr(main, "_runtime_request", request)

    await main.call_scoped_tool(
        "signed-session-token",
        "approve",
        {"callId": "call-1", "rationale": "matched"},
    )

    request.assert_awaited_once_with(
        "signed-session-token",
        "POST",
        "/v1/autonomous-agent-session/tools/approve",
        {"callId": "call-1", "rationale": "matched"},
    )
