"""Outcomes: Day-90 productization (cohorts and forecast), the reuse flywheel, starts by type, consumption."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data
import ui
from model.params import TYPES

runs = data.current()
p, mc = runs["point"], runs["mc"]
W = data.WINDOW
months = mc.months
window_label = f"{ui.month_label(months[W.start])[:3]}–{ui.month_label(months[W.stop - 1])}"
targets = {t.metric: t for t in data.targets()}
calib = dict(data.query("SELECT param, value FROM v_calibration").itertuples(index=False))
forecast_end = pd.Timestamp(months[-1]) + pd.Timedelta(days=20)

cohorts = data.query("""
    SELECT date_trunc('quarter', cohort_month)::DATE AS quarter, sum(kicked_off) AS kicked_off,
           sum(live_by_d30) / sum(kicked_off) AS d30, sum(live_by_d60) / sum(kicked_off) AS d60,
           sum(live_by_d90) / sum(kicked_off) AS d90, bool_and(mature) AS mature
    FROM v_day90_cohorts GROUP BY 1 ORDER BY 1""")
reuse_hist = data.query("""
    SELECT date_trunc('quarter', closed_date)::DATE AS quarter, count(*) AS closed,
           sum(hours_saved) / sum(delivery_hours + hours_saved) AS reuse
    FROM v_cycle_times WHERE status = 'closed' AND reuse_ratio IS NOT NULL GROUP BY 1 ORDER BY 1""")
days_hist = data.query("""
    SELECT date_trunc('quarter', kickoff_date)::DATE AS quarter, count(*) AS live, avg(days_to_prod) AS mean_days
    FROM v_cycle_times, meta
    WHERE days_to_prod IS NOT NULL AND kickoff_date >= meta.history_start
      AND date_trunc('quarter', kickoff_date) + INTERVAL 3 MONTH + INTERVAL 120 DAY <= meta.as_of
    GROUP BY 1 ORDER BY 1""")
lib_hist = data.query("SELECT month, active_assets FROM v_asset_library_monthly ORDER BY month")
starts_hist = data.query("""
    SELECT date_trunc('quarter', kickoff_date)::DATE AS quarter, type, count(*) AS n
    FROM engagements, meta WHERE kickoff_date >= meta.history_start GROUP BY ALL ORDER BY 1""")
consumption = data.query("""
    SELECT months_from_golive, accounts, spend_index_median FROM v_consumption_curve
    WHERE months_from_golive BETWEEN -3 AND 12 ORDER BY 1""")
mid_quarter = lambda d: pd.Timestamp(d) + pd.Timedelta(days=45)
qlabel = lambda d: f"Q{pd.Timestamp(d).quarter}<br>{pd.Timestamp(d).year}"   # two-line axis label
plain = lambda s: s.replace("<br>", " ")                                        # same label for tables/text

# ---------------------------------------------------------------- number boxes
mature = cohorts[cohorts.mature]
last4 = mature.tail(4)
d90_actual = (last4.d90 * last4.kicked_off).sum() / last4.kicked_off.sum()


def window_q(metric, qs=(0.1, 0.5, 0.9)):
    return np.quantile(mc[metric][:, W].mean(axis=1), qs)


lo, mid, hi = window_q("day90")
prob = float(targets["day90"].met(mc).mean())
r_lo, r_mid, r_hi = window_q("reuse_ratio")
r_prob = float(targets["reuse_ratio"].met(mc).mean())
lib = np.quantile(mc["library"][:, -1], (0.1, 0.5, 0.9))
dd = window_q("mean_days_to_prod")
partner = mc["starts_partner_by_type"].sum(axis=(1, 2)) / mc["starts"].sum(axis=1)
ui.tile_row([
    ui.stat_tile("Day-90, last 4 mature quarters (actual)", ui.pct(d90_actual),
                 f"{int(last4.kicked_off.sum())} engagements, cancelled included", spark=mature.d90),
    ui.stat_tile(f"Day-90 forecast, {window_label}", ui.pct(mid), f"P10–P90  {ui.pct(lo)} – {ui.pct(hi)}",
                 (ui.status_for(prob), f"{prob:.0%} chance of ≥ {ui.pct(targets['day90'].threshold)}"),
                 mc.p50("day90"), W),
    ui.stat_tile(f"Reusable-asset ratio, {window_label}", ui.pct(r_mid), f"P10–P90  {ui.pct(r_lo)} – {ui.pct(r_hi)}",
                 (ui.status_for(r_prob), f"{r_prob:.0%} chance of ≥ {ui.pct(targets['reuse_ratio'].threshold)}"),
                 mc.p50("reuse_ratio"), W),
    ui.stat_tile(f"Asset library, {ui.month_label(months[-1])}", ui.num(lib[1]),
                 f"P10–P90  {ui.num(lib[0])} – {ui.num(lib[2])} · now {ui.num(lib_hist.active_assets.iloc[-1])}",
                 spark=mc.p50("library")),
    ui.stat_tile(f"Average days to production, {window_label}", ui.num(dd[1]),
                 f"P10–P90  {ui.num(dd[0])} – {ui.num(dd[2])}", spark=mc.p50("mean_days_to_prod"), highlight=W),
    ui.stat_tile("Spend 6 months after go-live", f"{calib['consumption_lift_m6']:.1f}×",
                 "vs the 3 months before kickoff (median account)"),
])
ui.note(f"Partner-led share of starts over 24 months: P50 {ui.pct(np.median(partner))}. Forecast Day-90 and reuse "
        "are for engagements starting each month; actual reuse is measured at close, so it trails by about one "
        "engagement.")

# ---------------------------------------------------------------- Day-90: actual cohorts + forecast | cohort curves
left, right = st.columns(2)
with left:
    q = mc.quantiles("day90")
    fig = go.Figure()
    ui.forecast_panel(fig, x1=forecast_end)
    fig.add_trace(go.Scatter(x=[mid_quarter(x) for x in mature.quarter], y=mature.d90, mode="lines+markers",
                             name="Actual (quarterly cohort)", line=dict(color=ui.SERIES[0], width=2.2),
                             marker=dict(size=8, color=ui.SERIES[0], line=dict(color=ui.SURFACE, width=2)),
                             customdata=mature.kicked_off,
                             hovertemplate="<b>%{y:.0%}</b> live by day 90 · %{customdata:.0f} kicked off<extra></extra>"))
    ui.fan(fig, months, q, ui.SERIES[0], "Forecast", fmt=".0%")
    ui.target_line(fig, targets["day90"].threshold, f"Target {ui.pct(targets['day90'].threshold)}",
                   x=ui.AS_OF_DIVIDER)
    ui.layout(fig, height=330, yfmt=".0%", legend=False, xrange=[mature.quarter.iloc[0], forecast_end])
    fig.update_yaxes(range=[0, 1])
    table = pd.concat([
        pd.DataFrame({"Period": [plain(qlabel(x)) for x in mature.quarter], "Kind": "Actual cohort", "P10": np.nan,
                      "P50": mature.d90, "P90": np.nan, "Kicked off": mature.kicked_off}),
        pd.DataFrame({"Period": [ui.month_label(m) for m in months], "Kind": "Forecast",
                      "P10": q[0], "P50": q[1], "P90": q[2], "Kicked off": np.nan})]).round(3)
    ui.chart(fig, "Day-90 productization", "% of engagements live in production within 90 days of kickoff; "
                                           "quarterly cohorts (actual), forecast P50 with P10–P90 range", table,
             "Cohorts of 6–19 engagements make the actual line jumpy (50%–83%, averaging ~69%). The forecast is the "
             "expected rate for the planned mix and staffing, a few points below that average and within the noise.")

with right:
    labels = [qlabel(x) for x in cohorts.quarter]
    fig = go.Figure()
    for col, name, step in (("d30", "By day 30", 250), ("d60", "By day 60", 450), ("d90", "By day 90", 650)):
        fig.add_trace(go.Bar(x=labels, y=cohorts[col], name=name,
                             marker=dict(color=ui.BLUE_RAMP[step],
                                         opacity=[1.0 if m else 0.35 for m in cohorts.mature]),
                             customdata=cohorts.kicked_off,
                             hovertemplate=f"<b>%{{y:.0%}}</b> {name.lower()} · %{{customdata:.0f}} kicked off<extra></extra>"))
    ui.layout(fig, height=330, yfmt=".0%")
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_xaxes(tickangle=0)
    fig.update_yaxes(range=[0, 1])
    ui.chart(fig, "How fast cohorts go live", "% of each quarterly kickoff cohort live by day 30, 60 and 90",
             cohorts.assign(quarter=[plain(x) for x in labels]).round(3),
             f"Cancelled engagements count as not live. {plain(labels[-1])} is faded: most of it hasn't reached day 90 yet.",
             source="Source: made-up FDE warehouse")

# ---------------------------------------------------------------- the flywheel, as small multiples
st.markdown("### The reuse flywheel")
ui.note("Finished engagements harvest assets → reuse covers more of each engagement → engagements finish sooner. "
        "Three measures on three scales, so three charts rather than one with two axes.")
cols = st.columns(3)
flywheel = [
    ("Assets in the library", "Active catalogued assets", "library", ",.0f", None, list(lib_hist.month),
     lib_hist.active_assets.to_numpy(), False),
    ("Reusable-asset ratio", "% of effort covered by assets", "reuse_ratio", ".0%", ".0%",
     [mid_quarter(q) for q in reuse_hist.quarter], reuse_hist.reuse.to_numpy(), True),
    ("Days to production", "Average, kickoff to production, days", "mean_days_to_prod", ",.0f", None,
     [mid_quarter(q) for q in days_hist.quarter], days_hist.mean_days.to_numpy(), True),
]
for col, (title, subtitle, metric, fmt, yfmt, hx, hy, markers) in zip(cols, flywheel):
    with col:
        q = mc.quantiles(metric)
        fig = go.Figure()
        ui.forecast_panel(fig, x1=forecast_end)
        ui.line(fig, hx, hy, ui.SERIES[0], "Actual", fmt=fmt, markers=markers)
        ui.fan(fig, months, q, ui.SERIES[0], "Forecast", fmt=fmt, end_label=False)
        ui.label_end(fig, months[-1], q[1][-1], format(q[1][-1], fmt))
        ui.layout(fig, height=250, yfmt=yfmt, legend=False, xrange=[pd.Timestamp("2025-04-01"), forecast_end])
        fig.update_yaxes(rangemode="tozero")
        table = pd.concat([
            pd.DataFrame({"Period": [pd.Timestamp(x).strftime("%b %Y") for x in hx], "Kind": "Actual",
                          "P10": np.nan, "P50": hy, "P90": np.nan}),
            pd.DataFrame({"Period": [ui.month_label(m) for m in months], "Kind": "Forecast",
                          "P10": q[0], "P50": q[1], "P90": q[2]})]).round(3)
        ui.chart(fig, title, subtitle, table, source=None)
st.markdown(f'<div class="ec-source">{ui.SOURCE}</div>', unsafe_allow_html=True)
ui.note("Actual reuse is effort-weighted at close (quarterly). Days to production is the average from kickoff to "
        "production for engagements that go live, blockers included; actuals are by kickoff quarter, shown only once "
        "a quarter is old enough that slow engagements have mostly finished.")

# ---------------------------------------------------------------- starts by type | consumption after go-live
left, right = st.columns(2)
with left:
    hist_w = starts_hist.pivot(index="quarter", columns="type", values="n").reindex(columns=TYPES).fillna(0)
    fq = pd.PeriodIndex(pd.to_datetime(months), freq="Q")
    starts = mc["starts_fde_by_type"] + mc["starts_partner_by_type"]          # (n, T, 3)
    by_q = [pd.DataFrame(starts[:, :, k].T, index=fq).groupby(level=0).sum() for k in range(3)]
    fc = np.stack([b.median(axis=1) for b in by_q], axis=1)
    labels = [qlabel(q) for q in hist_w.index] + [f"Q{q.quarter}<br>{q.year}" for q in by_q[0].index]
    vals = np.vstack([hist_w.to_numpy(), fc])
    fig = go.Figure()
    ui.forecast_panel(fig, x0=len(hist_w) - 0.5, x1=len(labels) - 0.5)
    for k, typ in enumerate(TYPES):
        fig.add_trace(go.Bar(x=labels, y=vals[:, k], name=typ,
                             marker=dict(color=ui.SERIES[k], line=dict(color=ui.SURFACE, width=1)),
                             hovertemplate=f"<b>%{{y:.0f}}</b> {typ}<extra></extra>"))
    ui.layout(fig, height=330)
    fig.update_layout(barmode="stack", bargap=0.3)
    fig.update_xaxes(tickangle=0, tickfont=dict(size=10))
    ui.chart(fig, "Engagements started", "Per quarter, by type; FDE- and partner-led; forecast quarters are P50",
             pd.DataFrame(vals, columns=TYPES).assign(Quarter=[plain(x) for x in labels],
             Kind=["Actual"] * len(hist_w) + ["Forecast P50"] * len(fc))[["Quarter", "Kind"] + TYPES].round(1),
             "Greenfield's share falls slowly as reuse grows.")

with right:
    fig = go.Figure()
    ui.line(fig, consumption.months_from_golive.to_numpy(), consumption.spend_index_median.to_numpy(), ui.SERIES[0],
            "Spend index", fmt=".1f", markers=True)
    fig.update_traces(customdata=consumption.accounts,
                      hovertemplate="<b>%{y:.1f}×</b> pre-kickoff spend · %{customdata} accounts<extra></extra>")
    fig.add_hline(y=1, line=dict(color=ui.REF_RED, width=1.2))      # index line
    fig.add_vline(x=0, line=dict(color=ui.INK_2, width=1))
    fig.add_annotation(x=0, y=1, yref="paper", text="Go-live", showarrow=False, xanchor="left", yanchor="top",
                       xshift=4, font=dict(color=ui.INK_2, size=11))
    m6 = consumption.set_index("months_from_golive").spend_index_median.get(6)
    if m6 is not None:
        fig.add_annotation(x=6, y=m6, text=f"{m6:.1f}× by month 6", showarrow=False, yshift=16,
                           font=dict(color=ui.INK, size=12))
    ui.layout(fig, height=330, legend=False)
    fig.update_xaxes(dtick=3, title=dict(text="Months from go-live", font=dict(color=ui.INK_2, size=11)))
    fig.update_yaxes(rangemode="tozero")
    ui.chart(fig, "Customer spend after go-live", "Median account spend as a multiple of the 3 months before kickoff",
             consumption.round(2), "Accounts with a production go-live; the count falls for later months because "
                                   "recent go-lives haven't reached them yet.",
             source="Source: made-up FDE warehouse (consumption)")
