"""Print a plain-text model report: the single-value plan, Monte Carlo confidence, drivers,
scenarios, and the engagement planner.

    .venv/bin/python -m model.run [--trials 2000] [--scenario Base]
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .engagement import staffing_table
from .engine import run_model
from .montecarlo import band, confidence_curve, default_targets, prob, run_mc, scenario_table, tornado
from .params import load_assumptions, load_scenarios, point_params

QUARTER_ENDS = [2, 5, 8, 11, 14, 17, 20, 23]


def section(title: str):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=None)
    ap.add_argument("--scenario", default="Base")
    args = ap.parse_args()
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.float_format", lambda v: f"{v:,.3f}")

    tree = load_assumptions()
    scenarios = load_scenarios()
    ov = scenarios[args.scenario]["overrides"]
    targets = default_targets(tree)

    section(f"{args.scenario}: single-value plan (every input at its value), quarter-end months")
    r = run_model(point_params(tree, ov))
    cols = dict(requests="requests/mo", demand_weeks="demand wks", effective_capacity_weeks="capacity wks",
                coverage="coverage", starts="starts", declined="declined", wait_months="wait (mo)",
                hc_total="HC", utilization="util", library="assets", reuse_ratio="reuse", day90="day-90",
                hires_needed="hires needed")
    df = pd.DataFrame({v: r[k][0][QUARTER_ENDS] for k, v in cols.items()},
                      index=[str(r.months[i])[:7] for i in QUARTER_ENDS])
    print(df.T.round(2).to_string())

    section(f"{args.scenario}: Monte Carlo")
    res, params = run_mc(tree, args.trials, overrides=ov)
    print(f"{res.n:,} trials\n")
    for t in targets:
        x = t.values(res)
        print(f"  P({t.label}) = {prob(res, t):.0%}   [P10 {np.quantile(x, .1):.2f} | "
              f"P50 {np.median(x):.2f} | P90 {np.quantile(x, .9):.2f}]")
    print("\nCoverage fan (P10 / P50 / P90):")
    print(band(res, "coverage").iloc[QUARTER_ENDS].round(2).T.to_string())
    print("\nHires needed to close the gap (P50 / P80 / P90):")
    h = res.quantiles("hires_needed", (0.5, 0.8, 0.9))[:, QUARTER_ENDS]
    print(pd.DataFrame(h, index=["P50", "P80", "P90"], columns=[str(res.months[i])[:7] for i in QUARTER_ENDS]).round(0).to_string())

    section("Confidence vs resources: P(coverage >= target, months 7-12) by hires per month")
    print(confidence_curve(tree, "supply.hires_per_month", [1, 2, 3, 4, 5, 6], targets[0], overrides=ov).round(2).to_string(index=False))

    section("What drives coverage (months 7-12): swing from each input's P10 to P90")
    tor = tornado(tree, "coverage", 6, 12, overrides=ov)
    print(f"base = {tor.attrs['base']:.2f}")
    print(tor.head(10).round(3).to_string(index=False))

    section("Scenarios (Monte Carlo, target windows as above)")
    st = scenario_table(tree, scenarios, targets, n=args.trials)
    print(st.set_index("scenario").T.round(3).to_string())

    section("Engagement planner: Greenfield go-live by staffing level")
    print(staffing_table(tree, "Greenfield", overrides=ov).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
