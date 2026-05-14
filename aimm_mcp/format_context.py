"""Render the project as XML or markdown for the agent.

Direct port of `extension/shared/format_context.ts`. Same XML
vocabulary so an agent that learned to read project_context.xml from
the VS Code extension parses our output verbatim.

XML is the default — Claude is post-trained on tag-delimited inputs
and cross-referential reasoning (lineage chains, joinability) lands
more reliably on XML than on prose. Markdown is offered for token-
constrained contexts.
"""

from __future__ import annotations

import xml.sax.saxutils as xml_utils
from typing import Iterable, Optional

from .schemas import Connection, ProjectConfig, TableMeta


XML_SCHEMA_PREAMBLE = """<aimm_schema>
This is an AI Model Manager project context dump. The vocabulary:
- <aimm_project> wraps the whole document. Children are <description>, <connection> elements (data sources), and <table> elements (the tracked artefacts).
- A <connection> is an ODBC data source. `engine` ∈ {trino, sql_server, databricks}. `dsn` is a system DSN registered on the local machine. `catalog` qualifies information_schema queries (Trino catalog; SQL Server database; Databricks Unity catalog).
- A <table> belongs to one connection (the `connection` attribute) or is unassigned. Tables with a `source_file` attribute are authored locally as SQL views; tables without one were added from the live catalog and live only in the database. Children:
    <description> prose describing the table.
    <primary_key> PK column names, comma-separated.
    <columns> with one <column> per column. Attributes: name (qualified table.column), raw_name, type, pk, fk, not_null. Inline content is the column description.
    <relationships> FK-like edges. Each <relationship> has `from` and `to` qualified as table.column (composite keys comma-separated), plus `cardinality`. Inline content is a human-readable sentence summarising the edge.
    <upstream> lineage. Each <depends_on> has `ref` (another table or free-form external identifier). Inline content is the reason / description.
    <downstream> derived (read-only) — comma-separated list of tables that declare this one as upstream.
- Column references inside <relationship> and lineage tags are qualified as `table.column` so cross-references are unambiguous.
- Empty / default fields are omitted to reduce noise.
</aimm_schema>"""


def format_project_context(
    cfg: ProjectConfig,
    connections: list[Connection],
    tables: list[TableMeta],
    joins_doc: Optional[dict] = None,  # kept for backwards-compat; ignored
    fmt: str = "xml",
) -> str:
    if fmt == "markdown":
        return _render_markdown(cfg, connections, tables)
    return _render_xml(cfg, connections, tables)


# ---------------------------------------------------------------------------
# XML
# ---------------------------------------------------------------------------


def _render_xml(
    cfg: ProjectConfig,
    connections: list[Connection],
    tables: list[TableMeta],
) -> str:
    out: list[str] = [XML_SCHEMA_PREAMBLE, ""]

    project_attrs = _attrs({
        "name": cfg.name,
        "dialect": cfg.dialect,
        "default_connection": cfg.default_connection,
    })
    out.append(f"<aimm_project {project_attrs}>")
    if cfg.description:
        out.append(f"  <description>{_xml_text(cfg.description)}</description>")
    if cfg.tags:
        out.append(f"  <tags>{_xml_text(', '.join(cfg.tags))}</tags>")

    # Connections first so tables can reference them by name.
    for c in connections:
        _render_xml_connection(c, out)

    # Pre-compute downstream by inverting upstream once.
    downstream_by_ref: dict[str, list[str]] = {}
    for t in tables:
        for dep in t.upstream:
            downstream_by_ref.setdefault(dep.ref, []).append(t.table_name)

    # Tables grouped by connection, then unassigned at the end so
    # they're easy to spot.
    seen: set[str] = set()
    for c in connections:
        owned = [t for t in tables if t.connection == c.name]
        for t in owned:
            seen.add(t.table_name)
            _render_xml_table(t, out, downstream_by_ref.get(t.table_name, []))
    for t in tables:
        if t.table_name not in seen:
            _render_xml_table(t, out, downstream_by_ref.get(t.table_name, []))

    out.append("</aimm_project>")
    out.append("")
    return "\n".join(out)


def _render_xml_connection(c: Connection, out: list[str]) -> None:
    a = _attrs({
        "name": c.name,
        "engine": c.engine,
        "catalog": c.catalog,
        "default_schema": c.default_schema,
    })
    out.append(f"  <connection {a}>")
    out.append(f"    <dsn>{_xml_text(c.dsn)}</dsn>")
    if c.description:
        out.append(f"    <description>{_xml_text(c.description)}</description>")
    if c.tags:
        out.append(f"    <tags>{_xml_text(', '.join(c.tags))}</tags>")
    out.append("  </connection>")


def _render_xml_table(meta: TableMeta, out: list[str], downstream: list[str]) -> None:
    a = _attrs({
        "name": meta.table_name,
        "connection": meta.connection,
        "source_file": meta.source_file,
        "ddl_only": "true" if meta.ddl_only else None,
        "db_kind": meta.db_kind,
    })
    out.append(f"  <table {a}>")
    if meta.description:
        out.append(f"    <description>{_xml_text(meta.description)}</description>")
    if meta.tags:
        out.append(f"    <tags>{_xml_text(', '.join(meta.tags))}</tags>")
    if meta.primary_keys:
        out.append(f"    <primary_key>{_xml_text(', '.join(meta.primary_keys))}</primary_key>")

    if meta.columns:
        out.append("    <columns>")
        for col in meta.columns:
            ca = _attrs({
                "name": f"{meta.table_name}.{col.name}",
                "raw_name": col.name,
                "type": col.type or None,
                "pk": "true" if col.is_primary_key else None,
                "fk": "true" if col.is_foreign_key else None,
                "not_null": "true" if col.nullable is False else None,
            })
            desc = _xml_text(col.description) if col.description else ""
            if desc:
                out.append(f"      <column {ca}>{desc}</column>")
            else:
                out.append(f"      <column {ca}/>")
        out.append("    </columns>")

    if meta.relationships:
        out.append("    <relationships>")
        for rel in meta.relationships:
            from_q = ", ".join(f"{meta.table_name}.{c}" for c in rel.from_columns)
            to_q = ", ".join(f"{rel.to_table}.{c}" for c in rel.to_columns)
            ra = _attrs({
                "from": from_q,
                "to": to_q,
                "cardinality": rel.cardinality,
            })
            sentence = _relationship_sentence(
                meta.table_name, rel.to_table, rel.cardinality, rel.description,
            )
            out.append(f"      <relationship {ra}>{_xml_text(sentence)}</relationship>")
        out.append("    </relationships>")

    if meta.upstream:
        out.append("    <upstream>")
        for dep in meta.upstream:
            da = _attrs({"ref": dep.ref})
            body = _xml_text(dep.description) if dep.description else f"{meta.table_name} reads from {dep.ref}."
            out.append(f"      <depends_on {da}>{body}</depends_on>")
        out.append("    </upstream>")

    if downstream:
        out.append(f"    <downstream>{_xml_text(', '.join(downstream))}</downstream>")

    out.append("  </table>")


def _relationship_sentence(
    from_table: str, to_table: str, cardinality: str, description: Optional[str],
) -> str:
    phrase = {
        "one_to_one": f"Each {from_table} maps to exactly one {to_table}, and vice versa.",
        "one_to_many": f"Each {from_table} relates to one {to_table}; a {to_table} has many {from_table}.",
        "many_to_many": f"{from_table} and {to_table} are joined many-to-many.",
    }.get(cardinality, f"{from_table} relates to {to_table} ({cardinality}).")
    return f"{phrase} {description}" if description else phrase


def _attrs(kvs: dict[str, Optional[str]]) -> str:
    """Render only non-None, non-empty values as XML attributes."""
    parts: list[str] = []
    for k, v in kvs.items():
        if v is None or v == "":
            continue
        parts.append(f'{k}="{xml_utils.quoteattr(str(v))[1:-1]}"')
    return " ".join(parts)


def _xml_text(value: str) -> str:
    return xml_utils.escape(value or "")


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _render_markdown(
    cfg: ProjectConfig,
    connections: list[Connection],
    tables: list[TableMeta],
) -> str:
    out: list[str] = []
    out.append(f"# {cfg.name}")
    if cfg.description:
        out.append("")
        out.append(cfg.description)
    out.append("")
    out.append(f"- Dialect: `{cfg.dialect}`")
    if cfg.default_connection:
        out.append(f"- Default connection: `{cfg.default_connection}`")
    if cfg.tags:
        out.append(f"- Tags: {', '.join(cfg.tags)}")

    out.append("")
    out.append(f"## Connections ({len(connections)})")
    for c in connections:
        out.append(f"- **{c.name}** — {c.engine}, dsn=`{c.dsn}`{', catalog=`' + c.catalog + '`' if c.catalog else ''}")
        if c.description:
            out.append(f"  - {c.description}")

    downstream_by_ref: dict[str, list[str]] = {}
    for t in tables:
        for dep in t.upstream:
            downstream_by_ref.setdefault(dep.ref, []).append(t.table_name)

    out.append("")
    out.append(f"## Tables ({len(tables)})")
    for t in tables:
        out.append("")
        out.append(f"### {t.table_name}")
        if t.connection:
            out.append(f"- Connection: `{t.connection}`")
        if t.staging_target:
            out.append(f"- Target: `{t.staging_target}`")
        if t.description:
            out.append("")
            out.append(t.description)
        if t.primary_keys:
            out.append("")
            out.append(f"PK: `{', '.join(t.primary_keys)}`")
        if t.columns:
            out.append("")
            out.append("Columns:")
            for col in t.columns:
                line = f"- `{col.name}` {col.type}"
                flags = []
                if col.is_primary_key:
                    flags.append("PK")
                if col.is_foreign_key:
                    flags.append("FK")
                if col.nullable is False:
                    flags.append("NOT NULL")
                if flags:
                    line += f"  _({', '.join(flags)})_"
                if col.description:
                    line += f" — {col.description}"
                out.append(line)
        if t.relationships:
            out.append("")
            out.append("Relationships:")
            for rel in t.relationships:
                out.append(
                    f"- {t.table_name}.{','.join(rel.from_columns)} → "
                    f"{rel.to_table}.{','.join(rel.to_columns)} ({rel.cardinality})"
                    + (f" — {rel.description}" if rel.description else "")
                )
        if t.upstream:
            out.append("")
            out.append("Upstream:")
            for dep in t.upstream:
                out.append(f"- `{dep.ref}`" + (f" — {dep.description}" if dep.description else ""))
        ds = downstream_by_ref.get(t.table_name, [])
        if ds:
            out.append("")
            out.append(f"Downstream: {', '.join(ds)}")

    out.append("")
    return "\n".join(out)
