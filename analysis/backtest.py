"""Backtest: calibrate on the first 12 months of history only, forecast the last 6, score against actuals.

    .venv/bin/python -m analysis.backtest

The warehouse is snapshotted as of the cutoff (everything dated later is removed or blanked, so the
SQL views see only what was known then). Every `calibrated_from` input in assumptions.yaml is
re-centred on its snapshot SQL value; judgment inputs keep their priors; k is re-fitted to the
snapshot's reuse ratio; decisions that were known (hiring pace, harvest share) are taken as given.
The model then forecasts the next 6 months with 2,000 trials and each measure is scored:
months inside the P10-P90 band, and the percentile of the actual 6-month total in the forecast.

This tests the model's STRUCTURE against a differently built history: the generator is a weekly,
engagement-by-engagement simulation with queues and staffing fragmentation; the model is a monthly
flow with calibrated distributions.
"""
from __future__ import annotations

import copy
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from analysis.productize_sensitivity import fit_k
from model.engine import run_model
from model.montecarlo import run_mc
from model.params import REGIONS, load_assumptions, node, point_params

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "warehouse"))
from build import build  # noqa: E402

CUTOFF = date(2026, 3, 31)
MONTHS = 6

SNAPSHOT_SQL = """
UPDATE meta SET as_of = DATE '{c}';
DELETE FROM fde_requests WHERE requested_date > DATE '{c}';
UPDATE fde_requests SET decision = 'pending', decision_date = NULL, engagement_id = NULL WHERE decision_date > DATE '{c}';
DELETE FROM engagements WHERE signed_date > DATE '{c}';
UPDATE engagements SET kickoff_date = NULL WHERE kickoff_date > DATE '{c}';
UPDATE engagements SET prod_date = NULL WHERE prod_date > DATE '{c}' OR kickoff_date IS NULL;
UPDATE engagements SET closed_date = NULL WHERE closed_date > DATE '{c}' OR kickoff_date IS NULL;
UPDATE engagements SET partner_hours = round(fdes_planned * 40 * 0.85 * (coalesce(closed_date, DATE '{c}') - kickoff_date) / 7, 1)
    WHERE partner_led AND kickoff_date IS NOT NULL;
UPDATE engagements SET partner_hours = NULL WHERE kickoff_date IS NULL;
UPDATE engagements SET status = CASE
    WHEN kickoff_date IS NULL THEN 'queued'
    WHEN closed_date IS NOT NULL AND prod_date IS NULL THEN 'cancelled'
    WHEN closed_date IS NOT NULL THEN 'closed'
    WHEN prod_date IS NOT NULL THEN 'live_handoff'
    ELSE 'in_build' END;
DELETE FROM staffing WHERE start_date > DATE '{c}';
UPDATE staffing SET end_date = NULL WHERE end_date > DATE '{c}';
DELETE FROM time_entries WHERE week_start > DATE '{c}';
DELETE FROM roster WHERE hire_date > DATE '{c}';
UPDATE roster SET term_date = NULL WHERE term_date > DATE '{c}';
DELETE FROM requisitions WHERE opened_date > DATE '{c}';
UPDATE requisitions SET filled_date = NULL, fde_id = NULL WHERE filled_date > DATE '{c}';
DELETE FROM assets WHERE created_date > DATE '{c}';
UPDATE assets SET deprecated_date = NULL WHERE deprecated_date > DATE '{c}';
DELETE FROM asset_usage WHERE engagement_id NOT IN (SELECT engagement_id FROM engagements WHERE kickoff_date IS NOT NULL);
DELETE FROM consumption WHERE month > DATE '{c}';
"""


def snapshot(full_db: Path, tmp: Path, cutoff: date = CUTOFF) -> duckdb.DuckDBPyConnection:
    """Copy of the warehouse with only what was known at the cutoff."""
    snap = tmp / "snapshot.duckdb"
    shutil.copy(full_db, snap)
    con = duckdb.connect(str(snap))
    con.execute(SNAPSHOT_SQL.format(c=cutoff.isoformat()))
    return con


def recenter(spec: dict, new: float):
    """Move a spec's value (and distribution centre) to `new`, keeping its relative width."""
    old = spec["value"]
    spec["value"] = new
    d = spec.get("dist")
    if d == "triangular":
        r = new / spec["mode"] if spec["mode"] else 1.0
        spec.update(low=spec["low"] * r, mode=new, high=spec["high"] * r)
    elif d == "lognormal":
        spec["median"] = new
    elif d == "beta":
        spec["mean"] = min(max(new, 0.01), 0.99)
    return old


def backtest_assumptions(snap: duckdb.DuckDBPyConnection, full: duckdb.DuckDBPyConnection, cutoff: date = CUTOFF,
                         overrides: dict | None = None):
    """Assumptions as they would have been set at the cutoff, plus the decisions actually taken after it."""
    tree = copy.deepcopy(load_assumptions())
    calib = dict(snap.execute("SELECT param, value FROM v_calibration").fetchall())
    moved = []

    def walk(n, path):
        if isinstance(n, dict):
            if "calibrated_from" in n and n.get("value") is not None:
                v = calib.get(n["calibrated_from"])
                if v is not None and np.isfinite(v):
                    v = float(v) * n.get("calibration_scale", 1.0)
                    if path == "supply.open_reqs":
                        v = round(v)
                    old = recenter(n, v)
                    moved.append(dict(input=path, full_history=old, at_cutoff=round(v, 4)))
            for k, c in n.items():
                walk(c, f"{path}.{k}" if path else k)

    walk(tree, "")
    # supply at the cutoff, by region x role
    hc = snap.execute("""SELECT region, role, count(*) FROM roster WHERE term_date IS NULL GROUP BY ALL""").fetchall()
    by = {r: {"FDE": 0, "Senior FDE": 0, "Eng Manager": 0} for r in REGIONS}
    for region, role, n in hc:
        by[region][role] = n
    tree["supply"]["starting_headcount"]["by_region_role"] = by
    tree["supply"]["in_ramp_at_start"]["value"] = int(snap.execute(
        "SELECT count(*) FROM roster WHERE role <> 'Eng Manager' AND term_date IS NULL "
        "AND hire_date > ?::DATE - INTERVAL 3 MONTH", [cutoff]).fetchone()[0])
    # decisions taken after the cutoff, given to the model as known inputs
    tree["supply"]["hires_per_month"]["value"] = float(full.execute(
        "SELECT count(*) / 6.0 FROM requisitions WHERE opened_date > ?::DATE AND opened_date <= ?::DATE + INTERVAL 6 MONTH",
        [cutoff, cutoff]).fetchone()[0])
    tree["overhead"]["harvest_share"]["value"] = 0.07
    tree["horizon"] = {"start": (pd.Timestamp(cutoff) + pd.offsets.MonthBegin(1)).date(), "months": MONTHS}
    for path, v in (overrides or {}).items():             # variants, e.g. a different abandon rate
        spec = node(tree, path)
        recenter(spec, v) if isinstance(spec, dict) and "value" in spec else None
    # k re-fitted so the model starts at the snapshot's reuse ratio
    reuse_at_cutoff = calib.get("reuse_ratio")
    import analysis.productize_sensitivity as ps
    ps.REUSE_AT_START, saved = float(reuse_at_cutoff), ps.REUSE_AT_START
    try:
        k = fit_k(tree, {"assets.reuse_max": tree["assets"]["reuse_max"]["value"]})
    finally:
        ps.REUSE_AT_START = saved
    recenter(tree["assets"]["reuse_half_k"], k)
    moved.append(dict(input="assets.reuse_half_k (re-fitted)", full_history=58, at_cutoff=round(k, 1)))
    return tree, pd.DataFrame(moved)


def actuals(full: duckdb.DuckDBPyConnection, cutoff: date = CUTOFF) -> dict[str, pd.Series]:
    """Monthly actuals for the 6 months after the cutoff."""
    start = pd.Timestamp(cutoff) + pd.offsets.MonthBegin(1)
    months = pd.date_range(start, periods=MONTHS, freq="MS")
    def q(sql):
        df = full.execute(sql, [start.date()]).df()
        df["month"] = pd.to_datetime(df["month"])
        return df.set_index("month").reindex(months)
    starts = q("""SELECT date_trunc('month', kickoff_date)::DATE AS month, count(*) AS v FROM engagements
                  WHERE kickoff_date >= ? GROUP BY 1""").v.fillna(0)
    requests = q("""SELECT date_trunc('month', requested_date)::DATE AS month, count(*) AS v FROM fde_requests
                    WHERE requested_date >= ? GROUP BY 1""").v.fillna(0)
    declined = q("""SELECT date_trunc('month', decision_date)::DATE AS month, count(*) AS v FROM fde_requests
                    WHERE decision = 'declined_capacity' AND decision_date >= ? GROUP BY 1""").v.fillna(0)
    hc = q("""SELECT month, sum(hc_end) AS v FROM v_headcount_monthly WHERE month >= ? GROUP BY 1""").v
    util = q("""SELECT date_trunc('month', week_start)::DATE AS month,
                       sum(hours) FILTER (category = 'deploy') / sum(hours) FILTER (category <> 'pto') AS v
                FROM time_entries t JOIN roster r USING (fde_id)
                WHERE r.role <> 'Eng Manager' AND week_start >= ? GROUP BY 1""").v
    lib = q("""SELECT month, active_assets AS v FROM v_asset_library_monthly WHERE month >= ?""").v
    d90 = q("""SELECT kickoff_month AS month, avg(live_by_d90::INT) AS v, count(*) AS n FROM v_cycle_times
               WHERE kickoff_month >= ? AND d90_mature GROUP BY 1""")
    return dict(requests=requests, starts=starts, declined=declined, hc_total=hc, utilization=util, library=lib,
                day90=d90.v, day90_n=d90.n.fillna(0))


LABELS = {"requests": "Requests", "starts": "Engagements started", "declined": "Declined, team full",
          "hc_total": "Headcount (month end)", "utilization": "FDE utilization", "library": "Asset library",
          "day90": "Day-90 (mature cohorts)"}
TOTALS = {"requests", "starts", "declined"}       # flows: score the 6-month total; others: the month-6 level


def run_backtest(full_db: Path = ROOT / "fde.duckdb", n: int = 2000, overrides: dict | None = None) -> dict:
    if not full_db.exists():
        build(full_db).close()
    full = duckdb.connect(str(full_db), read_only=True)
    with tempfile.TemporaryDirectory() as tmp:
        snap = snapshot(full_db, Path(tmp))
        tree, moved = backtest_assumptions(snap, full, overrides=overrides)
        snap.close()
    mc, _ = run_mc(tree, n=n)
    act = actuals(full)
    full.close()
    rows, monthly = [], []
    for key, label in LABELS.items():
        a = act[key].to_numpy(dtype=float)
        sim = mc[key]                                         # (n, 6)
        q = np.quantile(sim, (0.1, 0.5, 0.9), axis=0)
        ok = ~np.isnan(a)
        inside = ((a >= q[0]) & (a <= q[2]))[ok]
        if key in TOTALS:
            tot_sim, tot_act, how = sim[:, ok].sum(axis=1), a[ok].sum(), "6-month total"
        elif key == "day90":       # pool every mature cohort, weighted by its size
            w = act["day90_n"].to_numpy(dtype=float)[ok]
            tot_sim = (sim[:, ok] * w).sum(axis=1) / w.sum()
            tot_act, how = float((a[ok] * w).sum() / w.sum()), f"pooled, {int(w.sum())} engagements"
        else:
            last = np.nonzero(ok)[0][-1]
            tot_sim, tot_act, how = sim[:, last], a[last], f"month {last + 1} level"
        rows.append(dict(measure=label, scored_on=how, actual=tot_act, p10=np.quantile(tot_sim, 0.1),
                         p50=np.median(tot_sim), p90=np.quantile(tot_sim, 0.9),
                         actual_percentile=float((tot_sim <= tot_act).mean()),
                         months_in_band=f"{int(inside.sum())} of {int(ok.sum())}"))
        for i, m in enumerate(mc.months):
            monthly.append(dict(measure=label, month=pd.Timestamp(m).strftime("%b %Y"), actual=a[i],
                                p10=q[0][i], p50=q[1][i], p90=q[2][i]))
    summary = pd.DataFrame(rows)
    band_hits = sum(int(s.split(" of ")[0]) for s in summary.months_in_band)
    band_total = sum(int(s.split(" of ")[1]) for s in summary.months_in_band)
    return dict(summary=summary, monthly=pd.DataFrame(monthly), moved=moved,
                coverage=band_hits / band_total, cutoff=CUTOFF, months=[pd.Timestamp(m) for m in mc.months])


def main():
    pd.set_option("display.width", 200)
    res = run_backtest()
    print(f"Calibrated on history to {res['cutoff']}; forecast {res['months'][0]:%b %Y}–{res['months'][-1]:%b %Y}\n")
    print("Inputs re-calibrated at the cutoff:")
    print(res["moved"].to_string(index=False))
    print("\nScore (P10–P90 band should catch ~80% of months if the model is well calibrated):")
    print(res["summary"].round(3).to_string(index=False))
    print(f"\nMonths inside the P10–P90 band, all measures: {res['coverage']:.0%}")


if __name__ == "__main__":
    main()
