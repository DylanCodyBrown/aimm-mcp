"""Diagram + JSON-export regeneration.

Exposes `aimm_regenerate_mermaid` as a manual tool AND installs the
auto-regenerate hook on `state.set_after_mutation_hook`, so every
mutation through the state layer refreshes the derived artefacts in
real time. Server boot calls `install_auto_regenerate()` once.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.types import TextContent, Tool

from .. import paths, state
from ..mermaid import builders
from ..schemas import Project


TOOLS: list[Tool] = [
    Tool(
        name="aimm_regenerate_mermaid",
        description=(
            "Manually regenerate every derived artefact in one pass:\n"
            "  - AIMM/model.mmd            ER diagram (mermaid)\n"
            "  - AIMM/model_lineage.mmd    upstream→downstream flowchart\n"
            "  - AIMM/lineage.json         flat lineage edge list\n"
            "  - AIMM/relationships.json   flat FK edge list\n"
            "  - AIMM/joins.json           project-tracked joins\n"
            "  - AIMM/project_context.xml  agent-facing XML dump\n"
            "These are also regenerated automatically on every project "
            "mutation; this tool is for the occasional manual refresh."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
]


async def dispatch(name: str, args: dict[str, Any]) -> list[TextContent]:
    if name == "aimm_regenerate_mermaid":
        return await _regenerate(args)
    raise ValueError(f"diagrams.dispatch: unknown tool {name}")


async def _regenerate(_: dict[str, Any]) -> list[TextContent]:
    project = state.load()
    if project is None:
        return [TextContent(type="text", text="No project initialised; nothing to regenerate.")]
    counts = regenerate_all(project)
    return [TextContent(
        type="text",
        text=(
            f"Regenerated artefacts in {paths.aimm_root()}:\n"
            f"  - model.mmd             ({counts['tables']} table(s))\n"
            f"  - model_lineage.mmd     ({counts['lineage_edges']} lineage edge(s))\n"
            f"  - lineage.json          ({counts['lineage_edges']} edge(s))\n"
            f"  - relationships.json    ({counts['rel_edges']} edge(s))\n"
            f"  - joins.json            ({counts['joins']} join(s) across "
            f"{counts['tracked_sql_files']} tracked SQL file(s))\n"
            f"  - project_context.xml   (XML dump)"
        ),
    )]


def install_auto_regenerate() -> None:
    """Wire the regenerate-on-every-mutation behaviour into state.py.
    Called once from server.py at boot."""
    def hook(project: Project) -> None:
        regenerate_all(project)
    state.set_after_mutation_hook(hook)


def regenerate_all(project: Project) -> dict[str, int]:
    """Write every derived artefact. Returns small counts for logging."""
    paths.ensure_layout()
    tables = project.tables

    # Per-tracked-SQL-file join extraction.
    extracted: list[tuple[str, list[dict]]] = []
    dialect = project.project.dialect
    for t in tables:
        if not t.source_file:
            continue
        src = Path(t.source_file).expanduser()
        if not src.is_absolute():
            src = Path.home() / t.source_file
        if not src.exists():
            continue
        try:
            sql = src.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        from ..parse.joins import extract_joins
        result = extract_joins(sql, dialect=dialect, file=t.source_file)
        extracted.append((t.source_file, result.get("joins", [])))

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

    # project_context.xml — agent-facing XML rendering of the unified
    # project. Reads joins.json off disk (just written above) so the
    # <joins> block matches.
    try:
        from ..format_context import format_project_context
        body = format_project_context(
            project.project,
            project.connections,
            tables,
            joins_doc=joins_doc,
            fmt="xml",
        )
        paths.context_xml_path().write_text(body, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    return {
        "tables": len(tables),
        "lineage_edges": len(lineage_doc["edges"]),
        "rel_edges": len(relationships_doc["edges"]),
        "joins": len(joins_doc["joins"]),
        "tracked_sql_files": len(extracted),
    }
