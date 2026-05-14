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
        root = paths.aimm_root()
        assert root.exists()
        assert (root / "tables").is_dir()
        assert (root / "connections").is_dir()


def test_is_initialized_flips_after_writing_aimm_json(tmp_path: Path) -> None:
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    with patch("aimm_mcp.paths.Path.home", return_value=fake_home):
        assert not paths.is_initialized()
        paths.ensure_layout()
        (paths.aimm_root() / "aimm.json").write_text('{"name":"demo"}', encoding="utf-8")
        assert paths.is_initialized()
