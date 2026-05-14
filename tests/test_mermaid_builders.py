"""Unit tests for the pure aggregator builders."""

from __future__ import annotations

from aimm_mcp.mermaid import builders
from aimm_mcp.schemas import Dependency, Relationship, TableMeta


def _table(name: str, **kw) -> TableMeta:
    return TableMeta(table_name=name, **kw)


def test_er_diagram_handles_empty_project() -> None:
    out = builders.render_er_diagram([])
    assert out.startswith("erDiagram")
    assert "_empty" in out  # placeholder entity so mermaid renders


def test_er_diagram_emits_pk_columns_only() -> None:
    from aimm_mcp.schemas import Column
    t = _table("orders", columns=[
        Column(name="id", type="bigint", is_primary_key=True),
        Column(name="customer_id", type="bigint"),
    ], primary_keys=["id"])
    out = builders.render_er_diagram([t])
    assert "id PK" in out
    assert "customer_id PK" not in out  # not a PK


def test_lineage_flowchart_renders_arrows() -> None:
    t = _table("orders", upstream=[Dependency(ref="raw.orders")])
    out = builders.render_lineage_flowchart([t])
    assert "flowchart LR" in out
    assert "raw_orders --> orders" in out


def test_lineage_doc_dedupes_and_sorts() -> None:
    t = _table("orders", upstream=[
        Dependency(ref="b"),
        Dependency(ref="a", description="reads"),
        Dependency(ref="a"),  # duplicate
    ])
    doc = builders.build_lineage_doc([t])
    edges = doc["edges"]
    assert len(edges) == 2
    assert edges[0]["to"] == "a"
    assert edges[1]["to"] == "b"
    assert edges[0].get("description") == "reads"


def test_relationships_doc_preserves_composite_keys() -> None:
    t = _table("orders", relationships=[Relationship(
        to_table="products",
        from_columns=["product_id", "region"],
        to_columns=["id", "region"],
        cardinality="one_to_many",
    )])
    doc = builders.build_relationships_doc([t])
    assert doc["edges"][0]["from_columns"] == ["product_id", "region"]
    assert doc["edges"][0]["to_columns"] == ["id", "region"]


def test_joins_doc_collapses_relationship_and_sql_into_one_entry() -> None:
    t = _table("orders", relationships=[Relationship(
        to_table="customers",
        from_columns=["customer_id"],
        to_columns=["id"],
        cardinality="one_to_many",
    )])
    extracted = [(
        "orders.sql",
        [{
            "kind": "LEFT",
            "right_table": "customers",
            "on_text": "o.customer_id = c.id",
            "clause_text": "LEFT JOIN customers c ON o.customer_id = c.id",
            "line": 12,
            "equalities": [{
                "left": {"schema": None, "table": "orders", "column": "customer_id"},
                "right": {"schema": None, "table": "customers", "column": "id"},
            }],
        }],
    )]
    doc = builders.build_joins_doc([t], extracted)
    assert len(doc["joins"]) == 1
    j = doc["joins"][0]
    kinds = sorted(s["kind"] for s in j["sources"])
    assert kinds == ["relationship", "sql"]


def test_joins_doc_drops_unresolved_equalities() -> None:
    extracted = [("a.sql", [{
        "kind": "JOIN",
        "on_text": "?",
        "clause_text": "?",
        "equalities": [{
            "left": {"schema": None, "table": None, "column": "x"},
            "right": {"schema": None, "table": "b", "column": "id"},
        }],
    }])]
    doc = builders.build_joins_doc([], extracted)
    assert doc["joins"] == []
