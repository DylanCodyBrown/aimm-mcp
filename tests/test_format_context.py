"""format_context — XML + markdown renderer.

Spot-checks every semantic-context field shows up when set. The
renderer is the agent's only view of the project; if a field doesn't
make it through, no agent reasoning will pick it up.
"""

from __future__ import annotations

from aimm_mcp.format_context import format_project_context
from aimm_mcp.schemas import (
    Column,
    Connection,
    GlossaryTerm,
    Measure,
    ProjectConfig,
    ScdMetadata,
    TableMeta,
)


def _full_project() -> tuple[ProjectConfig, list[Connection], list[TableMeta]]:
    cfg = ProjectConfig(
        name="Demo",
        modeling_paradigm="star",
        dialect="trino",
        description="demo project",
        conventions="All booleans end in _flag. All dates UTC.",
        glossary=[
            GlossaryTerm(term="active customer", definition="at least one paid order in trailing 90 days"),
        ],
        measures=[
            Measure(
                name="MAC",
                definition="Monthly Active Customers",
                formula="count(distinct customer_id)",
                owner="data-eng",
            ),
        ],
    )
    connections = [
        Connection(name="wh", engine="trino", dsn="wh", catalog="hive"),
    ]
    tables = [
        TableMeta(
            table_name="fct_orders",
            connection="wh",
            paradigm_role="fact",
            description="order facts",
            grain="one row per order line item",
            aliases=["transactions"],
            pitfalls=["Don't join on email; use customer_id."],
            owner="alice@example.com",
            refresh_cadence="hourly",
            refresh_notes="Lambda CDC pipeline, ~15min lag",
            scd=ScdMetadata(type="scd2", valid_from="valid_from", valid_to="valid_to", is_current_flag="is_current"),
            row_count_last_run=1_234_567,
            last_run_at="2026-05-14T12:00:00Z",
            columns=[
                Column(
                    name="order_id",
                    type="bigint",
                    nullable=False,
                    is_primary_key=True,
                    classification="internal",
                ),
                Column(
                    name="customer_email",
                    type="varchar",
                    classification="pii",
                    quality_notes="historical bad data pre-2023",
                    example_values=["a@example.com", "b@example.com"],
                ),
                Column(
                    name="full_name",
                    type="varchar",
                    computed=True,
                    expression="first_name || ' ' || last_name",
                ),
            ],
            primary_keys=["order_id"],
        ),
    ]
    return cfg, connections, tables


def test_xml_emits_all_semantic_fields() -> None:
    cfg, conns, tables = _full_project()
    xml = format_project_context(cfg, conns, tables, fmt="xml")

    # Project-level
    assert "<conventions>" in xml
    assert "All booleans end in _flag" in xml
    assert "<glossary>" in xml
    assert 'name="active customer"' in xml
    assert "<measures>" in xml
    assert 'name="MAC"' in xml
    assert "<formula>count(distinct customer_id)" in xml
    assert 'paradigm="star"' in xml

    # Table-level
    assert "<grain>one row per order line item</grain>" in xml
    assert "<aliases>transactions</aliases>" in xml
    assert "<pitfalls>" in xml
    assert "<pitfall>Don&apos;t join on email" in xml or "Don't join on email" in xml
    assert 'owner="alice@example.com"' in xml
    assert 'refresh_cadence="hourly"' in xml
    assert "<refresh_notes>Lambda CDC pipeline" in xml
    assert '<scd type="scd2"' in xml
    assert 'is_current_flag="is_current"' in xml
    assert 'row_count_last_run="1234567"' in xml
    assert 'last_run_at="2026-05-14T12:00:00Z"' in xml

    # Column-level
    assert 'classification="pii"' in xml
    assert 'computed="true"' in xml
    assert "<quality_notes>historical bad data pre-2023" in xml
    assert "<expression>first_name" in xml
    assert "<example_values>a@example.com, b@example.com</example_values>" in xml


def test_xml_omits_default_semantic_fields() -> None:
    """Empty / default values should NOT appear — the dump stays dense.

    Assertions run against the rendered document body, not the
    `<aimm_schema>` preamble (which references every field by name).
    """
    cfg = ProjectConfig(name="bare")
    rendered = format_project_context(cfg, [], [TableMeta(table_name="t")], fmt="xml")
    body = rendered.split("</aimm_schema>", 1)[1]
    # Project defaults
    assert "<conventions>" not in body
    assert "<glossary>" not in body
    assert "<measures>" not in body
    assert "paradigm=" not in body
    # Table defaults
    assert "<grain>" not in body
    assert "<aliases>" not in body
    assert "<pitfalls>" not in body
    assert "refresh_cadence=" not in body
    assert "row_count_last_run=" not in body
    assert "<scd " not in body


def test_markdown_emits_semantic_fields() -> None:
    cfg, conns, tables = _full_project()
    md = format_project_context(cfg, conns, tables, fmt="markdown")

    assert "## Conventions" in md
    assert "All booleans end in _flag" in md
    assert "## Glossary (1)" in md
    assert "**active customer**" in md
    assert "## Measures (1)" in md
    assert "**MAC**" in md
    assert "count(distinct customer_id)" in md

    assert "Grain: one row per order line item" in md
    assert "Aliases: transactions" in md
    assert "Owner: alice@example.com" in md
    assert "Refresh: `hourly`" in md
    assert "Row count: 1,234,567 @ 2026-05-14T12:00:00Z" in md
    assert "SCD: type=scd2" in md
    assert "Pitfalls:" in md
    assert "PII" in md
    assert "computed" in md
    assert "Quality: historical bad data pre-2023" in md
    assert "Expression: `first_name" in md
    assert "Examples: a@example.com, b@example.com" in md
