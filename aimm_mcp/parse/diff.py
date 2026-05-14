"""Column-shape diff between authored SQL and live DB.

Ported from `extension/src/columns/diff.ts`. Case-insensitive name
matching (Trino + SQL Server + Databricks are all case-insensitive on
identifiers; lowercasing collapses author casing vs. info_schema
returns). Type-change detection only fires when sqlglot inferred a
type for the authored column — empty type is "we don't know," not
"different from <db_type>."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..schemas import Column


@dataclass(frozen=True)
class ChangedColumn:
    name: str
    before_type: str
    before_nullable: bool
    after_type: str
    after_nullable: bool


@dataclass
class ColumnDiff:
    added: list[Column] = field(default_factory=list)
    removed: list[Column] = field(default_factory=list)
    changed: list[ChangedColumn] = field(default_factory=list)


def diff_columns(authored: list[Column], live: list[Column]) -> ColumnDiff:
    """authored = what the local SQL parser produced; live = what the
    DB returns via information_schema. Returns added (in authored, not
    in live), removed (in live, not in authored), changed (in both
    but differs on type or nullability)."""
    live_by_name = {c.name.lower(): c for c in live}
    authored_by_name = {c.name.lower(): c for c in authored}

    added: list[Column] = []
    changed: list[ChangedColumn] = []
    for a in authored:
        l = live_by_name.get(a.name.lower())
        if l is None:
            added.append(a)
            continue
        if not a.type or not a.type.strip():
            # Skip the change branch — caller doesn't know the
            # authored type yet, can't claim "this changed."
            continue
        if _types_equal(a.type, l.type) and a.nullable == l.nullable:
            continue
        changed.append(ChangedColumn(
            name=a.name,
            before_type=l.type,
            before_nullable=l.nullable,
            after_type=a.type,
            after_nullable=a.nullable,
        ))

    removed = [l for l in live if l.name.lower() not in authored_by_name]
    return ColumnDiff(added=added, removed=removed, changed=changed)


def _types_equal(a: str, b: str) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def is_empty(diff: ColumnDiff) -> bool:
    return not (diff.added or diff.removed or diff.changed)
