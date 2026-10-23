# FDE Capacity Model & Dashboard — Build Plan

A working demo for the **GTM Strategy & Operations, FDE** role at Anthropic: a demand / capacity /
staffing model for a Forward Deployed Engineering team, backed by a SQL warehouse, with a
Monte Carlo layer that shows how certain the plan is at a given level of resourcing.

> All data in this repo is **made up**, generated from documented "truth" parameters
> (`config/synthetic_truth.yaml`) loosely calibrated to typical professional-services numbers.
> None of it is Anthropic data.

---

## 1. The story

FDE demand grows faster than the team can hire. Leadership has three levers: **hire**,
**partners**, and **productize**. Only productizing compounds: reusable assets shorten
engagements → day-90 productization rises → capacity frees up → partners can take
pattern-based work. The model shows what that costs up front (a J-curve) and when it pays back,
and the Monte Carlo layer turns "the gap is −310 FDE-weeks" into "there's a 64% chance we cover
Q3 demand; for 80% we need 3 more hires."

## 2. Master metrics

Full definitions in [docs/metric_dictionary.md](docs/metric_dictionary.md).

| Metric | Short definition |
|---|---|
| **Day-90 Productization Rate** | Share of a kickoff cohort live in production within 90 days of kickoff (cancelled engagements stay in the denominator) |
| **Reusable-Asset Ratio** (effort-weighted) | Hours saved by catalogued assets ÷ (hours actually spent + hours saved) |

## 3. Architecture

```
config/synthetic_truth.yaml ──▶ warehouse/generate.py ──▶ fde.duckdb (raw tables)
                                                              │
                                     warehouse/views.sql ─────┤  calibration views
                                                              ▼
config/assumptions.yaml  ◀──── calibrated defaults + distributions
        │
        ▼
model/engine.py   run_model(params) → monthly outputs (NumPy, vectorized over trials)
model/montecarlo.py  draw params → run N trials → percentiles, P(target)
model/engagement.py  single-engagement go-live simulator
        │
        ▼
app/ (Streamlit)  Scorecard · Supply · Outcomes · Confidence · Scenarios · Data & Definitions
```

### Repo layout

```
PLAN.md
requirements.txt
config/
  synthetic_truth.yaml     # parameters used to GENERATE the fake history
  assumptions.yaml         # forward-model inputs: value + distribution + source view
docs/
  metric_dictionary.md
warehouse/
  schema.sql               # raw tables
  views.sql                # analytic + calibration views
  generate.py              # simulates 18 months of FDE operations
  build.py                 # generate → load → create views → print summary
tests/
  test_warehouse.py        # integrity, metric definitions, views recover the truth parameters
  test_assumptions.py      # every `calibrated_from` assumption still matches v_calibration
model/   (Phase 2)
app/     (Phase 3)
```

## 4. Data layer (Phase 1)

18 months of history (2025-04-01 → 2026-09-30) simulated week by week: requests arrive,
get accepted or declined (fit, or capacity), wait for customer mobilization and staffing, kick
off, go live (or slip, or cancel), hand off, and harvest assets. FDEs are hired (managers added
to hold an 8:1 span), ramp, take PTO, and leave.

A 26-week warm-up runs before 2025-04-01 so the history opens with work in flight. Requests and
engagements from the warm-up stay in the tables (they're real prior records); time tracking and
all monthly views start at `meta.history_start`.

| Table | Grain |
|---|---|
| `roster` | one row per FDE (role, region, hire/term dates) |
| `requisitions` | one row per req (opened, filled, hired FDE) |
| `accounts` | one row per customer account (segment, region) |
| `partners` | one row per delivery partner |
| `fde_requests` | one row per inbound FDE request and its decision |
| `engagements` | one row per accepted engagement (dates, type, staffing, status) |
| `staffing` | FDE ↔ engagement assignments with allocation and dates |
| `time_entries` | FDE × week × category (deploy / presales / internal / harvest / pto / bench) hours |
| `assets` | catalogued reusable assets (type, source engagement, created / deprecated) |
| `asset_usage` | engagement ↔ asset, with effort hours saved |
| `consumption` | account × month API spend |

Views (`warehouse/views.sql`) produce both dashboard-ready tables and **calibration
views** that output distribution parameters (lognormal median/σ for durations, attach-rate
mean/variance, attrition hazard, time-to-fill quantiles), so model defaults trace back to SQL.

## 5. Model (Phase 2)

Monthly steps, 24-month horizon (2026-10 → 2028-09), by segment × region.

- **Gross demand (FDE-weeks)** = Σ requests × fit rate × mix_type × duration_type × FDEs_type
  (capacity declines are an *output* of the gap, not an input)
- **Headcount**: HC_t = HC_{t-1} + hires − attrition; **effective HC** = Σ heads × ramp factor
- **Deployable capacity** = effective HC × 4.33 × (1 − PTO − presales − internal − harvest)
  + partner weeks × efficiency (pattern-based and expansion work only)
- **Coverage** = capacity ÷ demand; uncovered demand → backlog; wait time via Little's Law
- **Asset library**: L_t = L_{t-1}(1 − decay) + completions_t × yield × (harvest share ÷ 5%)
- **Reuse ratio** (effort-weighted): R_t = R_max × (1 − e^(−L_t / k)); Greenfield gets R_t × 0.4
- **Effective duration**: D_t = D_base_type × (ref_FDEs ÷ FDEs)^α × (1 − R_t)
- **Day-90 rate** = P(lognormal(median D_t, σ) + blocker delay ≤ 90 days) × (1 − cancel rate)

The reuse ratio already measures *effort covered by assets*, so it reduces duration directly
(no separate "time saved" factor).

## 6. Monte Carlo layer (Phase 2b)

**One engine, two modes.** `run_model(params)` is written in NumPy so every parameter can be
a scalar (single-value / P50 mode) or an array of N draws (Monte Carlo mode). No separate code
path to keep in sync. Fixed seed for repeatable demos; 2,000–5,000 trials in under a second.

**A. Portfolio level — "is the plan resourced well enough?"** Each trial runs the full 24-month
model with drawn inputs → distributions of gap, coverage, utilization, day-90, reuse, hires needed.

**B. Engagement level — "when will this customer go live?"** For a given type, staffing level,
and asset use:
duration = base × (ref ÷ FDEs)^α × (1 − R) × lognormal noise + Bernoulli(blocker) × blocker delay
→ P50/P80/P90 go-live date and P(live by day 90) for 1 / 2 / 3 FDEs, with and without assets.

| Uncertain input | Distribution | Calibrated from |
|---|---|---|
| Demand growth | Triangular | `v_demand_monthly` |
| Attach rate | Beta | `v_demand_monthly` |
| Engagement duration | Lognormal per type | `v_duration_fit` |
| Attrition | Binomial per head per month | `v_headcount_monthly` |
| Time to fill, ramp | Triangular | `v_time_to_fill` |
| Partner efficiency | Triangular | `v_cycle_times` (partner vs FDE-led) |
| Harvest yield | Poisson | `v_asset_library_monthly` |
| Customer blockers | Bernoulli × lognormal delay | `v_cycle_times` |

One correlation is modeled: demand growth ↔ greenfield share. Everything else is treated as
independent and called out as a simplification.

## 7. Dashboard (Phases 3–4)

Streamlit + Plotly, deployed to Streamlit Community Cloud, with an Excel export.

1. **Scorecard** — KPI tiles (Day-90, Reuse, Coverage, Utilization, Gap, Hires needed), each
   with a P10–P90 range under the P50; demand vs capacity; capacity waterfall; levers.
2. **Supply** — headcount bridge by region × role; ramp-adjusted effective HC.
3. **Outcomes** — day-90 cohort curves (30/60/90), flywheel (library ↗, reuse ↗, duration ↘),
   consumption after go-live.
4. **Confidence** — P(target) tiles, **confidence-vs-resources curve** (x = hires/qtr or partner
   weeks, y = P(coverage ≥ 90%)), demand/capacity fan chart, engagement planner (go-live CDF by
   staffing), Monte Carlo tornado.
5. **Scenarios** — Base / Hire-heavy / Partner-leverage / Productize compared on medians *and*
   spread.
6. **Data & Definitions** — metric dictionary, SQL views, assumption → source table.
7. *(Stretch)* **Ask Claude** — plain-language explanation of scenario differences via the Claude API.

## 8. Phases

| Phase | Deliverable | Status |
|---|---|---|
| 1 | Plan, metric dictionary, assumptions with distributions, data generator, DuckDB tables + views, tests | **done** |
| 2 | Vectorized model engine + tests (zero spread ⇒ Monte Carlo = single-value; same seed ⇒ same output) | next |
| 2b | Monte Carlo runner, engagement simulator, percentile summaries | |
| 3 | Dashboard pages 1–3 | |
| 4 | Confidence page, scenarios, tornado, Excel export, definitions page | |
| 5 | Deploy, 1-page memo, 7-minute demo script, optional Ask Claude panel | |

## 9. Demo script (~8.5 minutes)

1. **Definitions first (1 min)** — what counts as productionized; why cancelled engagements stay in the denominator.
2. **Base case (1 min)** — demand outpaces capacity; the gap opens in Q2.
3. **Hire-heavy (1 min)** — closes the gap, but ramp and attrition delay it; show the cost.
4. **Partner-leverage (1 min)** — helps only as far as pattern-based work exists; reuse caps it.
5. **Productize at 12% harvest (2 min)** — dip in Q1–Q2, then reuse rises, cycle times fall,
   day-90 climbs, gap closes by Q4 without extra hires.
6. **Confidence (1.5 min)** — "That's the median. At today's hiring there's only a 58% chance.
   At P80 we need 3 more hires *or* 20 more partner weeks. For any one customer, here's the P80
   go-live date to put in the SOW."
7. **Recommendation (1 min)** — blended plan + the 3 assumptions to validate first with real data.

## 10. How to run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python warehouse/build.py      # builds fde.duckdb and prints a summary
.venv/bin/python -m pytest tests -q
```
