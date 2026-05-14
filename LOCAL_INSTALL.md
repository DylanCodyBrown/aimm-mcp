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

## Distributing to a team without PyPI

PyPI isn't the only path. If you want your team installing the same
server without publishing publicly, three options in order of
ceremony:

### Option 1: install from a git repo (zero infrastructure)

`uvx` accepts a git URL directly. For a public repo, this is one
command:

```bash
claude mcp add aimm --scope user -- \
  uvx --from git+https://github.com/<org>/<repo>.git aimm-mcp
```

For a private repo, embed an auth token or use SSH:

```bash
# HTTPS + PAT (the token needs `repo` scope on a private repo)
claude mcp add aimm --scope user -- \
  uvx --from "git+https://x-access-token:${GITHUB_TOKEN}@github.com/<org>/<repo>.git" aimm-mcp

# SSH (uses the user's SSH keys)
claude mcp add aimm --scope user -- \
  uvx --from "git+ssh://git@github.com/<org>/<repo>.git" aimm-mcp
```

Pin to a tag or branch by appending `@<ref>`:
`git+https://github.com/<org>/<repo>.git@v0.3.0`.

uv clones the repo on first run and caches the built venv — second
spawn is fast. Updating means clearing the cache (`uv cache clean
aimm-mcp`) or pinning a new ref.

**Pros:** one command, no infrastructure, easy to roll forward.
**Cons:** every machine needs repo access; first-spawn is a few
seconds slower than a wheel install.

### Option 2: GitHub Releases + built wheels (clean versioning)

Build a wheel in CI, attach it to a release, install from URL:

```yaml
# .github/workflows/release.yml — runs on tag push
- run: uv build                          # produces dist/aimm_mcp-*-py3-none-any.whl
- uses: softprops/action-gh-release@v2
  with:
    files: dist/*
```

Then team members run:

```bash
claude mcp add aimm --scope user -- \
  uvx --from "https://github.com/<org>/<repo>/releases/download/v0.3.0/aimm_mcp-0.3.0-py3-none-any.whl" aimm-mcp
```

Private repos: same URL, just append a `--header
"Authorization: token ${GITHUB_TOKEN}"` via `UV_EXTRA_INDEX_AUTH` or
wrap in a tiny launcher script. Pinning is built in — the URL
carries the version.

**Pros:** fast spawn (wheel install, no build), explicit version
pinning, audit trail on the release.
**Cons:** needs a release workflow.

### Option 3: private package index

For a team that already runs a private index (Azure Artifacts, AWS
CodeArtifact, GitHub Packages, DevPI, JFrog, …), the path mirrors
PyPI:

```bash
# Publishing
uv build
uv publish --index https://your.internal/simple ...

# Installing
claude mcp add aimm --scope user -- \
  uvx --index https://your.internal/simple aimm-mcp
```

Auth via `UV_INDEX_URL` env var or `~/.netrc`. Versions are
discoverable via the index; `uvx aimm-mcp==0.3.0` pins exactly.

**Pros:** identical UX to PyPI (`uvx aimm-mcp`); full version
resolution; works with internal compliance scans.
**Cons:** standing infrastructure to maintain.

### What I'd pick

Small team (<10): **option 1**. One command, no infra. Use a tagged
ref for stability (`@v0.3.0`).

Medium team or "we want stable installs the team doesn't have to
re-clone on every update": **option 2**. CI builds wheels on tag
push; team installs from the release URL.

Already running an internal index for other Python tools:
**option 3**. Adds aimm-mcp to a path they already trust.

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
