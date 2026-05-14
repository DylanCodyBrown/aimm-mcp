"""System DSN enumeration via pyodbc.

`pyodbc.dataSources()` walks the platform's ODBC config:

  - Windows: HKLM\\SOFTWARE\\ODBC\\ODBC.INI plus the user hive
  - macOS / Linux: /etc/odbc.ini plus ~/.odbc.ini (or whatever the
    iODBC / unixODBC install points at)

Returns a `{ name: driver }` dict. We surface it as a list of DSN
records so callers can render with whatever shape suits them.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    import pyodbc  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    pyodbc = None  # type: ignore[assignment]


@dataclass(frozen=True)
class Dsn:
    name: str
    driver: str


def list_system_dsns() -> list[Dsn]:
    """Returns every DSN visible to pyodbc on this machine. Empty list
    when pyodbc isn't installed or no driver registered any DSN."""
    if pyodbc is None:
        return []
    try:
        sources = pyodbc.dataSources()
    except Exception:  # noqa: BLE001 - pyodbc occasionally throws on misconfig
        return []
    return [Dsn(name=name, driver=str(driver)) for name, driver in sorted(sources.items())]
