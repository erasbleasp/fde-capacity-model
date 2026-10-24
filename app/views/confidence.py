"""Confidence: how certain the plan is at a given level of resourcing.

P(target) boxes, confidence-vs-resources curves, FDEs short at P50/P80/P90, the engagement
planner (go-live dates for an SOW), and the tornado of what drives the uncertainty.
"""
import datetime as dt

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data
import ui
from model.engagement import summarize
from model.params import TYPES

runs = data.current()
p, mc = runs["point"], runs["mc"]
ov = data.overrides()
ovd = dict(ov)
W = data.WINDOW
months = mc.months
window_label = f"{ui.month_label(months[W.start])[:3]}–{ui.month_label(months[W.stop - 1])}"
targets = {t.metric: t for t in data.targets()}

# ---------------------------------------------------------------- page controls
c1, c2, _ = st.columns([1, 1, 2])
cov_target = c1.select_slider("Coverage target", options=[0.6, 0.7, 0.8, 0.9, 1.0], value=0.9,
                              format_func=ui.pct, key="conf_target")
commit = c2.segmented_control("Commit level", options=[0.5, 0.8, 0.9], default=0.8, key="conf_commit",
                              format_func=lambda q: f"P{int(q * 100)}") or 0.8
commit_label = f"P{int(commit * 100)}"
cov_t = data.Target("coverage", W.start, W.stop, ">=", cov_target)

# ---------------------------------------------------------------- number boxes
cov = cov_t.values(mc)
p_cov = float(cov_t.met(mc).mean())
p_d90 = float(targets["day90"].met(mc).mean())
p_reuse = float(targets["reuse_ratio"].met(mc).mean())
commit_cov = float(np.quantile(cov, 1 - commit))            # coverage you can commit to at this level
short = float(np.quantile(mc["hires_needed"][:, W].mean(axis=1), commit))
hire_values = tuple(float(v) for v in range(0, 9))
curve_h = data.confidence(ov, "supply.hires_per_month", hire_values, "coverage", cov_target)
reach = curve_h[curve_h.p_target >= commit]
hires_for_commit = f"{reach.lever_value.iloc[0]:.0f} / month" if len(reach) else "> 8 / month"
ui.tile_row([
    ui.stat_tile(f"Chance coverage ≥ {ui.pct(cov_target)}", f"{p_cov:.0%}", f"{window_label} average",
                 (ui.status_for(p_cov), "of 2,000 trials")),
    ui.stat_tile(f"Coverage you can commit to ({commit_label})", ui.pct(commit_cov),
                 f"{commit:.0%} of trials do at least this well"),
    ui.stat_tile(f"Hires needed for {commit:.0%} confidence", hires_for_commit,
                 f"to reach {ui.pct(cov_target)} coverage, everything else as set"),
    ui.stat_tile(f"FDEs short ({commit_label})", ui.num(short), "ramped FDEs to close the gap; hire ~5 months ahead"),
    ui.stat_tile("Chance Day-90 ≥ 75%", f"{p_d90:.0%}", window_label, (ui.status_for(p_d90), "of 2,000 trials")),
    ui.stat_tile("Chance reuse ≥ 25%", f"{p_reuse:.0%}", window_label, (ui.status_for(p_reuse), "of 2,000 trials")),
])
ui.note(f"Commit level: plan to the outcome that {commit:.0%} of trials meet or beat. "
        f"Targets are judged on the {window_label} average (months 7–12).")

# ---------------------------------------------------------------- confidence vs resources
partner_values = tuple(float(v) for v in range(0, 90, 10))
curve_p = data.confidence(ov, "partners.weeks_per_month", partner_values, "coverage", cov_target)
current = {"supply.hires_per_month": ovd.get("supply.hires_per_month"),
           "partners.weeks_per_month": ovd.get("partners.weeks_per_month")}
left, right = st.columns(2)
for col, curve, lever, title, xlab, fmt in [
        (left, curve_h, "supply.hires_per_month", "Confidence vs hiring", "Hires per month", "{:g}"),
        (right, curve_p, "partners.weeks_per_month", "Confidence vs partner capacity", "Partner weeks per month", "{:.0f}")]:
    with col:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=curve.lever_value, y=curve.p_target, mode="lines+markers", name="Confidence",
                                 line=dict(color=ui.SERIES[0], width=2.2),
                                 marker=dict(size=8, color=ui.SERIES[0], line=dict(color=ui.SURFACE, width=2)),
                                 customdata=np.stack([curve.p10, curve.p50, curve.p90], axis=1),
                                 hovertemplate=f"{xlab} %{{x}}: <b>%{{y:.0%}}</b> chance · coverage P50 "
                                               "%{customdata[1]:.0%} (P10 %{customdata[0]:.0%} – P90 %{customdata[2]:.0%})<extra></extra>"))
        x_now = current[lever]
        if x_now is not None:
            y_now = float(np.interp(x_now, curve.lever_value, curve.p_target))
            fig.add_trace(go.Scatter(x=[x_now], y=[y_now], mode="markers", name="Current setting",
                                     marker=dict(size=12, color=ui.SERIES[3], line=dict(color=ui.SURFACE, width=2)),
                                     hovertemplate=f"Current setting {fmt.format(x_now)}: <b>%{{y:.0%}}</b><extra></extra>"))
            fig.add_annotation(x=x_now, y=y_now, text=f"Now: {fmt.format(x_now)}", showarrow=False, xanchor="left",
                               xshift=10, yshift=-12, font=dict(color=ui.INK, size=12))
        ui.target_line(fig, commit, f"{commit:.0%} confidence")
        ui.layout(fig, height=310, yfmt=".0%", legend=False, hovermode="closest")
        fig.update_yaxes(range=[0, 1.02])
        fig.update_xaxes(title=dict(text=xlab, font=dict(color=ui.INK_2, size=11)))
        table = curve.rename(columns={"lever_value": xlab, "p_target": f"P(coverage ≥ {ui.pct(cov_target)})",
                                      "p10": "Coverage P10", "p50": "Coverage P50", "p90": "Coverage P90"}).round(3)
        ui.chart(fig, title, f"Chance coverage averages ≥ {ui.pct(cov_target)} over {window_label}, %; "
                             "1,000 trials per point", table,
                 "Everything else stays as set in the filter row. The same random draws are used at every point, "
                 "so the curve moves only because of the lever.")

# ---------------------------------------------------------------- FDEs short over time
q = mc.quantiles("hires_needed", (0.5, 0.8, 0.9))
fig = go.Figure()
for i, (lvl, step) in enumerate([("P50", 250), ("P80", 450), ("P90", 650)]):
    ui.line(fig, months, q[i], ui.BLUE_RAMP[step], lvl, fmt=",.0f", width=2.6 if lvl == commit_label else 1.8)
    ui.label_end(fig, months[-1], q[i][-1], f"{lvl} {q[i][-1]:,.0f}")
ui.layout(fig, height=320, xrange=[months[0], months[-1]])
fig.update_yaxes(rangemode="tozero")
ui.chart(fig, "How many FDEs short", "Ramped FDEs needed to close each month's gap, at P50, P80 and P90",
         pd.DataFrame({"Month": [ui.month_label(m) for m in months], "P50": q[0], "P80": q[1], "P90": q[2]}).round(1),
         "The gap between P50 and P80 is the price of certainty: the extra FDEs to plan for if you want to be "
         "right four times in five rather than half the time.")

# ---------------------------------------------------------------- engagement planner
st.markdown("### Engagement planner")
ui.note("When will one customer go live? Each line is 20,000 simulated engagements: engagement-to-engagement "
        "spread, customer blockers and cancellations, plus uncertainty in the inputs.")
e1, e2, e3 = st.columns([1.2, 1, 1])
eng_type = e1.selectbox("Engagement type", TYPES, key="plan_type")
assets = e2.toggle("Use the asset library", value=True, key="plan_assets")
kickoff = e3.date_input("Kickoff date", value=dt.date(2026, 11, 2), min_value=dt.date(2026, 10, 1),
                        max_value=dt.date(2028, 9, 30), key="plan_kickoff")
k_idx = max(0, min(len(months) - 1, (kickoff.year - months[0].year) * 12 + kickoff.month - months[0].month))
library = float(p["library"][0, k_idx - 1]) if k_idx > 0 else float(data.assumptions()["assets"]["starting_library"]["value"])

staffing = {"Greenfield": (1.0, 2.0, 3.0), "Pattern-based": (1.0, 1.5, 2.0), "Expansion": (0.5, 1.0, 1.5)}[eng_type]
fig = go.Figure()
rows = []
grid = np.arange(0, 241, 5)
for f, step in zip(staffing, (250, 450, 650)):
    days = data.engagement_days(ov, eng_type, f, assets, library)
    live = np.nan_to_num(days, nan=np.inf)
    share = [(live <= g).mean() for g in grid]
    name = f"{f:g} FDE" + ("s" if f != 1 else "")
    fig.add_trace(go.Scatter(x=grid, y=share, mode="lines", name=name, line=dict(color=ui.BLUE_RAMP[step], width=2.2),
                             hovertemplate=f"{name}: <b>%{{y:.0%}}</b> live by day %{{x}}<extra></extra>"))
    s = summarize(days)
    rows.append({"Staffing": name, "P50 days": s["p50_days"], "P80 days": s["p80_days"], "P90 days": s["p90_days"],
                 "P80 go-live date": (kickoff + dt.timedelta(days=int(round(s["p80_days"])))).strftime("%d %b %Y"),
                 "Live by day 90": s["p_live_by_deadline"], "Cancelled": s["p_cancel"],
                 "Staffing weeks (P50)": f * s["p50_days"] / 7})
fig.add_vline(x=90, line=dict(color=ui.REF_RED, width=1.2))
fig.add_annotation(x=90, y=0.02, yref="paper", text="Day 90", showarrow=False, xanchor="left", xshift=4,
                   yanchor="bottom", font=dict(color=ui.REF_RED, size=11))
ui.layout(fig, height=330, yfmt=".0%", hovermode="x unified")
fig.update_yaxes(range=[0, 1])
fig.update_xaxes(title=dict(text="Days from kickoff", font=dict(color=ui.INK_2, size=11)), dtick=30)
plan = pd.DataFrame(rows)
left, right = st.columns([1.3, 1])
with left:
    ui.chart(fig, f"{eng_type}: share live by day", f"% of simulated engagements in production, by staffing; "
                                                   f"kickoff {kickoff:%d %b %Y}", plan.round(2),
             "Cancelled engagements never go live, so no line reaches 100%.")
with right:
    st.markdown('<div class="ec-head"><div class="ec-rule"></div><div class="ec-title">Dates to put in the SOW</div>'
                '<div class="ec-sub">P80 = 4 in 5 engagements are live by then</div></div>', unsafe_allow_html=True)
    show = plan[["Staffing", "P50 days", "P80 days", "P80 go-live date", "Live by day 90", "Staffing weeks (P50)"]].copy()
    show["P50 days"] = show["P50 days"].round(0).astype(int)
    show["P80 days"] = show["P80 days"].round(0).astype(int)
    show["Live by day 90"] = (show["Live by day 90"] * 100).round(0).astype(int).astype(str) + "%"
    show["Staffing weeks (P50)"] = show["Staffing weeks (P50)"].round(0).astype(int)
    st.dataframe(show, hide_index=True, width="stretch")
    ui.note(f"Asset library at kickoff: {library:,.0f} assets (single-value plan). More FDEs finish sooner but "
            "use more staffing weeks; the speed-up per extra FDE is the judgment input α.")

# ---------------------------------------------------------------- tornado
tor = data.tornado_table(ov).head(10).iloc[::-1]
base = float(tor["base"].iloc[0])
fig = go.Figure()
fig.add_trace(go.Bar(y=tor.label, x=tor.at_low - base, base=base, orientation="h", name="Input at its P10",
                     marker=dict(color=ui.SERIES[0]), customdata=np.stack([tor.low_input, tor.at_low], axis=1),
                     hovertemplate="%{y} at P10 (%{customdata[0]:.3g}): coverage <b>%{customdata[1]:.0%}</b><extra></extra>"))
fig.add_trace(go.Bar(y=tor.label, x=tor.at_high - base, base=base, orientation="h", name="Input at its P90",
                     marker=dict(color=ui.SERIES[1]), customdata=np.stack([tor.high_input, tor.at_high], axis=1),
                     hovertemplate="%{y} at P90 (%{customdata[0]:.3g}): coverage <b>%{customdata[1]:.0%}</b><extra></extra>"))
fig.add_vline(x=base, line=dict(color=ui.INK, width=1))
ui.layout(fig, height=400, hovermode="closest")
fig.update_layout(barmode="overlay", bargap=0.35, margin=dict(t=8, b=36),
                  legend=dict(yanchor="top", y=-0.02))      # values run along the top, so the key sits below
fig.update_yaxes(side="left", showgrid=False, tickfont=dict(color=ui.INK))
fig.update_xaxes(side="top", tickformat=".0%", showgrid=True, gridcolor=ui.GRID, showline=False, ticks="")
ui.chart(fig, "What drives the answer", f"Coverage, {window_label} average, as each input moves from its P10 to its "
                                        f"P90 (all others at their value); base {ui.pct(base)}",
         tor.iloc[::-1][["label", "input", "low_input", "high_input", "at_low", "at_high", "swing"]].round(3),
         "The longest bars are where better data would narrow the plan most. Demand inputs lead, so the forecast "
         "is worth validating before the hiring plan is.")
