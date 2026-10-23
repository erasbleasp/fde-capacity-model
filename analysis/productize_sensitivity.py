"""How sensitive is the Productize result to the reuse settings that are judgment calls?

Compares Productize (12% harvest) against Base (7%) while varying one judgment setting at a
time, then in combination. Any setting that changes month-0 reuse gets k re-fitted so the model
still starts at the measured 9% reuse ratio, so every variant stays consistent with the history.

    .venv/bin/python -m analysis.productize_sensitivity
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from model.engine import run_model
from model.montecarlo import run_mc
from model.params import load_assumptions, point_params

PRODUCTIZE = {"overhead.harvest_share": 0.12}
REUSE_AT_START = 0.09      # measured (v_calibration.reuse_ratio)
REFIT_K = {"assets.reuse_max", "assets.greenfield_reuse_factor"}

# judgment settings: current value first, then the range tested
SETTINGS = {
    "assets.reuse_max": [0.35, 0.20, 0.25, 0.45, 0.60],
    "assets.greenfield_reuse_factor": [0.4, 0.2, 0.6, 0.8, 1.0],
    "demand.greenfield_shift_per_reuse": [0.8, 0.0, 0.4, 1.2, 2.0],
    "assets.yield_at_5pct_harvest": [0.8, 0.5, 1.1, 1.4],
    "assets.monthly_decay": [0.04, 0.02, 0.06, 0.08],
    "overhead.harvest_from_slack": [0.0, 0.25, 0.5, 0.75, 1.0],
}


def fit_k(tree: dict, overrides: dict) -> float:
    """Bisection on k so month-0 reuse ratio equals the measured value (reuse falls as k rises)."""
    lo, hi = 1.0, 2000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        r0 = run_model(point_params(tree, {**overrides, "assets.reuse_half_k": mid}))["reuse_ratio"][0, 0]
        lo, hi = (mid, hi) if r0 > REUSE_AT_START else (lo, mid)
    return (lo + hi) / 2


def with_k(tree: dict, overrides: dict) -> dict:
    if REFIT_K & overrides.keys():
        return {**overrides, "assets.reuse_half_k": fit_k(tree, overrides)}
    return overrides


def compare(tree: dict, overrides: dict) -> dict:
    """Productize minus Base under the same settings (single-value runs)."""
    ov = with_k(tree, overrides)
    b = run_model(point_params(tree, ov))
    p = run_model(point_params(tree, {**ov, **PRODUCTIZE}))
    cum = np.cumsum(p["starts"][0]) - np.cumsum(b["starts"][0])
    ahead = np.nonzero(cum >= 0)[0]
    # breakeven = first month after which Productize has delivered at least as many engagements
    breakeven = next((int(m) + 1 for m in ahead if (cum[m:] >= 0).all()), None)
    y2 = slice(12, 24)
    return dict(
        k=ov.get("assets.reuse_half_k", 60),
        d_starts_24m=cum[-1],
        d_starts_pct=cum[-1] / b["starts"][0].sum(),
        worst_deficit=cum.min(),
        breakeven_month=breakeven,
        d_coverage_y2=(p["coverage"][0, y2] - b["coverage"][0, y2]).mean(),
        d_day90_y2=(p["day90"][0, y2] - b["day90"][0, y2]).mean(),
        d_reuse_m12=p["reuse_ratio"][0, 11] - b["reuse_ratio"][0, 11],
        d_cost_per_eng=(p["cost"][0].sum() / p["starts"][0].sum()) / (b["cost"][0].sum() / b["starts"][0].sum()) - 1,
    )


def one_at_a_time(tree: dict) -> pd.DataFrame:
    rows = []
    for path, values in SETTINGS.items():
        for v in values:
            rows.append(dict(setting=path, value=v, current=(v == values[0]), **compare(tree, {path: v})))
    return pd.DataFrame(rows)


def paired_win_probability(tree: dict, overrides: dict, n: int = 2000) -> dict:
    """Monte Carlo with the same input draws for both runs, so the difference is only the harvest
    lever. P(Productize delivers more engagements over 24 months).
    Process noise is off: random hires/exits/arrivals desynchronize between the two runs (their
    draws depend on state) and add about +/-35 engagements of noise that isn't about harvest."""
    ov = with_k(tree, overrides)
    b, _ = run_mc(tree, n, overrides=ov, process_noise=False)
    p, _ = run_mc(tree, n, overrides={**ov, **PRODUCTIZE}, process_noise=False)
    d = p["starts"].sum(axis=1) - b["starts"].sum(axis=1)
    return dict(p_win=float((d > 0).mean()), d_p10=np.quantile(d, 0.1), d_p50=np.median(d), d_p90=np.quantile(d, 0.9))


def harvest_curve(tree: dict, overrides: dict, levels=(0.03, 0.05, 0.07, 0.09, 0.12, 0.15, 0.20)) -> pd.DataFrame:
    ov = with_k(tree, overrides)
    base = run_model(point_params(tree, ov))["starts"][0].sum()
    rows = []
    for h in levels:
        r = run_model(point_params(tree, {**ov, "overhead.harvest_share": h}))
        rows.append(dict(harvest=h, starts_24m=r["starts"][0].sum(), d_vs_7pct=r["starts"][0].sum() - base,
                         reuse_m24=r["reuse_ratio"][0, -1], day90_y2=r["day90"][0, 12:].mean()))
    return pd.DataFrame(rows)


def main():
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    tree = load_assumptions()
    fmt = {"value": "{:g}", "k": "{:.0f}", "d_starts_24m": "{:+.1f}", "d_starts_pct": "{:+.1%}",
           "worst_deficit": "{:+.1f}", "d_coverage_y2": "{:+.3f}", "d_day90_y2": "{:+.3f}",
           "d_reuse_m12": "{:+.3f}", "d_cost_per_eng": "{:+.1%}"}

    def show(df):
        out = df.copy()
        for c, f in fmt.items():
            if c in out:
                out[c] = out[c].map(lambda v, f=f: f.format(v))
        print(out.to_string(index=False))

    print("Productize (12% harvest) minus Base (7%), single-value runs.")
    print("d_starts_24m = extra engagements delivered over 24 months; breakeven = month after which Productize stays ahead.\n")
    print("== One setting at a time (current value marked) ==")
    oat = one_at_a_time(tree)
    oat["setting"] = np.where(oat.current, oat.setting + " *", oat.setting)
    show(oat.drop(columns="current"))

    print("\n== Swing in extra engagements (lowest to highest value tested) ==")
    sw = oat.groupby(oat.setting.str.rstrip(" *")).d_starts_24m.agg(["min", "max"])
    sw["swing"] = sw["max"] - sw["min"]
    print(sw.sort_values("swing", ascending=False).round(1).to_string())

    print("\n== Two biggest levers together ==")
    top = sw.sort_values("swing", ascending=False).index[:2].tolist()
    rows = []
    for a, b in itertools.product(SETTINGS[top[0]], SETTINGS[top[1]]):
        rows.append(dict(**{top[0]: a, top[1]: b}, d_starts_24m=compare(tree, {top[0]: a, top[1]: b})["d_starts_24m"]))
    grid = pd.DataFrame(rows).pivot(index=top[0], columns=top[1], values="d_starts_24m")
    print(grid.round(1).to_string())

    favorable = {"assets.reuse_max": 0.45, "assets.greenfield_reuse_factor": 0.6,
                 "demand.greenfield_shift_per_reuse": 1.2, "assets.monthly_decay": 0.06,
                 "overhead.harvest_from_slack": 0.5}
    print("\n== Plausibly favorable combination (each setting one step toward Productize) ==")
    print(favorable)
    show(pd.DataFrame([compare(tree, favorable)]))

    print("\n== Monte Carlo, paired: P(Productize delivers more engagements over 24 months) ==")
    for name, ov in [("current settings", {}), ("favorable combination", favorable)]:
        w = paired_win_probability(tree, ov)
        print(f"  {name:22s} P(win) = {w['p_win']:.0%}   extra engagements P10 {w['d_p10']:+.1f} | "
              f"P50 {w['d_p50']:+.1f} | P90 {w['d_p90']:+.1f}")

    print("\n== Harvest level curve (extra engagements over 24 months vs 7%) ==")
    for name, ov in [("current settings", {}), ("favorable combination", favorable)]:
        print(f"-- {name}")
        print(harvest_curve(tree, ov).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
