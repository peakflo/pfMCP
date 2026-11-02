"""Protocol-version negotiation tests for the stateless Streamable HTTP server.

These tests run the real ``src/servers/remote.py`` Starlette application under a
real uvicorn instance on a loopback port and speak raw JSON-RPC over HTTP, so
they pin the wire behaviour a client sees rather than SDK internals:

* a 2026-07-28 client (``@modelcontextprotocol/client`` 2.x) probes with
  ``server/discover`` and then sends ``tools/list`` / ``tools/call`` with the
  ``MCP-Protocol-Version: 2026-07-28`` header and no ``initialize`` handshake;
* a legacy client sends ``initialize`` without the header, gets the version it
  asked for back, and sends the negotiated version as the header on every
  following request;
* an unknown version in the header is rejected with HTTP 400 and a JSON-RPC
  error that names the supported versions;
* the mcp 1.x decorator semantics kept by ``src/utils/mcp_compat.py`` (error
  results, input validation, resource wrapping) hold on both protocol eras.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterable, Iterator
from typing import Any

import httpx
import pytest
import uvicorn

from mcp.server.models import InitializationOptions
from mcp.shared.inbound import NAME_BEARING_METHODS, encode_header_value
from mcp.types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
    Resource,
    TextContent,
    Tool,
)
from mcp.types.version import (
    HANDSHAKE_PROTOCOL_VERSIONS,
    LATEST_HANDSHAKE_VERSION,
    MODERN_PROTOCOL_VERSIONS,
)

from src.servers import remote
from src.utils.mcp_compat import NotificationOptions, ReadResourceContents, Server

MODERN = "2026-07-28"
FIXTURE = "negotiation-fixture"
UNKNOWN_VERSION = "2099-01-01"
ACCEPT = "application/json, text/event-stream"


# --------------------------------------------------------------------- fixture server
def create_fixture_server(user_id: str, api_key: str | None = None) -> Server:
    server = Server(FIXTURE)
    server.user_id = user_id  # type: ignore[attr-defined]

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="echo",
                description="Echo the text argument",
                inputSchema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            ),
            Tool(
                name="boom",
                description="Always raises",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="structured",
                description="Returns structured content",
                inputSchema={"type": "object", "properties": {}},
                outputSchema={
                    "type": "object",
                    "properties": {"answer": {"type": "integer"}},
                    "required": ["answer"],
                },
            ),
            Tool(
                name="array-schema",
                description="Declares a spec-invalid array outputSchema, returns text",
                inputSchema={"type": "object", "properties": {}},
                outputSchema={"type": "array", "items": {"type": "string"}},
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]):
        if name == "echo":
            return [TextContent(type="text", text=f"{user_id}:{arguments['text']}")]
        if name == "boom":
            raise RuntimeError("kaboom")
        if name == "structured":
            return {"answer": 42}
        if name == "array-schema":
            return [TextContent(type="text", text='["a", "b"]')]
        raise ValueError(f"unknown tool {name}")

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        return [
            Resource(uri="fixture://greeting", name="greeting", mimeType="text/plain")
        ]

    @server.read_resource()
    async def read_resource(uri: str) -> Iterable[ReadResourceContents]:
        assert isinstance(uri, str)
        return [
            ReadResourceContents(content=f"hello from {uri}", mime_type="text/plain")
        ]

    return server


def get_fixture_initialization_options(
    server_instance: Server,
) -> InitializationOptions:
    return InitializationOptions(
        server_name=FIXTURE,
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(), experimental_capabilities={}
        ),
    )


# ---------------------------------------------------------------------- HTTP harness
def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RunningServer:
    def __init__(self, app, port: int):
        self.port = port
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> "RunningServer":
        self._thread.start()
        deadline = time.monotonic() + 15
        while not self._server.started:
            if time.monotonic() > deadline:  # pragma: no cover - startup failure
                raise RuntimeError("uvicorn did not start")
            time.sleep(0.02)
        return self

    def __exit__(self, *exc) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=15)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def parse_jsonrpc_response(response: httpx.Response) -> dict[str, Any]:
    """Return the JSON-RPC message of a JSON or SSE response body."""
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("text/event-stream"):
        messages = [
            json.loads(line[len("data:") :].strip())
            for line in response.text.splitlines()
            if line.startswith("data:")
        ]
        assert messages, f"no SSE data lines in response: {response.text!r}"
        return messages[-1]
    return response.json()


class Rpc:
    """Minimal JSON-RPC-over-Streamable-HTTP client."""

    def __init__(self, base_url: str, path: str):
        self.url = f"{base_url}/{path}"
        self._id = 0

    def post(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        protocol_version: str | None = None,
        notification: bool = False,
    ) -> httpx.Response:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = dict(params)
        if not notification:
            self._id += 1
            body["id"] = self._id
        headers = {"Accept": ACCEPT, "Content-Type": "application/json"}
        if protocol_version is not None:
            headers["MCP-Protocol-Version"] = protocol_version
        if (
            protocol_version is not None
            and protocol_version not in HANDSHAKE_PROTOCOL_VERSIONS
        ):
            # 2026-07-28 wire shape: no handshake, so every request carries the
            # envelope in params._meta plus the routing headers (SEP-2243).
            body.setdefault("params", {})["_meta"] = {
                PROTOCOL_VERSION_META_KEY: protocol_version,
                CLIENT_CAPABILITIES_META_KEY: {},
                CLIENT_INFO_META_KEY: {"name": "negotiation-test", "version": "0"},
            }
            headers["Mcp-Method"] = method
            name_key = NAME_BEARING_METHODS.get(method)
            if name_key is not None and name_key in body["params"]:
                headers["Mcp-Name"] = encode_header_value(body["params"][name_key])
        return httpx.post(self.url, json=body, headers=headers, timeout=30)

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        protocol_version: str | None = None,
    ) -> dict[str, Any]:
        response = self.post(method, params, protocol_version=protocol_version)
        assert response.status_code == 200, (response.status_code, response.text)
        message = parse_jsonrpc_response(response)
        assert "error" not in message, message
        return message["result"]

    def initialize(self, requested_version: str) -> dict[str, Any]:
        result = self.call(
            "initialize",
            {
                "protocolVersion": requested_version,
                "capabilities": {},
                "clientInfo": {"name": "negotiation-test", "version": "0"},
            },
        )
        ack = self.post("notifications/initialized", notification=True)
        assert ack.status_code == 202, (ack.status_code, ack.text)
        return result


@pytest.fixture(scope="module")
def fixture_app(request):
    """The real remote.py app with only the fixture server registered."""
    monkeypatch = pytest.MonkeyPatch()
    request.addfinalizer(monkeypatch.undo)
    monkeypatch.setattr(remote, "discover_servers", lambda: None)
    monkeypatch.setattr(
        remote,
        "servers",
        {
            FIXTURE: {
                "create_server": create_fixture_server,
                "get_initialization_options": get_fixture_initialization_options,
            }
        },
    )
    return remote.create_starlette_app()


@pytest.fixture(scope="module")
def running(fixture_app) -> Iterator[RunningServer]:
    with RunningServer(fixture_app, _free_port()) as server:
        yield server


@pytest.fixture
def rpc(running) -> Rpc:
    return Rpc(running.base_url, f"{FIXTURE}/test-user")


# ------------------------------------------------------------------ modern (2026-07-28)
def test_sdk_advertises_2026_07_28_as_a_modern_version():
    assert MODERN in MODERN_PROTOCOL_VERSIONS
    assert MODERN not in HANDSHAKE_PROTOCOL_VERSIONS


def test_modern_probe_server_discover_is_accepted(rpc: Rpc):
    """The first request of client 2.x: server/discover at 2026-07-28, no initialize."""
    response = rpc.post("server/discover", protocol_version=MODERN)
    assert response.status_code == 200, response.text
    assert "mcp-session-id" not in {k.lower() for k in response.headers}
    result = parse_jsonrpc_response(response)["result"]
    assert result["supportedVersions"] == [MODERN]
    assert "tools" in result["capabilities"]
    assert "resources" in result["capabilities"]


def test_modern_tools_list_and_call_without_initialize(rpc: Rpc):
    tools = rpc.call("tools/list", protocol_version=MODERN)["tools"]
    assert {t["name"] for t in tools} == {"echo", "boom", "structured", "array-schema"}
    echo = next(t for t in tools if t["name"] == "echo")
    assert echo["inputSchema"]["required"] == ["text"]

    result = rpc.call(
        "tools/call",
        {"name": "echo", "arguments": {"text": "hi"}},
        protocol_version=MODERN,
    )
    assert result["isError"] is False
    assert result["content"] == [{"type": "text", "text": "test-user:hi"}]


def test_modern_notification_is_acknowledged_with_202(rpc: Rpc):
    ack = rpc.post(
        "notifications/initialized", protocol_version=MODERN, notification=True
    )
    assert ack.status_code == 202


# ------------------------------------------------------------- legacy (initialize)
@pytest.mark.parametrize("requested", list(HANDSHAKE_PROTOCOL_VERSIONS))
def test_legacy_initialize_returns_the_requested_version(rpc: Rpc, requested: str):
    result = rpc.initialize(requested)
    assert result["protocolVersion"] == requested
    assert result["serverInfo"]["name"] == FIXTURE
    assert "tools" in result["capabilities"]


def test_legacy_initialize_with_unknown_version_falls_back_to_latest_handshake(
    rpc: Rpc,
):
    result = rpc.initialize(UNKNOWN_VERSION)
    assert result["protocolVersion"] == LATEST_HANDSHAKE_VERSION
    assert LATEST_HANDSHAKE_VERSION == "2025-11-25"


@pytest.mark.parametrize("negotiated", ["2025-06-18", "2025-11-25"])
def test_negotiated_version_header_is_accepted_on_tools_list_and_call(
    rpc: Rpc, negotiated: str
):
    """After initialize the client sends the negotiated version on every request."""
    assert rpc.initialize(negotiated)["protocolVersion"] == negotiated

    tools = rpc.call("tools/list", protocol_version=negotiated)["tools"]
    assert "echo" in {t["name"] for t in tools}

    result = rpc.call(
        "tools/call",
        {"name": "echo", "arguments": {"text": "legacy"}},
        protocol_version=negotiated,
    )
    assert result["content"][0]["text"] == "test-user:legacy"


def test_missing_header_is_served_as_a_legacy_request(rpc: Rpc):
    """Clients older than 2025-06-18 never send the header; the server must not reject them."""
    tools = rpc.call("tools/list")["tools"]
    assert "echo" in {t["name"] for t in tools}


# ------------------------------------------------------------ unsupported versions
def test_unknown_header_version_is_rejected_with_400(rpc: Rpc):
    response = rpc.post("tools/list", protocol_version=UNKNOWN_VERSION)
    assert response.status_code == 400, response.text
    error = parse_jsonrpc_response(response)["error"]
    assert "Unsupported protocol version" in error["message"]
    assert error["data"]["requested"] == UNKNOWN_VERSION
    assert error["data"]["supported"] == [MODERN]


def test_unknown_header_version_on_tools_call_is_rejected_before_dispatch(
    rpc: Rpc, monkeypatch
):
    calls: list[str] = []
    original = create_fixture_server

    def spying_create_server(user_id, api_key=None):
        calls.append(user_id)
        return original(user_id, api_key)

    monkeypatch.setitem(remote.servers[FIXTURE], "create_server", spying_create_server)
    response = rpc.post(
        "tools/call",
        {"name": "echo", "arguments": {"text": "x"}},
        protocol_version=UNKNOWN_VERSION,
    )
    assert response.status_code == 400
    # The server factory runs per request (stateless mode) but the tool never does:
    # the rejection carries no tool result.
    assert "result" not in parse_jsonrpc_response(response)


# --------------------------------------------------- mcp 1.x semantics kept by the shim
@pytest.mark.parametrize("era", [MODERN, "2025-06-18"])
def test_tool_exception_becomes_an_is_error_result(rpc: Rpc, era: str):
    if era != MODERN:
        rpc.initialize(era)
    result = rpc.call(
        "tools/call", {"name": "boom", "arguments": {}}, protocol_version=era
    )
    assert result["isError"] is True
    assert result["content"] == [{"type": "text", "text": "kaboom"}]


@pytest.mark.parametrize("era", [MODERN, "2025-06-18"])
def test_input_validation_error_is_reported_as_a_tool_error(rpc: Rpc, era: str):
    if era != MODERN:
        rpc.initialize(era)
    result = rpc.call(
        "tools/call", {"name": "echo", "arguments": {"text": 7}}, protocol_version=era
    )
    assert result["isError"] is True
    assert result["content"][0]["text"].startswith("Input validation error:")


@pytest.mark.parametrize("era", [MODERN, "2025-06-18"])
def test_missing_arguments_default_to_empty_dict(rpc: Rpc, era: str):
    if era != MODERN:
        rpc.initialize(era)
    result = rpc.call("tools/call", {"name": "structured"}, protocol_version=era)
    assert result["isError"] is False
    assert result["structuredContent"] == {"answer": 42}
    assert json.loads(result["content"][0]["text"]) == {"answer": 42}


@pytest.mark.parametrize("era", [MODERN, "2025-06-18"])
def test_resources_are_listed_and_read_with_mime_type(rpc: Rpc, era: str):
    if era != MODERN:
        rpc.initialize(era)
    resources = rpc.call("resources/list", protocol_version=era)["resources"]
    assert resources[0]["uri"] == "fixture://greeting"
    assert resources[0]["mimeType"] == "text/plain"
    contents = rpc.call(
        "resources/read", {"uri": "fixture://greeting"}, protocol_version=era
    )["contents"]
    assert contents == [
        {
            "uri": "fixture://greeting",
            "mimeType": "text/plain",
            "text": "hello from fixture://greeting",
        }
    ]


@pytest.mark.parametrize("era", [MODERN, "2025-06-18"])
def test_non_object_output_schema_is_dropped_and_the_tool_still_answers(
    rpc: Rpc, era: str
):
    if era != MODERN:
        rpc.initialize(era)
    tools = rpc.call("tools/list", protocol_version=era)["tools"]
    listed = next(t for t in tools if t["name"] == "array-schema")
    assert "outputSchema" not in listed
    structured = next(t for t in tools if t["name"] == "structured")
    assert structured["outputSchema"]["type"] == "object"

    result = rpc.call(
        "tools/call", {"name": "array-schema", "arguments": {}}, protocol_version=era
    )
    assert result["isError"] is False
    assert result["content"] == [{"type": "text", "text": '["a", "b"]'}]


# --------------------------------------------------------------- request body limit
def test_request_body_larger_than_the_sdk_default_is_accepted(rpc: Rpc):
    """mcp 2.x defaults to 4 MiB; attachment tools carry base64 payloads bigger than that."""
    payload = "a" * (6 * 1024 * 1024)
    result = rpc.call(
        "tools/call",
        {"name": "echo", "arguments": {"text": payload}},
        protocol_version=MODERN,
    )
    assert result["content"][0]["text"] == f"test-user:{payload}"


def test_request_body_above_the_configured_limit_is_rejected(rpc: Rpc):
    payload = "a" * (remote.MAX_REQUEST_BODY_SIZE + 1024)
    response = rpc.post(
        "tools/call",
        {"name": "echo", "arguments": {"text": payload}},
        protocol_version=MODERN,
    )
    assert response.status_code == 413
