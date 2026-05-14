"""Module entry: `python -m aimm_mcp` is equivalent to `uvx aimm-mcp`."""

from __future__ import annotations

import sys

from .server import main


if __name__ == "__main__":
    sys.exit(main())
