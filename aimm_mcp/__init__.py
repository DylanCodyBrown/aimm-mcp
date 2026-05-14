"""Local MCP server for AI Model Manager (AIMM).

Captures SQL data-model metadata under ~/Documents/AIMM and exposes
it to Claude / any MCP client over stdio.

Entry points:
    `uvx aimm-mcp`                  (via the [project.scripts] entry)
    `python -m aimm_mcp`            (module form)

See README.md for the install one-liner and the tool list.
"""

__version__ = "0.1.0"
