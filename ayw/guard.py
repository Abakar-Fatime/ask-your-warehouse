"""SQL guardrails. Every statement the model writes passes through check() before it can run.

Policy (deny by default):
  * exactly one statement, and it must be a SELECT (CTEs and UNIONs allowed)
  * only tables from the allow-list (plus the query's own CTE names), no schema-qualified names
  * no table functions (read_csv, read_parquet, range, duckdb_tables(), ...)
  * no file, system or extension functions
  * a row cap is always applied
This is the first of three layers: the engine also opens the database read-only with external
access disabled, and enforces a timeout.
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

DIALECT = "duckdb"
SETOP = getattr(exp, "SetOperation", exp.Union)

BLOCKED_FUNCTION_PREFIXES = ("read_", "pragma_", "duckdb_", "sniff_", "parquet_", "glob")
BLOCKED_FUNCTIONS = {
    "current_setting", "getenv", "load_extension", "install_extension",
    "query", "query_table", "list_files", "write_csv", "write_parquet",
}


class GuardError(ValueError):
    """The SQL was rejected. The message is safe to show to the model and the user."""


@dataclass(frozen=True)
class Checked:
    sql: str
    tables: frozenset[str]


def _function_name(fn: exp.Func) -> str:
    return (fn.name if isinstance(fn, exp.Anonymous) else fn.sql_name()).lower()


def _limit_value(node) -> int | None:
    lim = node.args.get("limit")
    if lim is None:
        return None
    try:
        return int(lim.expression.name)
    except (AttributeError, ValueError):
        return -1  # present but not a plain integer literal


def check(sql: str, allowed_tables, max_rows: int = 1000) -> Checked:
    allowed = {t.lower() for t in allowed_tables}
    text = (sql or "").strip()
    if not text:
        raise GuardError("empty SQL")

    try:
        statements = [s for s in sqlglot.parse(text, read=DIALECT) if s is not None]
    except SqlglotError as e:
        raise GuardError(f"could not parse SQL: {str(e).splitlines()[0]}") from e
    if len(statements) != 1:
        raise GuardError("exactly one SQL statement is allowed")

    root = statements[0]
    while isinstance(root, exp.Subquery):
        root = root.this
    if not isinstance(root, (exp.Select, SETOP)):
        raise GuardError(f"only SELECT queries are allowed (got {type(root).__name__})")

    # Anything in FROM/JOIN must be a plain table or subquery, never a table function.
    for node in root.find_all(exp.From, exp.Join):
        src = node.this
        if not isinstance(src, (exp.Table, exp.Subquery)):
            raise GuardError("table functions are not allowed")

    ctes = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
    used: set[str] = set()
    for t in root.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            raise GuardError("table functions are not allowed")
        if t.catalog or (t.db and t.db.lower() != "main"):
            raise GuardError(f"schema-qualified table '{t.db}.{t.name}' is not allowed")
        name = t.name.lower()
        if name in ctes and not t.db:
            continue
        if name not in allowed:
            raise GuardError(f"table '{t.name}' is not available. Available tables: {', '.join(sorted(allowed))}")
        used.add(name)

    for fn in root.find_all(exp.Func):
        name = _function_name(fn)
        if name in BLOCKED_FUNCTIONS or name.startswith(BLOCKED_FUNCTION_PREFIXES):
            raise GuardError(f"function '{name}' is not allowed")

    limit = _limit_value(root)
    body = text.rstrip().rstrip(";").rstrip()
    if limit is None:
        final = f"{body}\nLIMIT {max_rows}"
    elif limit == -1 or limit > max_rows:
        final = f"SELECT * FROM (\n{body}\n) AS _capped\nLIMIT {max_rows}"
    else:
        final = body
    return Checked(sql=final, tables=frozenset(used))
