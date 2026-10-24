"""Scenarios: every named scenario plus the current settings, compared on medians and spread."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data
import ui

mc = data.current()["mc"]
W = data.WINDOW
months = mc.months
window_label = f"{ui.month_label(months[W.start])[:3]}–{ui.month_label(months[W.stop - 1])}"
targets = {t.metric: t for t in data.targets()}
sc = data.scenarios()
df = data.scenario_comparison(data.overrides())
order = list(sc) + ["Current settings"]
df = df.set_index("scenario").loc[order].reset_index()
color_for = lambda name: ui.SERIES[3] if name == "Current settings" else ui.SERIES[0]

desc = "".join(f"<li><b>{name}</b> — {spec['description']}</li>" for name, spec in sc.items())
ui.note(f"<ul style='margin:0.2rem 0 0.4rem 1.1rem;padding:0'>{desc}<li><b>Current settings</b> — whatever the "
        "filter row is set to now (highlighted in dark red below).</li></ul>"
        f"Every scenario runs the same 2,000 Monte Carlo trials; values are averages over {window_label}.")

# ---------------------------------------------------------------- dot-and-whisker small multiples
cols = st.columns(3)
for col, (metric, title, target) in zip(cols, [("coverage", "Coverage of demand taken on", targets["coverage"].threshold),
                                                ("day90", "Day-90 productization", targets["day90"].threshold),
                                                ("reuse_ratio", "Reusable-asset ratio", targets["reuse_ratio"].threshold)]):
    with col:
        d = df.iloc[::-1]
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=d[f"{metric}_p50"], y=d.scenario, mode="markers", name="P50",
            marker=dict(size=11, color=[color_for(s) for s in d.scenario], line=dict(color=ui.SURFACE, width=2)),
            error_x=dict(type="data", symmetric=False, array=d[f"{metric}_p90"] - d[f"{metric}_p50"],
                         arrayminus=d[f"{metric}_p50"] - d[f"{metric}_p10"], color=ui.INK_2, thickness=1.2, width=0),
            customdata=np.stack([d[f"{metric}_p10"], d[f"{metric}_p90"], d[f"P({metric})"]], axis=1),
            hovertemplate="%{y}: <b>%{x:.0%}</b> P50 (P10 %{customdata[0]:.0%} – P90 %{customdata[1]:.0%}) · "
                          f"P(≥ {ui.pct(target)}) %{{customdata[2]:.0%}}<extra></extra>"))
        fig.add_vline(x=target, line=dict(color=ui.REF_RED, width=1.2))
        fig.add_annotation(x=target, y=0, yref="paper", text=f"Target {ui.pct(target)}", showarrow=False,
                           xanchor="center", yanchor="top", yshift=-2, font=dict(color=ui.REF_RED, size=11))
        ui.layout(fig, height=340, legend=False, hovermode="closest")
        fig.update_layout(margin=dict(b=22))
        fig.update_yaxes(side="left", showgrid=False, tickfont=dict(color=ui.INK))
        fig.update_xaxes(side="top", tickformat=".0%", showgrid=True, gridcolor=ui.GRID, showline=False, ticks="")
        table = d.iloc[::-1][["scenario", f"{metric}_p10", f"{metric}_p50", f"{metric}_p90", f"P({metric})"]].round(3)
        ui.chart(fig, title, f"{window_label} average; dot = P50, line = P10–P90", table, source=None)
st.markdown(f'<div class="ec-source">{ui.SOURCE}</div>', unsafe_allow_html=True)
ui.note("Coverage is measured against the demand each scenario chooses to take on. Prioritize and Blended turn "
        "some Greenfield requests down up front, so read coverage next to the share of all fit demand served, below.")

# ---------------------------------------------------------------- trade-off: cost vs engagements delivered
left, right = st.columns([1.15, 1])
with left:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df.cost_24m_p50 / 1e6, y=df.starts_24m_p50, mode="markers", name="Scenario",
        marker=dict(size=12, color=[color_for(s) for s in df.scenario], line=dict(color=ui.SURFACE, width=2)),
        customdata=np.stack([df.scenario, df.fit_served, df.hc_end_p50], axis=1),
        hovertemplate="<b>%{customdata[0]}</b><br>$%{x:.1f}m over 24 months · %{y:.0f} engagements<br>"
                      "%{customdata[1]:.0%} of fit demand served · %{customdata[2]:.0f} people by Sep 2028<extra></extra>"))
    clusters = []          # points that land on top of each other share one label
    for _, r in df.iterrows():
        x, y = r.cost_24m_p50 / 1e6, r.starts_24m_p50
        for c in clusters:
            if abs(c["x"] - x) < 1.0 and abs(c["y"] - y) < 6:
                c["names"].append(r.scenario)
                break
        else:
            clusters.append({"x": x, "y": y, "names": [r.scenario]})
    span = max(c["x"] for c in clusters) - min(c["x"] for c in clusters) or 1.0
    for c in clusters:
        # label on the left when another point sits just to the right at a similar height
        crowded = any(0 < o["x"] - c["x"] < 0.3 * span and abs(o["y"] - c["y"]) < 15 for o in clusters)
        fig.add_annotation(x=c["x"], y=c["y"], text=" · ".join(c["names"]), showarrow=False,
                           xanchor="right" if crowded else "left", xshift=-9 if crowded else 9,
                           font=dict(color=ui.INK, size=12))
    ui.layout(fig, height=360, legend=False, hovermode="closest", right=90)
    fig.update_xaxes(title=dict(text="Cost over 24 months, $m (FDE loaded cost + partners)", font=dict(color=ui.INK_2, size=11)),
                     showgrid=True, gridcolor=ui.GRID)
    ui.chart(fig, "What each scenario buys", "Engagements started over 24 months vs 24-month cost; P50",
             df[["scenario", "cost_24m_p50", "starts_24m_p50", "fit_served", "hc_end_p50"]].round(2),
             "Up and to the left is better. Turning some Greenfield down starts more engagements for the same "
             "cost (it is ~3× the effort and partners can't take it), but the model counts every engagement as "
             "equal, so it can't say whether declining Greenfield is wise. Costs are illustrative.")

with right:
    st.markdown('<div class="ec-head"><div class="ec-rule"></div><div class="ec-title">Scenario scorecard</div>'
                f'<div class="ec-sub">P50 unless noted; coverage and chances judged on {window_label}</div></div>',
                unsafe_allow_html=True)
    show = pd.DataFrame({
        "Scenario": df.scenario,
        "Coverage": [f"{a:.0%} ({b:.0%}–{c:.0%})" for a, b, c in zip(df.coverage_p50, df.coverage_p10, df.coverage_p90)],
        "P(≥90%)": df["P(coverage)"].map(lambda v: f"{v:.0%}"),
        "P(≥80%)": df.p_cov80.map(lambda v: f"{v:.0%}"),
        "Fit demand served": df.fit_served.map(lambda v: f"{v:.0%}"),
        "Engagements (24 mo)": df.starts_24m_p50.round(0).astype(int),
        "Turned down by policy": df.declined_policy.round(0).astype(int),
        "Declined, team full": df.declined_capacity.round(0).astype(int),
        "Day-90": df.day90_p50.map(lambda v: f"{v:.0%}"),
        "Reuse": df.reuse_ratio_p50.map(lambda v: f"{v:.0%}"),
        "People Sep 2028": df.hc_end_p50.round(0).astype(int),
        "Cost (24 mo)": df.cost_24m_p50.map(ui.money),
        "Cost per engagement": (df.cost_24m_p50 / df.starts_24m_p50).map(ui.money),
    })
    st.dataframe(show, hide_index=True, width="stretch", height=300)
    ui.note("Fit demand served = engagements started ÷ fit requests (before any policy). Costs are illustrative: "
            "$6.7k per FDE-week loaded, $8k per partner week.")
