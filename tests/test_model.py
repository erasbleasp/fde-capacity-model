"""Model engine, Monte Carlo, and engagement simulator checks."""
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from model.engagement import simulate_engagement, staffing_table, summarize
from model.engine import WEEKS_PER_MONTH, run_model
from model.montecarlo import (Target, confidence_curve, default_targets, prob, run_mc, scenario_table,
                              tornado, variance_drivers)
from model.params import (REGIONS, ROLES, TYPES, draw_params, load_assumptions, load_scenarios, point_params,
                          uncertain_specs, zero_spread)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "warehouse"))
from build import build  # noqa: E402


@pytest.fixture(scope="module")
def tree():
    return load_assumptions()


@pytest.fixture(scope="module")
def base(tree):
    return run_model(point_params(tree))


@pytest.fixture(scope="module")
def calibration(tmp_path_factory):
    con = build(tmp_path_factory.mktemp("wh") / "fde.duckdb")
    return dict(con.execute("SELECT param, value FROM v_calibration").fetchall())


# ---------------------------------------------------------------- engine mechanics
def test_shapes_and_finite(tree, base):
    T = tree["horizon"]["months"]
    assert len(base.months) == T
    for name, s in base.series.items():
        assert s.shape[:2] == (1, T), name
        assert np.isfinite(s).all(), name
    assert base["hc_ic_by_region_role"].shape == (1, T, len(REGIONS), len(ROLES))
    assert base["starts_fde_by_type"].shape == (1, T, len(TYPES))


def test_zero_spread_monte_carlo_equals_single_value(tree, base):
    """One engine, two modes: with every input collapsed to its value and no process noise,
    each Monte Carlo trial must reproduce the single-value run exactly."""
    mc = run_model(draw_params(zero_spread(tree), 50, seed=3), process_noise=False)
    for name, s in base.series.items():
        np.testing.assert_allclose(mc[name], np.repeat(s, 50, axis=0), rtol=1e-9, atol=1e-9, err_msg=name)


def test_same_seed_same_output(tree):
    a, _ = run_mc(tree, n=200, seed=5)
    b, _ = run_mc(tree, n=200, seed=5)
    c, _ = run_mc(tree, n=200, seed=6)
    for name in a.series:
        np.testing.assert_array_equal(a[name], b[name])
    assert not np.array_equal(a["coverage"], c["coverage"])


def test_no_hires_no_attrition_keeps_headcount_flat(tree):
    r = run_model(point_params(tree, {"supply.hires_per_month": 0, "supply.open_reqs": 0,
                                      "supply.annual_attrition": 0.0}))
    start = sum(sum(v.values()) for v in tree["supply"]["starting_headcount"]["by_region_role"].values())
    np.testing.assert_allclose(r["hc_total"][0], start)
    # ramping ICs finish ramping, so effective capacity rises then flattens
    eff = r["effective_ic"][0]
    assert eff[3] == pytest.approx(eff[-1]) and eff[0] < eff[3]


def test_hires_land_after_time_to_fill(tree):
    r = run_model(point_params(tree, {"supply.open_reqs": 0, "supply.annual_attrition": 0.0,
                                      "supply.time_to_fill_days": 91.2}))   # 3 months
    ic_hires = np.diff(np.concatenate([[r["hc_ic"][0][0]], r["hc_ic"][0]]))
    assert ic_hires[:3].sum() == pytest.approx(0, abs=1e-9)
    assert ic_hires[4:] == pytest.approx(tree["supply"]["hires_per_month"]["value"])


def test_manager_span_held(base, tree):
    span = tree["supply"]["manager_span"]["value"]
    ratio = base["hc_ic"][0] / base["hc_mgr"][0]
    assert (ratio <= span + 1e-6).all()


def test_flow_identities(base):
    new = base["new_by_type"][0].sum(axis=1)
    served = base["starts"][0]
    declined, backlog = base["declined"][0], base["backlog"][0]
    # everything that arrives is served, declined, or still waiting
    assert new.sum() == pytest.approx(served.sum() + declined.sum() + backlog[-1])
    np.testing.assert_allclose(base["wait_months"][0], backlog / served)          # Little's Law
    np.testing.assert_allclose(base["gap_weeks"][0],
                               base["effective_capacity_weeks"][0] - base["demand_weeks"][0])


def test_partners_never_serve_greenfield(tree):
    r = run_model(point_params(tree, {"partners.weeks_per_month": 500}))
    assert r["starts_partner_by_type"][0][:, TYPES.index("Greenfield")].sum() == 0
    assert r["starts_partner_by_type"][0].sum() > 0


# ---------------------------------------------------------------- calibration: month 0 looks like the history
def test_starting_point_matches_history(base, calibration):
    assert base["day90"][0][0] == pytest.approx(calibration["day90_rate"], abs=0.08)
    assert base["reuse_ratio"][0][0] == pytest.approx(calibration["reuse_ratio"], abs=0.03)
    # warehouse deploy_share is over all heads incl. managers (who don't deploy); model utilization is ICs only
    ic_share = base["hc_ic"][0][0] / base["hc_total"][0][0]
    assert base["utilization"][0][0] == pytest.approx(calibration["deploy_share"] / ic_share, abs=0.05)
    assert base["hc_total"][0][0] == pytest.approx(calibration["hc_as_of"], abs=3)


# ---------------------------------------------------------------- levers move the model the right way
def test_more_hires_more_capacity(tree, base):
    r = run_model(point_params(tree, {"supply.hires_per_month": 4.6}))
    assert (r["fde_capacity_weeks"][0] >= base["fde_capacity_weeks"][0] - 1e-9).all()
    assert r["coverage"][0][-1] > base["coverage"][0][-1]


def test_harvest_is_a_j_curve(tree, base):
    """More harvest time costs delivery hours now (longer engagements) and grows the library."""
    r = run_model(point_params(tree, {"overhead.harvest_share": 0.12}))
    assert r["coverage"][0][0] < base["coverage"][0][0]
    assert r["library"][0][-1] > base["library"][0][-1]
    assert r["reuse_ratio"][0][12] > base["reuse_ratio"][0][12]


def test_reuse_shortens_engagements(tree):
    r = run_model(point_params(tree))
    assert r["median_days_to_prod"][0][-1] < r["median_days_to_prod"][0][0]


# ---------------------------------------------------------------- Monte Carlo
def test_growth_greenfield_correlation(tree):
    p = draw_params(tree, 5000, seed=1)
    rho = stats.spearmanr(p.drawn["demand.monthly_growth"], p.drawn["demand.greenfield_share"]).statistic
    assert rho == pytest.approx(tree["demand"]["greenfield_growth_correlation"]["value"], abs=0.05)


def test_draws_stay_in_bounds(tree):
    p = draw_params(tree, 5000, seed=2)
    for path, spec in uncertain_specs(tree).items():
        x = p.drawn[path]
        if spec["dist"] == "triangular":
            assert spec["low"] - 1e-9 <= x.min() and x.max() <= spec["high"] + 1e-9, path
        if spec["dist"] == "beta":
            assert 0 < x.min() and x.max() < 1, path


def test_quantiles_ordered_and_probs_valid(tree):
    res, params = run_mc(tree, n=500)
    q = res.quantiles("coverage", (0.1, 0.5, 0.9))
    assert (q[0] <= q[1]).all() and (q[1] <= q[2]).all()
    for t in default_targets(tree):
        assert 0 <= prob(res, t) <= 1
    drivers = variance_drivers(res, params, default_targets(tree)[0])
    assert drivers["share"].sum() == pytest.approx(1)


def test_confidence_rises_with_hiring(tree):
    target = Target("coverage", 6, 12, ">=", 0.8)
    cc = confidence_curve(tree, "supply.hires_per_month", [1, 3, 5, 7], target, n=500)
    assert (np.diff(cc.p_target) >= -0.01).all()
    assert cc.p_target.iloc[-1] > cc.p_target.iloc[0]


def test_tornado_sorted_and_complete(tree):
    df = tornado(tree, "coverage", 6, 12)
    assert len(df) == len(uncertain_specs(tree))
    assert (np.diff(df.swing) <= 1e-12).all()


def test_scenarios_run(tree):
    df = scenario_table(tree, load_scenarios(), default_targets(tree), n=200)
    assert set(df.scenario) == set(load_scenarios())
    hh = df.set_index("scenario")
    assert hh.loc["Hire-heavy", "coverage_p50"] > hh.loc["Base", "coverage_p50"]
    assert hh.loc["Productize", "reuse_ratio_p50"] > hh.loc["Base", "reuse_ratio_p50"]


# ---------------------------------------------------------------- engagement simulator
def test_engagement_simulator_matches_engine_day90(tree, base):
    """Same formula two ways: the engine's analytic Day-90 and the simulator's sampled one."""
    flat = zero_spread(tree)
    eng = run_model(point_params(flat))
    for k, typ in enumerate(TYPES):
        days = simulate_engagement(flat, typ, n=200_000, seed=4)
        assert summarize(days)["p_live_by_deadline"] == pytest.approx(eng["day90_by_type"][0][0][k], abs=0.01), typ


def test_more_fdes_sooner_but_more_staffing_weeks(tree):
    df = staffing_table(tree, "Greenfield", (1, 2, 3), n=20000)
    with_assets = df[df.assets].reset_index(drop=True)
    assert (np.diff(with_assets.p80_days) < 0).all()
    assert (np.diff(with_assets.p_live_by_deadline) > 0).all()
    assert (np.diff(with_assets.staffing_weeks_p50) > 0).all()
    no_assets = df[~df.assets].reset_index(drop=True)
    assert (with_assets.p50_days < no_assets.p50_days).all()


# ---------------------------------------------------------------- prioritization lever
def test_full_intake_declines_nothing_by_policy(base):
    assert base["declined_policy"][0].sum() == pytest.approx(0)
    np.testing.assert_allclose(base["fit_demand_weeks"][0], base["demand_weeks"][0])


def test_greenfield_intake_turns_down_its_share(tree):
    r = run_model(point_params(tree, {"demand.intake.Greenfield": 0.8}))
    gf_offered = r["new_by_type"][0][:, 0] / 0.8          # new = offered x intake
    np.testing.assert_allclose(r["declined_policy"][0], gf_offered * 0.2)
    # everything offered is taken on and served, declined (capacity or policy), or still waiting
    assert r["fit_requests"][0].sum() == pytest.approx(
        r["starts"][0].sum() + r["declined"][0].sum() + r["declined_policy"][0].sum() + r["backlog"][0][-1])
    assert (r["demand_weeks"][0] < r["fit_demand_weeks"][0]).all()


def test_lower_greenfield_intake_raises_coverage_of_what_is_taken_on(tree, base):
    r = run_model(point_params(tree, {"demand.intake.Greenfield": 0.8}))
    assert (r["coverage"][0] > base["coverage"][0]).all()
