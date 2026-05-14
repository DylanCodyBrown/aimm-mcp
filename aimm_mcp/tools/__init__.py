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

from . import connections, diagnostics, joins, pending, project, semantic, session, tables


# Order shapes the tool list returned to clients. Session tools go
# first so the agent's "discover what's here" reflex lands on
# aimm_show_active_project / aimm_list_projects before anything
# project-touching. Semantic tools sit alongside tables since they
# operate on the same project document.
GROUPS = [session, project, connections, tables, semantic, joins, diagnostics, pending]


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
