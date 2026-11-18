"""Semantic catalog + lightweight schema linking.

The catalog is plain YAML. For each question we retrieve only the tables, metric definitions and
join hints that look relevant (BM25 over names and descriptions, no embeddings, no network),
because small local models do much better with a short, focused prompt than with a whole schema.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

_TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset("""a an the of by and or for to in on at as is are was were be been do does did have has had
there their them they it its this that these those with from per each all any what which who whom how many much
show list give me us our we you your tell find get number total""".split())


def _stem(tok: str) -> str:
    """Very light plural/gerund stripping so 'streamers' matches 'streamer' and 'names' matches 'name'."""
    if len(tok) <= 3:
        return tok
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    if tok.endswith(("sses", "xes", "ches", "shes")):
        return tok[:-2]
    if tok.endswith("s") and not tok.endswith(("ss", "us", "is")):
        return tok[:-1]
    if tok.endswith("ing") and len(tok) > 6:
        return tok[:-3]
    return tok


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.avg = (sum(len(d) for d in docs) / len(docs)) if docs else 0.0
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in docs]

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for d, tf in zip(self.docs, self.tf):
            s = 0.0
            for t in set(query):
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / (self.avg or 1)))
            out.append(s)
        return out


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    description: str


@dataclass(frozen=True)
class Table:
    name: str
    description: str
    columns: tuple[Column, ...]


@dataclass(frozen=True)
class Metric:
    name: str
    description: str
    sql: str
    tables: tuple[str, ...]


@dataclass(frozen=True)
class Example:
    question: str
    sql: str


@dataclass
class Context:
    tables: list[Table]
    metrics: list[Metric]
    joins: list[str]


class Catalog:
    def __init__(self, tables: list[Table], metrics: list[Metric], joins: list[str],
                 notes: list[str], examples: list[Example]):
        self.tables = {t.name: t for t in tables}
        self.metrics, self.joins, self.notes, self.examples = metrics, joins, notes, examples
        self._table_index = BM25([tokenize(self._table_doc(t)) for t in tables])
        self._metric_index = BM25([tokenize(f"{m.name} {m.description}") for m in metrics])
        self._table_list = tables

    @staticmethod
    def _table_doc(t: Table) -> str:
        cols = " ".join(f"{c.name} {c.description}" for c in t.columns)
        # A table's own name is the strongest signal of what it holds, so it counts three times.
        return f"{t.name} {t.name} {t.name} {t.description} {cols}"

    @classmethod
    def load(cls, path: str | Path) -> "Catalog":
        raw = yaml.safe_load(Path(path).read_text())
        tables = [Table(n, v["description"], tuple(Column(c, d["type"], d["description"])
                                                   for c, d in v["columns"].items()))
                  for n, v in raw["tables"].items()]
        metrics = [Metric(m["name"], m["description"], m["sql"], tuple(m["tables"]))
                   for m in raw.get("metrics", [])]
        return cls(tables, metrics, raw.get("joins", []), raw.get("notes", []),
                   [Example(e["question"], e["sql"]) for e in raw.get("examples", [])])

    def table_names(self) -> list[str]:
        return list(self.tables)

    def retrieve(self, question: str, k_tables: int = 4, k_metrics: int = 2) -> Context:
        q = tokenize(question)
        t_scores = self._table_index.scores(q)
        ranked = sorted(zip(self._table_list, t_scores), key=lambda p: -p[1])
        chosen = [t.name for t, s in ranked[:k_tables] if s > 0]

        m_scores = self._metric_index.scores(q)
        metrics = [m for m, s in sorted(zip(self.metrics, m_scores), key=lambda p: -p[1])[:k_metrics] if s > 0]
        for m in metrics:
            for t in m.tables:
                if t not in chosen:
                    chosen.append(t)
        if not chosen:
            chosen = self.table_names()
        joins = [j for j in self.joins
                 if all(part.split(".")[0] in chosen for part in j.split("="))]
        return Context([self.tables[n] for n in chosen], metrics, joins)

    def everything(self) -> Context:
        return Context(list(self.tables.values()), list(self.metrics), list(self.joins))

    def diff(self, actual: dict[str, list[tuple[str, str]]]) -> list[str]:
        """Compare the catalog with the real warehouse columns. Empty list means in sync."""
        problems = []
        for name, table in self.tables.items():
            if name not in actual:
                problems.append(f"table '{name}' is in the catalog but not in the warehouse")
                continue
            have = {c for c, _ in actual[name]}
            want = {c.name for c in table.columns}
            for c in sorted(want - have):
                problems.append(f"{name}.{c} is in the catalog but not in the warehouse")
            for c in sorted(have - want):
                problems.append(f"{name}.{c} is in the warehouse but not in the catalog")
        return problems


def render_context(ctx: Context) -> str:
    lines = []
    for t in ctx.tables:
        lines.append(f"TABLE {t.name} -- {t.description}")
        for c in t.columns:
            lines.append(f"  {c.name} {c.type} -- {c.description}")
    if ctx.joins:
        lines.append("JOINS: " + "; ".join(ctx.joins))
    if ctx.metrics:
        lines.append("METRIC DEFINITIONS:")
        for m in ctx.metrics:
            lines.append(f"  {m.name}: {m.description} SQL: {m.sql}")
    return "\n".join(lines)
