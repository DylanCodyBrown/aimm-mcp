"""Path resolution + idempotent layout creation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from aimm_mcp import paths


def test_aimm_root_is_under_documents(tmp_path: Path) -> None:
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    with patch("aimm_mcp.paths.Path.home", return_value=fake_home):
        assert paths.aimm_root() == fake_home / "Documents" / "AIMM"


def test_ensure_layout_is_idempotent(tmp_path: Path) -> None:
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    with patch("aimm_mcp.paths.Path.home", return_value=fake_home):
        paths.ensure_layout()
        # Second call must not raise.
        paths.ensure_layout()
        assert paths.aimm_root().exists()


def test_is_initialized_flips_after_writing_project_json(tmp_path: Path) -> None:
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    with patch("aimm_mcp.paths.Path.home", return_value=fake_home):
        assert not paths.is_initialized()
        paths.ensure_layout()
        paths.project_path().write_text('{"project":{"name":"demo"}}', encoding="utf-8")
        assert paths.is_initialized()
