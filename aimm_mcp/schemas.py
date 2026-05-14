"""Pydantic v2 models mirroring the extension's zod schemas.

Same wire format as the VS Code extension — JSON files written by this
server are interchangeable with files written by the extension. Field
names, defaults, and validation rules match
`extension/shared/project_schema.ts` in the source repo.

Hard char caps are enforced via `max_length` so a misbehaving agent
can't write a 50KB description that bloats every future context dump.
Caps match the extension's `LIMITS` table.

v0.3 adds **semantic-context** fields the agent can fill in to make
the project model self-explanatory: per-table grain + pitfalls +
aliases + refresh cadence + SCD metadata, per-column classification
+ quality notes + computed-flag + example values, project glossary +
measures + conventions. Every new field is optional / defaulted so
v0.2 files still parse unchanged.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# --- limits -----------------------------------------------------------------

PROJECT_DESCRIPTION_MAX = 20_000
PROJECT_CONVENTIONS_MAX = 8_000
TABLE_DESCRIPTION_MAX = 8_000
TABLE_GRAIN_MAX = 240
TABLE_PITFALL_MAX = 240
TABLE_REFRESH_NOTES_MAX = 500
TABLE_OWNER_MAX = 240
COLUMN_DESCRIPTION_MAX = 500
COLUMN_QUALITY_NOTES_MAX = 240
COLUMN_EXPRESSION_MAX = 1_000
RELATIONSHIP_DESCRIPTION_MAX = 500
CONNECTION_DESCRIPTION_MAX = 4_000
GLOSSARY_DEFINITION_MAX = 1_000
MEASURE_DEFINITION_MAX = 1_000
MEASURE_FORMULA_MAX = 2_000


EngineId = Literal["trino", "sql_server", "databricks"]
Cardinality = Literal["one_to_one", "one_to_many", "many_to_many"]
ParadigmId = Literal["star", "snowflake", "parent_child", "unspecified"]

# How often the live table refreshes. `unknown` is the default for
# fields the agent hasn't filled in yet; everything else is an
# operational hint that drives the agent's freshness reasoning.
RefreshCadence = Literal[
    "unknown",
    "realtime",
    "minutes",
    "hourly",
    "daily",
    "weekly",
    "monthly",
    "adhoc",
]

# Per-column sensitivity tag. `unspecified` is the default; the agent
# can self-guardrail on `pii`/`phi`/`restricted` columns (e.g. avoid
# putting raw values in a chat response).
DataClassification = Literal[
    "unspecified",
    "public",
    "internal",
    "pii",
    "phi",
    "restricted",
]

# Slowly-Changing-Dimension type. `none` is the default; `scd2` /
# `snapshot` are the common "history is tracked" variants.
ScdType = Literal["none", "scd1", "scd2", "snapshot"]


# --- shared shapes ----------------------------------------------------------


class Column(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    type: str = ""
    nullable: bool = True
    is_primary_key: bool = False
    is_foreign_key: bool = False
    description: Optional[str] = Field(default=None, max_length=COLUMN_DESCRIPTION_MAX)
    # Sensitivity hint. Lets the agent self-guardrail on PII/PHI/etc.
    classification: DataClassification = "unspecified"
    # Free-text quality flag — "30% null pre-2023", "not normalized",
    # "test data only in dev". Cheap to write, high signal to read.
    quality_notes: Optional[str] = Field(default=None, max_length=COLUMN_QUALITY_NOTES_MAX)
    # `true` when this column is a derivation, not stored. `expression`
    # carries the formula in the project's dialect.
    computed: bool = False
    expression: Optional[str] = Field(default=None, max_length=COLUMN_EXPRESSION_MAX)
    # Sample values an agent can reason about — "active", "inactive",
    # "pending" for a status column. Curated, not auto-populated.
    example_values: list[str] = Field(default_factory=list)


class Relationship(BaseModel):
    model_config = ConfigDict(extra="ignore")

    to_table: str
    from_columns: list[str]
    to_columns: list[str]
    cardinality: Cardinality
    description: Optional[str] = Field(default=None, max_length=RELATIONSHIP_DESCRIPTION_MAX)


class Dependency(BaseModel):
    """One entry in a table's upstream lineage. `ref` is either another
    tracked table name or a free-form external identifier like
    `raw.public.orders`."""

    model_config = ConfigDict(extra="ignore")

    ref: str
    description: Optional[str] = None


class ScdMetadata(BaseModel):
    """Slowly-changing-dimension shape.

    `type='none'` means history isn't tracked. `scd2` / `snapshot`
    rely on `valid_from` / `valid_to` to project a point-in-time view;
    `is_current_flag` names the boolean column (typically
    `is_current` / `is_latest`) used as the "no time filter" shortcut.
    """

    model_config = ConfigDict(extra="ignore")

    type: ScdType = "none"
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    is_current_flag: Optional[str] = None


class GlossaryTerm(BaseModel):
    """One project-level domain-dictionary entry."""

    model_config = ConfigDict(extra="ignore")

    term: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1, max_length=GLOSSARY_DEFINITION_MAX)


class Measure(BaseModel):
    """One project-level KPI / business metric definition.

    `formula` is the canonical expression (dialect-specific) the agent
    should reference when asked to compute the metric. `definition` is
    the plain-English meaning — handed to humans and the agent alike.
    """

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1, max_length=MEASURE_DEFINITION_MAX)
    formula: Optional[str] = Field(default=None, max_length=MEASURE_FORMULA_MAX)
    owner: Optional[str] = Field(default=None, max_length=TABLE_OWNER_MAX)


# --- top-level documents ----------------------------------------------------


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=120)
    # 'unspecified' is the default for projects authored by aimm-mcp,
    # which doesn't have a paradigm-picker UI. The VS Code extension
    # uses this to drive its layout + lint dispatch; here it's
    # round-tripped only.
    modeling_paradigm: ParadigmId = "unspecified"
    dialect: str = "tsql"
    default_connection: Optional[str] = None
    description: str = Field(default="", max_length=PROJECT_DESCRIPTION_MAX)
    tags: list[str] = Field(default_factory=list)
    # Workspace-glob includes / excludes for which SQL files the
    # extension treats as part of the project. The MCP doesn't track
    # source files (no editor concept), but we round-trip these so
    # the extension can use the same file unchanged.
    included_files: list[str] = Field(default_factory=list)
    excluded_files: list[str] = Field(default_factory=list)
    # Project-level "how we name / type / structure things" notes.
    # Surfaced verbatim in every read_project_context call; the agent
    # consults it before guessing.
    conventions: str = Field(default="", max_length=PROJECT_CONVENTIONS_MAX)
    # Domain dictionary. Each entry is a {term, definition} pair the
    # agent can resolve when the user says "active customer" etc.
    glossary: list[GlossaryTerm] = Field(default_factory=list)
    # KPI / measure definitions. Lets the agent quote a canonical
    # formula instead of inventing one.
    measures: list[Measure] = Field(default_factory=list)


class Connection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    engine: EngineId
    dsn: str
    catalog: Optional[str] = None
    default_schema: Optional[str] = None
    description: str = Field(default="", max_length=CONNECTION_DESCRIPTION_MAX)
    tags: list[str] = Field(default_factory=list)


class TableMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    table_name: str = Field(min_length=1)
    source_file: Optional[str] = None
    connection: Optional[str] = None
    # Free-text role under the project's paradigm (e.g. "fact",
    # "conformed dimension", "scd2 dimension"). 60-char cap matches
    # the extension. Cosmetic; not validated against the paradigm.
    paradigm_role: str = Field(default="", max_length=60)
    description: str = Field(default="", max_length=TABLE_DESCRIPTION_MAX)
    # Single most important field for an agent reasoning about a fact
    # table: "what's a row?" Short by design — anything longer belongs
    # in `description`. Example: "one row per order line item".
    grain: Optional[str] = Field(default=None, max_length=TABLE_GRAIN_MAX)
    tags: list[str] = Field(default_factory=list)
    # Other names this table goes by. Resolves user-question ambiguity
    # ("transactions" → "orders") without a separate table-lookup detour.
    aliases: list[str] = Field(default_factory=list)
    # Short "don't do this" rules. Each one capped so the list stays
    # scannable. Hard-won wisdom belongs here, not in description.
    pitfalls: list[str] = Field(default_factory=list)
    # Free-text contact ("data-eng-slack", "alice@…"). The agent can
    # recommend "ask the owner" instead of guessing.
    owner: Optional[str] = Field(default=None, max_length=TABLE_OWNER_MAX)
    # How often the live table refreshes. Drives freshness reasoning.
    refresh_cadence: RefreshCadence = "unknown"
    refresh_notes: Optional[str] = Field(default=None, max_length=TABLE_REFRESH_NOTES_MAX)
    # Slowly-changing-dimension metadata. `type='none'` (the default)
    # means history isn't tracked; scd2/snapshot point at the
    # valid_from / valid_to / is_current_flag columns to use.
    scd: ScdMetadata = Field(default_factory=ScdMetadata)
    columns: list[Column] = Field(default_factory=list)
    primary_keys: list[str] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    upstream: list[Dependency] = Field(default_factory=list)
    ddl_only: bool = False
    staging_target: Optional[str] = None
    # Provenance of the column list: 'information_schema' (live DB),
    # 'sqlglot' (parsed from a local SQL file), or None.
    columns_from: Optional[Literal["information_schema", "sqlglot"]] = None
    # Whether the live DB object is a table or a view. Drives icon
    # selection on UI clients; cosmetic for the MCP server itself.
    db_kind: Optional[Literal["table", "view"]] = None
    # Operational stamps (auto-set by aimm_refresh_columns when the
    # live DB call succeeds). `row_count_last_run` is the COUNT(*)
    # the server saw; `last_run_at` is when the count was taken.
    row_count_last_run: Optional[int] = None
    last_run_at: Optional[str] = None


class Project(BaseModel):
    """Unified project document — the contents of a `<slug>.aimm.json` file.

    Single source of truth for everything an AIMM session reads or
    writes: project header, every connection, every table (with its
    columns / primary keys / relationships / upstream lineage), plus
    the semantic layer (grain, pitfalls, glossary, measures,
    conventions) the agent uses to reason like someone who's lived
    in the model for a year.

    Derived artefacts (mermaid diagrams, lineage.json,
    relationships.json, joins.json, project_context.xml) are
    regenerated from this document on every mutation by clients that
    care (the VS Code extension). The MCP server is read/write only
    on this file; it never emits derived artefacts.

    Shared by handing a teammate this one JSON file.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    updated_at: Optional[str] = None
    project: ProjectConfig
    connections: list[Connection] = Field(default_factory=list)
    tables: list[TableMeta] = Field(default_factory=list)
