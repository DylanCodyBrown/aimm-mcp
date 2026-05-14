"""Project-level tools: init, read context."""

from __future__ import annotations

from typing import Any

from mcp.types import TextContent, Tool

from .. import paths, session, state
from ..format_context import format_project_context
from ..schemas import Project, ProjectConfig


_BOOTSTRAP_HINT = (
    "Call aimm_list_projects to see what's available, then "
    "aimm_set_active_project. Or aimm_init_project to create a new one."
)


TOOLS: list[Tool] = [
    Tool(
        name="aimm_init_project",
        description=(
            "Create a new AIMM project file in the current projects folder "
            "and set it as active. Filename is derived from `name` via "
            "slugify — e.g. 'Customer Warehouse' → 'customer_warehouse.aimm.json'. "
            "Pass `filename` to override. Errors if a project with that "
            "filename already exists in the folder (use aimm_set_active_project "
            "to switch to it, or pass a different name). Required: `name`. "
            "Optional: `description` (free-text context the agent reads on "
            "every call), `dialect` ('tsql' / 'trino' / 'spark', defaults "
            "to 'tsql'), `filename`."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 120},
                "description": {"type": "string", "maxLength": 20_000},
                "dialect": {"type": "string"},
                "filename": {
                    "type": "string",
                    "description": "Optional override. Must end in `.aimm.json`.",
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="aimm_read_project_context",
        description=(
            "Return the active AIMM project — header, every connection, every "
            "tracked table with its columns, primary keys, FK relationships, "
            "and upstream/downstream lineage. Always call this once at the "
            "start of a session before answering data-model questions; one "
            "read is the canonical context for every other tool. Errors if "
            "no active project is set (call aimm_set_active_project first). "
            "Formats:\n"
            "  - `xml` (default) — tag-delimited, post-trained-on, best "
            "    for cross-referential reasoning.\n"
            "  - `markdown` — leaner prose digest.\n"
            "  - `json` — raw contents of the active project file, same "
            "    shape the server writes on every mutation. Use this when "
            "    you want to operate on the project structurally."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "format": {"type": "string", "enum": ["xml", "markdown", "json"]},
            },
        },
    ),
]


async def dispatch(name: str, args: dict[str, Any]) -> list[TextContent]:
    if name == "aimm_init_project":
        return await _init_project(args)
    if name == "aimm_read_project_context":
        return await _read_context(args)
    raise ValueError(f"project.dispatch: unknown tool {name}")


async def _init_project(args: dict[str, Any]) -> list[TextContent]:
    name = args.get("name")
    if not name:
        return [TextContent(type="text", text="Error: `name` is required.")]

    paths.ensure_layout()
    folder = session.projects_folder()
    folder.mkdir(parents=True, exist_ok=True)

    filename = args.get("filename") or session.filename_for(name)
    if not filename.endswith(session.PROJECT_FILE_SUFFIX):
        return [TextContent(
            type="text",
            text=f"Error: filename must end in `{session.PROJECT_FILE_SUFFIX}`.",
        )]
    target = folder / filename

    if target.exists():
        return [TextContent(
            type="text",
            text=(
                f"Project file already exists at {target}. "
                f"Call aimm_set_active_project({{filename: '{filename}'}}) to "
                "switch to it, or pass a different `name` / `filename`."
            ),
        )]

    cfg = ProjectConfig(
        name=name,
        description=args.get("description", ""),
        dialect=args.get("dialect", "tsql"),
    )
    project = Project(project=cfg)
    state.write_to(project, target)
    session.set_active_project(filename)

    return [TextContent(
        type="text",
        text=(
            f"Initialised AIMM project '{cfg.name}' at {target}. "
            f"Set as active. Next: add a connection with aimm_upsert_connection."
        ),
    )]


async def _read_context(args: dict[str, Any]) -> list[TextContent]:
    active = session.active_project_path()
    if active is None:
        return [TextContent(
            type="text",
            text=f"Error: project file not selected. {_BOOTSTRAP_HINT}",
        )]
    project = state.load()
    if project is None:
        return [TextContent(
            type="text",
            text=(
                f"Active project file missing or unreadable at {active}. "
                "Check the file, or call aimm_list_projects + aimm_set_active_project."
            ),
        )]
    fmt = args.get("format", "xml")
    if fmt == "json":
        # Hand back the on-disk JSON exactly — same bytes the server
        # writes on every mutation. Lets the agent reason over the
        # structural shape without a separate parse step.
        try:
            body = active.read_text(encoding="utf-8")
        except Exception as err:  # noqa: BLE001
            return [TextContent(type="text", text=f"Couldn't read {active}: {err}")]
        return [TextContent(type="text", text=body)]
    if fmt not in ("xml", "markdown"):
        fmt = "xml"
    body = format_project_context(
        project.project,
        project.connections,
        project.tables,
        joins_doc=None,
        fmt=fmt,
    )
    return [TextContent(type="text", text=body)]
