"""Render the project as XML or markdown for the agent.

Direct port of `extension/shared/format_context.ts`. Same XML
vocabulary so an agent that learned to read project_context.xml from
the VS Code extension parses our output verbatim.

XML is the default — Claude is post-trained on tag-delimited inputs
and cross-referential reasoning (lineage chains, joinability) lands
more reliably on XML than on prose. Markdown is offered for token-
constrained contexts.

v0.3 emits the **semantic-context** layer alongside the structural
one: per-table `<grain>` / `<aliases>` / `<pitfalls>` / `<owner>` /
`<refresh>` / `<scd>`, per-column `classification` / `quality_notes` /
`computed` / `expression` / `example_values`, project-level
`<conventions>` / `<glossary>` / `<measures>`. Empty / default
fields are still omitted to keep the dump dense.
"""

from __future__ import annotations

import xml.sax.saxutils as xml_utils
from typing import Iterable, Optional

from .schemas import Column, Connection, ProjectConfig, TableMeta


XML_SCHEMA_PREAMBLE = """<aimm_schema>
This is an AI Model Manager project context dump. The vocabulary:
- <aimm_project> wraps the whole document. Children are <description>, <conventions>, <glossary>, <measures>, <connection> elements (data sources), and <table> elements (the tracked artefacts).
- <conventions> is project-wide free-text about naming / typing / structural rules ("all booleans end in _flag, all dates UTC"). Consult before guessing.
- <glossary> holds <term name="…"> entries defining domain vocabulary. The agent resolves user phrases ("active customer") against these before going to the tables.
- <measures> holds <measure name="…"> entries. Each carries <definition> (plain English) and optionally <formula> (the canonical expression in this project's dialect). Quote the formula instead of inventing one.
- A <connection> is an ODBC data source. `engine` ∈ {trino, sql_server, databricks}. `dsn` is a system DSN registered on the local machine. `catalog` qualifies information_schema queries (Trino catalog; SQL Server database; Databricks Unity catalog).
- A <table> belongs to one connection (the `connection` attribute) or is unassigned. Tables with a `source_file` attribute are authored locally as SQL views; tables without one were added from the live catalog and live only in the database. Optional attributes: `owner`, `refresh_cadence` (unknown|realtime|minutes|hourly|daily|weekly|monthly|adhoc), `row_count_last_run`, `last_run_at`. Children:
    <description> prose describing the table.
    <grain> short answer to "what is one row in this table?" — anchors every fact-vs-dim discussion.
    <aliases> comma-separated other names this table is known by. Resolve user references against these before "unknown table".
    <pitfalls> with one <pitfall> per known gotcha. Read before suggesting a join / filter / aggregation against this table.
    <scd> when the table is history-tracked. Attributes: type (scd1|scd2|snapshot|none), valid_from / valid_to / is_current_flag pointing at the relevant columns.
    <refresh_notes> additional free-text about freshness behaviour.
    <primary_key> PK column names, comma-separated.
    <columns> with one <column> per column. Attributes: name (qualified table.column), raw_name, type, pk, fk, not_null, classification (public|internal|pii|phi|restricted), computed. Inline content is the column description. Optional children: <quality_notes>, <expression> (formula for computed columns), <example_values>.
    <relationships> FK-like edges. Each <relationship> has `from` and `to` qualified as table.column (composite keys comma-separated), plus `cardinality`. Inline content is a human-readable sentence summarising the edge.
    <upstream> lineage. Each <depends_on> has `ref` (another table or free-form external identifier). Inline content is the reason / description.
    <downstream> derived (read-only) — comma-separated list of tables that declare this one as upstream.
- Column references inside <relationship> and lineage tags are qualified as `table.column` so cross-references are unambiguous.
- Empty / default fields are omitted to reduce noise. Absence means "not set", not "false".
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
        "paradigm": cfg.modeling_paradigm if cfg.modeling_paradigm != "unspecified" else None,
    })
    out.append(f"<aimm_project {project_attrs}>")
    if cfg.description:
        out.append(f"  <description>{_xml_text(cfg.description)}</description>")
    if cfg.tags:
        out.append(f"  <tags>{_xml_text(', '.join(cfg.tags))}</tags>")
    if cfg.conventions:
        out.append(f"  <conventions>{_xml_text(cfg.conventions)}</conventions>")
    if cfg.glossary:
        out.append("  <glossary>")
        for g in cfg.glossary:
            out.append(
                f'    <term name="{_xml_attr(g.term)}">{_xml_text(g.definition)}</term>',
            )
        out.append("  </glossary>")
    if cfg.measures:
        out.append("  <measures>")
        for m in cfg.measures:
            ma = _attrs({"name": m.name, "owner": m.owner})
            out.append(f"    <measure {ma}>")
            out.append(f"      <definition>{_xml_text(m.definition)}</definition>")
            if m.formula:
                out.append(f"      <formula>{_xml_text(m.formula)}</formula>")
            out.append("    </measure>")
        out.append("  </measures>")

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
        "paradigm_role": meta.paradigm_role or None,
        "owner": meta.owner,
        "refresh_cadence": meta.refresh_cadence if meta.refresh_cadence != "unknown" else None,
        "row_count_last_run": meta.row_count_last_run,
        "last_run_at": meta.last_run_at,
    })
    out.append(f"  <table {a}>")
    if meta.description:
        out.append(f"    <description>{_xml_text(meta.description)}</description>")
    if meta.grain:
        out.append(f"    <grain>{_xml_text(meta.grain)}</grain>")
    if meta.aliases:
        out.append(f"    <aliases>{_xml_text(', '.join(meta.aliases))}</aliases>")
    if meta.tags:
        out.append(f"    <tags>{_xml_text(', '.join(meta.tags))}</tags>")
    if meta.pitfalls:
        out.append("    <pitfalls>")
        for p in meta.pitfalls:
            out.append(f"      <pitfall>{_xml_text(p)}</pitfall>")
        out.append("    </pitfalls>")
    if meta.scd and meta.scd.type != "none":
        sa = _attrs({
            "type": meta.scd.type,
            "valid_from": meta.scd.valid_from,
            "valid_to": meta.scd.valid_to,
            "is_current_flag": meta.scd.is_current_flag,
        })
        out.append(f"    <scd {sa}/>")
    if meta.refresh_notes:
        out.append(f"    <refresh_notes>{_xml_text(meta.refresh_notes)}</refresh_notes>")
    if meta.primary_keys:
        out.append(f"    <primary_key>{_xml_text(', '.join(meta.primary_keys))}</primary_key>")

    if meta.columns:
        out.append("    <columns>")
        for col in meta.columns:
            _render_xml_column(meta.table_name, col, out)
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


def _render_xml_column(table_name: str, col: Column, out: list[str]) -> None:
    ca = _attrs({
        "name": f"{table_name}.{col.name}",
        "raw_name": col.name,
        "type": col.type or None,
        "pk": "true" if col.is_primary_key else None,
        "fk": "true" if col.is_foreign_key else None,
        "not_null": "true" if col.nullable is False else None,
        "classification": col.classification if col.classification != "unspecified" else None,
        "computed": "true" if col.computed else None,
    })
    has_children = bool(col.description or col.quality_notes or col.expression or col.example_values)
    if not has_children:
        out.append(f"      <column {ca}/>")
        return
    out.append(f"      <column {ca}>")
    if col.description:
        out.append(f"        <description>{_xml_text(col.description)}</description>")
    if col.quality_notes:
        out.append(f"        <quality_notes>{_xml_text(col.quality_notes)}</quality_notes>")
    if col.expression:
        out.append(f"        <expression>{_xml_text(col.expression)}</expression>")
    if col.example_values:
        out.append(
            f"        <example_values>{_xml_text(', '.join(col.example_values))}</example_values>",
        )
    out.append("      </column>")


def _relationship_sentence(
    from_table: str, to_table: str, cardinality: str, description: Optional[str],
) -> str:
    phrase = {
        "one_to_one": f"Each {from_table} maps to exactly one {to_table}, and vice versa.",
        "one_to_many": f"Each {from_table} relates to one {to_table}; a {to_table} has many {from_table}.",
        "many_to_many": f"{from_table} and {to_table} are joined many-to-many.",
    }.get(cardinality, f"{from_table} relates to {to_table} ({cardinality}).")
    return f"{phrase} {description}" if description else phrase


def _attrs(kvs: dict[str, object]) -> str:
    """Render only non-None, non-empty values as XML attributes."""
    parts: list[str] = []
    for k, v in kvs.items():
        if v is None or v == "":
            continue
        parts.append(f'{k}="{_xml_attr(str(v))}"')
    return " ".join(parts)


def _xml_attr(value: str) -> str:
    # xml_utils.quoteattr returns the value wrapped in quotes; strip
    # them since we build the surrounding quotes ourselves.
    return xml_utils.quoteattr(value or "")[1:-1]


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
    if cfg.modeling_paradigm and cfg.modeling_paradigm != "unspecified":
        out.append(f"- Paradigm: `{cfg.modeling_paradigm}`")
    if cfg.default_connection:
        out.append(f"- Default connection: `{cfg.default_connection}`")
    if cfg.tags:
        out.append(f"- Tags: {', '.join(cfg.tags)}")

    if cfg.conventions:
        out.append("")
        out.append("## Conventions")
        out.append(cfg.conventions)

    if cfg.glossary:
        out.append("")
        out.append(f"## Glossary ({len(cfg.glossary)})")
        for g in cfg.glossary:
            out.append(f"- **{g.term}** — {g.definition}")

    if cfg.measures:
        out.append("")
        out.append(f"## Measures ({len(cfg.measures)})")
        for m in cfg.measures:
            out.append(f"- **{m.name}** — {m.definition}")
            if m.formula:
                out.append(f"    - Formula: `{m.formula}`")
            if m.owner:
                out.append(f"    - Owner: {m.owner}")

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
        if t.grain:
            out.append(f"- Grain: {t.grain}")
        if t.aliases:
            out.append(f"- Aliases: {', '.join(t.aliases)}")
        if t.owner:
            out.append(f"- Owner: {t.owner}")
        if t.refresh_cadence and t.refresh_cadence != "unknown":
            line = f"- Refresh: `{t.refresh_cadence}`"
            if t.refresh_notes:
                line += f" — {t.refresh_notes}"
            out.append(line)
        if t.row_count_last_run is not None:
            stamp = f" @ {t.last_run_at}" if t.last_run_at else ""
            out.append(f"- Row count: {t.row_count_last_run:,}{stamp}")
        if t.scd and t.scd.type != "none":
            scd_parts = [f"type={t.scd.type}"]
            if t.scd.valid_from:
                scd_parts.append(f"valid_from={t.scd.valid_from}")
            if t.scd.valid_to:
                scd_parts.append(f"valid_to={t.scd.valid_to}")
            if t.scd.is_current_flag:
                scd_parts.append(f"is_current={t.scd.is_current_flag}")
            out.append(f"- SCD: {', '.join(scd_parts)}")
        if t.description:
            out.append("")
            out.append(t.description)
        if t.pitfalls:
            out.append("")
            out.append("Pitfalls:")
            for p in t.pitfalls:
                out.append(f"- {p}")
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
                if col.classification and col.classification != "unspecified":
                    flags.append(col.classification.upper())
                if col.computed:
                    flags.append("computed")
                if flags:
                    line += f"  _({', '.join(flags)})_"
                if col.description:
                    line += f" — {col.description}"
                out.append(line)
                if col.quality_notes:
                    out.append(f"    - Quality: {col.quality_notes}")
                if col.expression:
                    out.append(f"    - Expression: `{col.expression}`")
                if col.example_values:
                    out.append(f"    - Examples: {', '.join(col.example_values)}")
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
