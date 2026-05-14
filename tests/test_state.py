"""state.py — read/write the active project file + helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from aimm_mcp import paths, session, state
from aimm_mcp.schemas import (
    Connection,
    Project,
    ProjectConfig,
    TableMeta,
)
from aimm_mcp.session import ActiveProjectNotSelected


def _patched_home(tmp_path: Path):
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    return patch("aimm_mcp.paths.Path.home", return_value=fake_home)


def _bootstrap_active(filename: str = "demo.aimm.json") -> None:
    """Create an empty project file and point the session at it."""
    paths.ensure_layout()
    folder = session.projects_folder()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / filename
    state.write_to(Project(project=ProjectConfig(name="demo")), target)
    session.set_active_project(filename)


def test_load_returns_none_when_no_active_project(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        assert state.load() is None


def test_save_raises_when_no_active_project(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        with pytest.raises(ActiveProjectNotSelected):
            state.save(Project(project=ProjectConfig(name="demo")))


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        _bootstrap_active()
        p = Project(
            project=ProjectConfig(name="demo", dialect="trino"),
            connections=[Connection(name="wh", engine="trino", dsn="wh", catalog="hive")],
            tables=[TableMeta(table_name="orders")],
        )
        state.save(p)
        back = state.load()
        assert back is not None
        assert back.project.name == "demo"
        assert back.connections[0].name == "wh"
        assert back.tables[0].table_name == "orders"
        # save() stamps an updated_at.
        assert back.updated_at is not None


def test_mutate_fires_after_mutation_hook(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        _bootstrap_active()
        seen: list[Project] = []
        state.set_after_mutation_hook(lambda p: seen.append(p))
        try:
            state.mutate(lambda p: state.upsert_table(p, TableMeta(table_name="x")))
            assert len(seen) == 1
            assert seen[0].tables[0].table_name == "x"
        finally:
            state.set_after_mutation_hook(None)


def test_mutate_raises_when_no_active_project(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        with pytest.raises(ActiveProjectNotSelected):
            state.mutate(lambda p: p)


def test_upsert_table_replaces_in_place(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        p = Project(
            project=ProjectConfig(name="demo"),
            tables=[TableMeta(table_name="a", description="old"), TableMeta(table_name="b")],
        )
        next_p = state.upsert_table(p, TableMeta(table_name="a", description="new"))
        a = next_p.tables[0]
        assert a.description == "new"
        # Order preserved.
        assert [t.table_name for t in next_p.tables] == ["a", "b"]


def test_upsert_connection_appends_new(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        p = Project(project=ProjectConfig(name="demo"))
        next_p = state.upsert_connection(p, Connection(name="wh", engine="trino", dsn="wh", catalog="hive"))
        assert len(next_p.connections) == 1
