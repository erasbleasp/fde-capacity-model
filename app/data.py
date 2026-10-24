"""Data access for the dashboard: cached model runs and warehouse queries.

The model runs once per distinct set of overrides (single-value plan + 2,000 Monte Carlo trials,
~0.2 s) and is cached; the warehouse is built on first use if fde.duckdb doesn't exist (e.g. on
Streamlit Community Cloud) and opened read-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "warehouse"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from build import build  # noqa: E402
from model.engine import Result, run_model  # noqa: E402
from model.engagement import simulate_engagement  # noqa: E402
from model.montecarlo import Target, confidence_curve, default_targets, run_mc, scenario_table, tornado  # noqa: E402
from model.params import load_assumptions, load_scenarios, node, point_params, uncertain_specs  # noqa: E402

DB = ROOT / "fde.duckdb"
WINDOW = slice(6, 12)          # months 7-12 of the horizon: the window every tile and target uses
LEVERS = {
    "supply.hires_per_month": dict(label="Hires per month", min=0.0, max=8.0, step=0.1, fmt="%.1f"),
    "overhead.harvest_share": dict(label="Harvest time", min=0.03, max=0.20, step=0.01, fmt="%.2f"),
    "partners.weeks_per_month": dict(label="Partner weeks per month", min=0.0, max=80.0, step=5.0, fmt="%.0f"),
    "demand.intake.Greenfield": dict(label="Greenfield intake", min=0.5, max=1.0, step=0.05, fmt="%.2f"),
}
PERCENT_LEVERS = {"overhead.harvest_share", "demand.intake.Greenfield"}


@st.cache_data
def assumptions() -> dict:
    return load_assumptions()


@st.cache_data
def scenarios() -> dict:
    return load_scenarios()


def lever_default(scenario: str, path: str) -> float:
    ov = scenarios()[scenario]["overrides"]
    if path in ov:
        return float(ov[path])
    node = assumptions()
    for key in path.split("."):
        node = node[key]
    return float(node["value"] if isinstance(node, dict) else node)


@st.cache_data(show_spinner="Running 2,000 Monte Carlo trials…", max_entries=8)
def run(overrides: tuple) -> dict[str, Result]:
    """overrides: sorted tuple of (path, value). Returns the single-value plan and the Monte Carlo run.
    Monte Carlo series are kept as float32 (~11 MB per run) and only the 8 most recent lever settings
    are cached, so memory stays well inside a free hosting tier."""
    tree = assumptions()
    ov = dict(overrides)
    point = run_model(point_params(tree, ov))
    mc, _ = run_mc(tree, overrides=ov)
    mc.series = {k: v.astype(np.float32) for k, v in mc.series.items()}
    return dict(point=point, mc=mc)


def targets() -> list[Target]:
    return default_targets(assumptions())


@st.cache_resource
def warehouse() -> duckdb.DuckDBPyConnection:
    if not DB.exists():
        build(DB).close()
    return duckdb.connect(str(DB), read_only=True)


@st.cache_data
def query(sql: str) -> pd.DataFrame:
    return warehouse().cursor().execute(sql).df()


def current() -> dict[str, Result]:
    """The run for the scenario and levers chosen in the filter row."""
    return run(st.session_state.get("overrides", ()))


# ---------------------------------------------------------------- Phase 4: confidence, scenarios, definitions
INPUT_LABELS = {
    "demand.requests_per_month": "Requests per month now",
    "demand.monthly_growth": "Demand growth per month",
    "demand.fit_rate": "Share of requests that fit",
    "demand.greenfield_share": "Greenfield share of requests",
    "supply.time_to_fill_days": "Time to fill a req",
    "supply.ramp_uncertainty": "Speed of new-hire ramp",
    "supply.annual_attrition": "Attrition rate",
    "overhead.pto_share": "PTO share",
    "overhead.presales_share": "Presales share",
    "overhead.internal_share": "Internal-time share",
    "cycle_time.median_uncertainty": "Engagement length (all types)",
    "cycle_time.staffing_alpha": "Speed-up from more FDEs",
    "cycle_time.blocker_prob": "Chance of a customer blocker",
    "cycle_time.cancel_prob": "Cancellation rate",
    "partners.efficiency": "Partner efficiency",
    "assets.yield_at_5pct_harvest": "Assets harvested per engagement",
    "assets.monthly_decay": "Asset decay per month",
    "assets.reuse_max": "Reuse ceiling",
    "assets.reuse_half_k": "Library size for reuse to build",
}


def overrides() -> tuple:
    return st.session_state.get("overrides", ())


@st.cache_data(show_spinner="Sweeping the lever across 1,000 trials each…", max_entries=24)
def confidence(ov: tuple, lever: str, values: tuple, metric: str, threshold: float) -> pd.DataFrame:
    """P(metric >= threshold over months 7-12) as one lever varies, everything else as currently set."""
    return confidence_curve(assumptions(), lever, list(values), Target(metric, WINDOW.start, WINDOW.stop, ">=", threshold),
                            n=1000, overrides=dict(ov))


@st.cache_data(show_spinner="Running the tornado…", max_entries=16)
def tornado_table(ov: tuple, metric: str = "coverage") -> pd.DataFrame:
    df = tornado(assumptions(), metric, WINDOW.start, WINDOW.stop, overrides=dict(ov))
    base = df.attrs["base"]
    df = df.assign(label=df["input"].map(INPUT_LABELS).fillna(df["input"]), base=base)
    return df


@st.cache_data(show_spinner=False, max_entries=48)
def engagement_days(ov: tuple, eng_type: str, fdes: float, assets: bool, library: float) -> np.ndarray:
    return simulate_engagement(assumptions(), eng_type, fdes, assets, library=library, n=20000,
                               overrides=dict(ov))


@st.cache_data(show_spinner="Running every scenario…", max_entries=8)
def scenario_comparison(ov: tuple) -> pd.DataFrame:
    """Every named scenario plus the current filter-row settings, on medians and spread."""
    sc = dict(scenarios())
    sc["Current settings"] = {"overrides": dict(ov)}
    df = scenario_table(assumptions(), sc, targets())
    extra = []
    for name, spec in sc.items():
        r, _ = run_mc(assumptions(), overrides=spec.get("overrides"))
        cov = targets()[0].values(r)
        extra.append(dict(scenario=name, p_cov80=float((cov >= 0.8).mean()),
                          fit_served=float(np.median(r["starts"].sum(axis=1) / r["fit_requests"].sum(axis=1))),
                          declined_policy=float(np.median(r["declined_policy"].sum(axis=1))),
                          declined_capacity=float(np.median(r["declined"].sum(axis=1)))))
    return df.merge(pd.DataFrame(extra), on="scenario")


def assumption_rows() -> pd.DataFrame:
    """Every input in assumptions.yaml with its value, spread, and the SQL value it was calibrated from."""
    tree = assumptions()
    calib = dict(query("SELECT param, value FROM v_calibration").itertuples(index=False))
    rows = []

    def walk(n, path):
        if not isinstance(n, dict):
            return
        if "value" in n or "dist" in n:
            dist = n.get("dist", "fixed")
            if dist == "triangular":
                spread = f"triangular {n['low']:g} / {n['mode']:g} / {n['high']:g}"
            elif dist == "lognormal":
                spread = f"lognormal, median {n['median']:g}, σ {n['sigma']:g}"
            elif dist == "beta":
                spread = f"beta, mean {n['mean']:g}, sd {n['sd']:g}"
            else:
                spread = "lever / fixed"
            src = n.get("calibrated_from")
            sql = calib.get(src) * n.get("calibration_scale", 1.0) if src in calib else None
            value = n.get("value")
            rows.append({"Input": path, "Value": value if not isinstance(value, dict) else str(value),
                         "Distribution": spread + (" (per engagement)" if n.get("per_engagement") else ""),
                         "Calibrated from (v_calibration)": src or "judgment / lever",
                         "SQL value now": None if sql is None else round(float(sql), 4),
                         "Note": " ".join(str(n.get("note", "")).split())})
            return
        for k, v in n.items():
            walk(v, f"{path}.{k}" if path else k)

    for section in ("demand", "supply", "overhead", "cycle_time", "partners", "assets", "economics", "targets"):
        walk(tree[section], section)
    df = pd.DataFrame(rows)
    df["Value"] = df["Value"].astype(str)
    return df
