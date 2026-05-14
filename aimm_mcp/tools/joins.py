"""Folder-scan join discovery."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from mcp.types import TextContent, Tool

from .. import paths, state
from ..discover import scan as scan_module
from ..discover import store as store_module


TOOLS: list[Tool] = [
    Tool(
        name="aimm_scan_folder_for_joins",
        description=(
            "Walk a local folder of .sql files, extract every JOIN clause via "
            "sqlglot (multi-dialect fallback: tsql → spark → none), and "
            "persist the aggregated edges to ~/Documents/AIMM/discovered_joins.json. "
            "Each unique edge is recorded once with its occurrence list (one "
            "entry per file the edge appears in). Required: `folder` (absolute "
            "path or one resolvable via cwd). Optional: `dialect` (defaults to "
            "the project's dialect from aimm.json, then trino). Skips common "
            "ignore dirs (.git, node_modules, build, etc.). Hard cap at "
            "5000 files unless `max_files` is set."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "folder": {"type": "string"},
                "dialect": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 1, "maximum": 100_000},
            },
            "required": ["folder"],
        },
    ),
]


async def dispatch(name: str, args: dict[str, Any]) -> list[TextContent]:
    if name == "aimm_scan_folder_for_joins":
        return await _scan_folder(args)
    raise ValueError(f"joins.dispatch: unknown tool {name}")


async def _scan_folder(args: dict[str, Any]) -> list[TextContent]:
    paths.ensure_layout()
    folder = args.get("folder")
    if not folder:
        return [TextContent(type="text", text="Error: `folder` is required.")]
    root = Path(folder).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return [TextContent(type="text", text=f"Folder not found: {root}")]

    dialect = args.get("dialect")
    if dialect is None:
        project = state.load()
        dialect = project.project.dialect if project else None
    max_files = int(args.get("max_files") or 5000)

    started = time.monotonic()
    result = scan_module.scan_folder(root, dialect=dialect, max_files=max_files)
    elapsed_ms = int((time.monotonic() - started) * 1000)

    persisted = store_module.write_store(
        relationships=result.relationships,
        source_location=str(root),
        files_scanned=result.files_scanned,
    )

    summary_lines = [
        f"Scanned {result.files_scanned} file(s) in {elapsed_ms}ms ({result.files_skipped} skipped).",
        f"Found {len(result.relationships)} candidate relationship(s).",
        f"Wrote: {persisted}",
    ]
    if result.errors:
        summary_lines.append(f"Parse errors: {len(result.errors)}.")
        first = result.errors[0]
        summary_lines.append(f"  first: {first.file} — {first.message[:120]}")
    return [TextContent(type="text", text="\n".join(summary_lines))]
