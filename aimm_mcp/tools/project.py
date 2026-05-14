"""Project-level tools: init, read context."""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

from .. import paths, repo
from ..schemas import ProjectConfig


TOOLS: list[Tool] = [
    Tool(
        name="aimm_init_project",
        description=(
            "Bootstrap the AIMM data model at ~/Documents/AIMM/. Creates the "
            "folder skeleton (aimm.json + tables/ + connections/ + diagnostics.log) "
            "if it doesn't exist. Idempotent — safe to call when already initialised. "
            "Required argument: `name`, a human-readable label for the project that "
            "shows up in every context dump. Optional: `description`, free-text context "
            "the agent reads on every call."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Project name (max 120 chars). Required.",
                    "maxLength": 120,
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Free-text project context. Max 20,000 chars. Defaults to '' "
                        "when omitted. Use this to capture the business domain the "
                        "model covers — agents read it on every call."
                    ),
                    "maxLength": 20_000,
                },
                "dialect": {
                    "type": "string",
                    "description": (
                        "Default SQL dialect for the project ('tsql', 'trino', 'spark'). "
                        "Falls back to 'tsql' when omitted. Engines on individual "
                        "connections override this for their own queries."
                    ),
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="aimm_read_project_context",
        description=(
            "Return everything the project records: project header, every "
            "connection, every tracked table with its columns / primary keys / "
            "FK relationships / upstream lineage, plus the project-tracked joins "
            "list. Always call this once at the start of a session before "
            "answering data-model questions; the cost is bounded and the payload "
            "is the canonical context for every other tool you'll use. "
            "Defaults to XML for cross-referential reasoning; pass "
            "`format: 'markdown'` for a leaner prose digest."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["xml", "markdown"],
                    "description": "Output format. Defaults to xml.",
                },
            },
        },
    ),
]


async def dispatch(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "aimm_init_project":
        return await _init_project(arguments)
    if name == "aimm_read_project_context":
        return await _read_context(arguments)
    raise ValueError(f"project.dispatch: unknown tool {name}")


async def _init_project(args: dict[str, Any]) -> list[TextContent]:
    if not args.get("name"):
        return [TextContent(type="text", text="Error: `name` is required.")]
    paths.ensure_layout()
    existing = repo.read_project()
    if existing is not None:
        # Idempotent: refresh fields the caller supplied, keep
        # everything else. Lets re-running this tool work as a
        # "patch project header" without surprising overwrites.
        next_cfg = existing.model_copy(update={
            k: v for k, v in {
                "name": args.get("name"),
                "description": args.get("description"),
                "dialect": args.get("dialect"),
            }.items()
            if v is not None
        })
        repo.write_project(next_cfg)
        return [TextContent(
            type="text",
            text=(
                f"Project already initialised at {paths.aimm_root()}. "
                f"Refreshed header fields from arguments. "
                f"Current state: {len(repo.list_table_names())} tables, "
                f"{len(repo.list_connection_names())} connections."
            ),
        )]
    cfg = ProjectConfig(
        name=args["name"],
        description=args.get("description", ""),
        dialect=args.get("dialect", "tsql"),
    )
    repo.write_project(cfg)
    return [TextContent(
        type="text",
        text=(
            f"Initialised AIMM project '{cfg.name}' at {paths.aimm_root()}. "
            "Folder layout ready (tables/, connections/). "
            "Next: add a connection with aimm_upsert_connection."
        ),
    )]


async def _read_context(args: dict[str, Any]) -> list[TextContent]:
    cfg = repo.read_project()
    if cfg is None:
        return [TextContent(
            type="text",
            text=(
                f"No AIMM project at {paths.aimm_root()}. "
                "Call aimm_init_project first."
            ),
        )]
    fmt = args.get("format", "xml")
    if fmt not in ("xml", "markdown"):
        fmt = "xml"
    connections = list(repo.iter_connections())
    tables = list(repo.iter_tables())
    joins_doc = _read_joins_doc()
    from ..format_context import format_project_context
    body = format_project_context(cfg, connections, tables, joins_doc=joins_doc, fmt=fmt)
    return [TextContent(type="text", text=body)]


def _read_joins_doc() -> dict | None:
    """Best-effort read of AIMM/joins.json so the XML preamble's
    <joins> block reflects the last regenerate. Missing or malformed
    file → no block emitted; nothing else breaks."""
    import json

    path = paths.joins_json_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("joins"), list):
            return data
    except Exception:  # noqa: BLE001
        pass
    return None
