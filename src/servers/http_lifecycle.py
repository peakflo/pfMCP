import contextlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

import anyio
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from prometheus_client import Counter, Gauge, Histogram
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

logger = logging.getLogger("pfmcp-server.lifecycle")

SESSION_IDLE_TTL_SECONDS = float(
    os.environ.get("PF_MCP_SESSION_IDLE_TTL_SECONDS", "300")
)
SESSION_MAX_TTL_SECONDS = float(os.environ.get("PF_MCP_SESSION_MAX_TTL_SECONDS", "900"))
SESSION_SWEEP_INTERVAL_SECONDS = float(
    os.environ.get("PF_MCP_SESSION_SWEEP_INTERVAL_SECONDS", "15")
)

http_requests_total = Counter(
    "pfmcp_http_requests_total",
    "MCP HTTP requests received by method and caller mode",
    ["method", "client_mode"],
)
sessions_opened_total = Counter(
    "pfmcp_sessions_opened_total", "Stateful MCP sessions opened", ["server"]
)
sessions_closed_total = Counter(
    "pfmcp_sessions_closed_total",
    "Stateful MCP sessions closed",
    ["server", "reason"],
)
active_sessions = Gauge(
    "pfmcp_active_sessions", "Currently active stateful MCP sessions", ["server"]
)
active_receive_streams = Gauge(
    "pfmcp_receive_streams_active",
    "Currently active standalone GET receive streams",
    ["server"],
)
receive_stream_age_seconds = Histogram(
    "pfmcp_receive_stream_age_seconds",
    "Lifetime of standalone GET receive streams",
    ["server"],
    buckets=(1, 5, 15, 30, 60, 120, 180, 240, 300, 600, float("inf")),
)
receive_stream_reconnects_total = Counter(
    "pfmcp_receive_stream_reconnects_total",
    "Standalone GET receive streams reopened for an existing session",
    ["server"],
)
receive_stream_rejections_total = Counter(
    "pfmcp_receive_stream_rejections_total",
    "Standalone GET receive streams rejected by lifecycle guard",
    ["server", "reason"],
)
get_to_post_ratio = Gauge(
    "pfmcp_get_to_post_ratio",
    "Process-local ratio of MCP GET receive streams to POST requests",
)
instance_info = Gauge(
    "pfmcp_instance_info",
    "Cloud Run instance identity baseline (one series per process)",
    ["service", "revision", "instance"],
)
instance_info.labels(
    service=os.environ.get("K_SERVICE", "local"),
    revision=os.environ.get("K_REVISION", "local"),
    instance=os.environ.get("HOSTNAME", "local"),
).set(1)

_method_counts = {"GET": 0, "POST": 0}


def _emit_lifecycle(event: str, **fields: Any) -> None:
    # A single JSON line is promoted to jsonPayload by Cloud Run logging.
    print(
        json.dumps(
            {
                "severity": "INFO",
                "component": "pfmcp_lifecycle",
                "event": event,
                **fields,
            }
        ),
        flush=True,
    )


def _header(scope: Scope, name: str) -> str | None:
    target = name.lower().encode("ascii")
    for key, value in scope.get("headers", []):
        if key.lower() == target:
            return value.decode("latin-1")
    return None


async def _json_response(
    scope: Scope, receive: Receive, send: Send, status: int, detail: str
) -> None:
    response = JSONResponse({"error": detail}, status_code=status)
    await response(scope, receive, send)


@dataclass
class SessionRecord:
    created_at: float
    last_activity_at: float
    stream_opens: int = 0


@dataclass
class EndpointState:
    server_name: str
    manager: StreamableHTTPSessionManager
    sessions: dict[str, SessionRecord] = field(default_factory=dict)
    active_streams: dict[str, float] = field(default_factory=dict)
    lock: anyio.Lock = field(default_factory=anyio.Lock)


class StreamingSessionRegistry:
    """Application-scoped stateful managers for notification-capable callers."""

    def __init__(self) -> None:
        self._states: dict[str, EndpointState] = {}
        self._state_lock = anyio.Lock()
        self._exit_stack: contextlib.AsyncExitStack | None = None

    @contextlib.asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        async with contextlib.AsyncExitStack() as stack:
            self._exit_stack = stack
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(self._sweep_loop)
                try:
                    yield
                finally:
                    task_group.cancel_scope.cancel()
                    await self.close_all("shutdown")
                    self._exit_stack = None

    async def get_or_create(
        self, endpoint_key: str, server_name: str, server_factory: Callable[[], Any]
    ) -> EndpointState:
        async with self._state_lock:
            existing = self._states.get(endpoint_key)
            if existing is not None:
                return existing
            if self._exit_stack is None:
                raise RuntimeError("Streaming session registry is not running")

            manager = StreamableHTTPSessionManager(
                app=server_factory(),
                event_store=None,
                json_response=False,
                stateless=False,
            )
            await self._exit_stack.enter_async_context(manager.run())
            state = EndpointState(server_name=server_name, manager=manager)
            self._states[endpoint_key] = state
            return state

    async def handle(
        self,
        state: EndpointState,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        method = scope["method"].upper()
        session_id = _header(scope, "mcp-session-id")

        if method == "GET":
            await self._handle_get(state, session_id, scope, receive, send)
            return

        captured_session_id: str | None = None

        async def tracked_send(message: dict) -> None:
            nonlocal captured_session_id
            if message["type"] == "http.response.start":
                for key, value in message.get("headers", []):
                    if key.lower() == b"mcp-session-id":
                        captured_session_id = value.decode("latin-1")
                        break
            await send(message)

        await state.manager.handle_request(scope, receive, tracked_send)

        resolved_session_id = session_id or captured_session_id
        if method == "POST" and resolved_session_id:
            now = time.monotonic()
            async with state.lock:
                record = state.sessions.get(resolved_session_id)
                if record is None:
                    state.sessions[resolved_session_id] = SessionRecord(now, now)
                    sessions_opened_total.labels(server=state.server_name).inc()
                    active_sessions.labels(server=state.server_name).inc()
                    _emit_lifecycle("session_opened", server=state.server_name)
                else:
                    record.last_activity_at = now
        elif method == "DELETE" and session_id:
            await self._close_session(state, session_id, "delete")

    async def _handle_get(
        self,
        state: EndpointState,
        session_id: str | None,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if not session_id:
            receive_stream_rejections_total.labels(
                server=state.server_name, reason="missing_session"
            ).inc()
            await _json_response(scope, receive, send, 400, "Missing MCP session ID")
            return

        if _header(scope, "last-event-id"):
            # This deployment has no event store. Pretending resumability exists
            # creates reconnect loops without any events to replay.
            receive_stream_rejections_total.labels(
                server=state.server_name, reason="stale_resume"
            ).inc()
            await _json_response(
                scope, receive, send, 410, "Receive stream cannot be resumed"
            )
            return

        async with state.lock:
            record = state.sessions.get(session_id)
            # MCP Python 1.12.3 does not expose session lookup/termination.
            # Keep this compatibility access isolated here and pinned by the
            # real-server tests until the SDK provides a public equivalent.
            manager_sessions = getattr(state.manager, "_server_instances", {})
            if record is None or session_id not in manager_sessions:
                receive_stream_rejections_total.labels(
                    server=state.server_name, reason="stale_session"
                ).inc()
                await _json_response(
                    scope, receive, send, 404, "Invalid or expired MCP session"
                )
                return
            if session_id in state.active_streams:
                receive_stream_rejections_total.labels(
                    server=state.server_name, reason="duplicate_stream"
                ).inc()
                await _json_response(
                    scope,
                    receive,
                    send,
                    409,
                    "Only one receive stream is allowed per MCP session",
                )
                return
            if record.stream_opens > 0:
                receive_stream_reconnects_total.labels(server=state.server_name).inc()
            record.stream_opens += 1
            record.last_activity_at = time.monotonic()
            started_at = time.monotonic()
            state.active_streams[session_id] = started_at
            active_receive_streams.labels(server=state.server_name).inc()
            _emit_lifecycle(
                "receive_stream_opened",
                server=state.server_name,
                reconnect=record.stream_opens > 1,
            )

        try:
            await state.manager.handle_request(scope, receive, send)
        finally:
            age = time.monotonic() - started_at
            async with state.lock:
                state.active_streams.pop(session_id, None)
            active_receive_streams.labels(server=state.server_name).dec()
            receive_stream_age_seconds.labels(server=state.server_name).observe(age)
            _emit_lifecycle(
                "receive_stream_closed",
                server=state.server_name,
                stream_age_seconds=round(age, 3),
            )

    async def _close_session(
        self, state: EndpointState, session_id: str, reason: str
    ) -> None:
        async with state.lock:
            record = state.sessions.pop(session_id, None)
            # See the SDK compatibility note in _handle_get.
            manager_sessions = getattr(state.manager, "_server_instances", {})
            transport = manager_sessions.pop(session_id, None)
        if transport is not None:
            await transport.terminate()
        if record is not None:
            sessions_closed_total.labels(server=state.server_name, reason=reason).inc()
            active_sessions.labels(server=state.server_name).dec()
            _emit_lifecycle("session_closed", server=state.server_name, reason=reason)

    async def _sweep_loop(self) -> None:
        while True:
            await anyio.sleep(SESSION_SWEEP_INTERVAL_SECONDS)
            now = time.monotonic()
            for state in list(self._states.values()):
                expired: list[tuple[str, str]] = []
                async with state.lock:
                    for session_id, record in state.sessions.items():
                        if now - record.created_at >= SESSION_MAX_TTL_SECONDS:
                            expired.append((session_id, "max_ttl"))
                        elif now - record.last_activity_at >= SESSION_IDLE_TTL_SECONDS:
                            expired.append((session_id, "idle_ttl"))
                for session_id, reason in expired:
                    await self._close_session(state, session_id, reason)

    async def close_all(self, reason: str) -> None:
        for state in list(self._states.values()):
            for session_id in list(state.sessions):
                await self._close_session(state, session_id, reason)
        self._states.clear()


class McpHttpLifecycle:
    def __init__(self, streaming_registry: StreamingSessionRegistry) -> None:
        self.streaming_registry = streaming_registry

    async def handle(
        self,
        endpoint_key: str,
        server_name: str,
        server_factory: Callable[[], Any],
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        method = scope["method"].upper()
        client_mode = (_header(scope, "mcp-client-mode") or "streaming").lower()
        http_requests_total.labels(method=method, client_mode=client_mode).inc()
        if method in _method_counts:
            _method_counts[method] += 1
            get_to_post_ratio.set(
                _method_counts["GET"] / max(1, _method_counts["POST"])
            )

        if client_mode == "one-shot":
            if method == "GET":
                receive_stream_rejections_total.labels(
                    server=server_name, reason="one_shot_get"
                ).inc()
                await _json_response(
                    scope,
                    receive,
                    send,
                    405,
                    "One-shot callers must use POST; receive streams are disabled",
                )
                return
            manager = StreamableHTTPSessionManager(
                app=server_factory(),
                event_store=None,
                json_response=True,
                stateless=True,
            )
            async with manager.run():
                await manager.handle_request(scope, receive, send)
            return

        state = await self.streaming_registry.get_or_create(
            endpoint_key, server_name, server_factory
        )
        await self.streaming_registry.handle(state, scope, receive, send)
