"""Diagnostics tools.

  - aimm_show_diagnostics_log   tail of the ODBC query log
"""

from __future__ import annotations

from typing import Any

from mcp.types import TextContent, Tool

from .. import paths
from ..diagnostics.log import tail_log


TOOLS: list[Tool] = [
    Tool(
        name="aimm_show_diagnostics_log",
        description=(
            "Return the tail of ~/Documents/AIMM/diagnostics.log, where the "
            "server records every information_schema / browse / refresh "
            "query it issues. Use this when a tool reports a connect_failed "
            "/ query_failed / no_native_odbc result and you want the exact "
            "SQL the server ran. Defaults to the last 32 KB (≈300 lines on "
            "a typical run). `max_bytes` overrides; capped at 256 KB."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "max_bytes": {"type": "integer", "minimum": 1024, "maximum": 262_144},
            },
        },
    ),
]


async def dispatch(name: str, args: dict[str, Any]) -> list[TextContent]:
    if name == "aimm_show_diagnostics_log":
        return await _show_log(args)
    raise ValueError(f"diagnostics.dispatch: unknown tool {name}")


async def _show_log(args: dict[str, Any]) -> list[TextContent]:
    max_bytes = int(args.get("max_bytes") or 32 * 1024)
    body = tail_log(paths.diagnostics_log_path(), max_bytes=max_bytes)
    if not body:
        return [TextContent(
            type="text",
            text="No diagnostics yet — no information_schema queries have run in this session.",
        )]
    return [TextContent(
        type="text",
        text=f"--- last {len(body)} bytes of {paths.diagnostics_log_path()} ---\n{body}",
    )]
