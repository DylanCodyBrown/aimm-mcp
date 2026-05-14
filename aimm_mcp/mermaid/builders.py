"""All four derived artefacts in one module:

  - model.mmd           ER diagram (`erDiagram` syntax)
  - model_lineage.mmd   `flowchart LR` of upstream → downstream
  - lineage.json        flat upstream edges
  - relationships.json  flat FK edges
  - joins.json          project-tracked joins (per-table relationships
                        + joins extracted from tracked SQL files via
                        sqlglot, when a sourcePath is known)

Each builder is a pure function over project state — no fs, no
sidecar. The MCP `aimm_regenerate_mermaid` tool wraps these and
writes the files.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from ..parse.joins import extract_joins
from ..schemas import TableMeta


# ---------------------------------------------------------------------------
# Mermaid ER diagram
# ---------------------------------------------------------------------------


def render_er_diagram(tables: list[TableMeta]) -> str:
    """Render an `erDiagram` body. PK columns only (full columns would
    dominate the diagram visually); FK edges from each table's
    `relationships` array."""
    lines: list[str] = ["erDiagram"]
    if not tables:
        # Mermaid requires at least one entity to render — emit a
        # placeholder so the file is always valid.
        lines.append('    "_empty" {')
        lines.append("        string note")
        lines.append("    }")
        return "\n".join(lines) + "\n"

    for t in tables:
        safe = _safe_identifier(t.table_name)
        lines.append(f'    "{safe}" {{')
        pk_set = set(t.primary_keys)
        # If primary_keys is set, prefer it; else fall back to
        # is_primary_key flags on columns.
        for col in t.columns:
            if col.is_primary_key or col.name in pk_set:
                lines.append(f"        {_safe_type(col.type)} {_safe_identifier(col.name)} PK")
        lines.append("    }")

    for t in tables:
        for rel in t.relationships:
            cardinality = _cardinality_arrow(rel.cardinality)
            from_safe = _safe_identifier(t.table_name)
            to_safe = _safe_identifier(rel.to_table)
            label = ", ".join(rel.from_columns) or "fk"
            lines.append(f'    "{from_safe}" {cardinality} "{to_safe}" : "{label}"')

    return "\n".join(lines) + "\n"


def _cardinality_arrow(c: str) -> str:
    return {
        "one_to_one": "||--||",
        "one_to_many": "||--o{",
        "many_to_many": "}o--o{",
    }.get(c, "||--o{")


def _safe_identifier(name: str) -> str:
    # Mermaid identifiers don't love hyphens or spaces; replace with
    # underscores in the diagram, keep originals everywhere else.
    return name.replace(" ", "_").replace("-", "_").replace(".", "_")


def _safe_type(t: str) -> str:
    # Mermaid's erDiagram parser is picky about the type token's
    # shape. Strip parens / commas so `varchar(255)` becomes
    # `varchar255` etc.
    if not t:
        return "unknown"
    return (t.replace("(", "_").replace(")", "").replace(",", "_").replace(" ", "_") or "unknown")


# ---------------------------------------------------------------------------
# Mermaid lineage flowchart
# ---------------------------------------------------------------------------


def render_lineage_flowchart(tables: list[TableMeta]) -> str:
    lines: list[str] = ["flowchart LR"]
    nodes: set[str] = set()
    edges: list[tuple[str, str]] = []
    for t in tables:
        nodes.add(t.table_name)
        for dep in t.upstream:
            nodes.add(dep.ref)
            edges.append((dep.ref, t.table_name))
    if not nodes:
        lines.append('    %% no tracked tables yet')
        return "\n".join(lines) + "\n"
    for n in sorted(nodes):
        safe = _safe_identifier(n)
        lines.append(f'    {safe}["{n}"]')
    for upstream, downstream in edges:
        lines.append(f"    {_safe_identifier(upstream)} --> {_safe_identifier(downstream)}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# lineage.json — flat upstream→downstream edges
# ---------------------------------------------------------------------------


def build_lineage_doc(tables: list[TableMeta]) -> dict:
    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for t in tables:
        for dep in t.upstream:
            key = (t.table_name, dep.ref)
            if key in seen:
                continue
            seen.add(key)
            edge = {"from": t.table_name, "to": dep.ref}
            if dep.description:
                edge["description"] = dep.description
            edges.append(edge)
    edges.sort(key=lambda e: (e["from"], e["to"]))
    return {
        "schema_version": 1,
        "computed_at": _now_iso(),
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# relationships.json — flat FK edges
# ---------------------------------------------------------------------------


def build_relationships_doc(tables: list[TableMeta]) -> dict:
    edges: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for t in tables:
        for rel in t.relationships:
            key = (
                t.table_name, rel.to_table,
                ",".join(rel.from_columns), ",".join(rel.to_columns),
            )
            if key in seen:
                continue
            seen.add(key)
            edge = {
                "from": t.table_name,
                "to": rel.to_table,
                "from_columns": list(rel.from_columns),
                "to_columns": list(rel.to_columns),
                "cardinality": rel.cardinality,
            }
            if rel.description:
                edge["description"] = rel.description
            edges.append(edge)
    edges.sort(key=lambda e: (e["from"], e["to"], ",".join(e["from_columns"])))
    return {
        "schema_version": 1,
        "computed_at": _now_iso(),
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# joins.json — project-tracked joins (relationships + sql)
# ---------------------------------------------------------------------------


def build_joins_doc(
    tables: list[TableMeta],
    extracted: list[tuple[str, list[dict]]],
) -> dict:
    """`extracted` is a list of (file, joins) tuples — the result of
    `extract_joins` per tracked SQL file. The aggregator merges those
    onto the same canonical id used by per-table relationships so an
    FK and a matching extracted join collapse into one entry with two
    sources."""
    by_id: dict[str, dict] = {}

    # 1) From per-table relationships.
    for t in tables:
        for rel in t.relationships:
            rid = _canonical_id(t.table_name, list(rel.from_columns), rel.to_table, list(rel.to_columns))
            src = {"kind": "relationship", "from_table": t.table_name}
            existing = by_id.get(rid)
            if existing:
                existing["sources"].append(src)
                if rel.description and not existing.get("description"):
                    existing["description"] = rel.description
                if rel.cardinality and not existing.get("cardinality"):
                    existing["cardinality"] = rel.cardinality
                continue
            by_id[rid] = {
                "id": rid,
                "from_table": t.table_name,
                "to_table": rel.to_table,
                "from_schema": _schema_of(t),
                "to_schema": None,
                "from_columns": list(rel.from_columns),
                "to_columns": list(rel.to_columns),
                "cardinality": rel.cardinality,
                **({"description": rel.description} if rel.description else {}),
                "sources": [src],
            }

    # 2) From extracted SQL joins.
    for file_rel, joins in extracted:
        for j in joins:
            equalities = [
                eq for eq in (j.get("equalities") or [])
                if eq.get("left", {}).get("table")
                and eq.get("right", {}).get("table")
                and eq.get("left", {}).get("column")
                and eq.get("right", {}).get("column")
            ]
            if not equalities:
                continue
            from_table = equalities[0]["left"]["table"]
            to_table = equalities[0]["right"]["table"]
            from_cols = [eq["left"]["column"] for eq in equalities]
            to_cols = [eq["right"]["column"] for eq in equalities]
            rid = _canonical_id(from_table, from_cols, to_table, to_cols)
            src = {
                "kind": "sql",
                "file": file_rel,
                "line": int(j.get("line") or 0),
                "on_text": j.get("on_text", ""),
                "clause_text": j.get("clause_text", ""),
                "join_kind": j.get("kind", "JOIN"),
            }
            existing = by_id.get(rid)
            if existing:
                duplicate = any(
                    s.get("kind") == "sql"
                    and s.get("file") == src["file"]
                    and s.get("on_text") == src["on_text"]
                    for s in existing["sources"]
                )
                if not duplicate:
                    existing["sources"].append(src)
                continue
            by_id[rid] = {
                "id": rid,
                "from_table": from_table,
                "to_table": to_table,
                "from_schema": equalities[0]["left"].get("schema"),
                "to_schema": equalities[0]["right"].get("schema"),
                "from_columns": from_cols,
                "to_columns": to_cols,
                "sources": [src],
            }

    joins_list = sorted(
        by_id.values(),
        key=lambda e: (e["from_table"], e["to_table"], ",".join(e["from_columns"])),
    )
    return {
        "schema_version": 1,
        "computed_at": _now_iso(),
        "joins": joins_list,
    }


def _canonical_id(from_table: str, from_cols: list[str], to_table: str, to_cols: list[str]) -> str:
    a = f"{from_table.lower()}::{','.join(sorted(c.lower() for c in from_cols))}"
    b = f"{to_table.lower()}::{','.join(sorted(c.lower() for c in to_cols))}"
    return f"{a}|{b}" if a < b else f"{b}|{a}"


def _schema_of(t: TableMeta) -> Optional[str]:
    if not t.staging_target or "." not in t.staging_target:
        return None
    return t.staging_target.split(".", 1)[0] or None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
