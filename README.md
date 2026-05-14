# aimm-mcp

Local **Model Context Protocol** server for the AI Model Manager. Captures
SQL data-model metadata under `~/Documents/AIMM/` and exposes it to Claude
Code (or any MCP client) over stdio.

Fork of the [AIMM VS Code extension](https://github.com/DylanCodyBrown/ODBC_AI_Workbench),
rebuilt in Python with no UI: just tools the agent calls.

## Why this exists

The VS Code extension lives inside an editor. This fork lets you skip
the editor entirely — install once with `claude mcp add`, and any
Claude session on the machine sees the same model.

## Install

One line. Claude Code spawns the server via `uvx` (uv's npx) — no
prior install, no setup.

```bash
claude mcp add aimm --scope user -- uvx aimm-mcp
```

First connection downloads the package (a few seconds). Subsequent
connections are cache-served. Server lives under `~/Documents/AIMM/`
so every project on the machine shares one model.

## What lives under `~/Documents/AIMM/`

```
~/Documents/AIMM/
├── aimm.json                project header
├── tables/<name>.json       per-table metadata
├── connections/<name>.json  ODBC connection descriptors
├── model.mmd                generated ER diagram (mermaid)
├── model_lineage.mmd        generated upstream→downstream flowchart
├── lineage.json             flat lineage edge list
├── relationships.json       flat FK edge list
├── joins.json               project-tracked joins (relationships + extracted SQL)
├── discovered_joins.json    candidates from a folder scan
├── project_context.xml      full agent-readable context
└── diagnostics.log          every ODBC query the server issued
```

## Engines

Three engines via ODBC: `trino`, `sql_server`, `databricks`. Connection
descriptors carry a DSN name (system DSN registered at the OS level)
plus the catalog / database qualifier.

## Tools (in v0.1)

- `aimm_init_project` — bootstrap `~/Documents/AIMM/`
- `aimm_read_project_context` — XML or markdown dump

More tools land per follow-up PR. See `aimm_mcp/tools/` for the
current set.

## Why ODBC?

Every warehouse this targets exposes an ODBC driver. We never run user
SQL — only `information_schema` reads for column / table / schema
metadata. Drivers stay read-only at the credential level.

## Development

```bash
uv sync
uv run python -m aimm_mcp        # starts the MCP stdio server
uv run pytest                    # tests
```

## License

MIT.
