"""Read-only browser over an ODBC connection's catalog.

Three queries:

  - list_schemas(conn)
  - list_tables(conn, schema)
  - list_columns(conn, schema, table)
  - list_columns_many(conn, schema, tables)

Results are cached in-process per (connection.name, scope) for the
lifetime of the MCP session so back-to-back agent calls don't hammer
the cluster. `clear_cache(connection_name?)` invalidates; the
upsert-connection / refresh flows call it when the descriptor changes.

Engine-specific SQL lives in `odbc/engines.py`. This module is the
dumb cache + dispatch layer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from ..odbc import runner
from ..odbc.engines import get_engine
from ..schemas import Connection


# 5 minutes — long enough to feel snappy, short enough to recover
# from a config fix in the same session.
_TTL_S = 5 * 60


@dataclass(frozen=True)
class SchemaInfo:
    name: str


@dataclass(frozen=True)
class TableInfo:
    name: str
    table_type: str


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str
    nullable: bool
    ordinal_position: int


@dataclass(frozen=True)
class CatalogFailure:
    reason: str
    detail: str
    ok: bool = False


@dataclass(frozen=True)
class _CacheEntry:
    result: Any
    fetched_at: float


# Singletons. One MCP session = one cache.
_schema_cache: dict[str, _CacheEntry] = {}
_table_cache: dict[str, _CacheEntry] = {}
_column_cache: dict[str, _CacheEntry] = {}


def clear_cache(connection_name: Optional[str] = None) -> None:
    """Drop cached enumerations. Without an argument: wipe everything.
    With a name: drop only entries for that connection."""
    if connection_name is None:
        _schema_cache.clear()
        _table_cache.clear()
        _column_cache.clear()
        return
    prefix = f"{connection_name}::"
    for cache in (_schema_cache, _table_cache, _column_cache):
        for k in list(cache.keys()):
            if k.startswith(prefix):
                del cache[k]


def _fresh(entry: _CacheEntry | None) -> Any | None:
    if entry is None:
        return None
    if time.monotonic() - entry.fetched_at > _TTL_S:
        return None
    return entry.result


def _no_engine(engine_id: str | None) -> CatalogFailure:
    return CatalogFailure(
        reason="no_engine",
        detail=f"No engine spec registered for {engine_id!r}.",
    )


def list_schemas(connection: Connection) -> Union[list[SchemaInfo], CatalogFailure]:
    key = f"{connection.name}::schemas"
    cached = _fresh(_schema_cache.get(key))
    if cached is not None:
        return cached
    engine = get_engine(connection.engine)
    if engine is None:
        return _no_engine(connection.engine)
    sql = engine.list_schemas_sql(connection.catalog)
    result = runner.run_query_rows(
        connection.dsn,
        sql,
        source=f"list_schemas:{connection.name}",
    )
    if not result.ok:
        return CatalogFailure(reason=result.reason, detail=result.detail)
    schemas = [
        SchemaInfo(name=str(r.get("schema_name", "")))
        for r in result.rows
        if r.get("schema_name")
    ]
    _schema_cache[key] = _CacheEntry(result=schemas, fetched_at=time.monotonic())
    return schemas


def list_tables(connection: Connection, schema: str) -> Union[list[TableInfo], CatalogFailure]:
    key = f"{connection.name}::tables::{schema}"
    cached = _fresh(_table_cache.get(key))
    if cached is not None:
        return cached
    engine = get_engine(connection.engine)
    if engine is None:
        return _no_engine(connection.engine)
    sql = engine.list_tables_sql(connection.catalog, schema)
    result = runner.run_query_rows(
        connection.dsn,
        sql,
        source=f"list_tables:{connection.name}.{schema}",
    )
    if not result.ok:
        return CatalogFailure(reason=result.reason, detail=result.detail)
    tables = [
        TableInfo(
            name=str(r.get("table_name", "")),
            table_type=str(r.get("table_type", "")).upper(),
        )
        for r in result.rows
        if r.get("table_name")
    ]
    _table_cache[key] = _CacheEntry(result=tables, fetched_at=time.monotonic())
    return tables


def list_columns(
    connection: Connection, schema: str, table: str,
) -> Union[list[ColumnInfo], CatalogFailure]:
    key = f"{connection.name}::columns::{schema}::{table}"
    cached = _fresh(_column_cache.get(key))
    if cached is not None:
        return cached
    engine = get_engine(connection.engine)
    if engine is None:
        return _no_engine(connection.engine)
    sql = engine.list_columns_sql(connection.catalog, schema, table)
    result = runner.run_query_rows(
        connection.dsn,
        sql,
        source=f"list_columns:{connection.name}.{schema}.{table}",
    )
    if not result.ok:
        return CatalogFailure(reason=result.reason, detail=result.detail)
    cols = _normalise_column_rows(result.rows)
    _column_cache[key] = _CacheEntry(result=cols, fetched_at=time.monotonic())
    return cols


def list_columns_many(
    connection: Connection, schema: str, tables: list[str],
) -> Union[dict[str, list[ColumnInfo]], CatalogFailure]:
    """Single round-trip per (connection, schema) for a batch of
    tables — Trino's federation overhead makes this a real speedup."""
    if not tables:
        return {}

    out: dict[str, list[ColumnInfo]] = {}
    stale: list[str] = []
    for t in tables:
        cached = _fresh(_column_cache.get(f"{connection.name}::columns::{schema}::{t}"))
        if cached is not None:
            out[t] = cached
        else:
            stale.append(t)
    if not stale:
        return out

    engine = get_engine(connection.engine)
    if engine is None:
        return _no_engine(connection.engine)
    sql = engine.list_columns_many_sql(connection.catalog, schema, stale)
    result = runner.run_query_rows(
        connection.dsn,
        sql,
        source=f"list_columns_many:{connection.name}.{schema}[{len(stale)}]",
    )
    if not result.ok:
        return CatalogFailure(reason=result.reason, detail=result.detail)

    grouped: dict[str, list[ColumnInfo]] = {}
    for row in result.rows:
        tn = str(row.get("table_name", ""))
        if not tn:
            continue
        grouped.setdefault(tn, []).append(_make_column(row))

    now = time.monotonic()
    for t in stale:
        cols = sorted(grouped.get(t, []), key=lambda c: c.ordinal_position)
        out[t] = cols
        _column_cache[f"{connection.name}::columns::{schema}::{t}"] = _CacheEntry(
            result=cols, fetched_at=now,
        )
    return out


def _make_column(row: dict[str, Any]) -> ColumnInfo:
    return ColumnInfo(
        name=str(row.get("column_name", "")),
        data_type=str(row.get("data_type", "")),
        nullable=str(row.get("is_nullable", "")).upper() != "NO",
        ordinal_position=int(row.get("ordinal_position") or 0),
    )


def _normalise_column_rows(rows: list[dict[str, Any]]) -> list[ColumnInfo]:
    out: list[ColumnInfo] = []
    for r in rows:
        if not r.get("column_name"):
            continue
        out.append(_make_column(r))
    out.sort(key=lambda c: c.ordinal_position)
    return out
