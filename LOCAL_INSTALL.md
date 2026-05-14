# Local install (pre-PyPI)

This server isn't on PyPI yet. Until it is, run it from a checkout. The
config below points Claude Code at your local clone — once published,
swap to the one-line `uvx aimm-mcp` form in `README.md`.

## Prerequisites

- **Python ≥ 3.11** on `PATH`.
- **uv** (`curl -LsSf https://astral.sh/uv/install.sh | sh`). uv
  manages the venv and the `aimm-mcp` entry point.
- **Claude Code** (`claude` CLI). Any MCP client over stdio also
  works; the config shape is the same.
- **ODBC drivers** for whichever engines you actually plan to hit
  (Trino, SQL Server, Databricks). Only needed for the live-catalog
  tools — `aimm_init_project`, `aimm_update_table`,
  `aimm_scan_folder_for_joins`, etc. work without any DSN.

## Set up the checkout

```bash
git clone https://github.com/DylanCodyBrown/aimm-mcp.git
cd aimm-mcp
uv sync --dev
uv run pytest -q              # 33 tests, ~1s
```

If the tests pass, the wiring is good. If `pytest` fails on a
pyodbc-related import, you're missing the unixODBC headers — install
`unixodbc-dev` (Debian/Ubuntu), `unixodbc` (Homebrew), or the Windows
ODBC SDK.

## Smoke-test the MCP handshake without Claude

```bash
printf '%s\n%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"local","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | uv run python -m aimm_mcp
```

You should see a JSON-RPC response listing 13 `aimm_*` tools. Ctrl-C
to exit. This is the same handshake CI runs on every push.

## Register with Claude Code

Use an **absolute path** to the checkout — `claude mcp add` resolves
the working directory at spawn time, not at registration time.

```bash
claude mcp add aimm --scope user -- \
  uv run --directory /absolute/path/to/aimm-mcp aimm-mcp
```

`--directory` tells uv to use the checkout's `pyproject.toml` /
`.venv`, then the script entry point `aimm-mcp` (from
`pyproject.toml#project.scripts`) launches the stdio server.

### Alternative: mimic the PyPI invocation

If you want the registration to look like the eventual published
form, use `uvx --from`:

```bash
claude mcp add aimm --scope user -- \
  uvx --from /absolute/path/to/aimm-mcp aimm-mcp
```

`uvx` builds an ephemeral venv from the local path on each spawn —
slower than `uv run --directory` but closer to what end users will
do with `uvx aimm-mcp` post-publish.

## Verify

```bash
claude mcp list                   # aimm should appear, status: connected
```

Then in a Claude Code session:

```
> what does aimm_show_active_project return?
> use aimm_init_project to create a project called "Scratch"
> use aimm_read_project_context to show me what's in it
```

After the second call you should see an XML rendering of the project.
On disk:

```
~/Documents/AIMM/
├── state.json              ← session pointer (which folder, which active file)
└── scratch.aimm.json       ← created by aimm_init_project, slug from name
```

To point the MCP at a different folder of project files (e.g. a team
repo), call `aimm_set_projects_folder` then `aimm_list_projects` to
see what's in it, and `aimm_set_active_project` to pick one.

## Where state lives

- `<projects_folder>/<slug>.aimm.json` — one file per project. Hand
  it to a teammate (or commit it to a repo) to share the whole model.
  `projects_folder` defaults to `~/Documents/AIMM/` and is overridable
  via `aimm_set_projects_folder`.
- `~/Documents/AIMM/state.json` — session pointer: which projects
  folder, which file is active. Machine-local; survives across
  Claude Code sessions.
- `~/Documents/AIMM/discovered_joins.json` — written by
  `aimm_scan_folder_for_joins`.
- `~/Documents/AIMM/diagnostics.log` — every ODBC query the server
  ran (256 KB rotation). Pull the tail with
  `aimm_show_diagnostics_log` when a connection call fails.

Delete `~/Documents/AIMM/` to reset machine-local state. Your
project files in a team repo are untouched by that reset.

## Iterating on the code

The MCP server is launched fresh per Claude Code session, so edits to
the source are picked up the next time you start a session — no
restart command needed beyond closing and reopening Claude Code.

Tests:

```bash
uv run pytest -q                     # all
uv run pytest tests/test_tools_tables.py -q   # one file
uv run pytest -k primary_key -q      # by keyword
```

## Updating

```bash
cd /absolute/path/to/aimm-mcp
git pull
uv sync --dev
```

The next Claude Code session picks up the new code automatically.

## Uninstall

```bash
claude mcp remove aimm --scope user
rm -rf ~/Documents/AIMM           # optional: wipe local state
```

The checkout itself is just a directory — delete it whenever.

## Troubleshooting

- **`claude mcp list` shows `failed`.** Run the smoke-test command
  above. If that succeeds, the issue is path resolution — confirm the
  `--directory` path is absolute and exists.
- **Tools that hit ODBC return `connect_failed`.** Confirm the DSN
  exists at the OS level (`aimm_list_system_dsns` reflects what
  `pyodbc.dataSources()` sees) before debugging credentials.
- **`uvx --from <path>` is slow.** Expected — it rebuilds the venv
  per spawn. Switch to `uv run --directory` for day-to-day use.
- **Need the exact SQL the server tried.**
  `aimm_show_diagnostics_log` returns the tail of the log; every
  ODBC call is recorded with DSN, timing, and result.
