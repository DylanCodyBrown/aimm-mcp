"""Project-level tools: init, read context."""

from __future__ import annotations

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
            "Return the entire project — header, connections, tables, "
            "columns, primary keys, FK relationships, upstream/downstream "
            "lineage, and the project-tracked joins list. Always call "
            "this once at the start of a session before answering data-"
            "model questions; one read is the canonical context for "
            "every other tool. Defaults to XML for cross-referential "
            "reasoning; pass `format: 'markdown'` for a leaner digest."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "format": {"type": "string", "enum": ["xml", "markdown"]},
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
                f"Project already initialised at {paths.aimm_root() / 'project.json'}. "
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
            f"Initialised AIMM project '{cfg.name}' at "
            f"{paths.aimm_root() / 'project.json'}. "
            "Next: add a connection with aimm_upsert_connection."
        ),
    )]


async def _read_context(args: dict[str, Any]) -> list[TextContent]:
    project = state.load()
    if project is None:
        return [TextContent(
            type="text",
            text=(
                f"No AIMM project at {paths.aimm_root()}. Call aimm_init_project first."
            ),
        )]
    fmt = args.get("format", "xml")
    if fmt not in ("xml", "markdown"):
        fmt = "xml"
    joins_doc = _read_joins_doc()
    body = format_project_context(
        project.project,
        project.connections,
        project.tables,
        joins_doc=joins_doc,
        fmt=fmt,
    )
    return [TextContent(type="text", text=body)]


def _read_joins_doc() -> dict | None:
    import json

    p = paths.joins_json_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("joins"), list):
            return data
    except Exception:  # noqa: BLE001
        pass
    return None
