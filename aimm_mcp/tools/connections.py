"""Connection + catalog tools.

  - aimm_upsert_connection         create / update a connection descriptor
  - aimm_list_system_dsns          enumerate OS-level DSNs
  - aimm_browse_connection         drill through schemas / tables / columns
  - aimm_refresh_columns           re-fetch column shapes per tracked table
"""

from __future__ import annotations

from typing import Any

from mcp.types import TextContent, Tool

from .. import paths, state
from ..catalog import browser
from ..odbc import dsn as dsn_module
from ..schemas import Column, Connection, TableMeta
from . import _common


TOOLS: list[Tool] = [
    Tool(
        name="aimm_upsert_connection",
        description=(
            "Create or update a connection descriptor in project.json. "
            "All connections are ODBC; engine ∈ {trino, sql_server, "
            "databricks} drives the dialect-specific information_schema "
            "queries. `dsn` must be the name of a system DSN already "
            "registered on the user's machine — see aimm_list_system_dsns. "
            "Idempotent: re-running with the same `name` patches the "
            "existing record."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "engine": {"type": "string", "enum": ["trino", "sql_server", "databricks"]},
                "dsn": {"type": "string"},
                "catalog": {"type": "string"},
                "default_schema": {"type": "string"},
                "description": {"type": "string", "maxLength": 4000},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name", "engine", "dsn"],
        },
    ),
    Tool(
        name="aimm_list_system_dsns",
        description=(
            "Enumerate ODBC DSNs registered on the user's machine. Returns "
            "{name, driver} per entry. Use this before aimm_upsert_connection "
            "to confirm a DSN exists."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="aimm_browse_connection",
        description=(
            "Drill-down browser over a connection's live information_schema. "
            "Without arguments returns the project's connection list. With "
            "`connection` returns its schemas. With `connection + schema` "
            "returns tables and views. With `connection + schema + table` "
            "returns column shape. Optional `search` filters at the current "
            "level by case-insensitive substring."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "connection": {"type": "string"},
                "schema": {"type": "string"},
                "table": {"type": "string"},
                "search": {"type": "string"},
            },
        },
    ),
    Tool(
        name="aimm_refresh_columns",
        description=(
            "Re-fetch the column shape from information_schema for tracked "
            "tables and merge it back into project.json (preserving "
            "user-edited PK / FK / description flags). Without `table` "
            "refreshes every tracked table that has a staging_target and "
            "connection. `force: true` bypasses the 5-minute catalog cache."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "force": {"type": "boolean"},
            },
        },
    ),
]


async def dispatch(name: str, args: dict[str, Any]) -> list[TextContent]:
    if name == "aimm_upsert_connection":
        return await _upsert_connection(args)
    if name == "aimm_list_system_dsns":
        return await _list_dsns(args)
    if name == "aimm_browse_connection":
        return await _browse(args)
    if name == "aimm_refresh_columns":
        return await _refresh_columns(args)
    raise ValueError(f"connections.dispatch: unknown tool {name}")


async def _upsert_connection(args: dict[str, Any]) -> list[TextContent]:
    err = _common.ensure_active()
    if err:
        return err
    try:
        conn = Connection(**{k: v for k, v in args.items() if v is not None})
    except Exception as err:  # noqa: BLE001
        return [TextContent(type="text", text=f"Invalid connection payload: {err}")]
    if conn.engine == "trino" and not (conn.catalog or "").strip():
        return [TextContent(
            type="text",
            text="Trino connections require a `catalog` (e.g. 'hive').",
        )]
    state.mutate(lambda p: state.upsert_connection(p, conn))
    browser.clear_cache(conn.name)
    return [TextContent(
        type="text",
        text=f"Saved connection '{conn.name}' (engine={conn.engine}, dsn={conn.dsn}, catalog={conn.catalog or 'none'}).",
    )]


async def _list_dsns(_: dict[str, Any]) -> list[TextContent]:
    dsns = dsn_module.list_system_dsns()
    if not dsns:
        return [TextContent(
            type="text",
            text="No DSNs found. Configure one in the OS's ODBC Data Source Administrator and re-run.",
        )]
    body = "Registered DSNs:\n" + "\n".join(f"  - {d.name}  ({d.driver})" for d in dsns)
    return [TextContent(type="text", text=body)]


async def _browse(args: dict[str, Any]) -> list[TextContent]:
    project, err = _common.load_active()
    if err:
        return err
    conn_name = args.get("connection")
    schema = args.get("schema")
    table = args.get("table")
    search = (args.get("search") or "").lower()

    if not conn_name:
        if not project.connections:
            return [TextContent(type="text", text="No connections recorded. Call aimm_upsert_connection first.")]
        lines = [
            f"  - {c.name}  ({c.engine}, dsn={c.dsn}, catalog={c.catalog or 'none'})"
            for c in project.connections
        ]
        return [TextContent(type="text", text="Project connections:\n" + "\n".join(lines))]

    conn = state.find_connection(project, conn_name)
    if conn is None:
        return [TextContent(type="text", text=f"Unknown connection '{conn_name}'.")]

    if schema is None:
        schemas = browser.list_schemas(conn)
        if isinstance(schemas, browser.CatalogFailure):
            return [TextContent(type="text", text=f"Couldn't list schemas: {schemas.reason} — {schemas.detail}")]
        names = [s.name for s in schemas if not search or search in s.name.lower()]
        return [TextContent(type="text", text=f"Schemas in {conn_name}:\n" + "\n".join(f"  - {n}" for n in names))]

    if table is None:
        tables = browser.list_tables(conn, schema)
        if isinstance(tables, browser.CatalogFailure):
            return [TextContent(type="text", text=f"Couldn't list tables: {tables.reason} — {tables.detail}")]
        filtered = [t for t in tables if not search or search in t.name.lower()]
        lines = [f"  - {t.name}  ({t.table_type})" for t in filtered]
        return [TextContent(type="text", text=f"Tables in {conn_name}.{schema}:\n" + "\n".join(lines))]

    cols = browser.list_columns(conn, schema, table)
    if isinstance(cols, browser.CatalogFailure):
        return [TextContent(type="text", text=f"Couldn't list columns: {cols.reason} — {cols.detail}")]
    filtered = [c for c in cols if not search or search in c.name.lower()]
    lines = [
        f"  - {c.name}  {c.data_type}{' NOT NULL' if not c.nullable else ''}"
        for c in filtered
    ]
    return [TextContent(type="text", text=f"Columns in {conn_name}.{schema}.{table}:\n" + "\n".join(lines))]


async def _refresh_columns(args: dict[str, Any]) -> list[TextContent]:
    force = bool(args.get("force"))
    table_arg = args.get("table")

    project, err = _common.load_active()
    if err:
        return err
    targets = [t for t in project.tables if not table_arg or t.table_name == table_arg]
    if table_arg and not targets:
        return [TextContent(type="text", text=f"Unknown table '{table_arg}'.")]
    if force:
        browser.clear_cache()

    refreshed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    next_tables = list(project.tables)
    for idx, t in enumerate(next_tables):
        if not (t in targets):
            continue
        if not t.connection or not t.staging_target or "." not in t.staging_target:
            skipped.append(t.table_name)
            continue
        conn = state.find_connection(project, t.connection)
        if conn is None:
            skipped.append(t.table_name)
            continue
        schema, name = t.staging_target.split(".", 1)
        cols = browser.list_columns(conn, schema, name)
        if isinstance(cols, browser.CatalogFailure):
            failed.append(f"{t.table_name} ({cols.reason})")
            continue
        existing_by_name = {c.name: c for c in t.columns}
        next_cols: list[Column] = []
        for c in cols:
            prior = existing_by_name.get(c.name)
            next_cols.append(Column(
                name=c.name,
                type=c.data_type,
                nullable=c.nullable,
                is_primary_key=prior.is_primary_key if prior else False,
                is_foreign_key=prior.is_foreign_key if prior else False,
                description=prior.description if prior else None,
            ))
        next_tables[idx] = t.model_copy(update={
            "columns": next_cols,
            "columns_from": "information_schema",
        })
        refreshed.append(t.table_name)

    if refreshed:
        state.mutate(lambda p: p.model_copy(update={"tables": next_tables}))

    parts = [f"Refreshed columns for {len(refreshed)} table(s)."]
    if refreshed:
        parts.append("  refreshed: " + ", ".join(refreshed))
    if skipped:
        parts.append("  skipped: " + ", ".join(skipped))
    if failed:
        parts.append("  failed: " + ", ".join(failed))
    return [TextContent(type="text", text="\n".join(parts))]
