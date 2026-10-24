# FDE Capacity Model & Dashboard

A demand, capacity and staffing model for a Forward Deployed Engineering team, with a Monte Carlo
layer that shows how certain the plan is at a given level of resourcing, and a Streamlit dashboard
to explore it.

**Recommendation memo:** [docs/recommendation_memo.md](docs/recommendation_memo.md) ([PDF](docs/recommendation_memo.pdf))

**Live dashboard:** https://jwells-fde-capacity-model.streamlit.app/ (Streamlit Community Cloud; if it has
been idle it takes a moment to wake up)

> All data here is **made up**, generated from documented parameters (`config/synthetic_truth.yaml`).
> None of it is Anthropic data.

## What's inside

| Layer | What it does |
|---|---|
| `warehouse/` | Simulates 18 months of FDE operations into DuckDB (11 tables) and SQL views, including `v_calibration`, which turns the history into model inputs |
| `config/assumptions.yaml` | Forward-model inputs: each has a value, a distribution, the SQL view it was calibrated from, and a note on why its range is that wide |
| `model/` | Vectorized engine (24 monthly steps), Monte Carlo (2,000 trials in ~0.1 s), confidence curves, tornado, scenarios, single-engagement go-live simulator |
| `analysis/` | Sensitivity analysis showing the Productize result hinges on the unmeasured reuse ceiling |
| `app/` | Streamlit dashboard: Scorecard, Supply, Outcomes, Confidence, Scenarios, Data & definitions (with Excel export); a scenario + four levers scope every page |
| `tests/` | 66 tests: data integrity, metric definitions, calibration recovery, model mechanics, the prioritization lever, dashboard smoke tests, Excel export |

Master metrics: **Day-90 Productization Rate** and **Reusable-Asset Ratio** (definitions in
[docs/metric_dictionary.md](docs/metric_dictionary.md)). Build plan, model equations and the demo
script are in [PLAN.md](PLAN.md); the running decision log is in [Project Memory.md](Project%20Memory.md).

## Run it locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app/streamlit_app.py      # dashboard at http://localhost:8501
.venv/bin/python -m model.run                     # plain-text model report
.venv/bin/python -m pytest tests -q               # 66 tests
```

The dashboard builds the warehouse (`fde.duckdb`) on first launch if it isn't there.

## Design

Chart styling is adapted from *The Economist*'s public visual style guide (v1.2, 2017): red tag and
rule, short bold title with a units subtitle, right-hand axis labels, shaded forecast panels. The
palette is the guide's colour order, adjusted where needed to pass colorblind checks; Fira Sans and
Source Serif 4 stand in for the licensed typefaces. This is an independent demo, not affiliated
with *The Economist*.
