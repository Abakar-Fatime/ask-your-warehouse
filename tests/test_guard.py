import pytest

from ayw.guard import GuardError, check

TABLES = ["fact_live_events", "dim_streamer", "dim_gift", "quarantine"]

GOOD = [
    "SELECT COUNT(*) FROM fact_live_events",
    "WITH t AS (SELECT streamer_id, SUM(gift_value_coins) c FROM fact_live_events GROUP BY 1) "
    "SELECT * FROM t JOIN dim_streamer USING (streamer_id) ORDER BY c DESC",
    "SELECT 1 FROM dim_gift UNION ALL SELECT 2 FROM dim_gift;",
    "(SELECT * FROM dim_gift)",
    "SELECT * FROM dim_gift -- trailing comment",
    "select * from main.dim_gift",
    "SELECT * FROM dim_gift d WHERE EXISTS (SELECT 1 FROM fact_live_events f WHERE f.gift_id = d.gift_id)",
]

BAD = [
    "DROP TABLE dim_gift", "DELETE FROM quarantine", "UPDATE dim_gift SET coin_value = 0",
    "CREATE TABLE x AS SELECT 1", "INSERT INTO dim_gift VALUES ('a','b',1)",
    "SELECT 1; DROP TABLE dim_gift", "/* hi */ dRoP table dim_gift",
    "COPY fact_live_events TO '/tmp/x.csv'", "ATTACH '/tmp/x.db'", "PRAGMA database_list",
    "INSTALL httpfs", "SET enable_external_access=true", "DESCRIBE dim_gift", "VALUES (1)",
    "SELECT * FROM read_csv('/etc/passwd')", "SELECT * FROM read_parquet('x')",
    "SELECT * FROM range(100000000000)", "SELECT * FROM generate_series(1,5)",
    "SELECT * FROM duckdb_settings()", "SELECT * FROM query('select 1')",
    "SELECT * FROM dim_gift d, read_parquet('x') p", "SELECT read_text('/etc/passwd')",
    "SELECT * FROM information_schema.tables", "SELECT * FROM system.main.dim_gift",
    "SELECT * FROM secret_table", "", "   ", "SELEC FROM",
]


@pytest.mark.parametrize("sql", GOOD)
def test_legitimate_queries_pass(sql):
    assert check(sql, TABLES).sql


@pytest.mark.parametrize("sql", BAD)
def test_hostile_or_invalid_queries_are_blocked(sql):
    with pytest.raises(GuardError):
        check(sql, TABLES)


def test_row_cap_is_added_when_missing():
    assert check("SELECT * FROM dim_gift", TABLES, 50).sql.rstrip().endswith("LIMIT 50")


def test_small_limit_is_kept_and_large_limit_is_capped():
    assert check("SELECT * FROM dim_gift LIMIT 5", TABLES, 50).sql == "SELECT * FROM dim_gift LIMIT 5"
    capped = check("SELECT * FROM dim_gift LIMIT 99999", TABLES, 50).sql
    assert "_capped" in capped and capped.rstrip().endswith("LIMIT 50")


def test_trailing_comment_cannot_swallow_the_row_cap():
    assert check("SELECT * FROM dim_gift -- note", TABLES, 7).sql.endswith("\nLIMIT 7")


def test_cte_name_is_not_mistaken_for_a_forbidden_table():
    assert check("WITH secret AS (SELECT 1 AS x) SELECT * FROM secret", TABLES).tables == frozenset()


def test_cte_cannot_hide_a_real_forbidden_table():
    with pytest.raises(GuardError):
        check("WITH ok AS (SELECT * FROM secret_table) SELECT * FROM ok", TABLES)


def test_tables_used_are_reported():
    r = check("SELECT * FROM fact_live_events f JOIN dim_gift g ON f.gift_id = g.gift_id", TABLES)
    assert r.tables == {"fact_live_events", "dim_gift"}
