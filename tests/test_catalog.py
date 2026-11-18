from ayw.catalog import Catalog, tokenize
from ayw.golden import load_golden, tables_in


def test_tokenizer_matches_plurals_and_drops_filler():
    assert tokenize("Show their names") == ["name"]
    assert tokenize("How many streamers by countries") == ["streamer", "country"]


def test_retrieval_finds_the_obvious_table(catalog):
    assert "dim_gift" in {t.name for t in catalog.retrieve("what is the price of each gift").tables}
    assert "quarantine" in {t.name for t in catalog.retrieve("most common rejection reason").tables}
    assert "agg_streamer_minute" in {t.name for t in catalog.retrieve("busiest minute window").tables}


def test_metric_definitions_are_attached_when_relevant(catalog):
    assert "gift revenue" in {m.name for m in catalog.retrieve("top streamers by gift revenue").metrics}


def test_join_hints_only_for_selected_tables(catalog):
    ctx = catalog.retrieve("total gift revenue by streamer name")
    names = {t.name for t in ctx.tables}
    assert all(part.split(".")[0] in names for j in ctx.joins for part in j.split("="))


def test_unrelated_question_falls_back_to_the_whole_schema(catalog):
    assert len(catalog.retrieve("zzz qqq").tables) == len(catalog.tables)


def test_table_recall_on_the_golden_set(catalog):
    cases = load_golden("eval/golden.yaml")
    hits = sum(tables_in(c.sql) <= {t.name for t in catalog.retrieve(c.question).tables} for c in cases)
    assert hits / len(cases) >= 0.95


def test_diff_detects_drift(catalog):
    actual = {"fact_live_events": [("event_id", "VARCHAR"), ("brand_new_col", "INT")]}
    problems = catalog.diff(actual)
    assert any("brand_new_col" in p and "not in the catalog" in p for p in problems)
    assert any("event_type" in p and "not in the warehouse" in p for p in problems)
    assert any("dim_gift" in p for p in problems)
