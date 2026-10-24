"""Supply: headcount (actual and forecast), hiring vs exits, region x role mix, where FDE time goes."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data
import ui
from model.params import REGIONS, ROLES

runs = data.current()
p, mc = runs["point"], runs["mc"]
W = data.WINDOW
months = mc.months
window_label = f"{ui.month_label(months[W.start])[:3]}–{ui.month_label(months[W.stop - 1])}"
tree = data.assumptions()
forecast_end = pd.Timestamp(months[-1]) + pd.Timedelta(days=20)

hist = data.query("""
    SELECT month, sum(hc_end) AS hc, sum(hires) AS hires, sum(exits) AS exits
    FROM v_headcount_monthly GROUP BY month ORDER BY month""")
calib = dict(data.query("SELECT param, value FROM v_calibration").itertuples(index=False))

# ---------------------------------------------------------------- number boxes
hc_now = hist.hc.iloc[-1]
end = np.quantile(mc["hc_total"][:, -1], (0.1, 0.5, 0.9))
hires = np.quantile(mc["hires"].sum(axis=1), (0.1, 0.5, 0.9))
exits = np.quantile(mc["exits"].sum(axis=1), (0.1, 0.5, 0.9))
span = p["hc_ic"][0] / p["hc_mgr"][0]
ttf = tree["supply"]["time_to_fill_days"]
ui.tile_row([
    ui.stat_tile("Headcount, Sep 2026", ui.num(hc_now), "Actual, incl. managers", spark=hist.hc),
    ui.stat_tile(f"Headcount, {ui.month_label(months[-1])}", ui.num(end[1]),
                 f"P10–P90  {ui.num(end[0])} – {ui.num(end[2])}", spark=mc.p50("hc_total")),
    ui.stat_tile("Hires over 24 months", ui.num(hires[1]), f"P10–P90  {ui.num(hires[0])} – {ui.num(hires[2])}",
                 spark=mc.p50("hires")),
    ui.stat_tile("Exits over 24 months", ui.num(exits[1]), f"P10–P90  {ui.num(exits[0])} – {ui.num(exits[2])}",
                 spark=mc.p50("exits")),
    ui.stat_tile("Time to fill (days)", ui.num(ttf["value"]),
                 f"Range {ui.num(ttf['low'])} – {ui.num(ttf['high'])} · history P50 {ui.num(calib['time_to_fill_p50'])}"),
    ui.stat_tile("ICs per manager", f"{span[-1]:.1f}", f"Target ≤ {tree['supply']['manager_span']['value']:g}",
                 spark=span),
])

# ---------------------------------------------------------------- headcount | hires vs exits
left, right = st.columns(2)
with left:
    fig = go.Figure()
    q = mc.quantiles("hc_total")
    ui.forecast_panel(fig, x1=forecast_end)
    ui.line(fig, list(hist.month), hist.hc.to_numpy(), ui.SERIES[0], "Actual")
    ui.fan(fig, months, q, ui.SERIES[0], "Forecast", end_label=False)
    ui.label_end(fig, months[-1], q[1][-1], f"{q[1][-1]:,.0f}")
    ui.layout(fig, height=330, legend=False, xrange=[hist.month.iloc[0], forecast_end])
    fig.update_yaxes(rangemode="tozero")
    table = pd.concat([
        pd.DataFrame({"Month": [ui.month_label(m) for m in hist.month], "Kind": "Actual", "P10": np.nan,
                      "P50": hist.hc, "P90": np.nan}),
        pd.DataFrame({"Month": [ui.month_label(m) for m in months], "Kind": "Forecast", "P10": q[0], "P50": q[1],
                      "P90": q[2]})]).round(1)
    ui.chart(fig, "Headcount", "People, FDEs plus managers; forecast P50 with P10–P90 range", table,
             "Forecast hires land a time-to-fill after the req opens, then ramp 25 / 50 / 75 / 100% over four "
             "months. Managers are added to hold the span.")

with right:
    hq = hist.assign(q=pd.PeriodIndex(pd.to_datetime(hist.month), freq="Q")).groupby("q")[["hires", "exits"]].sum()
    fq_index = pd.PeriodIndex(pd.to_datetime(months), freq="Q")
    fh = pd.DataFrame(mc["hires"].T, index=fq_index).groupby(level=0).sum().median(axis=1)
    fe = pd.DataFrame(mc["exits"].T, index=fq_index).groupby(level=0).sum().median(axis=1)
    quarters = [f"Q{x.quarter}<br>{x.year}" for x in list(hq.index) + list(fh.index)]
    h_all = np.concatenate([hq.hires.to_numpy(), fh.to_numpy()])
    e_all = np.concatenate([hq.exits.to_numpy(), fe.to_numpy()])
    fig = go.Figure()
    ui.forecast_panel(fig, x0=len(hq) - 0.5, x1=len(quarters) - 0.5)
    fig.add_trace(go.Bar(x=quarters, y=h_all, name="Hires", marker=dict(color=ui.SERIES[0]),
                         hovertemplate="<b>%{y:.0f}</b> hires<extra></extra>"))
    fig.add_trace(go.Bar(x=quarters, y=-e_all, name="Exits", marker=dict(color=ui.SERIES[1]),
                         customdata=e_all, hovertemplate="<b>%{customdata:.0f}</b> exits<extra></extra>"))
    ui.layout(fig, height=330)
    fig.update_layout(barmode="relative", bargap=0.35)
    fig.update_xaxes(showline=False, tickangle=0, tickfont=dict(size=10))
    fig.add_hline(y=0, line=dict(color=ui.INK, width=1))
    table = pd.DataFrame({"Quarter": [q.replace("<br>", " ") for q in quarters], "Kind": ["Actual"] * len(hq) + ["Forecast P50"] * len(fh),
                          "Hires": h_all, "Exits": e_all, "Net": h_all - e_all}).round(1)
    ui.chart(fig, "Hires and exits", "People per quarter; exits shown below zero; forecast quarters are P50",
             table, "Hires include managers added to hold the span.")

# ---------------------------------------------------------------- region x role | regional coverage
left, right = st.columns(2)
with left:
    start = tree["supply"]["starting_headcount"]["by_region_role"]
    ic_end, mgr_end = p["hc_ic_by_region_role"][0, -1], p["hc_mgr_by_region"][0, -1]
    roles = ROLES + ["Eng Manager"]
    rows = []
    for r, region in enumerate(REGIONS):
        for when, vals in (("Sep 2026", [start[region][x] for x in roles]),
                           (ui.month_label(months[-1]), list(ic_end[r]) + [mgr_end[r]])):
            rows.append(dict(bar=f"{region} · {when}", region=region, when=when, **dict(zip(roles, vals))))
    df = pd.DataFrame(rows).iloc[::-1]
    fig = go.Figure()
    for k, role in enumerate(roles):
        fig.add_trace(go.Bar(y=df.bar, x=df[role], name=role, orientation="h",
                             marker=dict(color=ui.SERIES[k], line=dict(color=ui.SURFACE, width=1)),
                             hovertemplate=f"<b>%{{x:.0f}}</b> {role}<extra></extra>"))
    for y, t in zip(df.bar, df[roles].sum(axis=1)):
        fig.add_annotation(y=y, x=t, text=f"{t:.0f}", showarrow=False, xanchor="left", xshift=4,
                           font=dict(color=ui.INK, size=12))
    ui.layout(fig, height=330, hovermode="y unified")
    fig.update_layout(barmode="stack", bargap=0.35, margin=dict(t=56))
    # horizontal bars: values along the top, vertical gridlines, category labels on the left (the guide's bar style)
    fig.update_yaxes(side="left", showgrid=False, tickfont=dict(color=ui.INK))
    fig.update_xaxes(side="top", showgrid=True, gridcolor=ui.GRID, showline=False, ticks="")
    fig.update_layout(legend=dict(y=1.12))
    ui.chart(fig, "Headcount by region and role", f"People, Sep 2026 and {ui.month_label(months[-1])} (single-value plan)",
             df.iloc[::-1][["region", "when"] + roles].round(1),
             "New reqs follow the hiring region mix (AMER 55% · EMEA 30% · APAC 15%).")

with right:
    cov = mc["fde_coverage_by_region"][:, W, :].mean(axis=1)
    q = np.quantile(cov, (0.1, 0.5, 0.9), axis=0)
    fig = go.Figure(go.Bar(
        x=REGIONS, y=q[1], marker=dict(color=ui.SERIES[0]),
        error_y=dict(type="data", symmetric=False, array=q[2] - q[1], arrayminus=q[1] - q[0],
                     color=ui.INK_2, thickness=1, width=6),
        customdata=np.stack([q[0], q[2]], axis=1),
        hovertemplate="<b>%{y:.0%}</b> P50 (P10 %{customdata[0]:.0%} – P90 %{customdata[1]:.0%})<extra></extra>"))
    for region, v in zip(REGIONS, q[1]):   # value beside the bar top, clear of the whisker
        fig.add_annotation(x=region, y=v, text=ui.pct(v), showarrow=False, xanchor="left", xshift=22,
                           font=dict(color=ui.INK, size=12))
    ui.target_line(fig, data.targets()[0].threshold, "Target 90%")
    ui.layout(fig, height=330, yfmt=".0%", legend=False, hovermode="closest")
    fig.update_traces(width=0.3)
    fig.update_yaxes(rangemode="tozero")
    ui.chart(fig, "FDE coverage by region", f"FDE capacity ÷ the region's demand, {window_label} average, %; "
                                            "whiskers P10–P90",
             pd.DataFrame({"Region": REGIONS, "P10": q[0], "P50": q[1], "P90": q[2]}).round(3),
             "Partners excluded. The model pools capacity across regions, so a low ratio is a question to check "
             "(must that region's demand be served locally?), not a finding about where reqs should go.")

# ---------------------------------------------------------------- where FDE time goes (actual)
mix = data.query("SELECT month, category, share_of_all FROM v_overhead_mix ORDER BY month")
wide = mix.pivot(index="month", columns="category", values="share_of_all").fillna(0)
wide["presales_internal"] = wide["presales"] + wide["internal"]
cats = [("deploy", "Delivery", ui.SERIES[0]), ("bench", "Unassigned", ui.SERIES[1]),
        ("harvest", "Harvest (assets)", ui.SERIES[2]), ("presales_internal", "Presales, internal & ramp", ui.NEUTRAL[0]),
        ("pto", "PTO", ui.NEUTRAL[1])]
x = [ui.month_label(m) for m in wide.index]
fig = go.Figure()
for c, name, color in cats:
    fig.add_trace(go.Bar(x=x, y=wide[c], name=name, marker=dict(color=color, line=dict(color=ui.SURFACE, width=1)),
                         hovertemplate=f"<b>%{{y:.0%}}</b> {name}<extra></extra>"))
cum = 0.0
for c, name, _ in cats:
    v = wide[c].iloc[-1]
    if v >= 0.04:
        fig.add_annotation(x=x[-1], y=cum + v / 2, text=f"{name} {v:.0%}", showarrow=False, xanchor="left",
                           xshift=18, font=dict(color=ui.INK, size=11))
    cum += v
ui.layout(fig, height=360, yfmt=".0%", right=170)
fig.update_layout(barmode="stack", bargap=0.25)
fig.update_yaxes(side="left")      # the right edge carries the direct labels
ui.chart(fig, "Where FDE time goes", "% of logged hours by month, all FDEs including managers; actual",
         (wide[[c for c, _, _ in cats]].rename(columns={c: n for c, n, _ in cats}) * 100).round(1).reset_index()
         .assign(month=lambda d: d.month.map(ui.month_label)),
         "Harvest rose from 3% to 7% in Jan 2026 (the productization push); the forecast treats 7% as the "
         "reference level. Presales, internal time and ramp are combined in grey.",
         source="Source: made-up FDE warehouse (time entries)")
