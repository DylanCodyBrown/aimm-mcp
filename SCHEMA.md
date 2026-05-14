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

## ProjectConfig

| field              | type                                                   | default         | notes                                                                  |
| ------------------ | ------------------------------------------------------ | --------------- | ---------------------------------------------------------------------- |
| `name`             | `string` (1–120)                                       | required        | human-readable project name; slugified to derive the filename          |
| `modeling_paradigm`| `'star' \| 'snowflake' \| 'parent_child' \| 'unspecified'` | `unspecified`   | used by the VS Code extension's layout + lint; round-tripped elsewhere |
| `dialect`          | `string`                                               | `tsql`          | SQL dialect for sqlglot fallback ordering                              |
| `default_connection` | `string \| null`                                     | `null`          | optional default for new tables                                        |
| `description`      | `string` (≤20 000)                                     | `''`            | free-text project context the agent reads on every call                |
| `tags`             | `string[]`                                             | `[]`            | freeform                                                               |
| `included_files`   | `string[]`                                             | `[]`            | workspace-glob includes for tracked SQL files (extension-only)         |
| `excluded_files`   | `string[]`                                             | `[]`            | workspace-glob excludes for tracked SQL files (extension-only)         |

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

| field            | type                                              | default      | notes                                                                  |
| ---------------- | ------------------------------------------------- | ------------ | ---------------------------------------------------------------------- |
| `table_name`     | `string` (≥1)                                     | required     | identity; cannot be patched (delete + re-add to rename)                |
| `source_file`    | `string?`                                         | -            | workspace-relative SQL path that authors this table                    |
| `connection`     | `string?`                                         | -            | connection name in this project's connections list                     |
| `paradigm_role`  | `string` (≤60)                                    | `''`         | free-text role under the project paradigm (e.g. "fact", "scd2 dim")    |
| `description`    | `string` (≤8 000)                                 | `''`         | free-text table context                                                |
| `tags`           | `string[]`                                        | `[]`         | freeform                                                               |
| `columns`        | `Column[]`                                        | `[]`         | see below                                                              |
| `primary_keys`   | `string[]`                                        | `[]`         | column names that form the PK (composite allowed)                      |
| `relationships`  | `Relationship[]`                                  | `[]`         | FK-style edges                                                         |
| `upstream`       | `Dependency[]`                                    | `[]`         | lineage edges (downstream computed)                                    |
| `ddl_only`       | `boolean`                                         | `false`      | source SQL is `CREATE TABLE` only, no SELECT path                      |
| `staging_target` | `string?`                                         | -            | `<schema>.<table>` qualifier into the live DB                          |
| `columns_from`   | `'information_schema' \| 'sqlglot'?`              | -            | provenance of the column list                                          |
| `db_kind`        | `'table' \| 'view'?`                              | -            | icon hint; cosmetic for the MCP                                         |

### Column

| field            | type                                              | default      | notes                                                                  |
| ---------------- | ------------------------------------------------- | ------------ | ---------------------------------------------------------------------- |
| `name`           | `string` (≥1)                                     | required     |                                                                        |
| `type`           | `string`                                          | `''`         | live type from information_schema                                      |
| `nullable`       | `boolean`                                         | `true`       |                                                                        |
| `is_primary_key` | `boolean`                                         | `false`      |                                                                        |
| `is_foreign_key` | `boolean`                                         | `false`      |                                                                        |
| `description`    | `string?` (≤500)                                  | -            |                                                                        |

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

`updated_at` is stamped on every write. `schema_version` is the
break-glass for future incompatible changes; readers that see a
higher version than they support should error rather than guess.

## Filename

`<slug>.aimm.json` where slug is the project's `name`, lowercased,
non-alphanumeric runs collapsed to `_`, leading/trailing `_` trimmed,
empty falling back to `untitled`.

Examples:
- `Customer Warehouse` → `customer_warehouse.aimm.json`
- `PII / 2024` → `pii_2024.aimm.json`
- `___` → `untitled.aimm.json`
