"""Engine registry: correct quoting + correct information_schema
qualification per engine."""

from __future__ import annotations

from aimm_mcp.odbc.engines import ENGINES, get_engine


def test_registry_has_three_engines() -> None:
    assert set(ENGINES.keys()) == {"trino", "sql_server", "databricks"}


def test_get_engine_unknown_returns_none() -> None:
    assert get_engine("nope") is None
    assert get_engine(None) is None


def test_trino_qualifies_with_double_quotes() -> None:
    e = ENGINES["trino"]
    sql = e.list_schemas_sql("hive")
    assert '"hive".information_schema.schemata' in sql
    assert sql.endswith("order by schema_name")


def test_trino_without_catalog_uses_bare_information_schema() -> None:
    e = ENGINES["trino"]
    sql = e.list_schemas_sql(None)
    assert "information_schema.schemata" in sql
    assert '"' not in sql.split("from")[1].split("order")[0]


def test_sql_server_uses_square_brackets_and_uppercase() -> None:
    e = ENGINES["sql_server"]
    sql = e.list_schemas_sql("reporting")
    assert "[reporting].INFORMATION_SCHEMA.SCHEMATA" in sql


def test_sql_server_synthesises_parameterised_data_type() -> None:
    e = ENGINES["sql_server"]
    sql = e.list_columns_sql("reporting", "dbo", "orders")
    # The CASE that builds nvarchar(255) / decimal(18,2) / etc.
    assert "CHARACTER_MAXIMUM_LENGTH" in sql
    assert "NUMERIC_PRECISION" in sql


def test_databricks_uses_backticks_and_unity_catalog_layout() -> None:
    e = ENGINES["databricks"]
    sql = e.list_schemas_sql("main")
    assert "`main`.information_schema.schemata" in sql


def test_databricks_columns_prefers_full_data_type() -> None:
    e = ENGINES["databricks"]
    sql = e.list_columns_sql("main", "default", "orders")
    assert "coalesce(full_data_type, data_type)" in sql


def test_columns_many_uses_in_list() -> None:
    e = ENGINES["trino"]
    sql = e.list_columns_many_sql("hive", "stg", ["a", "b", "c"])
    assert "table_name in ('a', 'b', 'c')" in sql


def test_single_quote_in_identifier_is_escaped() -> None:
    e = ENGINES["trino"]
    sql = e.list_columns_sql("hive", "weird'schema", "weird'table")
    # Single quotes inside string literals must be doubled.
    assert "weird''schema" in sql
    assert "weird''table" in sql
