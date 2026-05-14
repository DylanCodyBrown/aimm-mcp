"""Table-mutation tools.

  - aimm_update_table       patch fields on a table's entry in project.json
  - aimm_set_primary_key    atomically set PK columns + per-column flags
  - aimm_add_relationship   append an FK edge
  - aimm_add_upstream       append a lineage edge
"""

from __future__ import annotations

from typing import Any

from mcp.types import TextContent, Tool

from .. import state
from ..schemas import (
    Cardinality,
    Column,
    Dependency,
    Relationship,
    TableMeta,
)


_PATCH_DENYLIST = {"table_name", "source_file"}
_ALLOWED_PATCH_KEYS = {
    "connection",
    "description",
    "tags",
    "columns",
    "primary_keys",
    "relationships",
    "upstream",
    "ddl_only",
    "staging_target",
    "columns_from",
    "db_kind",
}


TOOLS: list[Tool] = [
    Tool(
        name="aimm_update_table",
        description=(
            "Patch a tracked table inside project.json. Provide only the "
            "fields you want changed in `patch`. Allowed: connection, "
            "description, tags, columns, primary_keys, relationships, "
            "upstream, ddl_only, staging_target, columns_from, db_kind. "
            "Identity fields (table_name, source_file) cannot be changed — "
            "renaming = delete + re-add. Creates the table when it doesn't "
            "exist yet."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "patch": {"type": "object"},
            },
            "required": ["name", "patch"],
        },
    ),
    Tool(
        name="aimm_set_primary_key",
        description=(
            "Atomically set the PK columns on a table. Flips is_primary_key "
            "on each matching column entry and clears it on the rest. Pass "
            "an empty array to clear the PK."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "columns": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["table", "columns"],
        },
    ),
    Tool(
        name="aimm_add_relationship",
        description=(
            "Append an FK-like edge. Composite keys via parallel "
            "from_columns / to_columns arrays. Idempotent: duplicate edges "
            "are silently dropped. Cardinality ∈ {one_to_one, one_to_many, "
            "many_to_many}."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "from": {"type": "string"},
                "to": {"type": "string"},
                "from_columns": {"type": "array", "items": {"type": "string"}},
                "to_columns": {"type": "array", "items": {"type": "string"}},
                "cardinality": {"type": "string", "enum": ["one_to_one", "one_to_many", "many_to_many"]},
                "description": {"type": "string"},
            },
            "required": ["from", "to", "from_columns", "to_columns", "cardinality"],
        },
    ),
    Tool(
        name="aimm_add_upstream",
        description=(
            "Append a lineage edge to a table's `upstream` array. `ref` is "
            "another tracked table or a free-form external identifier "
            "(e.g. 'raw.public.orders'). Downstream is computed by "
            "inverting upstream — never stored. Idempotent on duplicates."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "from": {"type": "string"},
                "ref": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["from", "ref"],
        },
    ),
]


async def dispatch(name: str, args: dict[str, Any]) -> list[TextContent]:
    if name == "aimm_update_table":
        return await _update_table(args)
    if name == "aimm_set_primary_key":
        return await _set_primary_key(args)
    if name == "aimm_add_relationship":
        return await _add_relationship(args)
    if name == "aimm_add_upstream":
        return await _add_upstream(args)
    raise ValueError(f"tables.dispatch: unknown tool {name}")


async def _update_table(args: dict[str, Any]) -> list[TextContent]:
    name = args.get("name")
    patch_raw = args.get("patch") or {}
    if not name:
        return [TextContent(type="text", text="Error: `name` is required.")]
    if not isinstance(patch_raw, dict):
        return [TextContent(type="text", text="Error: `patch` must be an object.")]
    rejected = [k for k in patch_raw if k in _PATCH_DENYLIST]
    if rejected:
        return [TextContent(type="text", text=f"Cannot patch identity fields: {', '.join(rejected)}.")]
    unknown = [k for k in patch_raw if k not in _ALLOWED_PATCH_KEYS]
    if unknown:
        return [TextContent(
            type="text",
            text=f"Unknown patch fields: {', '.join(unknown)}. Allowed: {', '.join(sorted(_ALLOWED_PATCH_KEYS))}.",
        )]

    def apply(project):
        existing = state.find_table(project, name)
        if existing is None:
            try:
                meta = TableMeta(table_name=name, **patch_raw)
            except Exception as err:
                raise ValueError(f"Invalid table payload: {err}") from err
        else:
            merged = existing.model_copy(update=patch_raw)
            meta = TableMeta.model_validate(merged.model_dump())
        return state.upsert_table(project, meta)

    try:
        state.mutate(apply)
    except ValueError as err:
        return [TextContent(type="text", text=str(err))]
    return [TextContent(type="text", text=f"Updated table '{name}' ({', '.join(sorted(patch_raw))}).")]


async def _set_primary_key(args: dict[str, Any]) -> list[TextContent]:
    name = args.get("table")
    cols = args.get("columns") or []
    if not name:
        return [TextContent(type="text", text="Error: `table` is required.")]
    if not isinstance(cols, list):
        return [TextContent(type="text", text="Error: `columns` must be an array.")]

    missing: list[str] = []

    def apply(project):
        nonlocal missing
        meta = state.find_table(project, name)
        if meta is None:
            raise ValueError(f"Unknown table '{name}'.")
        pk_set = set(cols)
        next_cols = [c.model_copy(update={"is_primary_key": c.name in pk_set}) for c in meta.columns]
        missing = [c for c in cols if not any(col.name == c for col in meta.columns)]
        next_meta = meta.model_copy(update={"columns": next_cols, "primary_keys": list(cols)})
        return state.upsert_table(project, next_meta)

    try:
        state.mutate(apply)
    except ValueError as err:
        return [TextContent(type="text", text=str(err))]

    base = f"Set PK on '{name}' to ({', '.join(cols) or '<empty>'})."
    if missing:
        return [TextContent(
            type="text",
            text=f"{base} Note: columns not yet in the table's column list: {', '.join(missing)}.",
        )]
    return [TextContent(type="text", text=base)]


async def _add_relationship(args: dict[str, Any]) -> list[TextContent]:
    from_table = args.get("from")
    to_table = args.get("to")
    from_columns = args.get("from_columns") or []
    to_columns = args.get("to_columns") or []
    cardinality: Cardinality = args.get("cardinality", "one_to_many")
    description = args.get("description")

    if not from_table or not to_table:
        return [TextContent(type="text", text="Error: `from` and `to` are required.")]
    if len(from_columns) != len(to_columns) or not from_columns:
        return [TextContent(type="text", text="Error: `from_columns` and `to_columns` must be non-empty equal length.")]

    new_rel = Relationship(
        to_table=to_table,
        from_columns=list(from_columns),
        to_columns=list(to_columns),
        cardinality=cardinality,
        description=description or None,
    )

    was_duplicate: list[bool] = [False]

    def apply(project):
        meta = state.find_table(project, from_table)
        if meta is None:
            raise ValueError(f"Unknown table '{from_table}'.")
        if any(
            r.to_table == new_rel.to_table
            and r.from_columns == new_rel.from_columns
            and r.to_columns == new_rel.to_columns
            for r in meta.relationships
        ):
            was_duplicate[0] = True
            return project  # no-op
        next_meta = meta.model_copy(update={"relationships": [*meta.relationships, new_rel]})
        return state.upsert_table(project, next_meta)

    try:
        state.mutate(apply)
    except ValueError as err:
        return [TextContent(type="text", text=str(err))]

    if was_duplicate[0]:
        return [TextContent(type="text", text=f"Relationship already exists on '{from_table}' → '{to_table}' ({', '.join(from_columns)}); not duplicated.")]
    return [TextContent(
        type="text",
        text=f"Added relationship '{from_table}' → '{to_table}' ({', '.join(from_columns)} = {', '.join(to_columns)}, {cardinality}).",
    )]


async def _add_upstream(args: dict[str, Any]) -> list[TextContent]:
    from_table = args.get("from")
    ref = args.get("ref")
    description = args.get("description")
    if not from_table or not ref:
        return [TextContent(type="text", text="Error: `from` and `ref` are required.")]

    was_duplicate: list[bool] = [False]

    def apply(project):
        meta = state.find_table(project, from_table)
        if meta is None:
            raise ValueError(f"Unknown table '{from_table}'.")
        if any(d.ref == ref for d in meta.upstream):
            was_duplicate[0] = True
            return project
        next_meta = meta.model_copy(update={
            "upstream": [*meta.upstream, Dependency(ref=ref, description=description or None)],
        })
        return state.upsert_table(project, next_meta)

    try:
        state.mutate(apply)
    except ValueError as err:
        return [TextContent(type="text", text=str(err))]

    if was_duplicate[0]:
        return [TextContent(type="text", text=f"'{from_table}' already lists '{ref}' as upstream; not duplicated.")]
    return [TextContent(type="text", text=f"Added upstream: '{from_table}' depends on '{ref}'.")]
