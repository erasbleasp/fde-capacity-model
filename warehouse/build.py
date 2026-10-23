"""Generate the made-up history, load it into DuckDB, create views, print the calibration.

    .venv/bin/python warehouse/build.py [--db fde.duckdb]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

from generate import ROOT, generate, load_truth

HERE = Path(__file__).resolve().parent


def build(db_path: Path = ROOT / "fde.duckdb", truth: dict | None = None) -> duckdb.DuckDBPyConnection:
    truth = truth or load_truth()
    tables = generate(truth)
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute((HERE / "schema.sql").read_text())
    for name, df in tables.items():
        con.register("df", df)
        con.execute(f"INSERT INTO {name} BY NAME SELECT * FROM df")
        con.unregister("df")
    con.execute("CREATE OR REPLACE TABLE meta AS "
                "SELECT ?::DATE AS history_start, ?::DATE AS as_of, ?::DOUBLE AS staffing_alpha",
                [truth["start_date"], truth["end_date"], truth["engagement"]["staffing_alpha"]])
    con.execute((HERE / "views.sql").read_text())
    return con


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "fde.duckdb")
    args = ap.parse_args()
    con = build(args.db)
    print(f"Built {args.db}\n")
    for (name,) in con.execute("SELECT table_name FROM duckdb_tables() ORDER BY 1").fetchall():
        print(f"  {name:14s} {con.execute(f'SELECT count(*) FROM {name}').fetchone()[0]:>7,d} rows")
    print("\nCalibration (v_calibration):")
    print(con.execute("SELECT param, round(value, 3) AS value, unit, source FROM v_calibration").df().to_string(index=False))


if __name__ == "__main__":
    main()
