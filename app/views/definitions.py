"""Data & definitions: every assumption and where it came from, the SQL views, the calibration,
the metric dictionary, and an Excel export of the whole model."""
import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data
import ui
from export import build_workbook

ROOT = data.ROOT
runs = data.current()
ov = dict(data.overrides())
scenario = st.session_state.get("scenario", "Base")

# ---------------------------------------------------------------- export
ui.note("Everything on this dashboard traces back to here: each forecast input is either calibrated from a "
        "SQL view over the warehouse or labelled as judgment, with a note on why its range is as wide as it is.")
settings = {"Scenario": scenario, **{data.LEVERS[k]["label"]: v for k, v in ov.items() if k in data.LEVERS}}
scen = data.scenario_comparison(data.overrides())
calib = data.query("SELECT param, value, unit, source FROM v_calibration")
xlsx = build_workbook(settings, data.assumption_rows(), runs["point"], runs["mc"], scen, calib)
st.download_button("Download the model (Excel)", xlsx, file_name=f"fde_capacity_model_{scenario.lower()}.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary",
                   help="README, assumptions, monthly plan, Monte Carlo P10/P50/P90, scenarios, SQL calibration — "
                        "for the scenario and levers currently set.")

tabs = st.tabs(["Assumptions", "Backtest", "SQL views", "Calibration", "Metric dictionary"])

# ---------------------------------------------------------------- assumptions
with tabs[0]:
    rows = data.assumption_rows()
    st.markdown('<div class="ec-head"><div class="ec-rule"></div><div class="ec-title">Every input, and where it '
                'came from</div><div class="ec-sub">config/assumptions.yaml; "SQL value now" is what v_calibration '
                'returns from the warehouse today</div></div>', unsafe_allow_html=True)
    kind = st.segmented_control("Show", ["All", "Calibrated from SQL", "Judgment or lever"], default="All",
                                key="assume_filter") or "All"
    if kind == "Calibrated from SQL":
        rows = rows[rows["SQL value now"].notna()]
    elif kind == "Judgment or lever":
        rows = rows[rows["SQL value now"].isna()]
    st.dataframe(rows, hide_index=True, width="stretch", height=520,
                 column_config={"Note": st.column_config.TextColumn(width="large")})
    ui.note(f"{len(rows)} inputs shown. tests/test_assumptions.py fails the build if a calibrated value drifts "
            "outside its stated range when the warehouse is regenerated.")

# ---------------------------------------------------------------- backtest
with tabs[1]:
    bt = data.backtest()
    st.markdown('<div class="ec-head"><div class="ec-rule"></div><div class="ec-title">Does it forecast a history it '
                'hasn\'t seen?</div><div class="ec-sub">Calibrated on data to 31 Mar 2026 only; forecast Apr–Sep 2026; '
                'scored against what happened</div></div>', unsafe_allow_html=True)
    summ = bt["summary"].copy()
    fmt = lambda m, v: f"{v:.0%}" if m in ("FDE utilization", "Day-90 (mature cohorts)") else f"{v:,.0f}"
    show = pd.DataFrame({
        "Measure": summ.measure, "Scored on": summ.scored_on,
        "Actual": [fmt(m, v) for m, v in zip(summ.measure, summ.actual)],
        "Forecast P10 / P50 / P90": [f"{fmt(m, a)} / {fmt(m, b)} / {fmt(m, c)}"
                                     for m, a, b, c in zip(summ.measure, summ.p10, summ.p50, summ.p90)],
        "Actual's percentile": summ.actual_percentile.map(lambda v: f"{v:.0%}"),
        "Months in P10–P90 band": summ.months_in_band})
    st.dataframe(show, hide_index=True, width="stretch")
    ui.note(f"<b>{bt['coverage']:.0%} of months fall inside the P10–P90 band</b> (≈80% if well calibrated). The model "
            "is overconfident and leans pessimistic: the misses are more demand, more work done and faster delivery "
            "than forecast. Causes: no seasonality (the cutoff window spans December), small-sample delivery rates, "
            "and month-to-month demand lumpier than the model assumes. The backtest already changed two inputs: the "
            "demand level now comes from the trend fit with a range from its standard error, and the abandon rate "
            "rose to 0.75. Full write-up: docs/backtest.md.")
    m = bt["monthly"]
    cols = st.columns(2)
    for col, measure in zip(cols, ["Requests", "Engagements started"]):
        with col:
            d = m[m.measure == measure]
            fig = go.Figure()
            ui.fan(fig, bt["months"], np.stack([d.p10, d.p50, d.p90]), ui.SERIES[0], "Forecast", end_label=False)
            ui.line(fig, bt["months"], d.actual.to_numpy(), ui.SERIES[3], "Actual", markers=True)
            ui.layout(fig, height=260)
            fig.update_yaxes(rangemode="tozero")
            ui.chart(fig, measure, "Per month; forecast P50 with P10–P90 range, and actual",
                     d[["month", "actual", "p10", "p50", "p90"]].round(1),
                     source="Source: made-up FDE warehouse; model calibrated at 31 Mar 2026")

# ---------------------------------------------------------------- SQL views
with tabs[2]:
    sql = (ROOT / "warehouse" / "views.sql").read_text()
    views = {m.group(1): f"CREATE OR REPLACE VIEW {m.group(1)} AS{m.group(2)};"
             for m in re.finditer(r"CREATE OR REPLACE VIEW (\w+) AS(.*?);\s*$", sql, re.S | re.M)}
    st.markdown('<div class="ec-head"><div class="ec-rule"></div><div class="ec-title">The SQL behind the numbers'
                '</div><div class="ec-sub">DuckDB views over 11 raw tables (warehouse/views.sql)</div></div>',
                unsafe_allow_html=True)
    name = st.selectbox("View", list(views), index=list(views).index("v_calibration") if "v_calibration" in views else 0,
                        key="sql_view")
    left, right = st.columns([1, 1.2])
    with left:
        st.code(views[name], language="sql", line_numbers=False)
    with right:
        preview = data.query(f"SELECT * FROM {name} LIMIT 200")    # name comes from the parsed file, not user text
        st.dataframe(preview, hide_index=True, width="stretch", height=480)
        ui.note(f"First {len(preview)} rows. Read-only; queries are limited to these views.")

# ---------------------------------------------------------------- calibration
with tabs[3]:
    st.markdown('<div class="ec-head"><div class="ec-rule"></div><div class="ec-title">Calibration</div>'
                '<div class="ec-sub">One row per model parameter estimated from the history (v_calibration)</div>'
                '</div>', unsafe_allow_html=True)
    st.dataframe(calib.assign(value=calib.value.round(4)), hide_index=True, width="stretch", height=520)

# ---------------------------------------------------------------- metric dictionary
with tabs[4]:
    md = (ROOT / "docs" / "metric_dictionary.md").read_text()
    st.markdown(md)
