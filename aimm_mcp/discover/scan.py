"""Walk a local folder of `.sql` files, extract JOIN clauses via
sqlglot, aggregate per-canonical-edge.

Mirrors the extension's `discover/scan.ts` minus the git clone path
(this fork drops the GitHub flow per design — agents `git clone`
themselves if needed). Returns a flat list of canonical relationships
plus per-file parse errors so the caller can persist both.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..parse.joins import extract_joins


# Names we never descend into during the walk. Same set as the
# extension's scanner; covers the common waste of time on real repos
# (vendored Node code, build outputs, VCS metadata).
_SKIPPED_DIRS = {
    ".git", ".svn", ".hg", ".idea", ".vscode",
    "node_modules", "venv", ".venv", "__pycache__",
    "target", "build", "dist", ".aimm-cache",
}


@dataclass(frozen=True)
class Endpoint:
    schema: Optional[str]
    table: str
    column: str


@dataclass(frozen=True)
class Occurrence:
    file: str
    line: int
    kind: str
    clause_text: str
    on_text: str


@dataclass
class Relationship:
    id: str
    left: Endpoint
    right: Endpoint
    # Composite-key extras share the same canonical id as the primary
    # equality. Stored as parallel left/right tuples so the renderer
    # can show them alongside the primary.
    extra_equalities: list[tuple[Endpoint, Endpoint]] = field(default_factory=list)
    occurrences: list[Occurrence] = field(default_factory=list)


@dataclass(frozen=True)
class ScanError:
    file: str
    message: str


@dataclass
class ScanResult:
    relationships: list[Relationship]
    files_scanned: int
    files_skipped: int
    errors: list[ScanError]


def scan_folder(
    root: str | Path,
    dialect: Optional[str] = None,
    max_files: int = 5_000,
) -> ScanResult:
    """Walk `root` for `.sql` files, parse each via sqlglot, aggregate."""
    root_path = Path(root).resolve()
    sql_files = list(_walk_sql_files(root_path, max_files))

    by_id: dict[str, Relationship] = {}
    errors: list[ScanError] = []
    visited = 0
    skipped = 0

    for abs_path in sql_files:
        rel = abs_path.relative_to(root_path).as_posix()
        visited += 1
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception as err:  # noqa: BLE001
            errors.append(ScanError(file=rel, message=f"read error: {err}"))
            skipped += 1
            continue

        result = extract_joins(text, dialect=dialect, file=rel)
        if result.get("parse_errors"):
            errors.append(ScanError(file=rel, message="; ".join(result["parse_errors"])))
            # Continue — partial parses can still emit joins.

        for join in result.get("joins", []):
            _merge_join(by_id, join, rel)

    return ScanResult(
        relationships=list(by_id.values()),
        files_scanned=visited - skipped,
        files_skipped=skipped,
        errors=errors,
    )


def _merge_join(by_id: dict[str, Relationship], join: dict, file_rel: str) -> None:
    equalities = join.get("equalities") or []
    usable = [
        eq for eq in equalities
        if eq.get("left", {}).get("table")
        and eq.get("right", {}).get("table")
        and eq.get("left", {}).get("column")
        and eq.get("right", {}).get("column")
    ]
    if not usable:
        return

    primary = usable[0]
    rest = usable[1:]
    left = Endpoint(
        schema=primary["left"].get("schema"),
        table=primary["left"]["table"],
        column=primary["left"]["column"],
    )
    right = Endpoint(
        schema=primary["right"].get("schema"),
        table=primary["right"]["table"],
        column=primary["right"]["column"],
    )
    rid = relationship_id(left, right)

    occurrence = Occurrence(
        file=file_rel,
        line=int(join.get("line") or 0),
        kind=str(join.get("kind") or "JOIN"),
        clause_text=str(join.get("clause_text") or ""),
        on_text=str(join.get("on_text") or ""),
    )

    entry = by_id.get(rid)
    if entry is None:
        entry = Relationship(
            id=rid,
            left=left,
            right=right,
            extra_equalities=[
                (
                    Endpoint(
                        schema=eq["left"].get("schema"),
                        table=eq["left"]["table"],
                        column=eq["left"]["column"],
                    ),
                    Endpoint(
                        schema=eq["right"].get("schema"),
                        table=eq["right"]["table"],
                        column=eq["right"]["column"],
                    ),
                )
                for eq in rest
            ],
        )
        by_id[rid] = entry

    # Dedupe within an entry: same (file, on_text) shouldn't appear twice.
    if not any(o.file == occurrence.file and o.on_text == occurrence.on_text for o in entry.occurrences):
        entry.occurrences.append(occurrence)


def relationship_id(left: Endpoint, right: Endpoint) -> str:
    """Direction-agnostic canonical id. `a→b` and `b→a` produce the
    same string so the two map onto one entry."""
    a = f"{(left.schema or '').lower()}.{left.table.lower()}.{left.column.lower()}"
    b = f"{(right.schema or '').lower()}.{right.table.lower()}.{right.column.lower()}"
    return f"{a}|{b}" if a < b else f"{b}|{a}"


def _walk_sql_files(root: Path, max_files: int) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Mutate dirnames in place so os.walk skips ignored trees.
        dirnames[:] = [d for d in dirnames if d not in _SKIPPED_DIRS]
        for fn in filenames:
            if fn.lower().endswith(".sql"):
                out.append(Path(dirpath) / fn)
                if len(out) >= max_files:
                    return out
    return out
