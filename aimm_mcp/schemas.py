"""Pydantic v2 models mirroring the extension's zod schemas.

Same wire format as the VS Code extension — JSON files written by this
server are interchangeable with files written by the extension. Field
names, defaults, and validation rules match
`extension/shared/project_schema.ts` in the source repo.

Hard char caps are enforced via `max_length` so a misbehaving agent
can't write a 50KB description that bloats every future context dump.
Caps match the extension's `LIMITS` table.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# --- limits -----------------------------------------------------------------

PROJECT_DESCRIPTION_MAX = 20_000
TABLE_DESCRIPTION_MAX = 8_000
COLUMN_DESCRIPTION_MAX = 500
RELATIONSHIP_DESCRIPTION_MAX = 500
CONNECTION_DESCRIPTION_MAX = 4_000


EngineId = Literal["trino", "sql_server", "databricks"]
Cardinality = Literal["one_to_one", "one_to_many", "many_to_many"]
ParadigmId = Literal["star", "snowflake", "parent_child", "unspecified"]


# --- shared shapes ----------------------------------------------------------


class Column(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    type: str = ""
    nullable: bool = True
    is_primary_key: bool = False
    is_foreign_key: bool = False
    description: Optional[str] = Field(default=None, max_length=COLUMN_DESCRIPTION_MAX)


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
    tags: list[str] = Field(default_factory=list)
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


class Project(BaseModel):
    """Unified project document — the contents of ~/Documents/AIMM/project.json.

    Single source of truth for everything an AIMM session reads or
    writes: project header, every connection, every table (with its
    columns / primary keys / relationships / upstream lineage).

    Derived artefacts (mermaid diagrams, lineage.json, relationships.json,
    joins.json, project_context.xml) are regenerated from this document
    on every mutation. The discovered_joins inventory and the diagnostics
    log live in their own files because they aren't project state —
    discovered joins are candidates from a scan, diagnostics is an
    append-log.

    Shared by handing a teammate this one JSON file.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    updated_at: Optional[str] = None
    project: ProjectConfig
    connections: list[Connection] = Field(default_factory=list)
    tables: list[TableMeta] = Field(default_factory=list)
