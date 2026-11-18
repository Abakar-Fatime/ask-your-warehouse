import datetime
from decimal import Decimal

import pytest

from ayw.agent import Agent
from ayw.evaluate import (OracleClient, load_adversarial, results_match, run_adversarial, run_eval)
from ayw.golden import load_golden
from ayw.llm import FunctionClient, ScriptedClient

CASES = load_golden("eval/golden.yaml")


def test_golden_set_shape():
    assert len(CASES) == 40 and len({c.id for c in CASES}) == 40
    assert {c.difficulty for c in CASES} == {"easy", "medium", "hard"}


def test_every_reference_query_runs_and_returns_rows(engine):
    for c in CASES:
        assert engine.execute(c.sql).rows, f"{c.id} returns nothing on the demo data"


def test_oracle_scores_100_percent(engine, catalog):
    rep = run_eval(Agent(engine, catalog, OracleClient(CASES)), CASES)
    s = rep.summary()
    assert s["execution_accuracy_pct"] == 100.0 and s["first_try_accuracy_pct"] == 100.0 and s["uninformative_excluded"] == 0


def test_constant_wrong_answer_scores_near_zero(engine, catalog):
    """Negative control: a model that answers every question the same way must not pass."""
    rep = run_eval(Agent(engine, catalog, ScriptedClient(["SELECT COUNT(*) FROM fact_live_events"])), CASES)
    assert rep.summary()["execution_accuracy_pct"] <= 5.0


def test_model_that_always_writes_invalid_sql_scores_zero(engine, catalog):
    rep = run_eval(Agent(engine, catalog, ScriptedClient(["SELECT nope FROM nowhere"]), max_repairs=1), CASES[:5])
    s = rep.summary()
    assert s["execution_accuracy_pct"] == 0.0 and s["valid_sql_pct"] == 0.0 and s["mean_attempts"] == 2


def test_partial_model_gets_partial_credit(engine, catalog):
    by_q = {c.question: c.sql for c in CASES}
    def half(msgs):
        q = msgs[1]["content"].rsplit("Question: ", 1)[-1].strip()
        return by_q[q] if q in {c.question for c in CASES[:20]} else "SELECT 1"
    s = run_eval(Agent(engine, catalog, FunctionClient(half)), CASES).summary()
    assert 45 <= s["execution_accuracy_pct"] <= 55


def test_repair_is_counted_separately_from_first_try(engine, catalog):
    case = CASES[0]
    client = ScriptedClient(["SELECT nope", case.sql])
    rep = run_eval(Agent(engine, catalog, client), [case])
    r = rep.results[0]
    assert r.correct and not r.first_try_correct and r.attempts == 2


@pytest.mark.parametrize("exp,got,ordered,same", [
    ([(1, "a"), (2, "b")], [(2, "b"), (1, "a")], False, True),
    ([(1, "a"), (2, "b")], [(2, "b"), (1, "a")], True, False),
    ([(5,)], [(5.0,)], False, True),
    ([(Decimal("2.50"),)], [(2.5,)], False, True),
    ([(1 / 3,)], [(0.3333333,)], False, True),
    ([(1 / 3,)], [(0.34,)], False, False),
    ([(datetime.date(2026, 1, 1),)], [("2026-01-01",)], False, True),
    ([(1,), (2,)], [(1,)], False, False),
    ([(None,)], [(0,)], False, False),
])
def test_result_comparison(exp, got, ordered, same):
    assert results_match(exp, got, ordered) is same


def test_adversarial_run_with_a_compliant_model_still_leaves_warehouse_intact(engine, catalog):
    evil = ["DROP TABLE fact_live_events", "DELETE FROM quarantine", "SELECT * FROM read_csv('/etc/passwd')"]
    rep = run_adversarial(Agent(engine, catalog, ScriptedClient(evil), max_repairs=1), load_adversarial("eval/adversarial.yaml"))
    assert rep.prompts == 10 and rep.warehouse_unchanged and rep.blocked_attempts >= 10
    assert rep.answered + rep.refused_or_blocked == rep.prompts


def test_report_files_are_written(engine, catalog, tmp_path):
    rep = run_eval(Agent(engine, catalog, OracleClient(CASES)), CASES[:3])
    j, m = rep.save(tmp_path)
    assert j.exists() and m.exists() and "Execution accuracy" in m.read_text()
