"""Loading and sanity-checking the golden evaluation set."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import sqlglot
import yaml
from sqlglot import exp


@dataclass(frozen=True)
class Case:
    id: str
    difficulty: str
    question: str
    sql: str
    ordered: bool = False


def load_golden(path: str | Path) -> list[Case]:
    raw = yaml.safe_load(Path(path).read_text())["cases"]
    return [Case(c["id"], c["difficulty"], c["question"], c["sql"], bool(c.get("ordered", False))) for c in raw]


def tables_in(sql: str) -> set[str]:
    tree = sqlglot.parse_one(sql, read="duckdb")
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    return {t.name.lower() for t in tree.find_all(exp.Table) if t.name.lower() not in ctes}
