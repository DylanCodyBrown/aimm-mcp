"""Semantic-context tools — grain, pitfalls, classification, glossary, measures."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from aimm_mcp import paths, session, state
from aimm_mcp.schemas import Column, Project, ProjectConfig, TableMeta
from aimm_mcp.tools import semantic


def _patched_home(tmp_path: Path):
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    return patch("aimm_mcp.paths.Path.home", return_value=fake_home)


def _bootstrap_active(table_names: list[str] = ()) -> None:
    paths.ensure_layout()
    folder = session.projects_folder()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "demo.aimm.json"
    project = Project(
        project=ProjectConfig(name="demo"),
        tables=[TableMeta(table_name=n) for n in table_names],
    )
    state.write_to(project, target)
    session.set_active_project("demo.aimm.json")


def _call(tool: str, args: dict) -> str:
    result = asyncio.run(semantic.dispatch(tool, args))
    return result[0].text


def test_set_grain_writes_to_table(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        _bootstrap_active(["orders"])
        out = _call("aimm_set_table_grain", {"table": "orders", "grain": "one row per order line"})
        assert "Set grain" in out
        loaded = state.load()
        assert loaded is not None
        assert loaded.tables[0].grain == "one row per order line"


def test_set_grain_rejects_overlong(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        _bootstrap_active(["orders"])
        out = _call("aimm_set_table_grain", {"table": "orders", "grain": "x" * 241})
        assert "exceeds 240" in out


def test_set_grain_unknown_table_errors(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        _bootstrap_active(["orders"])
        out = _call("aimm_set_table_grain", {"table": "nope", "grain": "x"})
        assert "Unknown table" in out


def test_add_pitfall_appends_and_dedupes(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        _bootstrap_active(["orders"])
        out1 = _call("aimm_add_pitfall", {"table": "orders", "message": "don't join on email"})
        assert "Added pitfall" in out1
        out2 = _call("aimm_add_pitfall", {"table": "orders", "message": "don't join on email"})
        assert "already recorded" in out2
        out3 = _call("aimm_add_pitfall", {"table": "orders", "message": "amount is in cents"})
        assert "Added pitfall" in out3
        loaded = state.load()
        assert loaded is not None
        assert loaded.tables[0].pitfalls == ["don't join on email", "amount is in cents"]


def test_set_classification_flips_column(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        _bootstrap_active()
        paths.ensure_layout()
        # Re-write with a column.
        target = session.active_project_path()
        assert target is not None
        project = Project(
            project=ProjectConfig(name="demo"),
            tables=[TableMeta(
                table_name="customer",
                columns=[Column(name="email"), Column(name="id")],
            )],
        )
        state.write_to(project, target)
        out = _call(
            "aimm_set_column_classification",
            {"table": "customer", "column": "email", "classification": "pii"},
        )
        assert "pii" in out.lower()
        loaded = state.load()
        assert loaded is not None
        cols = {c.name: c.classification for c in loaded.tables[0].columns}
        assert cols["email"] == "pii"
        assert cols["id"] == "unspecified"


def test_set_classification_unknown_column_errors(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        _bootstrap_active(["t"])
        out = _call(
            "aimm_set_column_classification",
            {"table": "t", "column": "missing", "classification": "pii"},
        )
        assert "Unknown column" in out


def test_set_classification_invalid_value(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        _bootstrap_active(["t"])
        out = _call(
            "aimm_set_column_classification",
            {"table": "t", "column": "c", "classification": "bogus"},
        )
        assert "Error" in out


def test_add_glossary_term_upserts(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        _bootstrap_active()
        out1 = _call(
            "aimm_add_glossary_term",
            {"term": "active customer", "definition": "v1 definition"},
        )
        assert "Added" in out1
        out2 = _call(
            "aimm_add_glossary_term",
            {"term": "active customer", "definition": "v2 definition"},
        )
        assert "Updated" in out2
        loaded = state.load()
        assert loaded is not None
        assert loaded.project.glossary[0].definition == "v2 definition"
        assert len(loaded.project.glossary) == 1


def test_add_measure_upserts_with_formula(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        _bootstrap_active()
        out = _call(
            "aimm_add_measure",
            {
                "name": "MAC",
                "definition": "Monthly Active Customers",
                "formula": "count(distinct customer_id) where last_active >= ...",
            },
        )
        assert "Added measure" in out
        loaded = state.load()
        assert loaded is not None
        m = loaded.project.measures[0]
        assert m.name == "MAC"
        assert m.formula and "distinct" in m.formula


def test_update_project_config_patches_allowed_fields(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        _bootstrap_active()
        out = _call(
            "aimm_update_project_config",
            {"patch": {"description": "demo project", "conventions": "all dates UTC", "modeling_paradigm": "star"}},
        )
        assert "Updated" in out
        loaded = state.load()
        assert loaded is not None
        assert loaded.project.description == "demo project"
        assert loaded.project.conventions == "all dates UTC"
        assert loaded.project.modeling_paradigm == "star"


def test_update_project_config_rejects_unknown_field(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        _bootstrap_active()
        out = _call("aimm_update_project_config", {"patch": {"bogus": 1}})
        assert "Unknown patch fields" in out


def test_semantic_tools_error_when_no_active_project(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        # Don't bootstrap.
        out = _call("aimm_set_table_grain", {"table": "t", "grain": "x"})
        assert "project file not selected" in out
