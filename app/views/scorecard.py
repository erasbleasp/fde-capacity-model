"""Scorecard: the monthly-business-review page. KPI tiles, demand vs capacity, coverage, capacity waterfall."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data
import ui
from model.engine import WEEKS_PER_MONTH

runs = data.current()
p, mc = runs["point"], runs["mc"]
W = data.WINDOW
months = mc.months
window_label = f"{ui.month_label(months[W.start])[:3]}–{ui.month_label(months[W.stop - 1])}"
targets = {t.metric: t for t in data.targets()}


def window_q(metric, qs=(0.1, 0.5, 0.9)):
    return np.quantile(mc[metric][:, W].mean(axis=1), qs)


def target_status(metric, fmt):
    t = targets[metric]
    prob = float(t.met(mc).mean())
    return ui.status_for(prob), f"{prob:.0%} chance of ≥ {fmt(t.threshold)}"


# ---------------------------------------------------------------- number boxes
tiles = []
for metric, label in [("coverage", "Coverage"), ("day90", "Day-90 productization"),
                      ("reuse_ratio", "Reusable-asset ratio")]:
    lo, mid, hi = window_q(metric)
    tiles.append(ui.stat_tile(label, ui.pct(mid), f"P10–P90  {ui.pct(lo)} – {ui.pct(hi)}",
                              target_status(metric, ui.pct), mc.p50(metric), W))
lo, mid, hi = window_q("utilization")
tiles.append(ui.stat_tile("FDE utilization", ui.pct(mid), f"P10–P90  {ui.pct(lo)} – {ui.pct(hi)}",
                          spark=mc.p50("utilization"), highlight=W))
lo, mid, hi = window_q("gap_weeks")
tiles.append(ui.stat_tile("Gap (staffing wks/mo)", f"{mid:+,.0f}", f"P10–P90  {lo:+,.0f} to {hi:+,.0f}",
                          spark=mc.p50("gap_weeks"), highlight=W))
h50, h80, h90 = window_q("hires_needed", (0.5, 0.8, 0.9))
tiles.append(ui.stat_tile("FDEs short (P80)", ui.num(h80), f"P50 {ui.num(h50)} · P90 {ui.num(h90)}",
                          spark=mc.p50("hires_needed"), highlight=W))
ui.tile_row(tiles)
ui.note(f"Each box is the P50 across 2,000 trials of the metric averaged over <b>{window_label}</b> (months 7–12, "
        f"blue on each sparkline). \"FDEs short\" counts ramped FDEs needed to close the gap, planned at P80; it "
        f"excludes time to fill and ramp, so hiring must start ~5 months earlier.")

# ---------------------------------------------------------------- demand vs capacity, coverage
qd, qc = mc.quantiles("demand_weeks"), mc.quantiles("effective_capacity_weeks")
cov = pd.DataFrame(mc["coverage"].T).rolling(3, min_periods=1).mean().to_numpy().T
qv = np.quantile(cov, (0.1, 0.5, 0.9), axis=0)
left, right = st.columns(2)
with left:
    fig = go.Figure()
    ui.fan(fig, months, qd, ui.SERIES[1], "Demand")
    ui.fan(fig, months, qc, ui.SERIES[0], "Capacity")
    ui.layout(fig, height=330, xrange=[months[0], months[-1]])
    fig.update_yaxes(rangemode="tozero")
    widening = qv[1][-1] < qv[1][0]
    table = pd.DataFrame({"Month": [ui.month_label(m) for m in months],
                          "Demand P10": qd[0], "Demand P50": qd[1], "Demand P90": qd[2],
                          "Capacity P10": qc[0], "Capacity P50": qc[1], "Capacity P90": qc[2]}).round(0)
    ui.chart(fig, "Demand is outrunning capacity" if widening else "Capacity is keeping pace",
             "Staffing weeks per month; P50, P10–P90 range", table,
             "Capacity = ramped FDEs × 4.33 weeks × 85% planned allocation, plus partner weeks usable on "
             "pattern-based and expansion work.")

with right:
    fig = go.Figure()
    ui.fan(fig, months, qv, ui.SERIES[0], "Coverage", fmt=".0%")
    ui.target_line(fig, targets["coverage"].threshold, f"Target {ui.pct(targets['coverage'].threshold)}")
    ui.layout(fig, height=330, yfmt=".0%", legend=False, xrange=[months[0], months[-1]])
    fig.update_yaxes(rangemode="tozero")
    table = pd.DataFrame({"Month": [ui.month_label(m) for m in months],
                          "P10": qv[0], "P50": qv[1], "P90": qv[2]}).round(3)
    ui.chart(fig, "Coverage of demand", "% of demand, 3-month rolling; P50, P10–P90 range",
             table, "Monthly demand is lumpy (a handful of large engagements), so coverage is averaged over "
                    "3 months in each trial before taking percentiles.")

# ---------------------------------------------------------------- capacity waterfall
w = lambda name: float(p[name][0, W].mean())
target_util = data.assumptions()["overhead"]["target_utilization"]["value"]
heads_weeks = w("hc_ic") * WEEKS_PER_MONTH
ramp_loss = (w("hc_ic") - w("effective_ic")) * WEEKS_PER_MONTH
buffer = w("effective_ic") * WEEKS_PER_MONTH * (1 - target_util)
fde_cap, eff_cap, demand = w("fde_capacity_weeks"), w("effective_capacity_weeks"), w("demand_weeks")
partners = eff_cap - fde_cap
steps = [("FDE headcount weeks", heads_weeks, "absolute"), ("Still ramping", -ramp_loss, "relative"),
         (f"Unassigned buffer ({ui.pct(1 - target_util)})", -buffer, "relative"),
         ("FDE capacity", fde_cap, "total"), ("Partners (eligible work)", partners, "relative"),
         ("Total capacity", eff_cap, "total")]
fig = go.Figure(go.Waterfall(
    x=[s[0] for s in steps], y=[s[1] if s[2] != "total" else 0 for s in steps], measure=[s[2] for s in steps],
    connector=dict(line=dict(color=ui.GRID, width=1)),
    totals=dict(marker=dict(color=ui.SERIES[0])), decreasing=dict(marker=dict(color=ui.MUTED)),
    increasing=dict(marker=dict(color=ui.SERIES[2])),
    text=[f"{s[1]:+,.0f}" if s[2] == "relative" else f"{s[1]:,.0f}" for s in steps], textposition="outside",
    textfont=dict(color=ui.INK), hovertemplate="%{x}: <b>%{text}</b><extra></extra>", name="Capacity"))
fig.add_trace(go.Bar(x=["Demand"], y=[demand], marker=dict(color=ui.SERIES[1]), name="Demand",
                     text=[f"{demand:,.0f}"], textposition="outside", textfont=dict(color=ui.INK),
                     hovertemplate="Demand: <b>%{y:,.0f}</b><extra></extra>"))
fig.add_annotation(x="Demand", y=demand, yshift=34, showarrow=False, font=dict(color=ui.INK, size=12),
                   text=f"<b>Gap {eff_cap - demand:+,.0f}</b> ({ui.pct(eff_cap / demand)} covered)")
ui.layout(fig, height=360, legend=False, hovermode="closest")
fig.update_traces(selector=dict(type="waterfall"), width=0.4)
fig.update_traces(selector=dict(type="bar"), width=0.4)
fig.update_yaxes(range=[0, max(heads_weeks, demand) * 1.2])
table = pd.DataFrame({"Step": [s[0] for s in steps] + ["Demand", "Gap"],
                      "Staffing weeks / month": [s[1] for s in steps] + [demand, eff_cap - demand]}).round(1)
ui.chart(fig, "Where capacity comes from", f"Staffing weeks per month, {window_label} average; single-value plan",
         table, "Overhead (PTO, presales, internal time, harvest) isn't a step here: it's already inside measured "
                "engagement durations, so it shows up as longer engagements, not lost capacity.")
