"""Project-level tools: init, read context."""

from __future__ import annotations

import json as _json
from typing import Any

from mcp.types import TextContent, Tool

from .. import paths, state
from ..format_context import format_project_context
from ..schemas import Project, ProjectConfig


TOOLS: list[Tool] = [
    Tool(
        name="aimm_init_project",
        description=(
            "Bootstrap the AIMM data model at ~/Documents/AIMM/. Creates "
            "project.json (the single source of truth) if it doesn't exist. "
            "Idempotent — safe to call when already initialised; arguments "
            "patch the project header. Required: `name`. Optional: "
            "`description` (free-text context the agent reads on every call), "
            "`dialect` ('tsql' / 'trino' / 'spark', defaults to 'tsql')."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 120},
                "description": {"type": "string", "maxLength": 20_000},
                "dialect": {"type": "string"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="aimm_read_project_context",
        description=(
            "Return the entire AIMM project — header, every connection, every "
            "tracked table with its columns, primary keys, FK relationships, "
            "and upstream/downstream lineage. Always call this once at the "
            "start of a session before answering data-model questions; one "
            "read is the canonical context for every other tool. Formats:\n"
            "  - `xml` (default) — tag-delimited, post-trained-on, best "
            "    for cross-referential reasoning.\n"
            "  - `markdown` — leaner prose digest.\n"
            "  - `json` — raw contents of ~/Documents/AIMM/project.json, "
            "    same shape the server writes on every mutation. Use this "
            "    when you want to operate on the project structurally."
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
    if not args.get("name"):
        return [TextContent(type="text", text="Error: `name` is required.")]
    paths.ensure_layout()
    existing = state.load()

    if existing is not None:
        # Patch header fields the caller supplied; leave everything
        # else untouched.
        patch = {
            k: v for k, v in {
                "name": args.get("name"),
                "description": args.get("description"),
                "dialect": args.get("dialect"),
            }.items()
            if v is not None
        }
        next_cfg = existing.project.model_copy(update=patch)
        next_project = existing.model_copy(update={"project": next_cfg})
        state.mutate(lambda _cur: next_project)
        return [TextContent(
            type="text",
            text=(
                f"Project already initialised at {paths.project_path()}. "
                f"Refreshed header fields from arguments. Current state: "
                f"{len(existing.tables)} tables, {len(existing.connections)} connections."
            ),
        )]

    cfg = ProjectConfig(
        name=args["name"],
        description=args.get("description", ""),
        dialect=args.get("dialect", "tsql"),
    )
    project = Project(project=cfg)
    state.mutate(lambda _cur: project)
    return [TextContent(
        type="text",
        text=(
            f"Initialised AIMM project '{cfg.name}' at {paths.project_path()}. "
            "Next: add a connection with aimm_upsert_connection."
        ),
    )]


async def _read_context(args: dict[str, Any]) -> list[TextContent]:
    project = state.load()
    if project is None:
        return [TextContent(
            type="text",
            text=f"No AIMM project at {paths.aimm_root()}. Call aimm_init_project first.",
        )]
    fmt = args.get("format", "xml")
    if fmt == "json":
        # Hand back the on-disk JSON exactly — same bytes the server
        # writes on every mutation. Lets the agent reason over the
        # structural shape without a separate parse step.
        try:
            body = paths.project_path().read_text(encoding="utf-8")
        except Exception as err:  # noqa: BLE001
            return [TextContent(type="text", text=f"Couldn't read project.json: {err}")]
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
