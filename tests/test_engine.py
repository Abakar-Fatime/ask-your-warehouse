import datetime

import pytest

from ayw.engine import Engine, QueryTimeout, WarehouseError


def test_loads_all_tables_with_expected_sizes(engine):
    fp = engine.fingerprint()
    assert fp["fact_live_events"] == 20000 and fp["dim_gift"] == 5 and fp["quarantine"] == 600


def test_hive_partition_column_is_readable_as_a_date(engine):
    dates = [r[0] for r in engine.execute("SELECT DISTINCT event_date FROM fact_live_events ORDER BY 1").rows]
    assert dates == [datetime.date(2026, 11, 1), datetime.date(2026, 11, 2)]


def test_catalog_matches_the_warehouse(engine, catalog):
    assert catalog.diff(engine.describe()) == []


@pytest.mark.parametrize("sql", [
    "DROP TABLE dim_gift", "DELETE FROM quarantine", "UPDATE dim_gift SET coin_value = 0",
    "CREATE TABLE evil AS SELECT 1", "SELECT * FROM read_csv('/etc/passwd')",
    "COPY dim_gift TO '/tmp/leak.csv'", "SET enable_external_access = true",
])
def test_engine_refuses_dangerous_statements_even_without_the_guard(engine, sql):
    before = engine.fingerprint()
    with pytest.raises(Exception):
        engine.execute(sql)
    assert engine.fingerprint() == before


def test_runaway_query_is_cancelled(engine):
    with pytest.raises(QueryTimeout):
        engine.execute("SELECT COUNT(*) FROM range(100000000000)", timeout_s=0.5)
    assert engine.execute("SELECT 1").rows == [(1,)]  # engine still usable afterwards


def test_missing_table_gives_a_clear_error(tmp_path):
    with pytest.raises(WarehouseError, match="not found"):
        Engine.from_warehouse(tmp_path)
