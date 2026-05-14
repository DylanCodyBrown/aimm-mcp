"""Single-file ODBC diagnostics log.

Every information_schema query the server issues writes one line to
`~/Documents/AIMM/diagnostics.log`. The runner calls into the
QueryLogger protocol; we install a FileQueryLogger at server boot.
Rotates at ~256 KB so it doesn't grow unbounded (single .old kept).

Mirrors the extension's diagnostics format so paste-back-and-debug
flows feel identical between the two.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_ROTATE_BYTES = 256 * 1024


def format_event(event: dict[str, Any]) -> str:
    """Single grep-friendly line per query. SQL is collapsed onto one
    line and capped at 500 chars so a runaway query (IN-list with
    thousands of names) doesn't dominate the log."""
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    dsn = event.get("dsn", "")
    source = event.get("source")
    duration_ms = event.get("duration_ms", 0)
    sql = _collapse(str(event.get("sql", "")), 500)
    result = event.get("result", {})
    head = f"{ts} {duration_ms}ms dsn={dsn}"
    if source:
        head += f" src={source}"
    if result.get("ok"):
        rows = result.get("row_count", 1)
        return f"{head} ok rows={rows} sql={sql}"
    reason = result.get("reason", "unknown")
    detail = _collapse(str(result.get("detail", "")), 240)
    return f"{head} fail {reason} {detail} sql={sql}"


def _collapse(s: str, cap: int) -> str:
    flat = " ".join(s.split())
    if len(flat) <= cap:
        return flat
    return flat[: cap - 1] + "…"


class FileQueryLogger:
    """QueryLogger implementation that appends to
    ~/Documents/AIMM/diagnostics.log. Rotation: when the file passes
    the byte cap, it's renamed to .old and a fresh log starts. Simple
    one-generation rotation — this is a debug aid, not a server log.

    All write failures are swallowed; diagnostics never break the
    tool it observes.
    """

    def __init__(self, log_path: Path, rotate_bytes: int = _ROTATE_BYTES):
        self._log_path = log_path
        self._rotate_bytes = rotate_bytes

    def log_query(self, event: dict[str, Any]) -> None:
        try:
            line = format_event(event)
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed()
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:  # noqa: BLE001
            pass

    def _rotate_if_needed(self) -> None:
        try:
            if not self._log_path.exists():
                return
            if self._log_path.stat().st_size <= self._rotate_bytes:
                return
            rolled = self._log_path.with_suffix(self._log_path.suffix + ".old")
            os.replace(self._log_path, rolled)
        except Exception:  # noqa: BLE001
            pass


def tail_log(log_path: Path, max_bytes: int = 64 * 1024) -> str:
    """Return the last N bytes of the diagnostics log. Used by
    aimm_show_diagnostics_log so the agent can read recent activity
    without slurping the whole file into context."""
    try:
        stat = log_path.stat()
    except FileNotFoundError:
        return ""
    if stat.st_size <= max_bytes:
        return log_path.read_text(encoding="utf-8", errors="replace")
    with log_path.open("rb") as fh:
        fh.seek(stat.st_size - max_bytes)
        return fh.read().decode("utf-8", errors="replace")
