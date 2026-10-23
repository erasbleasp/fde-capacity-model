"""Data access for the dashboard: cached model runs and warehouse queries.

The model runs once per distinct set of overrides (single-value plan + 2,000 Monte Carlo trials,
~0.2 s) and is cached; the warehouse is built on first use if fde.duckdb doesn't exist (e.g. on
Streamlit Community Cloud) and opened read-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "warehouse"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from build import build  # noqa: E402
from model.engine import Result, run_model  # noqa: E402
from model.montecarlo import Target, default_targets, run_mc  # noqa: E402
from model.params import load_assumptions, load_scenarios, point_params  # noqa: E402

DB = ROOT / "fde.duckdb"
WINDOW = slice(6, 12)          # months 7-12 of the horizon: the window every tile and target uses
LEVERS = {
    "supply.hires_per_month": dict(label="Hires per month", min=0.0, max=8.0, step=0.1, fmt="%.1f"),
    "overhead.harvest_share": dict(label="Harvest time", min=0.03, max=0.20, step=0.01, fmt="%.2f"),
    "partners.weeks_per_month": dict(label="Partner weeks per month", min=0.0, max=80.0, step=5.0, fmt="%.0f"),
}


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


@st.cache_data(show_spinner="Running 2,000 Monte Carlo trials…", max_entries=24)
def run(overrides: tuple) -> dict[str, Result]:
    """overrides: sorted tuple of (path, value). Returns the single-value plan and the Monte Carlo run."""
    tree = assumptions()
    ov = dict(overrides)
    point = run_model(point_params(tree, ov))
    mc, _ = run_mc(tree, overrides=ov)
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
