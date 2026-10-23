"""Engagement-level Monte Carlo: when will this customer go live, and what does certainty cost?

    days = simulate_engagement(tree, "Greenfield", fdes=2, assets=True)
    summarize(days)               # P50 / P80 / P90 days to production, P(live by day 90)
    staffing_table(tree, "Greenfield")   # 1 / 2 / 3 FDEs, with and without assets

Each sample draws the uncertain parameters (median uncertainty, staffing exponent, blocker and
cancel rates, reuse ceiling) AND the engagement's own luck (lognormal build time, whether a
blocker hits and how long it lasts, whether it is cancelled). Same formula as the portfolio
engine's Day-90 calculation, so the two agree.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import delivery_terms, reuse_level
from .params import TYPES, draw_params, node


def simulate_engagement(tree: dict, eng_type: str, fdes: float | None = None, assets: bool = True,
                        partner_led: bool = False, library: float | None = None, n: int = 20000,
                        seed: int = 11, overrides: dict | None = None) -> np.ndarray:
    """Days from kickoff to production for n simulated engagements; NaN = cancelled."""
    assert eng_type in TYPES, eng_type
    p = draw_params(tree, n, seed, overrides)
    rng = np.random.default_rng(seed + 1)
    t = p.tree
    spec = node(t, f"cycle_time.base_duration_days.{eng_type}")
    fdes = fdes or p.raw("cycle_time.fdes_per_engagement")[eng_type]
    ref = p.raw("cycle_time.ref_fdes")[eng_type]

    _, stretch = delivery_terms(p)
    R = np.zeros(n)
    if assets:
        lib = p("assets.starting_library") if library is None else np.full(n, float(library))
        R = reuse_level(lib, p("assets.reuse_max"), p("assets.reuse_half_k"))
        if eng_type == "Greenfield":
            R = R * p("assets.greenfield_reuse_factor")
    median = (spec["median"] * p("cycle_time.median_uncertainty") * stretch
              * (ref / fdes) ** p("cycle_time.staffing_alpha") * (1 - R))
    if partner_led:
        median = median / p("partners.efficiency")

    days = median * np.exp(spec["sigma"] * rng.standard_normal(n))
    b = node(t, "cycle_time.blocker_delay_weeks")
    blocked = rng.random(n) < p("cycle_time.blocker_prob")
    days = days + blocked * b["median"] * 7 * np.exp(b["sigma"] * rng.standard_normal(n))
    cancelled = rng.random(n) < p("cycle_time.cancel_prob")
    return np.where(cancelled, np.nan, days)


def summarize(days: np.ndarray, deadline: int = 90) -> dict:
    """Date percentiles are over engagements that go live; P(live by deadline) counts cancelled as not live."""
    live = days[~np.isnan(days)]
    return dict(p50_days=np.quantile(live, 0.5), p80_days=np.quantile(live, 0.8), p90_days=np.quantile(live, 0.9),
                p_live_by_deadline=float(np.nan_to_num(days, nan=np.inf).__le__(deadline).mean()),
                p_cancel=float(np.isnan(days).mean()))


def cdf_curve(days: np.ndarray, max_days: int = 240, step: int = 5) -> pd.DataFrame:
    """Share of engagements live by each day (cancelled never go live), for the planner chart."""
    grid = np.arange(0, max_days + step, step)
    d = np.nan_to_num(days, nan=np.inf)
    return pd.DataFrame(dict(day=grid, share_live=[(d <= g).mean() for g in grid]))


def staffing_table(tree: dict, eng_type: str, fdes_options=(1, 2, 3), n: int = 20000, seed: int = 11,
                   overrides: dict | None = None) -> pd.DataFrame:
    """Go-live certainty vs resources: more FDEs finish sooner but use more staffing weeks."""
    rows = []
    for f in fdes_options:
        for assets in (False, True):
            days = simulate_engagement(tree, eng_type, f, assets, n=n, seed=seed, overrides=overrides)
            s = summarize(days)
            rows.append(dict(type=eng_type, fdes=f, assets=assets, **s,
                             staffing_weeks_p50=f * s["p50_days"] / 7))
    return pd.DataFrame(rows)
