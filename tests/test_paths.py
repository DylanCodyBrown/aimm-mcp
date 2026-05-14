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


def test_state_file_path_sits_inside_aimm_root(tmp_path: Path) -> None:
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    with patch("aimm_mcp.paths.Path.home", return_value=fake_home):
        assert paths.state_file_path().parent == paths.aimm_root()
        assert paths.state_file_path().name == "state.json"
