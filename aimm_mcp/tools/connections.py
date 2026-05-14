"""Connection + catalog tools.

  - aimm_upsert_connection         create / update a connection descriptor
  - aimm_list_system_dsns          enumerate OS-level DSNs
  - aimm_browse_connection         drill through schemas / tables / columns
  - aimm_refresh_columns           re-fetch column shapes per tracked table
"""

from __future__ import annotations

from typing import Any

from mcp.types import TextContent, Tool

from .. import paths, repo
from ..catalog import browser
from ..odbc import dsn as dsn_module
from ..schemas import Column, Connection, TableMeta


TOOLS: list[Tool] = [
    Tool(
        name="aimm_upsert_connection",
        description=(
            "Create or update a connection JSON in ~/Documents/AIMM/connections/. "
            "All connections are ODBC; engine ∈ {trino, sql_server, databricks} "
            "drives the dialect-specific SQL the server runs against "
            "information_schema. `dsn` must be the name of a system DSN already "
            "registered on the user's machine — see aimm_list_system_dsns. "
            "Idempotent: re-running with the same `name` patches the existing "
            "record."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project handle for the connection. Used by tracked tables to reference it. Required."},
                "engine": {"type": "string", "enum": ["trino", "sql_server", "databricks"]},
                "dsn": {"type": "string", "description": "System DSN name (or full connection string with `=`)."},
                "catalog": {"type": "string", "description": "Trino catalog (e.g. 'hive'); SQL Server database; Databricks Unity catalog."},
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
            "Enumerate ODBC DSNs registered on the user's machine via "
            "pyodbc.dataSources(). Returns a list of {name, driver}. Use this "
            "before aimm_upsert_connection to confirm a DSN exists. The DSN "
            "itself is configured at the OS level, not by this server."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="aimm_browse_connection",
        description=(
            "Drill-down browser over a connection's live information_schema. "
            "Without arguments returns the project's connection list. With "
            "`connection` returns its schemas. With `connection + schema` "
            "returns tables and views in that schema. With `connection + "
            "schema + table` returns the column shape. Optional `search` "
            "filters at the current level by case-insensitive substring on "
            "names. Use this to discover existing tables to join against "
            "without first adding them to tracking."
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
            "tables and merge it into their JSON. Use after deploying a "
            "schema change so the agent sees the live shape on the next "
            "context read. Without `table`, refreshes every tracked table "
            "with a staging_target + connection. `force: true` bypasses the "
            "5-minute catalog cache."
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
    paths.ensure_layout()
    try:
        conn = Connection(**{k: v for k, v in args.items() if v is not None})
    except Exception as err:  # noqa: BLE001
        return [TextContent(type="text", text=f"Invalid connection payload: {err}")]
    if conn.engine == "trino" and not (conn.catalog or "").strip():
        return [TextContent(
            type="text",
            text="Trino connections require a `catalog` (e.g. 'hive'). information_schema is qualified by catalog on Trino.",
        )]
    repo.write_connection(conn)
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
            text=(
                "No DSNs found. Either no ODBC driver is installed, or the user "
                "hasn't registered any DSNs. Configure one in the OS's ODBC "
                "Data Source Administrator and re-run."
            ),
        )]
    body = "Registered DSNs:\n" + "\n".join(f"  - {d.name}  ({d.driver})" for d in dsns)
    return [TextContent(type="text", text=body)]


async def _browse(args: dict[str, Any]) -> list[TextContent]:
    conn_name = args.get("connection")
    schema = args.get("schema")
    table = args.get("table")
    search = (args.get("search") or "").lower()

    if not conn_name:
        # Top level: list project connections.
        conns = list(repo.iter_connections())
        if not conns:
            return [TextContent(type="text", text="No connections recorded. Call aimm_upsert_connection first.")]
        lines = [f"  - {c.name}  ({c.engine}, dsn={c.dsn}, catalog={c.catalog or 'none'})" for c in conns]
        return [TextContent(type="text", text="Project connections:\n" + "\n".join(lines))]

    conn = repo.read_connection(conn_name)
    if conn is None:
        return [TextContent(type="text", text=f"Unknown connection '{conn_name}'. Run aimm_browse_connection with no args to list available.")]

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

    tables = [t for t in repo.iter_tables() if not table_arg or t.table_name == table_arg]
    if table_arg and not tables:
        return [TextContent(type="text", text=f"Unknown table '{table_arg}'.")]

    if force:
        browser.clear_cache()

    refreshed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    for t in tables:
        if not t.connection or not t.staging_target or "." not in t.staging_target:
            skipped.append(t.table_name)
            continue
        conn = repo.read_connection(t.connection)
        if conn is None:
            skipped.append(t.table_name)
            continue
        schema, name = t.staging_target.split(".", 1)
        cols = browser.list_columns(conn, schema, name)
        if isinstance(cols, browser.CatalogFailure):
            failed.append(f"{t.table_name} ({cols.reason})")
            continue
        # Merge: preserve user-edited fields (is_primary_key,
        # is_foreign_key, description) and rebuild type/nullable from DB.
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
        updated = t.model_copy(update={
            "columns": next_cols,
            "columns_from": "information_schema",
        })
        repo.write_table(updated)
        refreshed.append(t.table_name)

    parts = [f"Refreshed columns for {len(refreshed)} table(s)."]
    if refreshed:
        parts.append("  refreshed: " + ", ".join(refreshed))
    if skipped:
        parts.append("  skipped (no connection or staging_target): " + ", ".join(skipped))
    if failed:
        parts.append("  failed: " + ", ".join(failed))
    return [TextContent(type="text", text="\n".join(parts))]
