"""Diagnostics log formatter + tail + file writer."""

from __future__ import annotations

from pathlib import Path

from aimm_mcp.diagnostics.log import FileQueryLogger, format_event, tail_log


def test_format_event_renders_single_line_on_success() -> None:
    line = format_event({
        "dsn": "wh", "sql": "select 1\n  from   t", "source": "list_schemas:wh",
        "duration_ms": 42, "result": {"ok": True, "row_count": 7},
    })
    assert "\n" not in line
    assert "42ms dsn=wh src=list_schemas:wh ok rows=7 sql=select 1 from t" in line


def test_format_event_renders_failure() -> None:
    line = format_event({
        "dsn": "wh", "sql": "select 1", "duration_ms": 100,
        "result": {"ok": False, "reason": "connect_failed", "detail": "unable to connect to host\n[ODBC]..."},
    })
    assert "fail connect_failed" in line
    assert "ODBC" in line


def test_format_event_collapses_long_sql() -> None:
    huge = "select " + "x," * 400 + "y from t"
    line = format_event({"dsn": "wh", "sql": huge, "duration_ms": 1, "result": {"ok": True, "row_count": 0}})
    sql_segment = line.split("sql=")[-1]
    assert len(sql_segment) <= 501


def test_file_logger_appends_and_rotates(tmp_path: Path) -> None:
    log = tmp_path / "diagnostics.log"
    logger = FileQueryLogger(log, rotate_bytes=200)
    for i in range(20):
        logger.log_query({
            "dsn": "wh",
            "sql": f"select {i} -- {'x' * 60}",
            "duration_ms": 1,
            "result": {"ok": True, "row_count": 0},
        })
    rolled = log.with_suffix(log.suffix + ".old")
    assert log.exists()
    assert rolled.exists()


def test_tail_log_returns_empty_when_missing(tmp_path: Path) -> None:
    assert tail_log(tmp_path / "nope.log") == ""


def test_tail_log_returns_last_bytes(tmp_path: Path) -> None:
    log = tmp_path / "diagnostics.log"
    big = ("A" * 10_000) + "\nLAST_LINE_CONTENT"
    log.write_text(big, encoding="utf-8")
    tail = tail_log(log, max_bytes=64)
    assert "LAST_LINE_CONTENT" in tail
    assert len(tail) <= 64
