"""Rich JOIN extraction for the discover-relationships feature.

Given a SQL file, return one entry per JOIN clause with:

  - kind ("LEFT" / "INNER" / "RIGHT" / "FULL" / "CROSS" / "JOIN")
  - left side and right side, each {schema?, table, column}
  - on_text — the rendered SQL of the ON expression
  - clause_text — a reconstructed `LEFT JOIN <right> ON <on>` for hover
  - line — 1-based line number of the JOIN keyword
  - file — caller passes through; we just echo it back

Aliases are resolved against the FROM clause + every JOIN source visible
at the join's site. `customers c` then `c.id = ...` → `(stg.customers, id)`.
Unresolved aliases (typo, missing source) keep the alias string verbatim
in `table` so the caller can decide whether to drop them.

Resilience policy. Real-world repos mix dialects (T-SQL, Spark, Trino),
include Redash-style Jinja templates, and ship the occasional non-UTF-8
byte. The parser:

  1. Strips obvious Jinja placeholders so `{{Reports}}` doesn't
     short-circuit the tokenizer.
  2. Splits the file into statements at `;` and parses each
     independently — one failed statement no longer takes down the
     other nine.
  3. Tries the configured dialect first, then falls back through a
     short list (tsql, spark, no-dialect). Whichever combination
     yields the most usable joins wins.

This module is independent of `parse.py` to keep the dispatch surface
narrow — the discover feature has different needs (cross-statement walk,
all CTEs, line numbers) from the canonical "what does this file produce"
parser.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import sqlglot
from sqlglot import exp


# Order matters: the first dialect that succeeds wins. Trino-specific
# pieces (federated catalog names) parse fine under most dialects, so the
# real win comes from tsql / spark catching bracket and backtick
# identifiers respectively. `None` is sqlglot's permissive no-dialect
# mode and serves as the catch-all.
_FALLBACK_DIALECTS: Tuple[Optional[str], ...] = ('tsql', 'spark', None)


def extract_joins(
    sql: str,
    dialect: Optional[str] = None,
    file: Optional[str] = None,
) -> Dict[str, Any]:
    """Walk every statement in `sql` and emit a flat list of join entries.

    Returns `{"joins": [...], "parse_errors": [...]}` so callers always get
    a list (empty on parse failure) plus a diagnostics channel.
    """
    cleaned = _strip_jinja(sql)
    statements = _split_statements(cleaned)

    # Build the dialect order: configured first (when supplied), then any
    # fallback that isn't already at the head of the list.
    order: List[Optional[str]] = []
    seen: set = set()
    if dialect is not None:
        order.append(dialect)
        seen.add(dialect)
    for d in _FALLBACK_DIALECTS:
        if d in seen:
            continue
        order.append(d)
        seen.add(d)

    joins: List[Dict[str, Any]] = []
    parse_errors: List[str] = []

    for stmt_text in statements:
        if not stmt_text.strip():
            continue
        result = _extract_from_statement(stmt_text, order, file)
        if result['error']:
            # Rescue split: many user files concatenate DDL statements
            # without semicolons (`drop view x  create view x as …`).
            # Re-split the offending chunk on top-level CREATE/DROP/ALTER/
            # TRUNCATE-VIEW/TABLE keywords and parse each piece.
            sub = _ddl_keyword_split(stmt_text)
            if len(sub) > 1:
                rescue_errors: List[str] = []
                rescue_joins: List[Dict[str, Any]] = []
                for piece in sub:
                    if not piece.strip():
                        continue
                    r = _extract_from_statement(piece, order, file)
                    rescue_joins.extend(r['joins'])
                    if r['error']:
                        rescue_errors.append(r['error'])
                # Use the rescue result when it actually recovered something
                # the all-or-nothing parse couldn't.
                if rescue_joins or len(rescue_errors) < 1:
                    joins.extend(rescue_joins)
                    if rescue_errors:
                        parse_errors.append(rescue_errors[-1])
                    continue
            parse_errors.append(result['error'])
        else:
            joins.extend(result['joins'])

    return {"joins": joins, "parse_errors": parse_errors}


# DDL-keyword rescue split. Only triggers as a fallback when a chunk
# fails every dialect — splits at the start of a new top-level DDL
# statement so multi-statement files without semicolons still yield
# their joins. Conservative pattern: requires the keyword to start a
# line / be preceded by whitespace, *and* be followed by VIEW or TABLE
# (with optional OR REPLACE), so words like `created_at` or
# `is_table_owner` never trip it.
_DDL_BOUNDARY = re.compile(
    r'(?im)(?:^|\s)(?=(?:create|drop|alter|truncate)\s+(?:or\s+replace\s+)?(?:view|table)\b)'
)


def _ddl_keyword_split(sql: str) -> List[str]:
    pieces = _DDL_BOUNDARY.split(sql)
    return [p for p in pieces if p and p.strip()]


def _extract_from_statement(
    stmt_text: str,
    dialect_order: List[Optional[str]],
    file: Optional[str],
) -> Dict[str, Any]:
    """Try each dialect in turn, return the joins from the first one that
    parses cleanly. When every dialect fails, return the last parse error
    so the caller can log it."""
    last_err: str = ''
    for dialect in dialect_order:
        try:
            parsed = sqlglot.parse(stmt_text, read=dialect)
        except sqlglot.errors.ParseError as err:
            last_err = str(err)
            continue
        joins = _walk(parsed, file)
        # Treat a clean parse as success even if the statement happened
        # to contain no joins; otherwise we'd cycle through every dialect
        # for an innocuous SELECT.
        return {'joins': joins, 'error': ''}
    return {'joins': [], 'error': last_err}


def _walk(statements: List[Optional[exp.Expression]], file: Optional[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for stmt in statements:
        if stmt is None:
            continue
        for select in stmt.find_all(exp.Select):
            alias_map = _build_alias_map(select)
            for join in select.args.get("joins") or []:
                entry = _join_entry(join, alias_map, file)
                if entry is not None:
                    out.append(entry)
    return out


# Redash-style Jinja parameters land verbatim in many internal repos:
# `{{ Sales Date }}`, `{{Reports}}`, `{{ store_id }}`. They're not SQL
# and break the tokenizer. Replace each with a numeric literal — that
# keeps the surrounding statement parseable while preserving structural
# context.
_JINJA_PATTERN = re.compile(r'\{\{[^{}]+\}\}')


def _strip_jinja(sql: str) -> str:
    return _JINJA_PATTERN.sub('1', sql)


# Naive statement splitter. Splits on `;` outside string / bracket
# literals. Good enough for our use case — when we get one statement
# wrong, we lose its joins, not the whole file. sqlglot has its own
# `split` but it itself parses the SQL, which defeats the purpose
# (we're trying to recover from parse failures).
def _split_statements(sql: str) -> List[str]:
    out: List[str] = []
    buf: List[str] = []
    in_single = False
    in_double = False
    in_bracket = False  # T-SQL [identifier]
    in_backtick = False  # Spark `identifier`
    in_line_comment = False
    in_block_comment = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ''
        if in_line_comment:
            if ch == '\n':
                in_line_comment = False
            buf.append(ch)
        elif in_block_comment:
            if ch == '*' and nxt == '/':
                in_block_comment = False
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
            buf.append(ch)
        elif in_single:
            buf.append(ch)
            if ch == "'" and nxt == "'":
                buf.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
        elif in_double:
            buf.append(ch)
            if ch == '"':
                in_double = False
        elif in_bracket:
            buf.append(ch)
            if ch == ']':
                in_bracket = False
        elif in_backtick:
            buf.append(ch)
            if ch == '`':
                in_backtick = False
        else:
            if ch == '-' and nxt == '-':
                in_line_comment = True
                buf.append(ch)
            elif ch == '/' and nxt == '*':
                in_block_comment = True
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
            elif ch == "'":
                in_single = True
                buf.append(ch)
            elif ch == '"':
                in_double = True
                buf.append(ch)
            elif ch == '[':
                in_bracket = True
                buf.append(ch)
            elif ch == '`':
                in_backtick = True
                buf.append(ch)
            elif ch == ';':
                out.append(''.join(buf))
                buf = []
            else:
                buf.append(ch)
        i += 1
    if buf:
        out.append(''.join(buf))
    return out


def _build_alias_map(select: exp.Select) -> Dict[str, Tuple[Optional[str], str]]:
    """Map alias-or-unaliased-name → (schema?, table) for every source the
    select has access to. Includes the FROM source plus every JOIN source.
    """
    out: Dict[str, Tuple[Optional[str], str]] = {}

    def add(table_node: exp.Expression, alias_node: Optional[exp.Expression]) -> None:
        if not isinstance(table_node, exp.Table):
            return
        schema = _ident_or_none(table_node.args.get("db"))
        name = _ident_or_none(table_node.this)
        if not name:
            return
        keys: List[str] = []
        if alias_node is not None:
            ident = alias_node.this if hasattr(alias_node, "this") else alias_node
            alias_name = _ident_or_none(ident)
            if alias_name:
                keys.append(alias_name)
        # An unaliased table is referenced by its bare name. Both Trino and
        # SQL Server are case-insensitive on identifiers, so we'll match
        # case-insensitively at lookup time — store both styles.
        keys.append(name)
        for key in keys:
            out.setdefault(key, (schema, name))

    # FROM source(s). sqlglot 30 renamed the args key from `from` →
    # `from_`; older versions kept `from`. Read both so we work
    # across sqlglot versions without pinning.
    from_clause = select.args.get("from") or select.args.get("from_")
    if from_clause is not None:
        for src in from_clause.find_all(exp.Table):
            # Aliased tables show up as: Table -> args["alias"] -> TableAlias
            alias = src.args.get("alias") if hasattr(src, "args") else None
            add(src, alias)

    # JOIN sources.
    for join in select.args.get("joins") or []:
        right = join.this
        if isinstance(right, exp.Table):
            add(right, right.args.get("alias"))
        elif isinstance(right, exp.Subquery):
            # Subquery joins (`JOIN (SELECT ...) sq ON ...`) — we can't
            # statically resolve column→table for these without column-level
            # propagation. Skip; the column refs in the ON expression will
            # fall through to the verbatim-alias path.
            continue

    return out


def _join_entry(
    join: exp.Join,
    alias_map: Dict[str, Tuple[Optional[str], str]],
    file: Optional[str],
) -> Optional[Dict[str, Any]]:
    on = join.args.get("on")
    if on is None:
        # CROSS JOIN or NATURAL JOIN — nothing to extract column-wise.
        return None
    right = join.this
    if not isinstance(right, exp.Table):
        return None

    right_schema = _ident_or_none(right.args.get("db"))
    right_table = _ident_or_none(right.this) or ""
    right_alias = _alias_name(right.args.get("alias"))

    kind = (join.args.get("side") or join.args.get("kind") or "JOIN").upper()
    if kind not in {"LEFT", "RIGHT", "FULL", "INNER", "OUTER", "CROSS", "JOIN", "SEMI", "ANTI"}:
        kind = "JOIN"

    on_text = on.sql()
    # Reconstructed clause for tooltip display.
    right_text = right_table
    if right_schema:
        right_text = f"{right_schema}.{right_text}"
    if right_alias and right_alias != right_table:
        right_text = f"{right_text} {right_alias}"
    clause_text = f"{kind} JOIN {right_text} ON {on_text}"

    line = _node_line(on) or _node_line(join) or 0

    equalities: List[Dict[str, Any]] = []
    for eq in on.find_all(exp.EQ):
        l = _resolve_column(eq.this, alias_map)
        r = _resolve_column(eq.expression, alias_map)
        if l is None or r is None:
            continue
        equalities.append({"left": l, "right": r})

    if not equalities:
        return None

    return {
        "kind": kind,
        "right_schema": right_schema,
        "right_table": right_table,
        "right_alias": right_alias,
        "on_text": on_text,
        "clause_text": clause_text,
        "line": line,
        "file": file,
        "equalities": equalities,
    }


def _resolve_column(
    node: exp.Expression,
    alias_map: Dict[str, Tuple[Optional[str], str]],
) -> Optional[Dict[str, Optional[str]]]:
    """Convert a Column expression like `c.id` into `{schema, table, column}`,
    using the alias map to look the qualifier up. Returns None for non-column
    operands (literals, function calls) — those joins aren't column-equality
    relationships and should be dropped from the discover output.
    """
    if not isinstance(node, exp.Column):
        return None
    column_name = _ident_or_none(node.this)
    if not column_name:
        return None
    qualifier_node = node.args.get("table")
    qualifier = _ident_or_none(qualifier_node)
    schema: Optional[str] = None
    table: Optional[str] = qualifier
    if qualifier is not None:
        # Try the alias map (case-insensitive on the qualifier).
        for key, (q_schema, q_table) in alias_map.items():
            if key.lower() == qualifier.lower():
                schema, table = q_schema, q_table
                break
    return {"schema": schema, "table": table, "column": column_name}


def _ident_or_none(node: Optional[exp.Expression]) -> Optional[str]:
    if node is None:
        return None
    name = getattr(node, "name", None)
    if isinstance(name, str) and name:
        return name
    return None


def _alias_name(alias_node: Optional[exp.Expression]) -> Optional[str]:
    if alias_node is None:
        return None
    inner = alias_node.this if hasattr(alias_node, "this") else alias_node
    return _ident_or_none(inner)


def _node_line(node: exp.Expression) -> Optional[int]:
    """Best-effort line lookup. sqlglot stashes token metadata on the
    expression's `_meta` dict when location tracking is enabled; if it's
    missing we return None and the caller falls back to 0."""
    meta = getattr(node, "_meta", None)
    if isinstance(meta, dict):
        line = meta.get("line")
        if isinstance(line, int) and line > 0:
            return line
    return None
