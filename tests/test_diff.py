"""Column diff: case-insensitive name match + unknown-type skip."""

from __future__ import annotations

from aimm_mcp.parse.diff import ColumnDiff, diff_columns, is_empty
from aimm_mcp.schemas import Column


def _col(name: str, type: str = "", nullable: bool = True) -> Column:
    return Column(name=name, type=type, nullable=nullable)


def test_identical_lists_diff_empty() -> None:
    d = diff_columns([_col("x", "int", False)], [_col("x", "int", False)])
    assert is_empty(d)


def test_added_and_removed() -> None:
    d = diff_columns(
        authored=[_col("a", "int"), _col("b", "varchar(40)")],
        live=[_col("a", "int"), _col("gone", "varchar")],
    )
    assert [c.name for c in d.added] == ["b"]
    assert [c.name for c in d.removed] == ["gone"]


def test_case_insensitive_name_match() -> None:
    # Trino's information_schema returns lowercased names; sqlglot
    # preserves the author's casing. Case-only differences must NOT
    # count as added+removed.
    d = diff_columns(
        authored=[_col("OrderId", "bigint", False)],
        live=[_col("orderid", "bigint", False)],
    )
    assert is_empty(d)


def test_case_insensitive_match_still_detects_type_change() -> None:
    d = diff_columns(
        authored=[_col("OrderId", "bigint", False)],
        live=[_col("orderid", "int", False)],
    )
    assert len(d.changed) == 1
    assert d.changed[0].before_type == "int"
    assert d.changed[0].after_type == "bigint"


def test_unknown_authored_type_suppresses_change() -> None:
    # sqlglot couldn't infer the authored type. Empty type isn't a
    # change vs. the live `bigint`.
    d = diff_columns(
        authored=[_col("col", "", True)],
        live=[_col("col", "bigint", False)],
    )
    assert d.changed == []


def test_unknown_type_still_flows_through_added() -> None:
    d = diff_columns(authored=[_col("newcol", "")], live=[])
    assert [c.name for c in d.added] == ["newcol"]
