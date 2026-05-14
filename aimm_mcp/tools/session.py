"""Session / context tools.

  - aimm_set_projects_folder    point at a folder of `.aimm.json` files
  - aimm_list_projects          enumerate `.aimm.json` files in current folder
  - aimm_set_active_project     pick one and persist as active
  - aimm_show_active_project    report current folder + active file

Bootstrap order: list → set_active, or call aimm_init_project to
create a new one. Every other tool that touches project state errors
with "project file not selected" until an active project is set.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.types import TextContent, Tool

from .. import paths, session
from ..schemas import Project


TOOLS: list[Tool] = [
    Tool(
        name="aimm_set_projects_folder",
        description=(
            "Point the server at the folder where AIMM project files live. "
            "Defaults to ~/Documents/AIMM/ on a fresh machine; switch to a "
            "team repo (e.g. /Users/me/repos/data-models) to share project "
            "files with teammates via version control. The folder must "
            "exist. Resets the active project pointer (call "
            "aimm_list_projects + aimm_set_active_project to pick one in "
            "the new folder, or aimm_init_project to create one)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to a folder of `.aimm.json` files."},
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="aimm_list_projects",
        description=(
            "List every `*.aimm.json` file in the current projects folder. "
            "Returns filename, the project name from inside each file, and "
            "the last-updated timestamp. Use before aimm_set_active_project "
            "to see what's available."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="aimm_set_active_project",
        description=(
            "Make `<filename>` the active project. Subsequent tool calls "
            "read and write that file. The file must already exist in the "
            "current projects folder (see aimm_list_projects). To create a "
            "new project file, call aimm_init_project."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "e.g. `customer_warehouse.aimm.json`"},
            },
            "required": ["filename"],
        },
    ),
    Tool(
        name="aimm_show_active_project",
        description=(
            "Report the current session pointer: which projects folder is "
            "in use, which project file is active, and whether the file "
            "exists on disk. Useful for the agent to introspect at session "
            "start before deciding whether to call aimm_list_projects / "
            "aimm_set_active_project."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
]


async def dispatch(name: str, args: dict[str, Any]) -> list[TextContent]:
    if name == "aimm_set_projects_folder":
        return await _set_folder(args)
    if name == "aimm_list_projects":
        return await _list_projects(args)
    if name == "aimm_set_active_project":
        return await _set_active(args)
    if name == "aimm_show_active_project":
        return await _show(args)
    raise ValueError(f"session.dispatch: unknown tool {name}")


async def _set_folder(args: dict[str, Any]) -> list[TextContent]:
    raw = args.get("path")
    if not raw:
        return [TextContent(type="text", text="Error: `path` is required.")]
    try:
        next_state = session.set_projects_folder(Path(raw))
    except FileNotFoundError as err:
        return [TextContent(type="text", text=f"Error: {err}")]
    return [TextContent(
        type="text",
        text=(
            f"Projects folder set to {next_state.projects_folder}. "
            "Active project cleared — call aimm_list_projects + "
            "aimm_set_active_project to pick one, or aimm_init_project to "
            "create a new one."
        ),
    )]


async def _list_projects(_: dict[str, Any]) -> list[TextContent]:
    folder = session.projects_folder()
    files = session.list_project_files()
    if not files:
        return [TextContent(
            type="text",
            text=(
                f"No `*.aimm.json` files in {folder}. "
                "Call aimm_init_project to create one, or "
                "aimm_set_projects_folder to point at a different folder."
            ),
        )]
    rows: list[str] = []
    for f in files:
        name = _peek_project_name(f) or "<unparseable>"
        updated = _peek_updated_at(f) or ""
        rows.append(f"  - {f.name}   name='{name}'   updated_at={updated}")
    return [TextContent(
        type="text",
        text=(
            f"Projects in {folder}:\n" + "\n".join(rows)
            + "\n\nCall aimm_set_active_project({filename: '<one of these>'}) to pick one."
        ),
    )]


async def _set_active(args: dict[str, Any]) -> list[TextContent]:
    filename = args.get("filename")
    if not filename:
        return [TextContent(type="text", text="Error: `filename` is required.")]
    try:
        next_state = session.set_active_project(filename)
    except FileNotFoundError as err:
        return [TextContent(type="text", text=f"Error: {err}")]
    except ValueError as err:
        return [TextContent(type="text", text=f"Error: {err}")]
    return [TextContent(
        type="text",
        text=(
            f"Active project set to {next_state.active_project_file} "
            f"(in {session.projects_folder()}). "
            "Call aimm_read_project_context to load it into context."
        ),
    )]


async def _show(_: dict[str, Any]) -> list[TextContent]:
    s = session.load_session()
    folder = session.projects_folder()
    active = session.active_project_path()
    lines = [
        f"projects_folder: {folder}" + (
            "  (default ~/Documents/AIMM/)" if not s.projects_folder else ""
        ),
        f"active_project_file: {s.active_project_file or '<none>'}",
    ]
    if active is None:
        lines.append("status: no active project — call aimm_list_projects then aimm_set_active_project.")
    elif not active.exists():
        lines.append(f"status: pointer set, but file missing at {active}.")
    else:
        lines.append(f"status: active at {active}")
    return [TextContent(type="text", text="\n".join(lines))]


# ---------------------------------------------------------------------------


def _peek_project_name(path: Path) -> str | None:
    """Read just the `project.name` field. Cheap; skips full validation."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (data.get("project") or {}).get("name")
    except Exception:  # noqa: BLE001
        return None


def _peek_updated_at(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("updated_at")
    except Exception:  # noqa: BLE001
        return None
