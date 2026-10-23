"""Warehouse checks: data integrity, metric definitions, and calibration views recovering the
parameters in config/synthetic_truth.yaml. Tolerances reflect sample size: ~100 engagements and
~40 FDEs make attrition and duration estimates noisy, which is exactly why the model draws them
from distributions."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "warehouse"))
from build import build  # noqa: E402
from generate import generate, load_truth  # noqa: E402


@pytest.fixture(scope="module")
def truth():
    return load_truth()


@pytest.fixture(scope="module")
def con(tmp_path_factory, truth):
    return build(tmp_path_factory.mktemp("wh") / "fde.duckdb", truth)


def one(con, sql):
    return con.execute(sql).fetchone()[0]


def calib(con, param):
    return one(con, f"SELECT value FROM v_calibration WHERE param = '{param}'")


# ---------------------------------------------------------------- integrity
def test_foreign_keys(con):
    assert one(con, "SELECT count(*) FROM engagements e ANTI JOIN fde_requests r USING (request_id)") == 0
    assert one(con, "SELECT count(*) FROM staffing s ANTI JOIN roster r USING (fde_id)") == 0
    assert one(con, "SELECT count(*) FROM asset_usage u ANTI JOIN assets a USING (asset_id)") == 0
    assert one(con, """SELECT count(*) FROM time_entries t ANTI JOIN engagements e USING (engagement_id)
                       WHERE t.engagement_id IS NOT NULL""") == 0
    assert one(con, "SELECT count(*) FROM fde_requests WHERE decision = 'accepted' AND engagement_id IS NULL") == 0


def test_date_order(con):
    assert one(con, "SELECT count(*) FROM engagements WHERE kickoff_date < signed_date") == 0
    assert one(con, "SELECT count(*) FROM engagements WHERE prod_date < kickoff_date") == 0
    assert one(con, "SELECT count(*) FROM engagements WHERE closed_date < coalesce(prod_date, kickoff_date)") == 0
    assert one(con, "SELECT max(closed_date) FROM engagements") <= one(con, "SELECT as_of FROM meta")
    assert one(con, "SELECT count(*) FROM fde_requests WHERE decision_date < requested_date") == 0


def test_status_matches_dates(con):
    assert one(con, "SELECT count(*) FROM engagements WHERE status = 'queued' AND kickoff_date IS NOT NULL") == 0
    assert one(con, "SELECT count(*) FROM engagements WHERE status = 'cancelled' AND prod_date IS NOT NULL") == 0
    assert one(con, "SELECT count(*) FROM engagements WHERE status = 'closed' AND prod_date IS NULL") == 0


def test_every_fde_week_is_40_hours(con):
    bad = one(con, """SELECT count(*) FROM (SELECT fde_id, week_start, sum(hours) h FROM time_entries GROUP BY ALL)
                      WHERE abs(h - 40) > 0.5""")
    assert bad == 0


def test_no_fde_over_allocated(con):
    over = one(con, """
        WITH weeks AS (SELECT DISTINCT week_start FROM time_entries)
        SELECT count(*) FROM (
            SELECT w.week_start, s.fde_id, sum(s.allocation) a
            FROM weeks w JOIN staffing s
              ON s.start_date <= w.week_start AND coalesce(s.end_date, DATE '9999-01-01') > w.week_start
            GROUP BY ALL) WHERE a > 1.0001""")
    assert over == 0


def test_deterministic(truth):
    a, b = generate(truth), generate(truth)
    assert {k: len(v) for k, v in a.items()} == {k: len(v) for k, v in b.items()}
    assert a["engagements"].equals(b["engagements"])


# ---------------------------------------------------------------- metric definitions
def test_day90_keeps_cancelled_in_denominator(con):
    manual = one(con, """SELECT count(*) FILTER (prod_date - kickoff_date <= 90) / count(*)
                         FROM engagements, meta
                         WHERE kickoff_date >= meta.history_start AND kickoff_date + 90 <= meta.as_of""")
    assert calib(con, "day90_rate") == pytest.approx(manual)
    assert one(con, "SELECT sum(cancelled) FROM v_day90_cohorts WHERE mature") > 0


def test_reuse_ratio_formula(con):
    manual = one(con, """SELECT sum(r.hours_saved) / sum(r.delivery_hours + r.hours_saved)
                         FROM v_engagement_reuse r JOIN engagements e USING (engagement_id), meta
                         WHERE e.status = 'closed' AND r.reuse_ratio IS NOT NULL
                           AND e.closed_date > meta.as_of - 183""")
    assert calib(con, "reuse_ratio") == pytest.approx(manual)


def test_monthly_views_start_at_history_start(con):
    start = one(con, "SELECT history_start FROM meta")
    for v in ["v_demand_summary", "v_months", "v_reuse_monthly", "v_asset_library_monthly"]:
        assert one(con, f"SELECT min(month) FROM {v}") == start, v
    assert one(con, "SELECT min(cohort_month) FROM v_day90_summary") >= start


# ---------------------------------------------------------------- calibration recovers the truth
def test_ramp_recovered(con, truth):
    for i, r in enumerate(truth["roster"]["ramp"][:4], start=1):
        assert calib(con, f"ramp_m{i}") == pytest.approx(r, abs=0.03)


def test_overhead_recovered(con, truth):
    t = truth["time"]
    # lognormal(0, 0.2) noise on each share has mean exp(0.02) ~ 1.02
    assert calib(con, "presales_share") == pytest.approx(t["presales_share"], abs=0.015)
    assert calib(con, "harvest_share") == pytest.approx(t["harvest_share_after"], abs=0.015)
    assert calib(con, "pto_share") == pytest.approx(0.07, abs=0.03)


def test_durations_recovered(con, truth):
    base = truth["engagement"]["base_duration_weeks"]
    assert calib(con, "median_days_greenfield_base") == pytest.approx(base["Greenfield"] * 7, rel=0.20)
    assert calib(con, "median_days_pattern_based_base") == pytest.approx(base["Pattern-based"] * 7, rel=0.35)


def test_rates_recovered(con, truth):
    assert calib(con, "decline_fit_rate") == pytest.approx(truth["demand"]["decline_fit_prob"], abs=0.07)
    assert calib(con, "blocker_rate") == pytest.approx(truth["engagement"]["blocker_prob"], abs=0.10)
    assert calib(con, "cancel_rate") == pytest.approx(truth["engagement"]["cancel_prob"], abs=0.06)
    assert calib(con, "asset_monthly_decay") == pytest.approx(truth["assets"]["monthly_decay"], abs=0.015)
    # small team: exits / avg HC over 18 months is noisy around the continuous rate -ln(0.85) ~ 0.16
    assert 0.08 <= calib(con, "annual_attrition") <= 0.30
    assert 0.02 <= calib(con, "monthly_demand_growth") <= 0.12


def test_time_to_fill_recovered(con, truth):
    lo, mode, hi = (truth["roster"]["time_to_fill_days"][k] for k in ("low", "mode", "high"))
    tri_median = hi - ((hi - lo) * (hi - mode) / 2) ** 0.5
    assert calib(con, "time_to_fill_p50") == pytest.approx(tri_median, abs=10)


# ---------------------------------------------------------------- the story the demo tells
def test_flywheel_visible_in_history(con):
    """Harvest push in 2026 grows the library and lifts reuse; capacity declines show unmet demand."""
    lib = con.execute("SELECT active_assets FROM v_asset_library_monthly ORDER BY month").fetchall()
    assert lib[-1][0] > lib[0][0]
    early = one(con, """SELECT sum(hours_saved) / sum(delivery_hours + hours_saved) FROM v_cycle_times
                        WHERE status = 'closed' AND reuse_ratio IS NOT NULL AND closed_date < DATE '2026-01-01'""")
    assert calib(con, "reuse_ratio") > early
    assert calib(con, "decline_capacity_rate") > 0.15
