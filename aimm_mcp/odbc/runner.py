"""Read-only ODBC runner.

Mirrors the extension's `extension/src/sync/runner.ts` — same
never-throws contract, same failure-reason taxonomy, with pyodbc in
place of the Node `odbc` package. Every call returns a typed result so
callers can build state machines without try/except around each query.

Callers in this codebase: catalog browser (information_schema reads).
That's it — there's no notebook, no result grid, no arbitrary user
SQL. This server is a metadata-stewardship tool, not a query
workbench.

A test seam lets the unit tests inject a fake connection factory in
place of the real pyodbc one. The diagnostics log is wired through
the same hook so every query the server issues lands in a
paste-able file.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Literal, Optional, Protocol, Union

try:
    import pyodbc  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised on platforms without driver
    pyodbc = None  # type: ignore[assignment]


FailureReason = Literal[
    "no_native_odbc",
    "connect_failed",
    "query_failed",
    "no_rows",
    "null_value",
    "timeout",
]


@dataclass(frozen=True)
class ScalarOk:
    ok: Literal[True] = True
    value: str = ""


@dataclass(frozen=True)
class RowsOk:
    ok: Literal[True] = True
    rows: list[dict[str, Any]] = None  # type: ignore[assignment]


@dataclass(frozen=True)
class Failure:
    reason: FailureReason
    detail: str
    ok: Literal[False] = False


ScalarResult = Union[ScalarOk, Failure]
RowsResult = Union[RowsOk, Failure]


# --- test seam --------------------------------------------------------------


class ConnectionLike(Protocol):
    """The narrow surface the runner needs from pyodbc. Tests
    substitute their own."""

    def cursor(self) -> Any: ...
    def close(self) -> None: ...


ConnectionFactory = Callable[[str], ConnectionLike]


_connection_factory: Optional[ConnectionFactory] = None


def set_connection_factory(factory: Optional[ConnectionFactory]) -> None:
    """Test hook. Setting `None` reverts to pyodbc."""
    global _connection_factory
    _connection_factory = factory


# --- diagnostics hook -------------------------------------------------------


class QueryLogger(Protocol):
    def log_query(self, event: dict[str, Any]) -> None: ...


_logger: Optional[QueryLogger] = None


def set_query_logger(logger: Optional[QueryLogger]) -> None:
    global _logger
    _logger = logger


# --- public API -------------------------------------------------------------


DEFAULT_TIMEOUT_S = 30.0


def run_query_rows(
    dsn: str,
    sql: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    source: Optional[str] = None,
) -> RowsResult:
    """Run a multi-row read. Lowercases every column name in the
    result so callers can read rows uniformly regardless of which
    engine returned the data (Trino lowercases, SQL Server preserves
    casing, Databricks lowercases)."""
    started = time.monotonic()
    if not _have_driver():
        result = _no_native()
        _log(dsn, sql, source, started, result)
        return result

    conn = _connect(dsn, timeout_s)
    if isinstance(conn, Failure):
        _log(dsn, sql, source, started, conn)
        return conn

    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        cols = [d[0].lower() for d in cursor.description] if cursor.description else []
        rows: list[dict[str, Any]] = []
        for raw in cursor.fetchall():
            rows.append({col: raw[i] for i, col in enumerate(cols)})
        result = RowsOk(rows=rows)
        _log(dsn, sql, source, started, result, row_count=len(rows))
        return result
    except Exception as err:  # noqa: BLE001
        result = Failure(reason="query_failed", detail=str(err))
        _log(dsn, sql, source, started, result)
        return result
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def run_scalar_string(
    dsn: str,
    sql: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    source: Optional[str] = None,
) -> ScalarResult:
    """Run a query that's expected to return a single scalar
    cell. Same never-throws contract as `run_query_rows`."""
    rows = run_query_rows(dsn, sql, timeout_s, source)
    if not rows.ok:
        return Failure(reason=rows.reason, detail=rows.detail)
    if not rows.rows:
        return Failure(reason="no_rows", detail="The query returned zero rows.")
    first = rows.rows[0]
    values = list(first.values())
    if not values:
        return Failure(reason="no_rows", detail="First row had no columns.")
    v = values[0]
    if v is None:
        return Failure(reason="null_value", detail="The scalar value came back NULL.")
    return ScalarOk(value=str(v))


# --- internals --------------------------------------------------------------


def _have_driver() -> bool:
    return _connection_factory is not None or pyodbc is not None


def _no_native() -> Failure:
    return Failure(
        reason="no_native_odbc",
        detail=(
            "pyodbc is not installed (or has no driver for this platform). "
            "Install the platform's ODBC driver and re-run."
        ),
    )


def _build_connection_string(dsn: str) -> str:
    """If the user pasted a full connection string (contains `=`),
    pass it verbatim. Otherwise treat it as a system DSN name."""
    return dsn if "=" in dsn else f"DSN={dsn}"


def _connect(dsn: str, timeout_s: float) -> Union[ConnectionLike, Failure]:
    factory = _connection_factory or _default_pyodbc_factory
    try:
        return factory(_build_connection_string(dsn))
    except Exception as err:  # noqa: BLE001
        return Failure(reason="connect_failed", detail=str(err))


def _default_pyodbc_factory(conn_str: str) -> ConnectionLike:
    if pyodbc is None:  # pragma: no cover
        raise RuntimeError("pyodbc not available")
    return pyodbc.connect(conn_str, autocommit=True)


def _log(
    dsn: str,
    sql: str,
    source: Optional[str],
    started_at: float,
    result: Union[ScalarResult, RowsResult],
    row_count: Optional[int] = None,
) -> None:
    if _logger is None:
        return
    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    if result.ok:
        payload = {
            "dsn": dsn,
            "sql": sql,
            "source": source,
            "duration_ms": elapsed_ms,
            "result": {"ok": True, "row_count": row_count if row_count is not None else 1},
        }
    else:
        payload = {
            "dsn": dsn,
            "sql": sql,
            "source": source,
            "duration_ms": elapsed_ms,
            "result": {"ok": False, "reason": result.reason, "detail": result.detail},
        }
    try:
        _logger.log_query(payload)
    except Exception:  # noqa: BLE001 - logging never breaks the caller
        pass
