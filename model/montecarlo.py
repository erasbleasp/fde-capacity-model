"""Portfolio-level Monte Carlo: how certain is the plan at a given level of resourcing?

    res, params = run_mc(tree)                                  # 2,000 trials, seeded
    prob(res, Target("coverage", 6, 12, ">=", 0.90))            # P(coverage >= 90%, months 7-12)
    confidence_curve(tree, "supply.hires_per_month", [1, 2, 3, 4, 5], target)
    tornado(tree, "coverage", 6, 12)                            # which input swings the answer most

Every trial runs the same engine as the single-value view, with inputs drawn from their
distributions (parameter uncertainty) and, by default, random hires, exits, and request
arrivals (process noise).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from .engine import Result, run_model
from .params import Params, apply_overrides, draw_params, node, point_params, quantile, uncertain_specs


def run_mc(tree: dict, n: int | None = None, seed: int | None = None, overrides: dict | None = None,
           process_noise: bool = True) -> tuple[Result, Params]:
    mc = tree["monte_carlo"]
    n = n or mc["trials"]
    seed = mc["seed"] if seed is None else seed
    params = draw_params(tree, n, seed, overrides)
    return run_model(params, process_noise=process_noise, seed=seed + 1), params


@dataclass(frozen=True)
class Target:
    """A metric averaged over months [start, end) compared to a threshold, e.g. coverage >= 0.9 in months 7-12."""
    metric: str
    start: int
    end: int
    op: str
    threshold: float

    @property
    def label(self) -> str:
        return f"{self.metric} {self.op} {self.threshold:g} (avg of months {self.start + 1}-{self.end})"

    def values(self, res: Result) -> np.ndarray:
        return res[self.metric][:, self.start:self.end].mean(axis=1)

    def met(self, res: Result) -> np.ndarray:
        v = self.values(res)
        return v >= self.threshold if self.op == ">=" else v <= self.threshold


def default_targets(tree: dict) -> list[Target]:
    t = tree["targets"]
    return [Target("coverage", 6, 12, ">=", t["coverage"]),
            Target("day90", 9, 12, ">=", t["day90_rate"]),
            Target("reuse_ratio", 9, 12, ">=", t["reuse_ratio"])]


def prob(res: Result, target: Target) -> float:
    return float(target.met(res).mean())


def band(res: Result, metric: str, qs=(0.1, 0.5, 0.9)) -> pd.DataFrame:
    """Fan-chart table: one row per month, one column per quantile."""
    q = res.quantiles(metric, qs)
    return pd.DataFrame({f"p{int(round(x * 100))}": q[i] for i, x in enumerate(qs)}, index=res.months)


def commit_value(res: Result, metric: str, level: float = 0.8, higher_is_worse: bool = True) -> np.ndarray:
    """Per-month value to plan to at a commit level: P80 of a cost-like metric, P20 of a benefit."""
    return np.quantile(res[metric], level if higher_is_worse else 1 - level, axis=0)


def confidence_curve(tree: dict, lever: str, values, target: Target, n: int | None = None,
                     seed: int | None = None, overrides: dict | None = None) -> pd.DataFrame:
    """P(target) as one lever varies, all else at plan. Common random numbers (same seed for every
    lever value) so the curve moves only because of the lever."""
    rows = []
    for v in values:
        res, _ = run_mc(tree, n, seed, {**(overrides or {}), lever: v})
        x = target.values(res)
        rows.append(dict(lever_value=v, p_target=prob(res, target),
                         p10=np.quantile(x, 0.1), p50=np.quantile(x, 0.5), p90=np.quantile(x, 0.9)))
    return pd.DataFrame(rows)


def tornado(tree: dict, metric: str, start: int, end: int, overrides: dict | None = None,
            q=(0.1, 0.9)) -> pd.DataFrame:
    """Swing analysis: move one uncertain input to its P10 and P90, all others at their value.
    Sorted by swing, largest first."""
    tree = apply_overrides(tree, overrides)
    base = run_model(point_params(tree))[metric][0, start:end].mean()
    rows = []
    for path, spec in uncertain_specs(tree).items():
        lo, hi = quantile(spec, q[0]), quantile(spec, q[1])
        m_lo = run_model(point_params(tree, {path: lo}))[metric][0, start:end].mean()
        m_hi = run_model(point_params(tree, {path: hi}))[metric][0, start:end].mean()
        rows.append(dict(input=path, low_input=lo, high_input=hi, at_low=m_lo, at_high=m_hi,
                         swing=abs(m_hi - m_lo)))
    df = pd.DataFrame(rows).sort_values("swing", ascending=False, ignore_index=True)
    df.attrs["base"] = base
    return df


def variance_drivers(res: Result, params: Params, target: Target) -> pd.DataFrame:
    """Which drawn inputs move the outcome across trials (Spearman rank correlation).
    Share = rho^2 normalized; an approximation that ignores interactions and process noise."""
    y = target.values(res)
    rows = []
    for path, x in params.drawn.items():
        if np.ptp(x) == 0:
            continue
        rho = stats.spearmanr(x, y).statistic
        rows.append(dict(input=path, rho=rho, rho2=rho ** 2))
    df = pd.DataFrame(rows)
    df["share"] = df.rho2 / df.rho2.sum()
    return df.sort_values("rho2", ascending=False, ignore_index=True).drop(columns="rho2")


def scenario_table(tree: dict, scenarios: dict, targets: list[Target], n: int | None = None,
                   seed: int | None = None) -> pd.DataFrame:
    """Each scenario on medians AND spread: P50 and P10-P90 of each target metric, plus P(target)."""
    rows = []
    for name, sc in scenarios.items():
        res, _ = run_mc(tree, n, seed, sc.get("overrides"))
        row = dict(scenario=name)
        for t in targets:
            x = t.values(res)
            row[f"{t.metric}_p50"] = np.median(x)
            row[f"{t.metric}_p10"] = np.quantile(x, 0.1)
            row[f"{t.metric}_p90"] = np.quantile(x, 0.9)
            row[f"P({t.metric})"] = prob(res, t)
        row["hc_end_p50"] = np.median(res["hc_total"][:, -1])
        row["cost_24m_p50"] = np.median(res["cost"].sum(axis=1))
        row["starts_24m_p50"] = np.median(res["starts"].sum(axis=1))
        rows.append(row)
    return pd.DataFrame(rows)
