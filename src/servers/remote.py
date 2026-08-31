import logging
import os
import uvicorn
import argparse
import importlib.util
from pathlib import Path
import contextlib
from typing import AsyncIterator
from starlette.routing import Route, Mount
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.types import Receive, Scope, Send
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

# Production mode: set DEBUG=true in environment to enable debug mode
DEBUG_MODE = os.environ.get("DEBUG", "false").lower() == "true"

from mcp.server.lowlevel import Server

from http_lifecycle import McpHttpLifecycle, StreamingSessionRegistry

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("pfmcp-server")

# Dictionary to store servers
servers = {}


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


# @profile
def create_server_for_session(server_name: str, session_key_encoded: str) -> Server:
    """Create an isolated MCP server for one authenticated endpoint."""

    # Parse user_id and api_key from session_key_encoded
    user_id = None
    api_key = None

    if ":" in session_key_encoded:
        user_id = session_key_encoded.split(":")[0]
        api_key = session_key_encoded.split(":")[1]
    else:
        user_id = session_key_encoded

    # Never log session_key_encoded: pfMCP URLs may contain an API key.
    logger.info(f"Creating MCP server for {server_name} and user: {user_id}")

    # Get server factory and create server instance
    server_info = servers[server_name]
    create_server = server_info["create_server"]
    # Create and return the server instance directly
    server = create_server(user_id, api_key)

    return server


def create_starlette_app():
    """Create an app with one-shot and guarded streaming MCP lifecycles."""

    # Discover and load all servers
    discover_servers()

    streaming_registry = StreamingSessionRegistry()
    lifecycle = McpHttpLifecycle(streaming_registry)

    # Create handlers for each server
    def create_server_handler(server_name: str):
        async def handle_server_request(
            scope: Scope, receive: Receive, send: Send
        ) -> None:
            path_parts = scope["path"].strip("/").split("/")
            if len(path_parts) < 2 or path_parts[0] != server_name:
                # Return 404 if session manager couldn't be created
                response = Response("Session not found", status_code=404)
                await response(scope, receive, send)
                return

            session_key_encoded = path_parts[1]
            endpoint_key = f"{server_name}:{session_key_encoded}"
            await lifecycle.handle(
                endpoint_key,
                server_name,
                lambda: create_server_for_session(server_name, session_key_encoded),
                scope,
                receive,
                send,
            )

        return handle_server_request

    # Create routes for each server
    routes = []

    for server_name in servers.keys():
        handler = create_server_handler(server_name)

        # Mount the server handler at /{server_name}/
        routes.append(Mount(f"/{server_name}", app=handler))

        logger.info(f"Added managed routes for server: {server_name}")

    # Health checks — do not expose server list in unauthenticated endpoints
    async def root_handler(request):
        """Root endpoint that returns a simple 200 OK response"""
        return JSONResponse(
            {
                "status": "ok",
                "message": "pfMCP server running",
                "mode": "managed",
                "server_count": len(servers),
            }
        )

    routes.append(Route("/", endpoint=root_handler))

    async def health_check(request):
        """Health check endpoint"""
        return JSONResponse(
            {"status": "ok", "mode": "managed", "server_count": len(servers)}
        )

    routes.append(Route("/health_check", endpoint=health_check))

    async def metrics_endpoint(request):
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    routes.append(Route("/metrics", endpoint=metrics_endpoint))

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        """Application lifespan context manager"""
        logger.info("Application started with managed MCP lifecycle")
        async with streaming_registry.run():
            try:
                yield
            finally:
                logger.info("Application shutting down...")

    app = Starlette(
        debug=DEBUG_MODE,
        routes=routes,
        lifespan=lifespan,
    )

    return app


def main():
    """Main entry point for the Starlette server"""
    parser = argparse.ArgumentParser(description="pfMCP managed HTTP server")
    parser.add_argument("--host", default="0.0.0.0", help="Host for Starlette server")
    parser.add_argument(
        "--port", type=int, default=8000, help="Port for Starlette server"
    )

    args = parser.parse_args()

    # Run the main Starlette server
    app = create_starlette_app()
    logger.info(f"Starting managed Starlette server on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
