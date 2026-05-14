# `.aimm.json` schema (v1)

The on-disk shape of an AIMM project. Identical across the Python MCP
server (this repo) and the VS Code extension. Hand-maintained on both
sides — keep them in lockstep.

```
<slug>.aimm.json
└── {
      schema_version: 1,
      updated_at?: ISO-8601 UTC string,
      project: ProjectConfig,
      connections: Connection[],
      tables: TableMeta[]
    }
```

`updated_at` is stamped on every write. `schema_version` is the
break-glass for future incompatible changes; readers that see a
higher version than they support should error rather than guess.

## ProjectConfig

| field              | type                                                       | default         | notes                                                                  |
| ------------------ | ---------------------------------------------------------- | --------------- | ---------------------------------------------------------------------- |
| `name`             | `string` (1–120)                                           | required        | human-readable project name; slugified to derive the filename          |
| `modeling_paradigm`| `'star' \| 'snowflake' \| 'parent_child' \| 'unspecified'`  | `unspecified`   | drives the VS Code extension's layout + lint; round-tripped elsewhere  |
| `dialect`          | `string`                                                   | `tsql`          | SQL dialect for sqlglot fallback ordering                              |
| `default_connection` | `string \| null`                                         | `null`          | optional default for new tables                                        |
| `description`      | `string` (≤20 000)                                         | `''`            | free-text project context the agent reads on every call                |
| `tags`             | `string[]`                                                 | `[]`            | freeform                                                               |
| `included_files`   | `string[]`                                                 | `[]`            | workspace-glob includes for tracked SQL files (extension-only)         |
| `excluded_files`   | `string[]`                                                 | `[]`            | workspace-glob excludes for tracked SQL files (extension-only)         |
| `conventions`      | `string` (≤8 000)                                          | `''`            | free-text naming / typing / structural conventions ("all dates UTC")   |
| `glossary`         | `GlossaryTerm[]`                                           | `[]`            | domain dictionary (see below); upsert via `aimm_add_glossary_term`     |
| `measures`         | `Measure[]`                                                | `[]`            | KPI / metric definitions (see below); upsert via `aimm_add_measure`    |

### GlossaryTerm

| field        | type                | default    | notes                                                                  |
| ------------ | ------------------- | ---------- | ---------------------------------------------------------------------- |
| `term`       | `string` (1–120)    | required   | the phrase the agent resolves ("active customer")                      |
| `definition` | `string` (1–1 000)  | required   | the meaning the agent should use                                       |

### Measure

| field        | type                | default    | notes                                                                  |
| ------------ | ------------------- | ---------- | ---------------------------------------------------------------------- |
| `name`       | `string` (1–120)    | required   | the metric name users refer to ("Monthly Active Customers")            |
| `definition` | `string` (1–1 000)  | required   | plain-English meaning                                                  |
| `formula`    | `string?` (≤2 000)  | -          | canonical expression in the project's dialect                          |
| `owner`      | `string?` (≤240)    | -          | optional contact for the metric                                        |

## Connection

| field            | type                                            | default      | notes                                                                  |
| ---------------- | ----------------------------------------------- | ------------ | ---------------------------------------------------------------------- |
| `name`           | `string` (1–60)                                 | required     | unique within a project                                                |
| `engine`         | `'trino' \| 'sql_server' \| 'databricks'`        | `trino`      | drives dialect-specific information_schema templates                   |
| `dsn`            | `string`                                        | required     | system DSN name registered at the OS level                             |
| `catalog`        | `string?`                                       | -            | Trino catalog; SQL Server database name                                |
| `default_schema` | `string?`                                       | -            | optional default schema for new tables                                 |
| `description`    | `string` (≤4 000)                               | `''`         | free-text connection context                                           |
| `tags`           | `string[]`                                      | `[]`         | freeform                                                               |

## TableMeta

| field              | type                                              | default      | notes                                                                  |
| ------------------ | ------------------------------------------------- | ------------ | ---------------------------------------------------------------------- |
| `table_name`       | `string` (≥1)                                     | required     | identity; cannot be patched (delete + re-add to rename)                |
| `source_file`      | `string?`                                         | -            | workspace-relative SQL path that authors this table                    |
| `connection`       | `string?`                                         | -            | connection name in this project's connections list                     |
| `paradigm_role`    | `string` (≤60)                                    | `''`         | free-text role under the project paradigm ("fact", "scd2 dim")         |
| `description`      | `string` (≤8 000)                                 | `''`         | free-text table context                                                |
| `grain`            | `string?` (≤240)                                  | -            | one-line answer to "what is one row?". `aimm_set_table_grain`          |
| `tags`             | `string[]`                                        | `[]`         | freeform                                                               |
| `aliases`          | `string[]`                                        | `[]`         | other names this table is known by                                     |
| `pitfalls`         | `string[]` (each ≤240)                            | `[]`         | "don't do this" rules. `aimm_add_pitfall` (dedups exact matches)       |
| `owner`            | `string?` (≤240)                                  | -            | free-text contact ("data-eng-slack", "alice@…")                        |
| `refresh_cadence`  | `'unknown' \| 'realtime' \| 'minutes' \| 'hourly' \| 'daily' \| 'weekly' \| 'monthly' \| 'adhoc'` | `unknown` | freshness hint                                                         |
| `refresh_notes`    | `string?` (≤500)                                  | -            | additional free-text about freshness behaviour                         |
| `scd`              | `ScdMetadata`                                     | `{type:'none'}` | slowly-changing-dimension shape (see below)                            |
| `columns`          | `Column[]`                                        | `[]`         | see below                                                              |
| `primary_keys`     | `string[]`                                        | `[]`         | column names that form the PK (composite allowed)                      |
| `relationships`    | `Relationship[]`                                  | `[]`         | FK-style edges                                                         |
| `upstream`         | `Dependency[]`                                    | `[]`         | lineage edges (downstream computed)                                    |
| `ddl_only`         | `boolean`                                         | `false`      | source SQL is `CREATE TABLE` only, no SELECT path                      |
| `staging_target`   | `string?`                                         | -            | `<schema>.<table>` qualifier into the live DB                          |
| `columns_from`     | `'information_schema' \| 'sqlglot'?`              | -            | provenance of the column list                                          |
| `db_kind`          | `'table' \| 'view'?`                              | -            | icon hint; cosmetic for the MCP                                         |
| `row_count_last_run` | `integer?`                                      | -            | auto-stamped by `aimm_refresh_columns` when the live DB call succeeds  |
| `last_run_at`      | `string?` (ISO-8601 UTC)                          | -            | auto-stamped alongside `row_count_last_run`                            |

### ScdMetadata

| field             | type                                               | default    | notes                                                                  |
| ----------------- | -------------------------------------------------- | ---------- | ---------------------------------------------------------------------- |
| `type`            | `'none' \| 'scd1' \| 'scd2' \| 'snapshot'`          | `none`     | history-tracking strategy                                              |
| `valid_from`      | `string?`                                          | -          | column name marking start of validity                                  |
| `valid_to`        | `string?`                                          | -          | column name marking end of validity                                    |
| `is_current_flag` | `string?`                                          | -          | column name that is `true` only for the current row                    |

### Column

| field            | type                                                      | default       | notes                                                                  |
| ---------------- | --------------------------------------------------------- | ------------- | ---------------------------------------------------------------------- |
| `name`           | `string` (≥1)                                             | required      |                                                                        |
| `type`           | `string`                                                  | `''`          | live type from information_schema                                      |
| `nullable`       | `boolean`                                                 | `true`        |                                                                        |
| `is_primary_key` | `boolean`                                                 | `false`       |                                                                        |
| `is_foreign_key` | `boolean`                                                 | `false`       |                                                                        |
| `description`    | `string?` (≤500)                                          | -             |                                                                        |
| `classification` | `'unspecified' \| 'public' \| 'internal' \| 'pii' \| 'phi' \| 'restricted'` | `unspecified` | sensitivity. `aimm_set_column_classification`                          |
| `quality_notes`  | `string?` (≤240)                                          | -             | "30% null pre-2023", "free-text", etc.                                 |
| `computed`       | `boolean`                                                 | `false`       | true when the column is a derivation, not stored                       |
| `expression`     | `string?` (≤1 000)                                        | -             | formula for `computed` columns                                         |
| `example_values` | `string[]`                                                | `[]`          | curated sample values                                                  |

### Relationship

| field          | type                                                | default    | notes                                                                  |
| -------------- | --------------------------------------------------- | ---------- | ---------------------------------------------------------------------- |
| `to_table`     | `string`                                            | required   |                                                                        |
| `from_columns` | `string[]`                                          | required   | parallel arrays with `to_columns`                                      |
| `to_columns`   | `string[]`                                          | required   |                                                                        |
| `cardinality`  | `'one_to_one' \| 'one_to_many' \| 'many_to_many'`    | required   |                                                                        |
| `description`  | `string?` (≤500)                                    | -          |                                                                        |

### Dependency

| field        | type                | default    | notes                                                                  |
| ------------ | ------------------- | ---------- | ---------------------------------------------------------------------- |
| `ref`        | `string` (≥1)       | required   | another tracked table name or a free-form identifier (e.g. `raw.public.orders`) |
| `description`| `string?` (≤500)    | -          |                                                                        |

## Round-trip guarantees

A file written by either side and read by the other must come back
byte-identical when re-serialised, modulo `updated_at`. Fields the
reader doesn't recognise (forward-compat) are dropped silently —
keep new fields optional + defaulted so older readers still validate
the file.

## Filename

`<slug>.aimm.json` where slug is the project's `name`, lowercased,
non-alphanumeric runs collapsed to `_`, leading/trailing `_` trimmed,
empty falling back to `untitled`.

Examples:
- `Customer Warehouse` → `customer_warehouse.aimm.json`
- `PII / 2024` → `pii_2024.aimm.json`
- `___` → `untitled.aimm.json`
