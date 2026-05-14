"""Diagram + JSON-export regeneration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.types import TextContent, Tool

from .. import paths, repo
from ..mermaid import builders


TOOLS: list[Tool] = [
    Tool(
        name="aimm_regenerate_mermaid",
        description=(
            "Regenerate the project's derived artefacts in one pass:\n"
            "  - AIMM/model.mmd           ER diagram (mermaid)\n"
            "  - AIMM/model_lineage.mmd   upstream→downstream flowchart\n"
            "  - AIMM/lineage.json        flat lineage edge list\n"
            "  - AIMM/relationships.json  flat FK edge list\n"
            "  - AIMM/joins.json          project-tracked joins\n"
            "joins.json sources both per-table relationships and joins "
            "extracted from any tracked SQL file via sqlglot. Same canonical "
            "id collapses an FK + matching extracted join onto one entry."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
]


async def dispatch(name: str, args: dict[str, Any]) -> list[TextContent]:
    if name == "aimm_regenerate_mermaid":
        return await _regenerate(args)
    raise ValueError(f"diagrams.dispatch: unknown tool {name}")


async def _regenerate(_: dict[str, Any]) -> list[TextContent]:
    paths.ensure_layout()
    tables = list(repo.iter_tables())

    # Per-tracked-SQL-file join extraction. Tables without a
    # sourcePath (DB-only) contribute their FK relationships but no
    # extracted-SQL sources. Each file is read with errors='replace'
    # so a stray non-UTF-8 byte in one file doesn't take down the
    # whole regenerate.
    extracted: list[tuple[str, list[dict]]] = []
    cfg = repo.read_project()
    dialect = cfg.dialect if cfg else None
    for t in tables:
        if not t.source_file:
            continue
        src = Path(t.source_file).expanduser()
        if not src.is_absolute():
            # Per-table JSON stores workspace-relative paths; resolve
            # against the user's home as a best-effort fallback when
            # the path is relative.
            src = Path.home() / t.source_file
        if not src.exists():
            continue
        try:
            sql = src.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        from ..parse.joins import extract_joins  # local import to avoid cycle on cold start
        result = extract_joins(sql, dialect=dialect, file=t.source_file)
        extracted.append((t.source_file, result.get("joins", [])))

    # Build all artefacts in memory first, then write atomically so
    # an error mid-build never leaves the AIMM folder half-updated.
    er_mmd = builders.render_er_diagram(tables)
    lineage_mmd = builders.render_lineage_flowchart(tables)
    lineage_doc = builders.build_lineage_doc(tables)
    relationships_doc = builders.build_relationships_doc(tables)
    joins_doc = builders.build_joins_doc(tables, extracted)

    paths.mermaid_er_path().write_text(er_mmd, encoding="utf-8")
    paths.mermaid_lineage_path().write_text(lineage_mmd, encoding="utf-8")
    paths.lineage_json_path().write_text(json.dumps(lineage_doc, indent=2) + "\n", encoding="utf-8")
    paths.relationships_json_path().write_text(json.dumps(relationships_doc, indent=2) + "\n", encoding="utf-8")
    paths.joins_json_path().write_text(json.dumps(joins_doc, indent=2) + "\n", encoding="utf-8")

    return [TextContent(
        type="text",
        text=(
            f"Regenerated artefacts in {paths.aimm_root()}:\n"
            f"  - model.mmd             ({len(tables)} table(s))\n"
            f"  - model_lineage.mmd     ({len(lineage_doc['edges'])} lineage edge(s))\n"
            f"  - lineage.json          ({len(lineage_doc['edges'])} edge(s))\n"
            f"  - relationships.json    ({len(relationships_doc['edges'])} edge(s))\n"
            f"  - joins.json            ({len(joins_doc['joins'])} join(s) across "
            f"{len(extracted)} tracked SQL file(s))"
        ),
    )]
