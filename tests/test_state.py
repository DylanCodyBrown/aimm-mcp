"""Unified project.json state + legacy-layout migration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from aimm_mcp import paths, state
from aimm_mcp.schemas import (
    Connection,
    Project,
    ProjectConfig,
    Relationship,
    TableMeta,
)


def _patched_home(tmp_path: Path):
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    return patch("aimm_mcp.paths.Path.home", return_value=fake_home)


def test_load_returns_none_when_no_project(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        assert state.load() is None


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
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


def test_legacy_per_file_layout_is_migrated(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        # Simulate the v0.1 per-file layout. load() should consolidate
        # into project.json AND remove the old files.
        paths.ensure_layout()
        (paths.aimm_root() / "aimm.json").write_text(
            json.dumps({"name": "legacy", "dialect": "trino"}),
            encoding="utf-8",
        )
        (paths.aimm_root() / "tables").mkdir(exist_ok=True)
        (paths.aimm_root() / "tables" / "orders.json").write_text(
            json.dumps({"table_name": "orders"}),
            encoding="utf-8",
        )
        (paths.aimm_root() / "connections").mkdir(exist_ok=True)
        (paths.aimm_root() / "connections" / "wh.json").write_text(
            json.dumps({"name": "wh", "engine": "trino", "dsn": "wh", "catalog": "hive"}),
            encoding="utf-8",
        )
        project = state.load()
        assert project is not None
        assert project.project.name == "legacy"
        assert [t.table_name for t in project.tables] == ["orders"]
        assert [c.name for c in project.connections] == ["wh"]
        # Old files cleaned up after migration.
        assert not (paths.aimm_root() / "aimm.json").exists()
        assert not (paths.aimm_root() / "tables").exists()
        assert not (paths.aimm_root() / "connections").exists()
        # New unified file exists.
        assert (paths.aimm_root() / "project.json").exists()


def test_mutate_fires_after_mutation_hook(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        seen: list[Project] = []
        state.set_after_mutation_hook(lambda p: seen.append(p))
        try:
            state.save(Project(project=ProjectConfig(name="demo")))
            state.mutate(lambda p: state.upsert_table(p, TableMeta(table_name="x")))
            assert len(seen) == 1
            assert seen[0].tables[0].table_name == "x"
        finally:
            state.set_after_mutation_hook(None)


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
