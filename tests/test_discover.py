"""Scan-folder smoke test using real sqlglot parsing."""

from __future__ import annotations

from pathlib import Path

from aimm_mcp.discover.scan import scan_folder


SQL_BASIC = """
SELECT o.id, c.name
FROM stg_finance.orders o
LEFT JOIN stg_customer.customers c ON o.customer_id = c.id
"""

SQL_TSQL_BRACKETS = """
SELECT a.id, b.name
FROM [stg_finance].[orders] a
INNER JOIN [stg_customer].[customers] b ON a.customer_id = b.id
"""

SQL_NO_JOINS = "SELECT 1 FROM t"


def test_scan_folder_extracts_joins_across_files(tmp_path: Path) -> None:
    (tmp_path / "a.sql").write_text(SQL_BASIC, encoding="utf-8")
    (tmp_path / "b.sql").write_text(SQL_TSQL_BRACKETS, encoding="utf-8")
    (tmp_path / "c.sql").write_text(SQL_NO_JOINS, encoding="utf-8")
    result = scan_folder(tmp_path, dialect="trino")
    assert result.files_scanned == 3
    # Both join files describe the same edge: orders ↔ customers.
    # Should collapse into one canonical relationship with two
    # occurrences (one per file).
    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert len(rel.occurrences) == 2
    files = sorted(o.file for o in rel.occurrences)
    assert files == ["a.sql", "b.sql"]


def test_scan_folder_skips_common_ignore_dirs(tmp_path: Path) -> None:
    # File hidden under node_modules should be invisible to the walk.
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "hidden.sql").write_text(SQL_BASIC, encoding="utf-8")
    (tmp_path / "real.sql").write_text(SQL_BASIC, encoding="utf-8")
    result = scan_folder(tmp_path)
    assert result.files_scanned == 1
    assert result.relationships[0].occurrences[0].file == "real.sql"


def test_scan_folder_handles_no_joins_gracefully(tmp_path: Path) -> None:
    (tmp_path / "a.sql").write_text(SQL_NO_JOINS, encoding="utf-8")
    result = scan_folder(tmp_path)
    assert result.relationships == []
    assert result.files_scanned == 1
