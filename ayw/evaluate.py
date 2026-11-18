"""Evaluation harness: execution accuracy on a golden set, plus an adversarial safety run."""
from __future__ import annotations

import json
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import yaml

from ayw.agent import Agent
from ayw.golden import Case
from ayw.llm import LLMResponse


def _norm_value(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float, Decimal)):
        return round(float(v), 6)
    return str(v)


def normalize(rows, ordered: bool):
    out = [tuple(_norm_value(v) for v in r) for r in rows]
    if not ordered:
        out.sort(key=lambda r: tuple((x is None, str(x)) for x in r))
    return out


def results_match(expected, got, ordered: bool) -> bool:
    return normalize(expected, ordered) == normalize(got, ordered)


@dataclass
class CaseResult:
    id: str
    difficulty: str
    question: str
    predicted_sql: str
    correct: bool
    executed: bool
    attempts: int
    blocked_attempts: int
    first_try_correct: bool
    uninformative: bool
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    context_tables: list[str]
    error: str = ""


@dataclass
class Report:
    model: str
    config: dict
    results: list[CaseResult] = field(default_factory=list)
    started: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def summary(self) -> dict:
        scored = [r for r in self.results if not r.uninformative]
        def pct(xs):
            return round(100 * sum(xs) / len(xs), 1) if xs else None
        by_diff = {d: pct([r.correct for r in scored if r.difficulty == d])
                   for d in ("easy", "medium", "hard") if any(r.difficulty == d for r in scored)}
        lat = sorted(r.latency_s for r in self.results)
        def q(p):
            return round(lat[min(len(lat) - 1, int(p * len(lat)))], 2) if lat else None
        return {
            "model": self.model, "cases": len(self.results), "scored": len(scored),
            "uninformative_excluded": len(self.results) - len(scored),
            "execution_accuracy_pct": pct([r.correct for r in scored]),
            "first_try_accuracy_pct": pct([r.first_try_correct for r in scored]),
            "valid_sql_pct": pct([r.executed for r in self.results]),
            "by_difficulty_pct": by_diff,
            "mean_attempts": round(statistics.mean(r.attempts for r in self.results), 2) if self.results else None,
            "blocked_attempts": sum(r.blocked_attempts for r in self.results),
            "latency_p50_s": q(0.5), "latency_p95_s": q(0.95),
            "prompt_tokens": sum(r.prompt_tokens for r in self.results),
            "completion_tokens": sum(r.completion_tokens for r in self.results),
        }

    def to_markdown(self) -> str:
        s = self.summary()
        lines = [f"# Evaluation: {self.model}", "",
                 f"Run {self.started}. Config: `{json.dumps(self.config)}`", "",
                 "| Metric | Value |", "|---|---|",
                 f"| Execution accuracy | {s['execution_accuracy_pct']}% ({s['scored']} scored cases) |",
                 f"| Accuracy on first attempt (no repair) | {s['first_try_accuracy_pct']}% |",
                 f"| Valid SQL (executed without error) | {s['valid_sql_pct']}% |"]
        for d, v in s["by_difficulty_pct"].items():
            lines.append(f"| Execution accuracy, {d} | {v}% |")
        lines += [f"| Mean attempts per question | {s['mean_attempts']} |",
                  f"| Attempts blocked by the safety guard | {s['blocked_attempts']} |",
                  f"| Latency p50 / p95 | {s['latency_p50_s']}s / {s['latency_p95_s']}s |",
                  f"| Tokens (prompt / completion) | {s['prompt_tokens']} / {s['completion_tokens']} |"]
        if s["uninformative_excluded"]:
            lines.append(f"| Excluded (reference result empty) | {s['uninformative_excluded']} |")
        wrong = [r for r in self.results if not r.correct and not r.uninformative]
        if wrong:
            lines += ["", "## Failures", "", "| Case | Question | Why |", "|---|---|---|"]
            for r in wrong:
                why = r.error or ("wrong result" if r.executed else "no valid query")
                lines.append(f"| {r.id} | {r.question} | {why[:90]} |")
        return "\n".join(lines) + "\n"

    def save(self, out_dir: str | Path) -> tuple[Path, Path]:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", self.model)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        j, m = out / f"{slug}_{stamp}.json", out / f"{slug}_{stamp}.md"
        j.write_text(json.dumps({"summary": self.summary(), "config": self.config,
                                 "results": [asdict(r) for r in self.results]}, indent=2, default=str))
        m.write_text(self.to_markdown())
        return j, m


def run_eval(agent: Agent, cases: list[Case], progress=None) -> Report:
    report = Report(model=agent.client.name,
                    config={"retrieval": agent.use_retrieval, "examples": agent.use_examples,
                            "max_repairs": agent.max_repairs})
    for i, case in enumerate(cases, 1):
        expected = agent.engine.execute(case.sql, agent.timeout_s * 3)
        ans = agent.ask(case.question)
        correct = ans.ok and results_match(expected.rows, ans.rows, case.ordered)
        report.results.append(CaseResult(
            id=case.id, difficulty=case.difficulty, question=case.question, predicted_sql=ans.sql,
            correct=correct, executed=ans.ok, attempts=len(ans.attempts),
            blocked_attempts=sum(a.status == "blocked" for a in ans.attempts),
            first_try_correct=correct and len(ans.attempts) == 1,
            uninformative=len(expected.rows) == 0, latency_s=round(ans.latency_s, 3),
            prompt_tokens=ans.prompt_tokens, completion_tokens=ans.completion_tokens,
            context_tables=ans.context_tables, error=ans.error))
        if progress:
            progress(i, len(cases), case, correct)
    return report


@dataclass
class SafetyReport:
    prompts: int
    answered: int
    refused_or_blocked: int
    blocked_attempts: int
    warehouse_unchanged: bool

    def to_markdown(self) -> str:
        return ("## Adversarial run\n\n| Metric | Value |\n|---|---|\n"
                f"| Hostile prompts | {self.prompts} |\n"
                f"| Ended with a harmless SELECT answer | {self.answered} |\n"
                f"| Ended refused or blocked | {self.refused_or_blocked} |\n"
                f"| Hostile queries stopped by the guard | {self.blocked_attempts} |\n"
                f"| Warehouse unchanged afterwards | {'yes' if self.warehouse_unchanged else 'NO'} |\n")


def run_adversarial(agent: Agent, prompts: list[str]) -> SafetyReport:
    before = agent.engine.fingerprint()
    answered = blocked = 0
    for p in prompts:
        ans = agent.ask(p)
        answered += ans.ok
        blocked += sum(a.status == "blocked" for a in ans.attempts)
    return SafetyReport(len(prompts), answered, len(prompts) - answered, blocked,
                        agent.engine.fingerprint() == before)


def load_adversarial(path: str | Path) -> list[str]:
    return list(yaml.safe_load(Path(path).read_text())["prompts"])


class OracleClient:
    """Answers every golden question with its reference SQL. Validates the harness: must score 100%."""
    def __init__(self, cases: list[Case]):
        self.by_question = {c.question: c.sql for c in cases}
        self.name = "oracle (reference SQL)"

    def generate(self, messages: list[dict]) -> LLMResponse:
        last = messages[0 if len(messages) == 1 else 1]["content"]
        q = last.rsplit("Question: ", 1)[-1].strip()
        return LLMResponse(f"```sql\n{self.by_question.get(q, 'SELECT 1')}\n```")
