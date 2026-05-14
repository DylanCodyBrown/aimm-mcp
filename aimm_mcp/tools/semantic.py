"""Semantic-context tools.

These mutate the v0.3 "agent-readable knowledge" fields on a project:

  - aimm_set_table_grain         per-table "what's one row?"
  - aimm_add_pitfall             per-table "don't do this" rules
  - aimm_set_column_classification  per-column PII/PHI/etc. tag
  - aimm_add_glossary_term       project-level domain dictionary
  - aimm_add_measure             project-level KPI / metric definition
  - aimm_update_project_config   patch the project header (description,
                                 conventions, paradigm, dialect, glossary,
                                 measures all in one go)

Every tool is a single-purpose verb the agent can discover from the
tool list and call directly — alternatives via `aimm_update_table`'s
generic patch surface still work, but dedicated tools are easier for
agents to reach for.
"""

from __future__ import annotations

from typing import Any

from mcp.types import TextContent, Tool

from .. import state
from ..schemas import (
    DataClassification,
    GlossaryTerm,
    Measure,
    ProjectConfig,
)
from . import _common


TOOLS: list[Tool] = [
    Tool(
        name="aimm_set_table_grain",
        description=(
            "Set the table's `grain` — the one-line answer to 'what is a "
            "row in this table?'. Anchors every fact-vs-dimension "
            "discussion. Short by design (240-char cap); anything longer "
            "belongs in description. Examples: 'one row per order line "
            "item', 'one row per (customer, day)', 'one row per snapshot "
            "of an order's status'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "grain": {"type": "string", "maxLength": 240},
            },
            "required": ["table", "grain"],
        },
    ),
    Tool(
        name="aimm_add_pitfall",
        description=(
            "Append a 'don't do this' rule to a table's pitfalls list. "
            "Each pitfall is one short sentence — high-signal, "
            "scannable. Use when the user explains a gotcha the agent "
            "should remember next time. Examples: 'Do not join on "
            "customer_email; use customer_id (email is reused after "
            "anonymisation).', 'amount is in cents, not dollars.'. "
            "Idempotent on exact duplicates."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "message": {"type": "string", "maxLength": 240},
            },
            "required": ["table", "message"],
        },
    ),
    Tool(
        name="aimm_set_column_classification",
        description=(
            "Set a column's sensitivity classification. Values: "
            "`public`, `internal`, `pii`, `phi`, `restricted`, "
            "`unspecified`. The agent uses this to self-guardrail (e.g. "
            "avoid putting raw PII values in responses, warn before "
            "exporting PHI). Defaults to `unspecified`."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "column": {"type": "string"},
                "classification": {
                    "type": "string",
                    "enum": ["unspecified", "public", "internal", "pii", "phi", "restricted"],
                },
            },
            "required": ["table", "column", "classification"],
        },
    ),
    Tool(
        name="aimm_add_glossary_term",
        description=(
            "Add (or replace) a project-level glossary term — one entry "
            "in the domain dictionary the agent consults before "
            "interpreting ambiguous user phrases. Examples: term='active "
            "customer', definition='customer with at least one paid "
            "order in the trailing 90 days'. Idempotent on `term` — "
            "passing the same term again updates the definition."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "term": {"type": "string", "maxLength": 120},
                "definition": {"type": "string", "maxLength": 1_000},
            },
            "required": ["term", "definition"],
        },
    ),
    Tool(
        name="aimm_add_measure",
        description=(
            "Add (or replace) a project-level measure / KPI definition. "
            "`name` is the metric the user references ('Monthly Active "
            "Customers'); `definition` is the plain-English meaning; "
            "`formula` is the canonical expression in the project's "
            "dialect ('count(distinct customer_id) where last_active >= "
            "current_date - interval ''30'' day'). The agent quotes the "
            "formula instead of inventing one. Idempotent on `name`."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 120},
                "definition": {"type": "string", "maxLength": 1_000},
                "formula": {"type": "string", "maxLength": 2_000},
                "owner": {"type": "string", "maxLength": 240},
            },
            "required": ["name", "definition"],
        },
    ),
    Tool(
        name="aimm_update_project_config",
        description=(
            "Patch any field on the project header in one call. "
            "Allowed: name, description, conventions, dialect, "
            "default_connection, modeling_paradigm, tags. Provide only "
            "the fields you want to change. Use aimm_add_glossary_term / "
            "aimm_add_measure for the list-shaped fields — those have "
            "dedicated upsert tools so the agent can append without "
            "rewriting the entire list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "patch": {"type": "object"},
            },
            "required": ["patch"],
        },
    ),
]


async def dispatch(name: str, args: dict[str, Any]) -> list[TextContent]:
    if name == "aimm_set_table_grain":
        return await _set_grain(args)
    if name == "aimm_add_pitfall":
        return await _add_pitfall(args)
    if name == "aimm_set_column_classification":
        return await _set_classification(args)
    if name == "aimm_add_glossary_term":
        return await _add_glossary_term(args)
    if name == "aimm_add_measure":
        return await _add_measure(args)
    if name == "aimm_update_project_config":
        return await _update_project_config(args)
    raise ValueError(f"semantic.dispatch: unknown tool {name}")


# ---------------------------------------------------------------------------
# Table-level tools


async def _set_grain(args: dict[str, Any]) -> list[TextContent]:
    err = _common.ensure_active()
    if err:
        return err
    table = args.get("table")
    grain = args.get("grain")
    if not table:
        return [TextContent(type="text", text="Error: `table` is required.")]
    if grain is None:
        return [TextContent(type="text", text="Error: `grain` is required.")]
    if len(grain) > 240:
        return [TextContent(type="text", text="Error: grain exceeds 240-char cap.")]

    def apply(project):
        meta = state.find_table(project, table)
        if meta is None:
            raise ValueError(f"Unknown table '{table}'.")
        next_meta = meta.model_copy(update={"grain": grain or None})
        return state.upsert_table(project, next_meta)

    try:
        state.mutate(apply)
    except ValueError as err:
        return [TextContent(type="text", text=str(err))]
    return [TextContent(type="text", text=f"Set grain on '{table}': {grain}")]


async def _add_pitfall(args: dict[str, Any]) -> list[TextContent]:
    err = _common.ensure_active()
    if err:
        return err
    table = args.get("table")
    message = (args.get("message") or "").strip()
    if not table or not message:
        return [TextContent(type="text", text="Error: `table` and `message` are required.")]
    if len(message) > 240:
        return [TextContent(type="text", text="Error: pitfall message exceeds 240-char cap.")]

    duplicate = [False]

    def apply(project):
        meta = state.find_table(project, table)
        if meta is None:
            raise ValueError(f"Unknown table '{table}'.")
        if message in meta.pitfalls:
            duplicate[0] = True
            return project
        next_meta = meta.model_copy(update={"pitfalls": [*meta.pitfalls, message]})
        return state.upsert_table(project, next_meta)

    try:
        state.mutate(apply)
    except ValueError as err:
        return [TextContent(type="text", text=str(err))]
    if duplicate[0]:
        return [TextContent(type="text", text=f"Pitfall already recorded on '{table}'; not duplicated.")]
    return [TextContent(type="text", text=f"Added pitfall to '{table}': {message}")]


async def _set_classification(args: dict[str, Any]) -> list[TextContent]:
    err = _common.ensure_active()
    if err:
        return err
    table = args.get("table")
    col_name = args.get("column")
    classification = args.get("classification")
    valid = {"unspecified", "public", "internal", "pii", "phi", "restricted"}
    if not table or not col_name or classification not in valid:
        return [TextContent(
            type="text",
            text=f"Error: `table`, `column`, and `classification` ∈ {{{', '.join(sorted(valid))}}} are required.",
        )]

    found = [False]

    def apply(project):
        meta = state.find_table(project, table)
        if meta is None:
            raise ValueError(f"Unknown table '{table}'.")
        next_cols = []
        for c in meta.columns:
            if c.name == col_name:
                found[0] = True
                next_cols.append(c.model_copy(update={"classification": classification}))
            else:
                next_cols.append(c)
        if not found[0]:
            raise ValueError(f"Unknown column '{col_name}' on '{table}'.")
        next_meta = meta.model_copy(update={"columns": next_cols})
        return state.upsert_table(project, next_meta)

    try:
        state.mutate(apply)
    except ValueError as err:
        return [TextContent(type="text", text=str(err))]
    return [TextContent(
        type="text",
        text=f"Classified {table}.{col_name} as {classification}.",
    )]


# ---------------------------------------------------------------------------
# Project-level tools


async def _add_glossary_term(args: dict[str, Any]) -> list[TextContent]:
    err = _common.ensure_active()
    if err:
        return err
    term = (args.get("term") or "").strip()
    definition = (args.get("definition") or "").strip()
    if not term or not definition:
        return [TextContent(type="text", text="Error: `term` and `definition` are required.")]
    try:
        entry = GlossaryTerm(term=term, definition=definition)
    except Exception as err:  # noqa: BLE001
        return [TextContent(type="text", text=f"Invalid glossary entry: {err}")]

    replaced = [False]

    def apply(project):
        next_glossary = []
        for g in project.project.glossary:
            if g.term == entry.term:
                replaced[0] = True
                next_glossary.append(entry)
            else:
                next_glossary.append(g)
        if not replaced[0]:
            next_glossary.append(entry)
        next_cfg = project.project.model_copy(update={"glossary": next_glossary})
        return project.model_copy(update={"project": next_cfg})

    state.mutate(apply)
    verb = "Updated" if replaced[0] else "Added"
    return [TextContent(type="text", text=f"{verb} glossary term '{entry.term}'.")]


async def _add_measure(args: dict[str, Any]) -> list[TextContent]:
    err = _common.ensure_active()
    if err:
        return err
    name = (args.get("name") or "").strip()
    definition = (args.get("definition") or "").strip()
    if not name or not definition:
        return [TextContent(type="text", text="Error: `name` and `definition` are required.")]
    try:
        entry = Measure(
            name=name,
            definition=definition,
            formula=(args.get("formula") or None) or None,
            owner=(args.get("owner") or None) or None,
        )
    except Exception as err:  # noqa: BLE001
        return [TextContent(type="text", text=f"Invalid measure entry: {err}")]

    replaced = [False]

    def apply(project):
        next_measures = []
        for m in project.project.measures:
            if m.name == entry.name:
                replaced[0] = True
                next_measures.append(entry)
            else:
                next_measures.append(m)
        if not replaced[0]:
            next_measures.append(entry)
        next_cfg = project.project.model_copy(update={"measures": next_measures})
        return project.model_copy(update={"project": next_cfg})

    state.mutate(apply)
    verb = "Updated" if replaced[0] else "Added"
    return [TextContent(type="text", text=f"{verb} measure '{entry.name}'.")]


_ALLOWED_CONFIG_PATCH = {
    "name",
    "description",
    "conventions",
    "dialect",
    "default_connection",
    "modeling_paradigm",
    "tags",
}


async def _update_project_config(args: dict[str, Any]) -> list[TextContent]:
    err = _common.ensure_active()
    if err:
        return err
    patch = args.get("patch")
    if not isinstance(patch, dict) or not patch:
        return [TextContent(type="text", text="Error: `patch` must be a non-empty object.")]
    unknown = [k for k in patch if k not in _ALLOWED_CONFIG_PATCH]
    if unknown:
        return [TextContent(
            type="text",
            text=(
                f"Unknown patch fields: {', '.join(unknown)}. "
                f"Allowed: {', '.join(sorted(_ALLOWED_CONFIG_PATCH))}. "
                "Use aimm_add_glossary_term / aimm_add_measure for those lists."
            ),
        )]

    def apply(project):
        try:
            next_cfg = project.project.model_copy(update=patch)
            # Re-validate via the schema to enforce caps + enums.
            next_cfg = ProjectConfig.model_validate(next_cfg.model_dump())
        except Exception as err:  # noqa: BLE001
            raise ValueError(f"Invalid project_config patch: {err}") from err
        return project.model_copy(update={"project": next_cfg})

    try:
        state.mutate(apply)
    except ValueError as err:
        return [TextContent(type="text", text=str(err))]
    return [TextContent(
        type="text",
        text=f"Updated project_config fields: {', '.join(sorted(patch))}.",
    )]
