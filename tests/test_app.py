"""Headless tests of the Streamlit interface (skipped when streamlit is not installed)."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
APP = str(Path(__file__).resolve().parent.parent / "app.py")
from streamlit.testing.v1 import AppTest  # noqa: E402


@pytest.fixture()
def app(warehouse_dir, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("no ollama")))
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["warehouse"] = str(warehouse_dir)
    return at.run()


def test_loads_in_demo_mode_without_errors(app):
    assert not app.exception
    assert app.sidebar.radio[0].value.startswith("Demo mode")
    assert any("Demo mode" in i.value for i in app.info)


def test_preset_question_shows_answer_sql_and_attempts(app):
    app.button(key="preset_m03").click().run()
    assert not app.exception
    assert len(app.dataframe) == 1 and "SELECT" in app.code[0].value
    assert {m.label: m.value for m in app.metric}["Attempts"] == "1"


def test_demo_mode_refuses_unknown_questions_honestly(app):
    app.text_input(key="question").set_value("what is the meaning of life").run()
    assert any("only knows the example questions" in w.value for w in app.warning)
    assert len(app.dataframe) == 0


def test_guard_blocks_hostile_sql_and_data_is_unchanged(app):
    app.text_area(key="hostile_sql").set_value("DROP TABLE fact_live_events").run()
    app.button(key="through_guard").click().run()
    assert any("Blocked by the guard" in e.value for e in app.error)
    assert any("unchanged" in m.value and "yes" in m.value for m in app.markdown)


def test_engine_still_refuses_when_guard_is_bypassed(app):
    app.text_area(key="hostile_sql").set_value("DELETE FROM quarantine").run()
    app.button(key="bypass_guard").click().run()
    assert any("Refused by the read-only engine" in e.value for e in app.error)


def test_harmless_select_is_allowed_through_the_guard(app):
    app.text_area(key="hostile_sql").set_value("SELECT COUNT(*) AS n FROM dim_gift").run()
    app.button(key="through_guard").click().run()
    assert any("guard allowed it" in s.value for s in app.success)


def test_evaluation_tab_explains_how_to_get_results(app):
    assert any("No evaluation results yet" in i.value for i in app.info) or len(app.metric) >= 4
