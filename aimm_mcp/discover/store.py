"""Persistence for `~/Documents/AIMM/discovered_joins.json`.

Mirrors the extension's discover store schema: relationships indexed by
both endpoints' `<schema>.<table>` so the catalog tree (or any consumer)
finds them from either side in O(1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .. import paths
from .scan import Endpoint, Occurrence, Relationship


SCHEMA_VERSION = 1


def _serialize_endpoint(ep: Endpoint) -> dict:
    return {"schema": ep.schema, "table": ep.table, "column": ep.column}


def _serialize_occurrence(occ: Occurrence) -> dict:
    return {
        "file": occ.file,
        "line": occ.line,
        "kind": occ.kind,
        "clause_text": occ.clause_text,
        "on_text": occ.on_text,
    }


def _serialize_relationship(rel: Relationship) -> dict:
    return {
        "id": rel.id,
        "left": _serialize_endpoint(rel.left),
        "right": _serialize_endpoint(rel.right),
        "extra_equalities": [
            {"left": _serialize_endpoint(l), "right": _serialize_endpoint(r)}
            for l, r in rel.extra_equalities
        ],
        "occurrences": [_serialize_occurrence(o) for o in rel.occurrences],
    }


def _table_key(schema: Optional[str], table: str) -> str:
    return f"{(schema or '').lower()}.{table.lower()}"


def write_store(
    relationships: list[Relationship],
    source_location: str,
    files_scanned: int,
) -> Path:
    """Materialise the flat relationships list into the schema the
    catalog tree expects (`by_table` keyed by endpoint) and persist
    to AIMM/discovered_joins.json. Returns the path."""
    by_table: dict[str, list[dict]] = {}
    for rel in relationships:
        payload = _serialize_relationship(rel)
        for ep in (rel.left, rel.right):
            key = _table_key(ep.schema, ep.table)
            if not any(r["id"] == rel.id for r in by_table.get(key, [])):
                by_table.setdefault(key, []).append(payload)

    doc = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "kind": "folder",
            "location": source_location,
            "files_scanned": files_scanned,
        },
        "by_table": by_table,
    }
    path = paths.discovered_joins_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path
