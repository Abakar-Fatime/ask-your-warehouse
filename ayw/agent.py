"""The text-to-SQL agent: retrieve context -> prompt the model -> guard -> execute -> repair on error."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ayw.catalog import Catalog, render_context
from ayw.engine import Engine, QueryTimeout
from ayw.guard import GuardError, check
from ayw.llm import LLMClient, LLMError, extract_sql

SYSTEM = """You are a careful analytics engineer. Answer the user's question by writing ONE DuckDB SQL SELECT query.
Rules:
- Use only the tables and columns listed under SCHEMA. Never invent columns.
- Write a single read-only SELECT (CTEs allowed). No INSERT, UPDATE, DELETE, DROP, CREATE, COPY, ATTACH or PRAGMA.
- Follow the METRIC DEFINITIONS exactly when the question uses those terms.
- When ranking or limiting, add the id column to ORDER BY so ties are broken deterministically.
- Reply with only the SQL inside a ```sql code block, with no explanation."""


@dataclass
class Attempt:
    sql: str
    status: str          # ok | blocked | error | timeout | no_sql
    detail: str = ""


@dataclass
class Answer:
    question: str
    sql: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    ok: bool = False
    error: str = ""
    attempts: list[Attempt] = field(default_factory=list)
    context_tables: list[str] = field(default_factory=list)
    latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class Agent:
    def __init__(self, engine: Engine, catalog: Catalog, client: LLMClient, *, max_repairs: int = 2,
                 max_rows: int = 1000, timeout_s: float = 10.0, use_retrieval: bool = True,
                 use_examples: bool = True):
        self.engine, self.catalog, self.client = engine, catalog, client
        self.max_repairs, self.max_rows, self.timeout_s = max_repairs, max_rows, timeout_s
        self.use_retrieval, self.use_examples = use_retrieval, use_examples

    def _messages(self, question: str):
        ctx = self.catalog.retrieve(question) if self.use_retrieval else self.catalog.everything()
        parts = ["SCHEMA", render_context(ctx)]
        if self.catalog.notes:
            parts += ["NOTES"] + [f"- {n}" for n in self.catalog.notes]
        if self.use_examples and self.catalog.examples:
            parts.append("EXAMPLES")
            for ex in self.catalog.examples:
                parts.append(f"Question: {ex.question}\n```sql\n{ex.sql}\n```")
        parts.append(f"Question: {question}")
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(parts)}]
        return msgs, [t.name for t in ctx.tables]

    def ask(self, question: str) -> Answer:
        t0 = time.perf_counter()
        ans = Answer(question=question)
        msgs, ans.context_tables = self._messages(question)
        for attempt_no in range(self.max_repairs + 1):
            try:
                resp = self.client.generate(msgs)
            except LLMError as e:
                ans.error = str(e)
                break
            ans.prompt_tokens += resp.prompt_tokens
            ans.completion_tokens += resp.completion_tokens
            sql = extract_sql(resp.text)
            problem = None
            try:
                checked = check(sql, self.catalog.table_names(), self.max_rows)
                result = self.engine.execute(checked.sql, self.timeout_s)
                ans.attempts.append(Attempt(sql, "ok"))
                ans.sql, ans.columns, ans.rows, ans.ok, ans.error = checked.sql, result.columns, result.rows, True, ""
                break
            except GuardError as e:
                problem = f"The query was rejected by the safety check: {e}"
                ans.attempts.append(Attempt(sql, "blocked", str(e)))
            except QueryTimeout as e:
                problem = f"The query was cancelled: {e}. Write a cheaper query."
                ans.attempts.append(Attempt(sql, "timeout", str(e)))
            except Exception as e:  # DuckDB binder/parser/runtime errors
                problem = f"The query failed with this error: {str(e).splitlines()[0]}"
                ans.attempts.append(Attempt(sql, "error", problem))
            ans.sql, ans.error = sql, problem
            msgs = msgs + [{"role": "assistant", "content": resp.text},
                           {"role": "user", "content": f"{problem}\nReturn a corrected single SELECT query in a ```sql block."}]
        ans.latency_s = time.perf_counter() - t0
        return ans
