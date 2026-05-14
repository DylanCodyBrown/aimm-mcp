"""Pending-changes tool.

Reports the diff between a tracked table's authored columns (what's
in project.json) and the live shape from information_schema. The
agent uses this to answer "what column-shape changes would I be
deploying if I promoted these views right now?"

Single tool: aimm_get_pending_changes.
"""

from __future__ import annotations

from typing import Any

from mcp.types import TextContent, Tool

from .. import state
from ..catalog import browser
from ..parse.diff import ColumnDiff, diff_columns
from ..schemas import Column, TableMeta


TOOLS: list[Tool] = [
    Tool(
        name="aimm_get_pending_changes",
        description=(
            "Compare each tracked table's authored columns (the columns "
            "array in project.json) against the live information_schema "
            "shape. Returns per-table {added, removed, changed} columns. "
            "Use to answer 'what column-shape changes would I be "
            "deploying right now?' before promoting views. Without "
            "`table` returns every tracked table with a non-empty diff. "
            "Skips tables without a connection or staging_target."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "force": {"type": "boolean", "description": "Bypass the 5-minute catalog cache."},
            },
        },
    ),
]


async def dispatch(name: str, args: dict[str, Any]) -> list[TextContent]:
    if name == "aimm_get_pending_changes":
        return await _get_pending(args)
    raise ValueError(f"pending.dispatch: unknown tool {name}")


async def _get_pending(args: dict[str, Any]) -> list[TextContent]:
    project = state.load()
    if project is None:
        return [TextContent(type="text", text="No project initialised.")]
    table_arg = args.get("table")
    if args.get("force"):
        browser.clear_cache()

    targets: list[TableMeta] = [
        t for t in project.tables if not table_arg or t.table_name == table_arg
    ]
    if table_arg and not targets:
        return [TextContent(type="text", text=f"Unknown table '{table_arg}'.")]

    results: list[tuple[TableMeta, ColumnDiff | None, str | None]] = []
    for t in targets:
        if not t.connection or not t.staging_target or "." not in t.staging_target:
            results.append((t, None, "no connection or staging_target"))
            continue
        conn = state.find_connection(project, t.connection)
        if conn is None:
            results.append((t, None, f"connection '{t.connection}' not found"))
            continue
        schema, name = t.staging_target.split(".", 1)
        live = browser.list_columns(conn, schema, name)
        if isinstance(live, browser.CatalogFailure):
            results.append((t, None, f"{live.reason}: {live.detail}"))
            continue
        live_cols = [
            Column(
                name=c.name,
                type=c.data_type,
                nullable=c.nullable,
            )
            for c in live
        ]
        d = diff_columns(t.columns, live_cols)
        results.append((t, d, None))

    return [TextContent(type="text", text=_render(results, all_tables=table_arg is None))]


def _render(
    results: list[tuple[TableMeta, ColumnDiff | None, str | None]],
    all_tables: bool,
) -> str:
    lines: list[str] = []
    shown = 0
    skipped = 0
    for t, diff, err in results:
        if err is not None:
            if not all_tables:
                lines.append(f"[{t.table_name}] skipped — {err}")
            else:
                skipped += 1
            continue
        if diff is None:
            continue
        if all_tables and not diff.added and not diff.removed and not diff.changed:
            continue
        shown += 1
        lines.append(f"\n[{t.table_name}]  ({t.staging_target})")
        for c in diff.added:
            lines.append(f"  + {c.name}  {c.type}{' NOT NULL' if not c.nullable else ''}")
        for c in diff.removed:
            lines.append(f"  - {c.name}  {c.type}{' NOT NULL' if not c.nullable else ''}")
        for c in diff.changed:
            lines.append(
                f"  ~ {c.name}  before={c.before_type}/{'null' if c.before_nullable else 'not null'}  "
                f"after={c.after_type}/{'null' if c.after_nullable else 'not null'}"
            )

    if not lines:
        if all_tables:
            return f"No pending changes across {len(results)} tracked table(s)."
        # Single-table query with no diff entries (and no skip reason printed above).
        only = results[0][0] if results else None
        return f"No pending changes for '{only.table_name}'." if only else "No pending changes."
    header = (
        f"Pending changes ({shown} table(s) with diffs"
        + (f", {skipped} skipped" if skipped else "")
        + "):"
    )
    return header + "\n" + "\n".join(lines)
