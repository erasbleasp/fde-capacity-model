"""Excel export of the model for a finance reviewer: settings, assumptions, the single-value monthly
plan, Monte Carlo percentiles, the scenario comparison, and the SQL calibration."""
from __future__ import annotations

import io

import numpy as np
import pandas as pd

PLAN_COLUMNS = {
    "requests": "Requests", "fit_requests": "Fit requests", "declined_policy": "Turned down by policy",
    "demand_weeks": "Demand taken on (staffing wks)", "fde_capacity_weeks": "FDE capacity (wks)",
    "effective_capacity_weeks": "Total capacity incl. partners (wks)", "coverage": "Coverage",
    "gap_weeks": "Gap (wks)", "starts": "Engagements started", "declined": "Declined, team full",
    "backlog": "Backlog (engagements)", "wait_months": "Expected wait (months)", "hc_total": "Headcount",
    "hc_ic": "FDEs (ICs)", "hc_mgr": "Managers", "effective_ic": "Ramped FDEs", "hires": "Hires", "exits": "Exits",
    "utilization": "FDE utilization", "library": "Asset library", "reuse_ratio": "Reusable-asset ratio",
    "day90": "Day-90 productization", "mean_days_to_prod": "Avg days to production", "hires_needed": "FDEs short",
    "cost": "Cost ($)",
}
MC_METRICS = ["coverage", "demand_weeks", "effective_capacity_weeks", "hc_total", "hires_needed", "day90",
              "reuse_ratio", "starts"]


def build_workbook(settings: dict, assumptions: pd.DataFrame, point, mc, scenarios: pd.DataFrame,
                   calibration: pd.DataFrame) -> bytes:
    """Return an .xlsx file as bytes. `point` and `mc` are model Results; `settings` maps label -> value."""
    months = [pd.Timestamp(m).strftime("%Y-%m") for m in point.months]
    readme = pd.DataFrame({
        "Item": ["What this is", "Data", "Horizon", "Monte Carlo"] + list(settings),
        "Value": ["FDE capacity model export (single-value plan, Monte Carlo percentiles, scenarios, inputs)",
                  "Made up for a demo; not Anthropic data",
                  f"{months[0]} to {months[-1]}, monthly",
                  f"{mc.n:,} trials; P10/P50/P90 across trials"] + [str(v) for v in settings.values()],
    })
    plan = pd.DataFrame({label: point[k][0] for k, label in PLAN_COLUMNS.items()}, index=months)
    plan.index.name = "Month"
    mc_rows = []
    for k in MC_METRICS:
        q = np.quantile(mc[k], (0.1, 0.5, 0.9), axis=0)
        for i, m in enumerate(months):
            mc_rows.append({"Metric": PLAN_COLUMNS.get(k, k), "Month": m, "P10": q[0][i], "P50": q[1][i], "P90": q[2][i]})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        readme.to_excel(xw, sheet_name="README", index=False)
        assumptions.to_excel(xw, sheet_name="Assumptions", index=False)
        plan.round(4).to_excel(xw, sheet_name="Plan (single value)")
        pd.DataFrame(mc_rows).round(4).to_excel(xw, sheet_name="Monte Carlo", index=False)
        scenarios.round(4).to_excel(xw, sheet_name="Scenarios", index=False)
        calibration.round(4).to_excel(xw, sheet_name="SQL calibration", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:60])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
            ws.freeze_panes = "B2"
    return buf.getvalue()
