"""Decorator-style handler registration on top of the mcp 2.x low-level ``Server``.

mcp 2.0 removed the decorator API of the low-level ``Server`` (``@server.list_tools()``,
``@server.call_tool()``, ``@server.read_resource()``, ...) together with the automatic
wrapping of handler return values and the conversion of tool exceptions into
``CallToolResult(is_error=True)``. Every pfMCP server is written against that API,
so this module restores it as a thin subclass. The semantics are copied from
``mcp.server.lowlevel.server.Server`` at 1.12.3 so that a server module behaves the
same on the wire before and after the SDK upgrade:

* ``list_tools`` / ``list_resources`` / ``list_resource_templates`` / ``list_prompts``
  return bare lists that are wrapped into the matching ``*Result``.
* ``call_tool`` receives ``(name, arguments)``; ``arguments`` defaults to ``{}``;
  arguments are validated against the tool's ``inputSchema`` (and structured output
  against ``outputSchema``); the return value may be an iterable of content blocks,
  a ``dict`` (structured content), or a ``(content, structured)`` tuple; any
  exception becomes ``CallToolResult(is_error=True)`` so the calling model can see it.
* ``read_resource`` receives the URI (a plain ``str`` in mcp 2.x — it was an
  ``AnyUrl`` in 1.x) and returns an iterable of ``ReadResourceContents``.
* ``get_prompt`` receives ``(name, arguments)`` and returns a ``GetPromptResult``.

``Server.dispatch`` replaces the removed ``server.request_handlers[RequestType]``
dictionary for in-process callers (the Peakflo composite server and the offline
tests). It runs the registered handler for a v1-style request object and returns
the bare result, without ``ServerResult.root`` indirection.
"""

from __future__ import annotations

import base64
import json
import logging
import warnings
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, cast

import jsonschema

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import NotificationOptions
from mcp.server.lowlevel import Server as _LowLevelServer
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types.version import LATEST_HANDSHAKE_VERSION

__all__ = ["NotificationOptions", "ReadResourceContents", "Server"]

logger = logging.getLogger(__name__)

UnstructuredContent = Iterable[types.ContentBlock]
StructuredContent = dict[str, Any]
CombinationContent = tuple[UnstructuredContent, StructuredContent]


def _error_result(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)],
        is_error=True,
    )


def drop_invalid_output_schemas(server_name: str, tools: list[types.Tool]) -> None:
    """Remove ``outputSchema`` declarations whose root type is not ``object``.

    The MCP schema (2025-06-18 and later) requires a tool's ``outputSchema`` to
    be an object schema, and mcp 2.x validates every ``tools/list`` result
    against it: one tool advertising ``{"type": "array"}`` fails the whole
    listing for that server. Seventeen pfMCP servers carry such declarations.
    None of their tools return structured content, so under mcp 1.12.3 every
    successful call to them was answered with ``Output validation error:
    outputSchema defined but no structured output returned``; dropping the
    declaration keeps the listing valid and lets the text result through.
    """
    dropped: list[str] = []
    for tool in tools:
        schema = tool.output_schema
        if schema is not None and schema.get("type") != "object":
            tool.output_schema = None
            dropped.append(tool.name)
    if dropped:
        logger.warning(
            "%s: dropped non-object outputSchema from %d tool(s): %s",
            server_name,
            len(dropped),
            ", ".join(dropped),
        )


class Server(_LowLevelServer[Any]):
    """Low-level MCP server with the 1.x decorator registration API."""

    def __init__(self, name: str, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self._pf_tool_cache: dict[str, types.Tool] = {}
        self._pf_list_tools: Callable[[], Awaitable[list[types.Tool]]] | None = None

    # ------------------------------------------------------------------ tools
    def list_tools(self):
        def decorator(func: Callable[[], Awaitable[list[types.Tool]]]):
            self._pf_list_tools = func

            async def handler(
                _ctx: ServerRequestContext[Any],
                _params: types.PaginatedRequestParams | None,
            ) -> types.ListToolsResult:
                tools = await func()
                drop_invalid_output_schemas(self.name, tools)
                self._pf_tool_cache.clear()
                for tool in tools:
                    self._pf_tool_cache[tool.name] = tool
                return types.ListToolsResult(tools=tools)

            self.add_request_handler(
                "tools/list", types.PaginatedRequestParams, handler
            )
            return func

        return decorator

    async def _get_cached_tool_definition(self, tool_name: str) -> types.Tool | None:
        if tool_name not in self._pf_tool_cache and self._pf_list_tools is not None:
            logger.debug("Tool cache miss for %s, refreshing cache", tool_name)
            tools = await self._pf_list_tools()
            drop_invalid_output_schemas(self.name, tools)
            self._pf_tool_cache.clear()
            for tool in tools:
                self._pf_tool_cache[tool.name] = tool
        tool = self._pf_tool_cache.get(tool_name)
        if tool is None:
            logger.warning(
                "Tool '%s' not listed, no validation will be performed", tool_name
            )
        return tool

    def call_tool(self, *, validate_input: bool = True):
        def decorator(
            func: Callable[
                ...,
                Awaitable[UnstructuredContent | StructuredContent | CombinationContent],
            ],
        ):
            async def handler(
                _ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
            ) -> types.CallToolResult:
                try:
                    tool_name = params.name
                    arguments = params.arguments or {}
                    tool = await self._get_cached_tool_definition(tool_name)

                    if validate_input and tool:
                        try:
                            jsonschema.validate(
                                instance=arguments, schema=tool.input_schema
                            )
                        except jsonschema.ValidationError as e:
                            return _error_result(f"Input validation error: {e.message}")

                    results = await func(tool_name, arguments)

                    unstructured_content: UnstructuredContent
                    maybe_structured_content: StructuredContent | None
                    if isinstance(results, tuple) and len(results) == 2:
                        unstructured_content, maybe_structured_content = cast(
                            CombinationContent, results
                        )
                    elif isinstance(results, dict):
                        maybe_structured_content = cast(StructuredContent, results)
                        unstructured_content = [
                            types.TextContent(
                                type="text", text=json.dumps(results, indent=2)
                            )
                        ]
                    elif hasattr(results, "__iter__"):
                        unstructured_content = cast(UnstructuredContent, results)
                        maybe_structured_content = None
                    else:
                        return _error_result(
                            f"Unexpected return type from tool: {type(results).__name__}"
                        )

                    if tool and tool.output_schema is not None:
                        if maybe_structured_content is None:
                            return _error_result(
                                "Output validation error: outputSchema defined but no structured output returned"
                            )
                        try:
                            jsonschema.validate(
                                instance=maybe_structured_content,
                                schema=tool.output_schema,
                            )
                        except jsonschema.ValidationError as e:
                            return _error_result(
                                f"Output validation error: {e.message}"
                            )

                    return types.CallToolResult(
                        content=list(unstructured_content),
                        structured_content=maybe_structured_content,
                        is_error=False,
                    )
                except Exception as e:  # noqa: BLE001 - mirrors mcp 1.x behaviour
                    return _error_result(str(e))

            self.add_request_handler("tools/call", types.CallToolRequestParams, handler)
            return func

        return decorator

    # -------------------------------------------------------------- resources
    def list_resources(self):
        def decorator(func: Callable[[], Awaitable[list[types.Resource]]]):
            async def handler(
                _ctx: ServerRequestContext[Any],
                _params: types.PaginatedRequestParams | None,
            ) -> types.ListResourcesResult:
                return types.ListResourcesResult(resources=await func())

            self.add_request_handler(
                "resources/list", types.PaginatedRequestParams, handler
            )
            return func

        return decorator

    def list_resource_templates(self):
        def decorator(func: Callable[[], Awaitable[list[types.ResourceTemplate]]]):
            async def handler(
                _ctx: ServerRequestContext[Any],
                _params: types.PaginatedRequestParams | None,
            ) -> types.ListResourceTemplatesResult:
                return types.ListResourceTemplatesResult(
                    resource_templates=await func()
                )

            self.add_request_handler(
                "resources/templates/list", types.PaginatedRequestParams, handler
            )
            return func

        return decorator

    def read_resource(self):
        def decorator(
            func: Callable[
                [str], Awaitable[str | bytes | Iterable[ReadResourceContents]]
            ],
        ):
            async def handler(
                _ctx: ServerRequestContext[Any], params: types.ReadResourceRequestParams
            ) -> types.ReadResourceResult:
                uri = params.uri
                result = await func(uri)

                def create_content(data: str | bytes, mime_type: str | None):
                    if isinstance(data, str):
                        return types.TextResourceContents(
                            uri=uri, text=data, mime_type=mime_type or "text/plain"
                        )
                    if isinstance(data, bytes):
                        return types.BlobResourceContents(
                            uri=uri,
                            blob=base64.b64encode(data).decode(),
                            mime_type=mime_type or "application/octet-stream",
                        )
                    raise ValueError(
                        f"Unexpected resource content type: {type(data).__name__}"
                    )

                if isinstance(result, (str, bytes)):
                    warnings.warn(
                        "Returning str or bytes from read_resource is deprecated. "
                        "Use Iterable[ReadResourceContents] instead.",
                        DeprecationWarning,
                        stacklevel=2,
                    )
                    contents = [create_content(result, None)]
                elif isinstance(result, Iterable):
                    contents = [
                        create_content(item.content, item.mime_type) for item in result
                    ]
                else:
                    raise ValueError(
                        f"Unexpected return type from read_resource: {type(result)}"
                    )
                return types.ReadResourceResult(contents=contents)

            self.add_request_handler(
                "resources/read", types.ReadResourceRequestParams, handler
            )
            return func

        return decorator

    # ---------------------------------------------------------------- prompts
    def list_prompts(self):
        def decorator(func: Callable[[], Awaitable[list[types.Prompt]]]):
            async def handler(
                _ctx: ServerRequestContext[Any],
                _params: types.PaginatedRequestParams | None,
            ) -> types.ListPromptsResult:
                return types.ListPromptsResult(prompts=await func())

            self.add_request_handler(
                "prompts/list", types.PaginatedRequestParams, handler
            )
            return func

        return decorator

    def get_prompt(self):
        def decorator(
            func: Callable[
                [str, dict[str, str] | None], Awaitable[types.GetPromptResult]
            ],
        ):
            async def handler(
                _ctx: ServerRequestContext[Any], params: types.GetPromptRequestParams
            ) -> types.GetPromptResult:
                return await func(params.name, params.arguments)

            self.add_request_handler(
                "prompts/get", types.GetPromptRequestParams, handler
            )
            return func

        return decorator

    # ------------------------------------------------------------- in-process
    async def dispatch(self, request: Any) -> Any:
        """Run the registered handler for a v1-style request object, in process.

        ``request`` is any ``mcp.types`` request model (``ListToolsRequest``,
        ``CallToolRequest``, ...). The handler receives a context without a client
        session, so it must not call back into the client. Returns the bare result
        (for example ``CallToolResult``), not a ``ServerResult`` wrapper.
        """
        method: str = request.method
        entry = self.get_request_handler(method)
        if entry is None:
            raise KeyError(f"No handler registered for {method!r}")
        raw_params = getattr(request, "params", None)
        params_dict: dict[str, Any] = (
            {}
            if raw_params is None
            else raw_params.model_dump(by_alias=True, exclude_unset=True)
        )
        typed_params = entry.params_type.model_validate(params_dict, by_name=False)
        ctx: ServerRequestContext[Any] = ServerRequestContext(
            session=cast(Any, None),
            lifespan_context={},
            protocol_version=LATEST_HANDSHAKE_VERSION,
            method=method,
            params=params_dict,
        )
        return await entry.handler(ctx, typed_params)
