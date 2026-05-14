"""Tool registry.

Each `tools/<group>.py` exposes:

  - `TOOLS: list[Tool]` — MCP tool definitions for the group.
  - `async def dispatch(name, arguments)` — handler that returns a
    list[TextContent] or raises if the name isn't its responsibility.

This module aggregates them so `server.py` has exactly two handlers
to wire (list_tools, call_tool) regardless of how many groups exist.
Adding a new tool is one file + one entry in `GROUPS`.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from mcp.types import TextContent, Tool

from . import connections, diagnostics, joins, pending, project, tables


GROUPS = [project, connections, tables, joins, diagnostics, pending]


def all_tools() -> list[Tool]:
    out: list[Tool] = []
    for g in GROUPS:
        out.extend(g.TOOLS)
    return out


async def dispatch(name: str, arguments: dict) -> list[TextContent]:
    for g in GROUPS:
        if any(t.name == name for t in g.TOOLS):
            return await g.dispatch(name, arguments)
    raise ValueError(f"unknown tool: {name}")
