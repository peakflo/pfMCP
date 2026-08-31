import asyncio
import contextlib
import socket
import threading
import time

import httpx
import mcp.types as types
import pytest
import uvicorn
from mcp.server.lowlevel import Server
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Mount, Route

from src.servers import http_lifecycle
from src.servers.http_lifecycle import McpHttpLifecycle, StreamingSessionRegistry

http_lifecycle.SESSION_SWEEP_INTERVAL_SECONDS = 0.01


def create_test_server() -> Server:
    server = Server("lifecycle-test")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="echo",
                description="Echo text",
                inputSchema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None):
        await asyncio.sleep(float((arguments or {}).get("delay", 0)))
        return [types.TextContent(type="text", text=(arguments or {}).get("text", ""))]

    return server


def create_test_app() -> Starlette:
    registry = StreamingSessionRegistry()
    lifecycle = McpHttpLifecycle(registry)

    async def endpoint(scope, receive, send):
        await lifecycle.handle(
            "test:local",
            "test",
            create_test_server,
            scope,
            receive,
            send,
        )

    async def metrics(_request):
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with registry.run():
            yield

    return Starlette(
        routes=[Mount("/test", app=endpoint), Route("/metrics", metrics)],
        lifespan=lifespan,
    )


@pytest.fixture(scope="module")
def local_server_url():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    sock.close()

    server = uvicorn.Server(
        uvicorn.Config(
            create_test_app(),
            host=host,
            port=port,
            log_level="warning",
            lifespan="on",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while not server.started and time.time() < deadline:
        time.sleep(0.01)
    assert server.started

    yield f"http://{host}:{port}"

    server.should_exit = True
    thread.join(timeout=5)
    assert not thread.is_alive()


def rpc(method: str, request_id: int | None, params: dict | None = None) -> dict:
    message = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        message["id"] = request_id
    if params is not None:
        message["params"] = params
    return message


def request_headers(**extra: str) -> dict[str, str]:
    return {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        **extra,
    }


async def initialize_streaming(client: httpx.AsyncClient, url: str) -> str:
    response = await client.post(
        url,
        headers=request_headers(),
        json=rpc(
            "initialize",
            1,
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        ),
    )
    response.raise_for_status()
    session_id = response.headers["mcp-session-id"]
    await client.post(
        url,
        headers=request_headers(**{"mcp-session-id": session_id}),
        json=rpc("notifications/initialized", None),
    )
    return session_id


@pytest.mark.asyncio
async def test_one_shot_uses_json_posts_and_rejects_receive_stream(local_server_url):
    url = f"{local_server_url}/test/local"
    headers = request_headers(**{"mcp-client-mode": "one-shot"})
    async with httpx.AsyncClient(timeout=3) as client:
        initialized = await client.post(
            url,
            headers=headers,
            json=rpc(
                "initialize",
                1,
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            ),
        )
        assert initialized.status_code == 200
        assert initialized.headers["content-type"].startswith("application/json")
        assert "mcp-session-id" not in initialized.headers

        notification = await client.post(
            url, headers=headers, json=rpc("notifications/initialized", None)
        )
        assert notification.status_code == 202

        tools = await client.post(url, headers=headers, json=rpc("tools/list", 2, {}))
        assert tools.status_code == 200
        assert tools.json()["result"]["tools"][0]["name"] == "echo"

        rejected = await client.get(
            url,
            headers={"accept": "text/event-stream", "mcp-client-mode": "one-shot"},
        )
        assert rejected.status_code == 405

        metrics = (await client.get(f"{local_server_url}/metrics")).text
        assert "pfmcp_get_to_post_ratio" in metrics
        assert "pfmcp_instance_info" in metrics


@pytest.mark.asyncio
async def test_stream_is_unique_disconnects_and_delete_rejects_stale_session(
    local_server_url,
):
    url = f"{local_server_url}/test/local"
    async with httpx.AsyncClient(timeout=3) as client:
        session_id = await initialize_streaming(client, url)
        stream_headers = {
            "accept": "text/event-stream",
            "mcp-session-id": session_id,
            "mcp-protocol-version": "2025-06-18",
        }

        async with client.stream("GET", url, headers=stream_headers) as first:
            assert first.status_code == 200
            duplicate = await client.get(url, headers=stream_headers)
            assert duplicate.status_code == 409

        # A clean client disconnect releases the receive-stream slot, so an
        # explicit streaming caller may reconnect once without cross-closing.
        async with client.stream("GET", url, headers=stream_headers) as reopened:
            assert reopened.status_code == 200

        deleted = await client.delete(url, headers=stream_headers)
        assert deleted.status_code == 200
        stale = await client.get(url, headers=stream_headers)
        assert stale.status_code == 404


@pytest.mark.asyncio
async def test_idle_ttl_terminates_session_and_closes_stream(
    local_server_url, monkeypatch
):
    monkeypatch.setattr(http_lifecycle, "SESSION_IDLE_TTL_SECONDS", 0.05)
    monkeypatch.setattr(http_lifecycle, "SESSION_SWEEP_INTERVAL_SECONDS", 0.01)
    url = f"{local_server_url}/test/local"
    async with httpx.AsyncClient(timeout=3) as client:
        session_id = await initialize_streaming(client, url)
        await asyncio.sleep(0.12)
        stale = await client.get(
            url,
            headers={
                "accept": "text/event-stream",
                "mcp-session-id": session_id,
                "mcp-protocol-version": "2025-06-18",
            },
        )
        assert stale.status_code == 404
