"""session.py — projects_folder + active_project_file lifecycle."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from aimm_mcp import paths, session


def _patched_home(tmp_path: Path):
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    return patch("aimm_mcp.paths.Path.home", return_value=fake_home)


def test_load_session_returns_defaults_when_missing(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        s = session.load_session()
        assert s.projects_folder is None
        assert s.active_project_file is None


def test_projects_folder_defaults_to_aimm_root(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        assert session.projects_folder() == paths.aimm_root()


def test_set_projects_folder_persists_and_validates(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        target = tmp_path / "team-models"
        with pytest.raises(FileNotFoundError):
            session.set_projects_folder(target)
        target.mkdir()
        session.set_projects_folder(target)
        # Re-read from disk to confirm persistence.
        assert session.projects_folder() == target


def test_set_projects_folder_clears_active_project(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        paths.ensure_layout()
        (paths.aimm_root() / "x.aimm.json").write_text("{}", encoding="utf-8")
        session.set_active_project("x.aimm.json")
        assert session.load_session().active_project_file == "x.aimm.json"
        other = tmp_path / "other"
        other.mkdir()
        session.set_projects_folder(other)
        assert session.load_session().active_project_file is None


def test_active_project_path_returns_none_when_unset(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        assert session.active_project_path() is None


def test_set_active_project_requires_file_exists(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        paths.ensure_layout()
        with pytest.raises(FileNotFoundError):
            session.set_active_project("missing.aimm.json")
        (paths.aimm_root() / "ok.aimm.json").write_text("{}", encoding="utf-8")
        session.set_active_project("ok.aimm.json")
        assert session.active_project_path() == paths.aimm_root() / "ok.aimm.json"


def test_require_active_project_path_raises_when_unset(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        with pytest.raises(session.ActiveProjectNotSelected):
            session.require_active_project_path()


def test_slugify_handles_common_inputs() -> None:
    assert session.slugify("Customer Warehouse") == "customer_warehouse"
    assert session.slugify("  Spaces   And  Stuff!! ") == "spaces_and_stuff"
    assert session.slugify("PII / 2024") == "pii_2024"
    assert session.slugify("___") == "untitled"
    assert session.slugify("") == "untitled"


def test_filename_for_appends_suffix() -> None:
    assert session.filename_for("My Project") == "my_project.aimm.json"


def test_list_project_files_sorted(tmp_path: Path) -> None:
    with _patched_home(tmp_path):
        paths.ensure_layout()
        for name in ("c.aimm.json", "a.aimm.json", "b.aimm.json", "ignore.json"):
            (paths.aimm_root() / name).write_text("{}", encoding="utf-8")
        names = [p.name for p in session.list_project_files()]
        assert names == ["a.aimm.json", "b.aimm.json", "c.aimm.json"]


def test_session_survives_corrupt_state_file(tmp_path: Path) -> None:
    """A corrupt state.json shouldn't brick the server — load returns defaults."""
    with _patched_home(tmp_path):
        paths.ensure_layout()
        paths.state_file_path().write_text("{not json", encoding="utf-8")
        s = session.load_session()
        assert s.projects_folder is None
        assert s.active_project_file is None
