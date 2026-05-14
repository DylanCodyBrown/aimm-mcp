"""Atomic JSON I/O for the AIMM folder.

Every write goes through `atomic_write_json` — write-to-tmp then
rename — so a Claude-induced crash mid-call never corrupts the
on-disk JSON. Reads validate through pydantic, returning typed models
to callers.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Type, TypeVar

from pydantic import BaseModel, ValidationError

from . import paths
from .schemas import Connection, ProjectConfig, TableMeta


T = TypeVar("T", bound=BaseModel)


def atomic_write_json(path: Path, model: BaseModel) -> None:
    """Write a pydantic model as pretty-printed JSON atomically.

    The temp file lives next to the target so the rename is a single
    filesystem op (works on Windows + POSIX). Mode-2-defaults
    `model_dump` drops None values and uses field aliases when set,
    matching what the extension's zod-validated writes produce.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump(exclude_none=False, by_alias=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_path, path)
    finally:
        # If replace succeeded, tmp_path is already gone; this is a
        # cleanup for the rare error case where replace raised.
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


def read_json(path: Path, model_cls: Type[T]) -> T | None:
    """Read and validate a JSON file. Returns None when the file
    doesn't exist; raises pydantic.ValidationError when the file is
    malformed (caller decides whether to surface or swallow)."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return model_cls.model_validate(data)


# --- typed helpers ---------------------------------------------------------


def read_project() -> ProjectConfig | None:
    return read_json(paths.project_config_path(), ProjectConfig)


def write_project(cfg: ProjectConfig) -> None:
    atomic_write_json(paths.project_config_path(), cfg)


def read_table(name: str) -> TableMeta | None:
    return read_json(paths.table_json_path(name), TableMeta)


def write_table(meta: TableMeta) -> None:
    atomic_write_json(paths.table_json_path(meta.table_name), meta)


def read_connection(name: str) -> Connection | None:
    return read_json(paths.connection_json_path(name), Connection)


def write_connection(conn: Connection) -> None:
    atomic_write_json(paths.connection_json_path(conn.name), conn)


def list_table_names() -> list[str]:
    """Sorted list of every tracked table name (from the on-disk
    tables/ directory). Dot-prefixed files are skipped — those are
    atomic-write temp leftovers, not real metadata."""
    d = paths.tables_dir()
    if not d.exists():
        return []
    return sorted(
        p.stem
        for p in d.glob("*.json")
        if not p.name.startswith(".")
    )


def list_connection_names() -> list[str]:
    d = paths.connections_dir()
    if not d.exists():
        return []
    return sorted(
        p.stem
        for p in d.glob("*.json")
        if not p.name.startswith(".")
    )


def iter_tables() -> Iterable[TableMeta]:
    for name in list_table_names():
        meta = read_table(name)
        if meta is not None:
            yield meta


def iter_connections() -> Iterable[Connection]:
    for name in list_connection_names():
        conn = read_connection(name)
        if conn is not None:
            yield conn
