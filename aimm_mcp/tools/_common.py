"""Shared helpers for tools — mostly the active-project guard.

Every project-touching tool starts the same way: confirm there's an
active project file selected, load it, surface a uniform error if
either step fails. This module is the one place that boilerplate
lives, so the error message stays consistent across tools.
"""

from __future__ import annotations

from typing import Optional

from mcp.types import TextContent

from .. import session, state
from ..schemas import Project


BOOTSTRAP_HINT = (
    "Call aimm_list_projects to see what's available, then "
    "aimm_set_active_project. Or aimm_init_project to create a new one."
)


def project_not_selected_error() -> list[TextContent]:
    """The single message every error-trapped tool returns when no active project is set."""
    return [TextContent(
        type="text",
        text=f"Error: project file not selected. {BOOTSTRAP_HINT}",
    )]


def ensure_active() -> Optional[list[TextContent]]:
    """Return an error response when no active project, else None.

    Use in mutate-style tools that don't read the project up front.
    """
    if session.active_project_path() is None:
        return project_not_selected_error()
    return None


def load_active() -> tuple[Optional[Project], Optional[list[TextContent]]]:
    """`(project, None)` on success, `(None, error_response)` otherwise.

    Use in read-style tools — saves a load() call when the active
    pointer isn't set, and converts "active set but file missing /
    corrupt" into its own specific error.
    """
    active = session.active_project_path()
    if active is None:
        return None, project_not_selected_error()
    project = state.load()
    if project is None:
        return None, [TextContent(
            type="text",
            text=(
                f"Active project file at {active} is missing or unreadable. "
                "Pick another with aimm_list_projects + aimm_set_active_project, "
                "or restore the file."
            ),
        )]
    return project, None
