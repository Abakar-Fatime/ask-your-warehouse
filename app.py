"""Streamlit interface for ask-your-warehouse.   streamlit run app.py"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pandas as pd
import streamlit as st

from ayw import demo_data
from ayw.agent import Agent
from ayw.catalog import Catalog
from ayw.engine import Engine
from ayw.evaluate import DemoClient
from ayw.golden import load_golden
from ayw.guard import GuardError, check
from ayw.llm import OllamaClient

ROOT = Path(__file__).resolve().parent
PRESETS = ["m03", "h01", "h06", "m14", "h04", "m09"]  # golden-set cases used as one-click examples
HOSTILE = [
    "DROP TABLE fact_live_events",
    "DELETE FROM quarantine",
    "SELECT * FROM read_csv('/etc/passwd')",
    "COPY fact_live_events TO '/tmp/events.csv'",
    "SELECT * FROM information_schema.tables",
    "SELECT 1; DROP TABLE dim_gift",
    "SET enable_external_access = true",
    "UPDATE dim_gift SET coin_value = 0",
]

st.set_page_config(page_title="Ask Your Warehouse", layout="wide")


@st.cache_resource
def load_engine(path: str) -> Engine:
    p = Path(path)
    if not p.exists():
        demo_data.build(p)
    return Engine.from_warehouse(p)


@st.cache_resource
def load_catalog() -> Catalog:
    return Catalog.load(ROOT / "catalog" / "warehouse.yaml")


@st.cache_data(ttl=5)
def ollama_models(host: str) -> list[str] | None:
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=0.7) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        return None


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Setup")
    warehouse = st.text_input("Warehouse folder", "demo_warehouse", key="warehouse",
                              help="Folder of Parquet tables. Created with synthetic data if missing.")
    host = st.text_input("Ollama address", "http://localhost:11434", key="host")
    installed = ollama_models(host)
    source = st.radio("Model", ["Ollama (local LLM)", "Demo mode (no LLM)"],
                      index=0 if installed else 1, key="source")
    model = None
    if source.startswith("Ollama"):
        if installed:
            model = st.selectbox("Installed model", installed, key="model")
        else:
            st.warning("Ollama is not reachable. Start it with `ollama serve`, or use demo mode.")
    st.divider()
    use_retrieval = st.toggle("Focus the prompt with catalog retrieval", True, key="retrieval")
    use_examples = st.toggle("Include few-shot examples", True, key="examples")
    repairs = st.slider("Self-repair attempts", 0, 3, 2, key="repairs")

engine = load_engine(warehouse)
catalog = load_catalog()
cases = load_golden(ROOT / "eval" / "golden.yaml")
demo = DemoClient(cases)
by_id = {c.id: c for c in cases}

st.title("Ask Your Warehouse")
st.caption("Plain-English questions over a Parquet warehouse. The model writes the SQL; a guard and a "
           "read-only engine make sure it can only read.")

tab_ask, tab_break, tab_eval = st.tabs(["Ask", "Try to break it", "Evaluation"])

# ---------------------------------------------------------------- ask
with tab_ask:
    if source.startswith("Demo"):
        st.info("**Demo mode.** Answers are canned for the example questions below, so you can see the interface "
                "without a model. Choose a local Ollama model in the sidebar to ask anything.")
    st.write("Try an example:")
    cols = st.columns(len(PRESETS))
    for col, cid in zip(cols, PRESETS):
        if col.button(by_id[cid].question, key=f"preset_{cid}", width="stretch"):
            st.session_state["question"] = by_id[cid].question
    question = st.text_input("Your question", key="question",
                             placeholder="e.g. Who are the top 5 streamers by gift revenue?")

    if question:
        if source.startswith("Demo"):
            client = demo
            runnable = demo.knows(question)
            if not runnable:
                st.warning("Demo mode only knows the example questions. Pick a local model in the sidebar to ask your own.")
        else:
            runnable = model is not None
            client = OllamaClient(model, host=host) if model else None
            if not runnable:
                st.warning("No model selected.")
        if runnable:
            agent = Agent(engine, catalog, client, max_repairs=repairs,
                          use_retrieval=use_retrieval, use_examples=use_examples)
            with st.spinner("Thinking..."):
                ans = agent.ask(question)

            left, right = st.columns([3, 2])
            with left:
                if ans.ok:
                    df = pd.DataFrame(ans.rows, columns=ans.columns)
                    st.subheader("Answer")
                    st.dataframe(df, width="stretch", hide_index=True)
                    if (len(df.columns) == 2 and 1 < len(df) <= 40
                            and pd.api.types.is_numeric_dtype(df.iloc[:, 1])
                            and not pd.api.types.is_numeric_dtype(df.iloc[:, 0])):
                        st.bar_chart(df.set_index(df.columns[0]))
                else:
                    st.error(f"No answer: {ans.error}")
                st.subheader("SQL")
                st.code(ans.sql or "(none)", language="sql", wrap_lines=True)
            with right:
                m1, m2, m3 = st.columns(3)
                m1.metric("Attempts", len(ans.attempts))
                m2.metric("Time", f"{ans.latency_s:.1f}s")
                m3.metric("Tokens", ans.prompt_tokens + ans.completion_tokens or "n/a")
                st.subheader("What happened")
                for i, a in enumerate(ans.attempts, 1):
                    label = {"ok": ":green[Ran successfully]", "blocked": ":red[Blocked by the safety guard]",
                             "error": ":orange[SQL error]", "timeout": ":orange[Timed out]"}.get(a.status, a.status)
                    st.markdown(f"**Attempt {i}:** {label}")
                    if a.detail:
                        st.caption(a.detail)
                st.subheader("Schema the model saw")
                st.write(", ".join(f"`{t}`" for t in ans.context_tables))

# ---------------------------------------------------------------- break it
with tab_break:
    st.write("Model-written SQL is never trusted. Try to get something destructive through. "
             "There are three layers: the **guard**, a **read-only engine**, and a **timeout**.")
    choice = st.selectbox("Pick a hostile statement or write your own", HOSTILE, key="hostile")
    sql = st.text_area("SQL", choice, height=90, key="hostile_sql")
    before = engine.fingerprint()
    c1, c2 = st.columns(2)
    if c1.button("Run it through the guard", key="through_guard", type="primary"):
        try:
            checked = check(sql, catalog.table_names())
            res = engine.execute(checked.sql)
            st.success("The guard allowed it: it is a plain SELECT on approved tables.")
            st.dataframe(pd.DataFrame(res.rows, columns=res.columns), hide_index=True)
        except GuardError as e:
            st.error(f"Blocked by the guard: {e}")
        except Exception as e:
            st.warning(f"Allowed by the guard, but failed in the database: {str(e).splitlines()[0]}")
    if c2.button("Bypass the guard (send straight to the engine)", key="bypass_guard"):
        try:
            engine.execute(sql)
            st.success("The engine ran it.")
        except Exception as e:
            st.error(f"Refused by the read-only engine: {str(e).splitlines()[0]}")
    after = engine.fingerprint()
    st.write("Row counts unchanged:", "yes" if before == after else "NO")
    st.json(after, expanded=False)

# ---------------------------------------------------------------- evaluation
with tab_eval:
    files = sorted((ROOT / "results").glob("*.json")) if (ROOT / "results").exists() else []
    if not files:
        st.info("No evaluation results yet. Run `python -m ayw eval --model <ollama-model> --adversarial` "
                "and reload this page.")
    else:
        pick = st.selectbox("Result file", files, format_func=lambda p: p.name, index=len(files) - 1, key="resfile")
        data = json.loads(pick.read_text())
        s = data["summary"]
        a, b, c, d = st.columns(4)
        a.metric("Execution accuracy", f"{s['execution_accuracy_pct']}%")
        b.metric("First attempt", f"{s['first_try_accuracy_pct']}%")
        c.metric("Valid SQL", f"{s['valid_sql_pct']}%")
        d.metric("Latency p50", f"{s['latency_p50_s']}s")
        st.caption(f"Model: {s['model']}   |   {s['scored']} scored cases   |   config: {data['config']}")
        st.bar_chart(pd.Series(s["by_difficulty_pct"], name="accuracy %"))
        rows = pd.DataFrame(data["results"])
        st.subheader("Cases that failed")
        st.dataframe(rows[~rows["correct"]][["id", "difficulty", "question", "predicted_sql", "error"]],
                     hide_index=True, width="stretch")
