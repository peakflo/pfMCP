import logging
import uvicorn
import argparse
import importlib.util
from pathlib import Path
import threading
import contextlib
import time
import json
from memory_profiler import profile
from typing import Dict, Any, AsyncIterator
from starlette.routing import Route, Mount
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.types import Receive, Scope, Send
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

from mcp.server.lowlevel import Server
from mcp.server import streamable_http_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("gumcp-server")

# Dictionary to store servers
servers = {}

# Prometheus metrics
active_connections = Gauge(
    "gumcp_active_connections", "Number of active SSE connections", ["server"]
)
connection_total = Counter(
    "gumcp_connection_total", "Total number of SSE connections", ["server"]
)

# Default metrics port
METRICS_PORT = 9091


@profile
def debug_session_store(event: str, session_id: str = None):
    """Debug session management state with structured JSON logging

    Args:
        event: Description of the event that triggered this debug log
        session_id: Optional specific session to look for. If None, shows all sessions.
    """

    debug_data = {
        "event": event,
        "timestamp": time.time(),
        "session_id": session_id,
        "stateless_mode": True,
    }

    logger.debug(f"SESSION_DEBUG: {json.dumps(debug_data, indent=2)}")


@profile
def discover_servers():
    """Discover and load all servers from the servers directory"""
    # Get the path to the servers directory
    servers_dir = Path(__file__).parent.absolute()

    logger.info(f"Looking for servers in {servers_dir}")

    # Iterate through all directories in the servers directory
    for item in servers_dir.iterdir():
        if item.is_dir():
            server_name = item.name
            server_file = item / "main.py"

            if server_file.exists():
                try:
                    # Load the server module
                    spec = importlib.util.spec_from_file_location(
                        f"{server_name}.server", server_file
                    )
                    server_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(server_module)

                    # Get the server and initialization options from the module
                    if hasattr(server_module, "create_server") and hasattr(
                        server_module, "get_initialization_options"
                    ):
                        create_server = server_module.create_server
                        get_init_options = server_module.get_initialization_options

                        # Store the server factory and init options
                        servers[server_name] = {
                            "create_server": create_server,
                            "get_initialization_options": get_init_options,
                        }
                        logger.info(f"Loaded server: {server_name}")
                    else:
                        logger.warning(
                            f"Server {server_name} does not have required create_server or get_initialization_options"
                        )
                except Exception as e:
                    logger.error(f"Failed to load server {server_name}: {e}")

    logger.info(f"Discovered {len(servers)} servers")


@profile
def create_metrics_app():
    """Create a separate Starlette app just for metrics"""

    @profile
    async def metrics_endpoint(request):
        """Prometheus metrics endpoint"""
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    routes = [Route("/metrics", endpoint=metrics_endpoint)]

    app = Starlette(
        debug=True,
        routes=routes,
    )

    return app


@profile
def create_server_for_session(server_name: str, session_key_encoded: str) -> Server:
    """Create a stateless MCP server for a specific session"""

    # Parse user_id and api_key from session_key_encoded
    user_id = None
    api_key = None

    if ":" in session_key_encoded:
        user_id = session_key_encoded.split(":")[0]
        api_key = session_key_encoded.split(":")[1]
    else:
        user_id = session_key_encoded

    session_key = f"{server_name}:{session_key_encoded}"

    logger.info(f"Creating stateless server for {server_name} with session: {user_id}")

    # Debug session state
    debug_session_store("stateless_server_creation", session_key)

    # Get server factory and create server instance
    server_info = servers[server_name]
    create_server = server_info["create_server"]
    get_init_options = server_info["get_initialization_options"]

    # Create and return the server instance directly
    server = create_server(user_id, api_key)

    # Increment metrics
    connection_total.labels(server=server_name).inc()

    return server


@profile
def create_starlette_app():
    """Create a Starlette app with stateless MCP servers"""

    # Discover and load all servers
    discover_servers()

    # Create session managers for each server
    session_managers = {}

    for server_name in servers.keys():
        # Create a session manager factory for this server
        @profile
        def create_session_manager_for_server(name):
            @profile
            def session_manager_factory(scope: Scope):
                # Extract session_key from the path
                path_parts = scope["path"].strip("/").split("/")
                if len(path_parts) >= 2 and path_parts[0] == name:
                    session_key_encoded = path_parts[1]

                    # Create server for this session
                    server = create_server_for_session(name, session_key_encoded)

                    # Create session manager with stateless mode
                    return streamable_http_manager.StreamableHTTPSessionManager(
                        app=server,
                        event_store=None,
                        json_response=False,
                        stateless=True,
                    )
                return None

            return session_manager_factory

        session_managers[server_name] = create_session_manager_for_server(server_name)

    # Create handlers for each server
    @profile
    def create_server_handler(server_name: str):
        @profile
        async def handle_server_request(
            scope: Scope, receive: Receive, send: Send
        ) -> None:
            session_manager = session_managers[server_name](scope)
            if session_manager:
                async with session_manager.run():
                    await session_manager.handle_request(scope, receive, send)
            else:
                # Return 404 if session manager couldn't be created
                response = Response("Session not found", status_code=404)
                await response(scope, receive, send)

        return handle_server_request

    # Create routes for each server
    routes = []

    for server_name in servers.keys():
        handler = create_server_handler(server_name)

        # Mount the server handler at /{server_name}/
        routes.append(Mount(f"/{server_name}", app=handler))

        logger.info(f"Added stateless routes for server: {server_name}")

    # Health checks
    @profile
    async def root_handler(request):
        """Root endpoint that returns a simple 200 OK response"""
        return JSONResponse(
            {
                "status": "ok",
                "message": "guMCP stateless server running",
                "servers": list(servers.keys()),
                "mode": "stateless",
            }
        )

    routes.append(Route("/", endpoint=root_handler))

    @profile
    async def health_check(request):
        """Health check endpoint"""
        return JSONResponse(
            {"status": "ok", "servers": list(servers.keys()), "mode": "stateless"}
        )

    routes.append(Route("/health_check", endpoint=health_check))

    @contextlib.asynccontextmanager
    @profile
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        """Application lifespan context manager"""
        logger.info("Application started with stateless MCP servers!")
        try:
            yield
        finally:
            logger.info("Application shutting down...")

    app = Starlette(
        debug=True,
        routes=routes,
        lifespan=lifespan,
    )

    return app


@profile
def run_metrics_server(host, port):
    """Run a separate metrics server on the specified port"""
    metrics_app = create_metrics_app()
    logger.info(f"Starting metrics server on {host}:{port}")
    uvicorn.run(metrics_app, host=host, port=port)


@profile
def main():
    """Main entry point for the Starlette server"""
    parser = argparse.ArgumentParser(description="guMCP Stateless Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host for Starlette server")
    parser.add_argument(
        "--port", type=int, default=8000, help="Port for Starlette server"
    )

    args = parser.parse_args()

    # Start metrics server in background
    metrics_thread = threading.Thread(
        target=run_metrics_server, args=(args.host, METRICS_PORT), daemon=True
    )
    metrics_thread.start()
    logger.info(f"Starting Metrics server on http://{args.host}:{METRICS_PORT}/metrics")

    # Run the main Starlette server
    app = create_starlette_app()
    logger.info(f"Starting stateless Starlette server on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
