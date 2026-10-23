"""Visual system for the dashboard, adapted from The Economist's visual style guide (v1.2, May 2017).

What's borrowed: white background; a red tag and hairline red rule above every chart; a short bold
title with a plain subtitle naming the units; horizontal gridlines only, labels on the right; a
black baseline; a light source line underneath; neutral shaded panels for forecasts; red for
reference lines; the web palette's hues and greys; number boxes on the box/nav grey.

What's adapted: the series palette is the guide's colour order (blue, cyan, yellow, dark red),
with yellow taken one step darker on the guide's own equal-lightness scale so the set passes the
dataviz skill's colorblind checks; the guide's green and purple read as grey at every step, so
categories past four fold into the guide's neutral greys. Cyan and yellow sit below 3:1 contrast
on white, so every chart carries a legend or direct labels and a table view. Econ Sans and Milo
are licensed; Fira Sans / Fira Sans Condensed and Source Serif 4 stand in (see .streamlit/config.toml).
No logo or wordmark is used.
"""
from __future__ import annotations

import html

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------- tokens (Economist web palette)
SURFACE = "#FFFFFF"
BOX = "#E9EDF0"            # boxes / nav; forecast highlight panels
ECON_RED = "#E3120B"       # tag and rule only
REF_RED = "#DB444B"        # reference lines (targets, zero, index)
INK = "#0C0C0C"            # titles, baseline, ticks
INK_2 = "#3F5661"          # body and label text
MUTED = "#758D99"          # secondary text, de-emphasis, neutral category 1
GRID = "#B7C6CF"           # gridlines, neutral category 2
AXIS = GRID
SERIES = ["#006BA2", "#3EBCD2", "#C89608", "#A81829"]    # fixed order; validated (adjacent and all-pairs)
NEUTRAL = [MUTED, GRID]                                   # categories past four, 'other'
BLUE_RAMP = {250: "#5DA4DF", 450: "#1270A8", 650: "#00588D"}   # ordinal, validated --ordinal
STATUS = {"good": ("#0ca30c", "✓"), "warning": ("#fab219", "!"), "critical": ("#d03b3b", "✕")}
FONT = '"Fira Sans", system-ui, -apple-system, "Segoe UI", sans-serif'
FONT_CND = '"Fira Sans Condensed", "Fira Sans", system-ui, sans-serif'
SERIF = '"Source Serif 4", Georgia, serif'
AS_OF_DIVIDER = "2026-09-16"   # between the last actual month and the first forecast month
SOURCE = "Source: made-up FDE warehouse (history); FDE capacity model (forecast)"


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


CSS = f"""
<style>
  @import url("https://fonts.googleapis.com/css2?family=Fira+Sans+Condensed:wght@300;400;500;600;700&display=swap");
  .block-container {{ padding-top: 2.4rem; max-width: 1240px; }}
  /* page masthead: fly title, serif headline, standfirst */
  .ec-fly {{ color: {ECON_RED}; font-family: {FONT}; font-size: 0.78rem; font-weight: 600;
            letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 0.15rem; }}
  .ec-h1 {{ font-family: {SERIF}; font-weight: 700; font-size: 2.3rem; line-height: 1.1; color: {INK};
           margin: 0 0 0.35rem 0; }}
  .ec-standfirst {{ font-family: {SERIF}; font-size: 1.06rem; color: {INK_2}; margin-bottom: 1rem; }}
  /* number boxes */
  .tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(175px, 1fr)); gap: 12px; margin: 0.4rem 0 6px; }}
  .tile {{ background: {BOX}; padding: 16px 16px 10px; min-height: 150px; display: flex; flex-direction: column;
          position: relative; }}
  .tile::before {{ content: ""; position: absolute; left: 0; top: 0; width: 26px; height: 5px; background: {ECON_RED}; }}
  .tile-label {{ color: {INK_2}; font-size: 0.82rem; line-height: 1.25; min-height: 2.5em; margin-bottom: 2px; }}
  .tile-value {{ color: {INK}; font-size: 2rem; font-weight: 600; line-height: 1.1; }}
  .tile-range {{ color: {INK_2}; font-family: {FONT_CND}; font-size: 0.8rem; margin-top: 3px; }}
  .tile-status {{ color: {INK_2}; font-size: 0.8rem; margin-top: 6px; display: flex; gap: 6px; align-items: center; }}
  .tile-status .icon {{ display: inline-flex; width: 16px; height: 16px; border-radius: 50%; flex: none;
          align-items: center; justify-content: center; color: #fff; font-size: 0.68rem; font-weight: 700; }}
  .tile svg {{ display: block; margin-top: auto; padding-top: 8px; width: 100%; }}
  /* chart header: red tag + hairline rule, bold title, plain subtitle */
  .ec-head {{ margin-top: 1.1rem; }}
  .ec-rule {{ position: relative; border-top: 1px solid {ECON_RED}; height: 10px; }}
  .ec-rule::before {{ content: ""; position: absolute; left: 0; top: -1px; width: 28px; height: 7px; background: {ECON_RED}; }}
  .ec-title {{ font-family: {FONT}; font-weight: 700; font-size: 1.08rem; color: {INK}; line-height: 1.25; }}
  .ec-sub {{ font-family: {FONT}; font-size: 0.9rem; color: {INK}; margin-top: 1px; }}
  .ec-source {{ font-family: {FONT_CND}; font-weight: 300; font-size: 0.8rem; color: {INK_2}; margin-top: 2px; }}
  .ec-note {{ font-family: {FONT}; font-size: 0.84rem; color: {INK_2}; }}
  h3 {{ font-weight: 700 !important; margin-top: 1.2rem !important; }}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def masthead(fly: str, title: str, standfirst: str):
    st.markdown(f'<div class="ec-fly">{html.escape(fly)}</div><div class="ec-h1">{html.escape(title)}</div>'
                f'<div class="ec-standfirst">{html.escape(standfirst)}</div>', unsafe_allow_html=True)


def note(text: str):
    st.markdown(f'<div class="ec-note">{text}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ number formats
def pct(v, digits=0):
    return f"{v * 100:.{digits}f}%"


def num(v, digits=0):
    return f"{v:,.{digits}f}"


def money(v):
    for div, suffix in ((1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if abs(v) >= div:
            return f"${v / div:.1f}{suffix}"
    return f"${v:,.0f}"


# ------------------------------------------------------------------ number boxes
def sparkline_svg(values, highlight: slice | None = None, width=180, height=34) -> str:
    """P50 path in the de-emphasis grey, the highlighted window in blue."""
    v = np.asarray(values, dtype=float)
    lo, hi = np.nanmin(v), np.nanmax(v)
    span = hi - lo or 1.0
    xs = np.linspace(2, width - 2, len(v))
    ys = height - 3 - (v - lo) / span * (height - 6)
    pts = lambda idx: " ".join(f"{xs[i]:.1f},{ys[i]:.1f}" for i in idx)
    stroke = 'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"'
    out = [f'<polyline points="{pts(range(len(v)))}" fill="none" stroke="{MUTED}" {stroke}/>']
    if highlight is not None:
        idx = range(*highlight.indices(len(v)))
        out.append(f'<polyline points="{pts(idx)}" fill="none" stroke="{SERIES[0]}" {stroke}/>')
    return (f'<svg height="{height}" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
            f'aria-hidden="true">{"".join(out)}</svg>')


def status_for(p: float) -> str:
    return "good" if p >= 0.8 else "warning" if p >= 0.5 else "critical"


def stat_tile(label: str, value: str, range_text: str | None = None, status: tuple[str, str] | None = None,
              spark=None, highlight: slice | None = None) -> str:
    """status = (level, text) with level in good / warning / critical; always icon + label, never color alone."""
    parts = [f'<div class="tile"><div class="tile-label" title="{html.escape(label)}">{html.escape(label)}</div>',
             f'<div class="tile-value">{html.escape(value)}</div>']
    if range_text:
        parts.append(f'<div class="tile-range">{html.escape(range_text)}</div>')
    if status:
        color, icon = STATUS[status[0]]
        parts.append(f'<div class="tile-status"><span class="icon" style="background:{color}">{icon}</span>'
                     f'{html.escape(status[1])}</div>')
    if spark is not None:
        parts.append(sparkline_svg(spark, highlight))
    parts.append("</div>")
    return "".join(parts)


def tile_row(tiles: list[str]):
    """Number boxes in a grid that wraps to fit the width."""
    st.markdown(f'<div class="tiles">{"".join(tiles)}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ plotly
def layout(fig: go.Figure, height=320, yfmt=None, legend=True, right=8, hovermode="x unified", xrange=None):
    """Economist web chart: white, no title inside the plot (it lives in the header, units in the
    subtitle), horizontal grid only, y labels on the right, black baseline with short outside ticks."""
    fig.update_layout(
        template="none", height=height, margin=dict(l=4, r=right, t=30 if legend else 8, b=4),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family=FONT_CND, size=12, color=INK),
        hovermode=hovermode,
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=GRID, font=dict(color=INK, family=FONT_CND)),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, xanchor="left", font=dict(color=INK, size=12),
                    bgcolor="rgba(0,0,0,0)", traceorder="normal"),
        bargap=0.3,
    )
    fig.update_xaxes(showgrid=False, showline=True, linecolor=INK, linewidth=1, ticks="outside", ticklen=4,
                     tickcolor=INK, tickfont=dict(color=INK), automargin=True, range=xrange, zeroline=False)
    fig.update_yaxes(side="right", showgrid=True, gridcolor=GRID, gridwidth=1, zeroline=False, showline=False,
                     ticks="", tickfont=dict(color=INK), tickformat=yfmt, automargin=True, title=None)
    return fig


def fan(fig: go.Figure, x, q, color: str, name: str, fmt: str = ",.0f", band=True, end_label=True, dash=None):
    """q = (3, T) array of P10, P50, P90. Band is a light tint of the series hue; the P50 line is 2px."""
    p10, p50, p90 = q
    if band:
        fig.add_trace(go.Scatter(x=x, y=p90, mode="lines", line=dict(width=0), hoverinfo="skip",
                                 showlegend=False, legendgroup=name))
        fig.add_trace(go.Scatter(x=x, y=p10, mode="lines", line=dict(width=0), fill="tonexty",
                                 fillcolor=rgba(color, 0.16), hoverinfo="skip", showlegend=False, legendgroup=name))
    fig.add_trace(go.Scatter(
        x=x, y=p50, mode="lines", name=name, legendgroup=name,
        line=dict(color=color, width=2.2, shape="linear", dash=dash),
        customdata=np.stack([p10, p90], axis=1),
        hovertemplate=f"<b>%{{y:{fmt}}}</b> {name} <span style='color:{INK_2}'>(P10 %{{customdata[0]:{fmt}}} – P90 %{{customdata[1]:{fmt}}})</span><extra></extra>"))
    if end_label:
        label_end(fig, x[-1], p50[-1], f"{name} {format(p50[-1], fmt)}")
    return fig


def line(fig: go.Figure, x, y, color: str, name: str, fmt=",.0f", markers=False, end_label=False, width=2.2):
    fig.add_trace(go.Scatter(x=x, y=y, mode="lines+markers" if markers else "lines", name=name,
                             line=dict(color=color, width=width),
                             marker=dict(size=8, color=color, line=dict(color=SURFACE, width=2)),
                             hovertemplate=f"<b>%{{y:{fmt}}}</b> {name}<extra></extra>"))
    if end_label:
        label_end(fig, x[-1], y[-1], f"{name} {format(y[-1], fmt)}")
    return fig


def label_end(fig: go.Figure, x, y, text: str):
    """Direct label riding the line end, inside the plot (labels sit on the lines, not in a margin)."""
    fig.add_annotation(x=x, y=y, text=html.escape(text), showarrow=False, xanchor="right", yanchor="bottom",
                       yshift=5, font=dict(color=INK, size=12, family=FONT_CND))


def forecast_panel(fig: go.Figure, x0=AS_OF_DIVIDER, x1=None, label="FORECAST"):
    """Neutral highlight panel behind the forecast period, labelled in small capitals."""
    fig.add_vrect(x0=x0, x1=x1, fillcolor=BOX, line_width=0, layer="below")
    if label:
        fig.add_annotation(x=x0, xref="x", y=1, yref="paper", text=label, showarrow=False, xanchor="left",
                           yanchor="top", xshift=6, yshift=-4, font=dict(color=INK_2, size=10, family=FONT_CND))


def target_line(fig: go.Figure, y: float, text: str, x=None):
    """Reference lines are red, as in the guide's index/zero lines. The label sits at the left edge, or at
    data position `x` when the left edge is busy."""
    fig.add_hline(y=y, line=dict(color=REF_RED, width=1.2))
    fig.add_annotation(x=0 if x is None else x, xref="paper" if x is None else "x", y=y, text=html.escape(text),
                       showarrow=False, xanchor="left", yanchor="bottom", xshift=0 if x is None else 6,
                       font=dict(color=REF_RED, size=11, family=FONT_CND))


def chart(fig: go.Figure, title: str, subtitle: str | None = None, table: pd.DataFrame | None = None,
          note_text: str | None = None, source: str | None = SOURCE):
    """Header (tag, rule, title, subtitle) + chart + source line + optional note + table view."""
    head = f'<div class="ec-head"><div class="ec-rule"></div><div class="ec-title">{html.escape(title)}</div>'
    if subtitle:
        head += f'<div class="ec-sub">{html.escape(subtitle)}</div>'
    st.markdown(head + "</div>", unsafe_allow_html=True)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    foot = ""
    if source:
        foot += f'<div class="ec-source">{html.escape(source)}</div>'
    if note_text:
        foot += f'<div class="ec-note" style="margin-top:4px">{note_text}</div>'
    if foot:
        st.markdown(foot, unsafe_allow_html=True)
    if table is not None:
        with st.expander("Table view"):
            st.dataframe(table, width="stretch", hide_index=True)


def month_label(d) -> str:
    return pd.Timestamp(d).strftime("%b %Y")
