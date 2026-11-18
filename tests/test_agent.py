import pytest

from ayw.agent import Agent
from ayw.golden import load_golden
from ayw.llm import FunctionClient, LLMError, ScriptedClient


def _agent(engine, catalog, responses, **kw):
    return Agent(engine, catalog, ScriptedClient(responses), **kw)


def test_first_try_success(engine, catalog):
    ans = _agent(engine, catalog, ["```sql\nSELECT COUNT(*) FROM fact_live_events\n```"]).ask("How many events?")
    assert ans.ok and ans.rows == [(20000,)] and len(ans.attempts) == 1 and ans.attempts[0].status == "ok"


def test_model_repairs_after_a_sql_error_and_sees_the_error(engine, catalog):
    client = ScriptedClient(["SELECT COUNT(*) FROM fact_live_events WHERE no_such_col = 1",
                             "SELECT COUNT(*) FROM fact_live_events"])
    ans = Agent(engine, catalog, client).ask("How many events?")
    assert ans.ok and [a.status for a in ans.attempts] == ["error", "ok"]
    assert "no_such_col" in client.calls[1][-1]["content"] or "Binder" in client.calls[1][-1]["content"]
    assert client.calls[1][-2]["role"] == "assistant"  # earlier attempt is replayed to the model


def test_guard_block_is_fed_back_and_can_be_repaired(engine, catalog):
    ans = _agent(engine, catalog, ["DROP TABLE dim_gift", "SELECT COUNT(*) FROM dim_gift"]).ask("count gifts")
    assert ans.ok and [a.status for a in ans.attempts] == ["blocked", "ok"] and ans.rows == [(5,)]


def test_gives_up_after_max_repairs_and_returns_no_data(engine, catalog):
    ans = _agent(engine, catalog, ["DROP TABLE dim_gift"], max_repairs=2).ask("delete everything")
    assert not ans.ok and ans.rows == [] and len(ans.attempts) == 3 and "safety check" in ans.error


def test_hostile_model_output_never_changes_the_warehouse(engine, catalog):
    before = engine.fingerprint()
    for sql in ["DELETE FROM fact_live_events", "DROP TABLE quarantine", "SELECT * FROM read_csv('/etc/passwd')",
                "UPDATE dim_gift SET coin_value = 0", "COPY dim_gift TO '/tmp/x.csv'"]:
        assert not _agent(engine, catalog, [sql], max_repairs=0).ask("x").ok
    assert engine.fingerprint() == before


def test_llm_failure_is_reported_not_raised(engine, catalog):
    def boom(_):
        raise LLMError("cannot reach Ollama")
    ans = Agent(engine, catalog, FunctionClient(boom)).ask("anything")
    assert not ans.ok and "cannot reach Ollama" in ans.error


def test_row_cap_applies(engine, catalog):
    ans = _agent(engine, catalog, ["SELECT event_id FROM fact_live_events"], max_rows=25).ask("all ids")
    assert ans.ok and len(ans.rows) == 25


def test_prompt_is_focused_with_retrieval_and_complete_without(engine, catalog):
    on = ScriptedClient(["SELECT 1"]); off = ScriptedClient(["SELECT 1"])
    Agent(engine, catalog, on).ask("what is the price of each gift")
    Agent(engine, catalog, off, use_retrieval=False).ask("what is the price of each gift")
    p_on, p_off = on.calls[0][1]["content"], off.calls[0][1]["content"]
    assert "TABLE dim_gift" in p_on and "TABLE dim_device" not in p_on
    assert all(f"TABLE {t}" in p_off for t in catalog.table_names())


def test_examples_can_be_switched_off(engine, catalog):
    c = ScriptedClient(["SELECT 1"])
    Agent(engine, catalog, c, use_examples=False).ask("x")
    assert "EXAMPLES" not in c.calls[0][1]["content"]


def test_few_shot_examples_do_not_leak_into_the_golden_set(catalog):
    golden_q = {c.question.strip().lower() for c in load_golden("eval/golden.yaml")}
    golden_sql = {" ".join(c.sql.lower().split()) for c in load_golden("eval/golden.yaml")}
    for ex in catalog.examples:
        assert ex.question.strip().lower() not in golden_q
        assert " ".join(ex.sql.lower().split()) not in golden_sql
