"""Atomic JSON write + read roundtrip via pydantic schemas."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from aimm_mcp import paths, repo
from aimm_mcp.schemas import Connection, ProjectConfig, TableMeta


def _patched_home(tmp_path: Path):
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    return patch("aimm_mcp.paths.Path.home", return_value=fake_home)


def test_project_roundtrip(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        paths.ensure_layout()
        cfg = ProjectConfig(name="finance", dialect="trino", description="warehouse")
        repo.write_project(cfg)
        back = repo.read_project()
        assert back is not None
        assert back.name == "finance"
        assert back.dialect == "trino"


def test_table_roundtrip(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        paths.ensure_layout()
        meta = TableMeta(table_name="orders", staging_target="stg.orders")
        repo.write_table(meta)
        back = repo.read_table("orders")
        assert back is not None
        assert back.table_name == "orders"
        assert back.staging_target == "stg.orders"


def test_connection_roundtrip(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        paths.ensure_layout()
        conn = Connection(name="wh", engine="trino", dsn="warehouse", catalog="hive")
        repo.write_connection(conn)
        back = repo.read_connection("wh")
        assert back is not None
        assert back.engine == "trino"
        assert back.catalog == "hive"


def test_list_helpers_skip_dot_files(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        paths.ensure_layout()
        repo.write_table(TableMeta(table_name="a"))
        repo.write_table(TableMeta(table_name="b"))
        # Simulate a half-written atomic-write leftover.
        (paths.tables_dir() / ".tmp.json.123").write_text("{}")
        assert repo.list_table_names() == ["a", "b"]


def test_read_returns_none_when_missing(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        paths.ensure_layout()
        assert repo.read_project() is None
        assert repo.read_table("nope") is None
        assert repo.read_connection("nope") is None
