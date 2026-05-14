"""Per-engine SQL templates and identifier quoting.

Every engine-specific query the server issues lives here — adding a
new engine is one dataclass entry, the rest of the codebase just calls
`get_engine(connection.engine)`.

Today: Trino (Presto-compat), SQL Server, Databricks. Keys match
`Connection.engine` in the project schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


def _sq(s: str) -> str:
    """Escape a literal for single-quoted SQL."""
    return s.replace("'", "''")


@dataclass(frozen=True)
class EngineSpec:
    """Per-engine SQL templates.

    Every function takes the qualifying `catalog` plus whatever
    additional scope it needs (schema, table, or batch of tables) and
    returns a SQL string. The runner doesn't know or care which engine
    it's talking to — that's the EngineSpec's job.
    """

    label: str

    list_schemas_sql: Callable[[Optional[str]], str]
    list_tables_sql: Callable[[Optional[str], str], str]
    list_columns_sql: Callable[[Optional[str], str, str], str]
    list_columns_many_sql: Callable[[Optional[str], str, list[str]], str]


# --- Trino / Presto ---------------------------------------------------------
#
# `information_schema` lives inside each catalog
# (`hive.information_schema.schemata`, etc.). Identifiers double-quoted
# per ANSI. `data_type` is already parameterised (`varchar(40)`,
# `decimal(18,2)`) — no synthesis needed.
#
# Cost note: Trino's information_schema is a federation layer over the
# catalog's connector (typically HiveMetastore). Per-table round trips
# dominate latency on large schemas; `list_columns_many_sql` amortises
# that via a single IN-list.


def _trino_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _trino_list_schemas(catalog: Optional[str]) -> str:
    fq = (
        f"{_trino_ident(catalog)}.information_schema.schemata"
        if catalog
        else "information_schema.schemata"
    )
    return f"select schema_name from {fq} order by schema_name"


def _trino_list_tables(catalog: Optional[str], schema: str) -> str:
    fq = (
        f"{_trino_ident(catalog)}.information_schema.tables"
        if catalog
        else "information_schema.tables"
    )
    return (
        f"select table_name, table_type from {fq} "
        f"where table_schema = '{_sq(schema)}' order by table_name"
    )


def _trino_list_columns(catalog: Optional[str], schema: str, table: str) -> str:
    fq = (
        f"{_trino_ident(catalog)}.information_schema.columns"
        if catalog
        else "information_schema.columns"
    )
    return (
        f"select column_name, data_type, is_nullable, ordinal_position from {fq} "
        f"where table_schema = '{_sq(schema)}' and table_name = '{_sq(table)}' "
        f"order by ordinal_position"
    )


def _trino_list_columns_many(catalog: Optional[str], schema: str, tables: list[str]) -> str:
    fq = (
        f"{_trino_ident(catalog)}.information_schema.columns"
        if catalog
        else "information_schema.columns"
    )
    in_list = ", ".join(f"'{_sq(t)}'" for t in tables)
    return (
        f"select table_name, column_name, data_type, is_nullable, ordinal_position from {fq} "
        f"where table_schema = '{_sq(schema)}' and table_name in ({in_list}) "
        f"order by table_name, ordinal_position"
    )


TRINO = EngineSpec(
    label="Trino / Presto",
    list_schemas_sql=_trino_list_schemas,
    list_tables_sql=_trino_list_tables,
    list_columns_sql=_trino_list_columns,
    list_columns_many_sql=_trino_list_columns_many,
)


# --- SQL Server -------------------------------------------------------------
#
# INFORMATION_SCHEMA lives inside the database (`catalog` in our
# schema). Identifiers wrapped in square brackets. `DATA_TYPE` is
# unparameterised (`nvarchar` / `decimal`) so we synthesise the
# parameterised form (`nvarchar(255)`, `decimal(18,2)`) via CASE.


_SQL_SERVER_DATA_TYPE_EXPR = """
  CASE
    WHEN DATA_TYPE IN ('char','varchar','nchar','nvarchar','binary','varbinary')
      AND CHARACTER_MAXIMUM_LENGTH IS NOT NULL
      THEN DATA_TYPE + '(' + CASE WHEN CHARACTER_MAXIMUM_LENGTH = -1 THEN 'max' ELSE CAST(CHARACTER_MAXIMUM_LENGTH AS VARCHAR(20)) END + ')'
    WHEN DATA_TYPE IN ('decimal','numeric')
      AND NUMERIC_PRECISION IS NOT NULL
      THEN DATA_TYPE + '(' + CAST(NUMERIC_PRECISION AS VARCHAR(20)) + ',' + CAST(COALESCE(NUMERIC_SCALE, 0) AS VARCHAR(20)) + ')'
    ELSE DATA_TYPE
  END
""".strip()


def _ms_list_schemas(catalog: Optional[str]) -> str:
    fq = f"[{catalog}].INFORMATION_SCHEMA.SCHEMATA" if catalog else "INFORMATION_SCHEMA.SCHEMATA"
    return f"select schema_name from {fq} order by schema_name"


def _ms_list_tables(catalog: Optional[str], schema: str) -> str:
    fq = f"[{catalog}].INFORMATION_SCHEMA.TABLES" if catalog else "INFORMATION_SCHEMA.TABLES"
    return (
        f"select table_name, table_type from {fq} "
        f"where table_schema = '{_sq(schema)}' order by table_name"
    )


def _ms_list_columns(catalog: Optional[str], schema: str, table: str) -> str:
    fq = f"[{catalog}].INFORMATION_SCHEMA.COLUMNS" if catalog else "INFORMATION_SCHEMA.COLUMNS"
    return (
        f"select column_name, {_SQL_SERVER_DATA_TYPE_EXPR} as data_type, is_nullable, ordinal_position from {fq} "
        f"where table_schema = '{_sq(schema)}' and table_name = '{_sq(table)}' "
        f"order by ordinal_position"
    )


def _ms_list_columns_many(catalog: Optional[str], schema: str, tables: list[str]) -> str:
    fq = f"[{catalog}].INFORMATION_SCHEMA.COLUMNS" if catalog else "INFORMATION_SCHEMA.COLUMNS"
    in_list = ", ".join(f"'{_sq(t)}'" for t in tables)
    return (
        f"select table_name, column_name, {_SQL_SERVER_DATA_TYPE_EXPR} as data_type, is_nullable, ordinal_position from {fq} "
        f"where table_schema = '{_sq(schema)}' and table_name in ({in_list}) "
        f"order by table_name, ordinal_position"
    )


SQL_SERVER = EngineSpec(
    label="SQL Server",
    list_schemas_sql=_ms_list_schemas,
    list_tables_sql=_ms_list_tables,
    list_columns_sql=_ms_list_columns,
    list_columns_many_sql=_ms_list_columns_many,
)


# --- Databricks (Unity Catalog) --------------------------------------------
#
# `information_schema` lives under the catalog name in Unity Catalog
# (e.g. `hive_metastore.information_schema.schemata` or
# `main.information_schema.schemata`). Identifiers wrapped in
# backticks. `data_type` is parameterised, like Trino — no synthesis
# needed. Connection arrives via the Databricks ODBC driver.


def _dbx_ident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def _dbx_list_schemas(catalog: Optional[str]) -> str:
    fq = (
        f"{_dbx_ident(catalog)}.information_schema.schemata"
        if catalog
        else "information_schema.schemata"
    )
    return f"select schema_name from {fq} order by schema_name"


def _dbx_list_tables(catalog: Optional[str], schema: str) -> str:
    fq = (
        f"{_dbx_ident(catalog)}.information_schema.tables"
        if catalog
        else "information_schema.tables"
    )
    return (
        f"select table_name, table_type from {fq} "
        f"where table_schema = '{_sq(schema)}' order by table_name"
    )


def _dbx_list_columns(catalog: Optional[str], schema: str, table: str) -> str:
    fq = (
        f"{_dbx_ident(catalog)}.information_schema.columns"
        if catalog
        else "information_schema.columns"
    )
    # Databricks names the ordinal column `ordinal_position` and
    # exposes `full_data_type` for the parameterised form; fall back to
    # `data_type` if the platform version doesn't expose it.
    return (
        f"select column_name, "
        f"coalesce(full_data_type, data_type) as data_type, "
        f"is_nullable, ordinal_position from {fq} "
        f"where table_schema = '{_sq(schema)}' and table_name = '{_sq(table)}' "
        f"order by ordinal_position"
    )


def _dbx_list_columns_many(catalog: Optional[str], schema: str, tables: list[str]) -> str:
    fq = (
        f"{_dbx_ident(catalog)}.information_schema.columns"
        if catalog
        else "information_schema.columns"
    )
    in_list = ", ".join(f"'{_sq(t)}'" for t in tables)
    return (
        f"select table_name, column_name, "
        f"coalesce(full_data_type, data_type) as data_type, "
        f"is_nullable, ordinal_position from {fq} "
        f"where table_schema = '{_sq(schema)}' and table_name in ({in_list}) "
        f"order by table_name, ordinal_position"
    )


DATABRICKS = EngineSpec(
    label="Databricks",
    list_schemas_sql=_dbx_list_schemas,
    list_tables_sql=_dbx_list_tables,
    list_columns_sql=_dbx_list_columns,
    list_columns_many_sql=_dbx_list_columns_many,
)


# --- registry ---------------------------------------------------------------

ENGINES: dict[str, EngineSpec] = {
    "trino": TRINO,
    "sql_server": SQL_SERVER,
    "databricks": DATABRICKS,
}


def get_engine(engine_id: str | None) -> EngineSpec | None:
    if engine_id is None:
        return None
    return ENGINES.get(engine_id)
