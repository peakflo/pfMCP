"""Every discovered server must serve ``tools/list`` on both protocol eras.

This drives the real ``remote.py`` application with the real server registry
(``discover_servers``) under uvicorn, and for each server:

* sends ``tools/list`` as a 2026-07-28 client (no handshake), and
* runs the legacy ``initialize`` handshake at 2025-06-18 and sends ``tools/list``
  with the negotiated header,

asserting both eras return the same non-empty tool names. It is the proof that
the mcp 1.x decorator API kept by ``src/utils/mcp_compat.py`` registers handlers
for all servers, not only for the fixture used by the negotiation tests. No
credentials are needed: ``create_server`` and ``list_tools`` are pure for every
server.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.servers import remote

from tests.servers.test_protocol_negotiation import (
    MODERN,
    Rpc,
    RunningServer,
    _free_port,
)

LEGACY = "2025-06-18"


@pytest.fixture(scope="module")
def real_app():
    remote.servers.clear()
    app = remote.create_starlette_app()
    assert len(remote.servers) >= 70, sorted(remote.servers)
    return app


@pytest.fixture(scope="module")
def running(real_app) -> Iterator[RunningServer]:
    with RunningServer(real_app, _free_port()) as server:
        yield server


def discovered_server_names() -> list[str]:
    remote.servers.clear()
    remote.discover_servers()
    return sorted(remote.servers)


@pytest.mark.parametrize("server_name", discovered_server_names())
def test_server_lists_the_same_tools_on_both_eras(
    running: RunningServer, server_name: str
):
    rpc = Rpc(running.base_url, f"{server_name}/era-test-user")

    modern_tools = rpc.call("tools/list", protocol_version=MODERN)["tools"]
    modern_names = sorted(t["name"] for t in modern_tools)
    assert modern_names, f"{server_name} lists no tools at {MODERN}"
    assert all(t["inputSchema"]["type"] == "object" for t in modern_tools)

    assert rpc.initialize(LEGACY)["protocolVersion"] == LEGACY
    legacy_tools = rpc.call("tools/list", protocol_version=LEGACY)["tools"]
    assert sorted(t["name"] for t in legacy_tools) == modern_names
