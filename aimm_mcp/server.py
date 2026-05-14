"""MCP server entry. Wires tool listing + dispatch onto the SDK's
stdio transport.

Lifecycle: Claude Code (or any MCP client) spawns this process via
`uvx aimm-mcp`, talks JSON-RPC over stdin/stdout. We register every
tool from `aimm_mcp.tools` and let the SDK drive the protocol.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import paths, tools


_log = logging.getLogger("aimm-mcp")


def _build_server() -> Server:
    server = Server("aimm-mcp")

    @server.list_tools()  # type: ignore[no-untyped-call]
    async def _list_tools() -> list[Tool]:
        return tools.all_tools()

    @server.call_tool()  # type: ignore[no-untyped-call]
    async def _call_tool(name: str, arguments: dict | None) -> list[TextContent]:
        try:
            return await tools.dispatch(name, arguments or {})
        except Exception as err:  # noqa: BLE001
            # Surface failures to the agent as a text response instead
            # of crashing the server — the agent can read the message
            # and adjust. Keeps the session alive for the next call.
            _log.exception("tool dispatch failed for %s", name)
            return [TextContent(type="text", text=f"Error in {name}: {err}")]

    return server


async def run() -> None:
    paths.ensure_layout()
    # Every information_schema query the runner issues from here on
    # writes one line to AIMM/diagnostics.log.
    from .diagnostics.log import FileQueryLogger
    from .odbc.runner import set_query_logger
    set_query_logger(FileQueryLogger(paths.diagnostics_log_path()))
    server = _build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> int:
    """`uvx aimm-mcp` entry point."""
    # Logging to stderr so it doesn't pollute the stdio JSON-RPC
    # stream. Level configurable via env if/when we need it.
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        return 130
    return 0
