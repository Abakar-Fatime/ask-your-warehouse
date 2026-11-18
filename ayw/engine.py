"""DuckDB engine over a Parquet warehouse.

Defence in depth: tables are copied into a temporary DuckDB file, which is then re-opened
READ-ONLY with external access disabled and the configuration locked. Even if a statement
slipped past the guard it could not write, read files, or load extensions. A watchdog timer
interrupts queries that run too long.
"""
from __future__ import annotations

import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import duckdb

TABLES = ["fact_live_events", "agg_streamer_minute", "quarantine",
          "dim_streamer", "dim_gift", "dim_country", "dim_device"]


class QueryTimeout(Exception):
    pass


class WarehouseError(Exception):
    pass


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]


def _parquet_source(root: Path, table: str) -> str:
    d, f = root / table, root / f"{table}.parquet"
    if d.is_dir():
        files = list(d.rglob("*.parquet"))
        if not files:
            raise WarehouseError(f"no .parquet files under {d}")
        return str(d / "**" / "*.parquet")
    if f.is_file():
        return str(f)
    raise WarehouseError(f"table '{table}' not found in {root} (expected a folder or {table}.parquet)")


class Engine:
    def __init__(self, con: duckdb.DuckDBPyConnection, tmpdir: str, tables: list[str]):
        self.con, self._tmpdir, self.table_names = con, tmpdir, list(tables)

    @classmethod
    def from_warehouse(cls, root: str | Path, tables: list[str] | None = None) -> "Engine":
        root = Path(root)
        tables = tables or TABLES
        tmp = tempfile.mkdtemp(prefix="ayw_")
        db = str(Path(tmp) / "warehouse.duckdb")
        try:
            con = duckdb.connect(db)
            for t in tables:
                src = _parquet_source(root, t).replace("'", "''")
                con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_parquet('{src}', "
                            f"hive_partitioning=true, union_by_name=true)")
            con.close()
            ro = duckdb.connect(db, read_only=True,
                                config={"enable_external_access": False, "lock_configuration": True})
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return cls(ro, tmp, tables)

    def describe(self) -> dict[str, list[tuple[str, str]]]:
        out = {}
        for t in self.table_names:
            rows = self.con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position", [t]).fetchall()
            out[t] = [(c, d) for c, d in rows]
        return out

    def fingerprint(self) -> dict[str, int]:
        return {t: self.con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in self.table_names}

    def execute(self, sql: str, timeout_s: float = 10.0) -> QueryResult:
        cur = self.con.cursor()
        timer = threading.Timer(timeout_s, cur.interrupt)
        timer.start()
        try:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            return QueryResult(cols, cur.fetchall())
        except duckdb.InterruptException as e:
            raise QueryTimeout(f"query exceeded {timeout_s:g}s and was cancelled") from e
        finally:
            timer.cancel()

    def close(self) -> None:
        try:
            self.con.close()
        finally:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
