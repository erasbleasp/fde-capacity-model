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
**partners**, and **productize**. I went in expecting productizing to be the lever that
compounds. **The model showed it hinges on a number nobody has measured yet**, the reuse ceiling
(how much of an engagement reusable assets can ever cover). Below ~40% coverage, extra harvest
time costs more delivery hours than it saves. Above it, 12% harvest delivers +9 to +50 more
engagements over 24 months. So the recommendation isn't "productize harder." It's **hold harvest
at 7–9%, measure the ceiling for two quarters, and pre-commit to a decision rule.**

The Monte Carlo layer turns single numbers into commitments: "at today's hiring there's a 10%
chance we cover 90% of demand next half; here's what each lever buys, and here's the P80
go-live date to put in a customer's SOW."

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
  scenarios.yaml           # named scenarios = overrides on assumptions.yaml
docs/
  metric_dictionary.md
  productize_sensitivity.md   # does 12% harvest pay? depends on the reuse ceiling
analysis/
  productize_sensitivity.py   # one-at-a-time, combined, paired Monte Carlo, harvest curve
warehouse/
  schema.sql               # raw tables
  views.sql                # analytic + calibration views
  generate.py              # simulates 18 months of FDE operations
  build.py                 # generate → load → create views → print summary
tests/
  test_warehouse.py        # integrity, metric definitions, views recover the truth parameters
  test_assumptions.py      # every `calibrated_from` assumption still matches v_calibration
  test_model.py            # engine mechanics, calibration at month 0, levers, Monte Carlo, simulator
  test_app.py              # dashboard smoke test: every page renders; scenario switch moves the levers
model/
  params.py                # load assumptions, apply overrides, draw inputs (Gaussian copula)
  engine.py                # run_model(params): monthly steps, vectorized over trials
  montecarlo.py            # run_mc, P(target), fan bands, confidence curves, tornado, scenarios
  engagement.py            # single-engagement go-live simulator and staffing table
  run.py                   # plain-text report: python -m model.run
app/
  streamlit_app.py         # entry: header, filter row (scenario + 3 levers) scoping every page, navigation
  data.py                  # cached model runs (single-value + 2,000 trials) and warehouse queries
  ui.py                    # palette tokens, Plotly layout, fan charts, stat tiles, table views
  views/                   # scorecard.py, supply.py, outcomes.py
.streamlit/config.toml     # light theme + fonts (Economist-style palette and typography)
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

Monthly steps, 24-month horizon (2026-10 → 2028-09). Supply by region × role; demand by type
(region and segment are splits for reporting). Built in `model/engine.py`; runs in ~10 ms.

**Units: staffing weeks** — one FDE assigned full time for one week. Overhead (PTO, presales,
internal, harvest) is already inside measured durations, so it matters only when it moves away
from the calibration level (`reference_delivery_share` = 0.70).

- **Supply**: exits = HC × (1 − e^(−attrition/12)); reqs opened at the hiring rate land
  time-to-fill later (open reqs land over the first time-to-fill); hires ramp 25/50/75/100%;
  managers hired to hold the 8:1 span
- **Capacity** = Σ ICs × ramp × 4.33 × target utilization (0.85)
  + partner weeks × efficiency (Pattern-based and Expansion only)
- **Effective duration**: D = D_base × median uncertainty × overhead stretch × (ref_FDEs ÷ FDEs)^α × (1 − R_type),
  where stretch = 0.70 ÷ ((1 − PTO) × (1 − presales − internal − harvest))
- **Effort per engagement** = FDEs × (mean build weeks + ½ × blocker delay × P(blocker) + ½ × handoff) × (1 − 0.4 × cancel rate)
- **Demand** = requests × (1 + growth)^t × fit rate, split by type; Greenfield share = base − 0.8 × (reuse gain)
  (capacity declines are an *output* of the gap, not an input)
- **Allocation**: partners take eligible work first, FDEs the rest; unserved demand waits, and
  50% of it walks away each month (capacity declines). Wait = backlog ÷ starts (Little's Law)
- **Coverage** = capacity ÷ demand for engagements arriving this month (a monthly flow — exact
  in steady state, lags reality by about one engagement length when things change fast)
- **Asset library**: L_t = L_{t-1}(1 − decay) + completions_t × yield × (harvest share ÷ 5%);
  completions follow FDE-led starts with a first-order lag of one engagement length
- **Reuse**: R = R_max × (1 − e^(−L / k)), k = 60 (calibrated so month 0 reproduces the measured 9%);
  Greenfield gets R × 0.4. Model reuse ratio is reported on engagements *starting* that month
  (the measured metric is at close, so it lags by about one engagement)
- **Day-90 rate** = (1 − cancel) × [(1 − P(blocker)) × P(D ≤ 90) + P(blocker) × E_B P(D ≤ 90 − B)],
  with D lognormal(median, σ_type) and B integrated over 5 quantiles of the blocker distribution

The reuse ratio already measures *effort covered by assets*, so it reduces duration directly
(no separate "time saved" factor).

**Month 0 matches the history** (tests/test_model.py): Day-90 0.64 vs 0.69 measured, reuse 0.09,
utilization 0.58, headcount 41.

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

**Built (Phase 3).** A filter row — scenario plus three levers (hires per month, harvest time,
partner weeks per month) — sits above every page and scopes everything below it. Every tile and
target uses one window: months 7–12 (Apr–Sep 2027). Every chart has a table view.

**Visual design: adapted from The Economist's visual style guide** (v1.2, May 2017 — the
design-system.economist.com site was not reachable from this environment, so the 2017 chart guide
was the source):
- Each chart: red tag + hairline red rule, short bold title, plain subtitle naming units, horizontal
  gridlines only with labels on the right, black baseline with short ticks, light source line.
- Forecast periods are a neutral shaded "FORECAST" highlight panel; targets are red reference lines.
- Number boxes on the guide's box grey (#E9EDF0) with the red tag; serif masthead with a red fly title.
- Palette: the guide's colour order — blue #006BA2, cyan #3EBCD2, yellow, dark red #A81829 — with
  yellow one step darker on the guide's own scale (#C89608) so the set passes the dataviz validator
  (adjacent and all-pairs). The guide's green and purple read as grey at every step, so categories
  past four fold into the guide's greys (#758D99, #B7C6CF). Ordinal ramp from the guide's blue scale.
- Fonts: Econ Sans and Milo are licensed, so Fira Sans / Fira Sans Condensed and Source Serif 4 stand
  in (Google Fonts). No logo or wordmark.

1. **Scorecard** — six tiles (coverage, Day-90, reuse, utilization, gap, FDEs short at P80), each
   P50 with P10–P90 and P(target) as icon + label; demand vs capacity fan; 3-month rolling coverage
   vs the 90% target; capacity waterfall (headcount weeks → ramp → unassigned buffer → FDE capacity
   → partners → total, vs demand).
2. **Supply** — headcount actual + forecast; hires and exits by quarter (actual | forecast P50);
   headcount by region × role, now vs Sep 2028; FDE coverage by region (APAC is the thin one);
   where FDE time goes (actual monthly hours mix).
3. **Outcomes** — Day-90 actual quarterly cohorts + forecast; cohort curves (by day 30/60/90,
   ordinal blue ramp); flywheel as three small multiples (library, reuse, average days to
   production — actual + forecast); starts by type; customer spend after go-live.

Known limits: light theme only (dark mode not yet stepped and validated); fonts load from Google
Fonts, so offline viewing falls back to system fonts; forecast Day-90 starts a few points below the
recent cohort average (within cohort noise).
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
| 2 | Vectorized model engine + tests (zero spread ⇒ Monte Carlo = single-value; same seed ⇒ same output) | **done** |
| 2b | Monte Carlo runner, engagement simulator, percentile summaries | **done** |
| 3 | Dashboard pages 1–3 | **done** |
| 4 | Confidence page, scenarios, tornado, Excel export, definitions page | next |
| 5 | Deploy, 1-page memo, 7-minute demo script, optional Ask Claude panel | |

## 9. Demo script (~9 minutes)

Numbers below are from the current made-up data (`python -m model.run`,
`python -m analysis.productize_sensitivity`); regenerate them if inputs change.

1. **Definitions first (1 min)** — what counts as productionized; why cancelled engagements stay
   in the denominator; why reuse is effort-weighted. Point to the metric dictionary: every number
   traces to a SQL view or is labeled as judgment.
2. **Base case + confidence (1.5 min)** — requests grow ~6%/month (13 → ~50/month over 24 months)
   while hiring at 2.3/month takes headcount from 41 to ~77. Coverage starts at ~62% and falls to
   ~40%. "That's the median. The chance of covering 90% of demand in months 7–12 is about 10%."
   Tornado: the top three drivers are all demand (growth, current volume, greenfield share), so
   the forecast is what to validate first.
3. **Hire-heavy (1 min)** — confidence-vs-resources curve: 2 hires/month → 7%, 4 → 22%, 6 → 41%.
   Time to fill plus ramp is ~5 months, so hiring can't fix the next two quarters. Doubling
   hiring (4.6/month) lifts coverage to ~76% but adds ~$16M over 24 months.
4. **Partner-leverage (1 min)** — 45 partner weeks/month adds ~32 engagements and lifts coverage
   to ~66% for ~$5M. It only helps on pattern-based and expansion work, which caps it.
5. **Productize — the model challenged my hypothesis (2.5 min)**
   - At 12% harvest with current settings, Productize roughly breaks even: reuse is +3 pts, but the
     extra overhead stretches every engagement ~7% and the Base library saturates anyway
     (P(Productize wins) = 16%).
   - Sensitivity: one judgment call drives it. The reuse ceiling swings the result from −14 to +41
     engagements; nothing else comes close. Greenfield reuse and whether harvest comes out of bench
     time are next.
   - With each setting one plausible step more favorable: +50 engagements (+15%), breakeven in
     month 5, Day-90 +5 pts, cost per engagement −13%, P(win) = 100%.
   - "So the data can't yet tell a losing bet from a winning one — and that's measurable."
6. **Engagement planner (1 min)** — Greenfield with 2 FDEs: P50 ~99 days, P80 ~136, 37% live by
   day 90. A third FDE moves P80 to ~106 days and day-90 odds to 62% for ~16% more staffing
   weeks. "Put the P80 date in the SOW, and staff the third FDE where the deadline matters."
7. **Recommendation (1 min)**
   - **Capacity:** no lever reaches 90% coverage next half; even 4.6 hires/month plus 45 partner
     weeks gets ~35% odds (~80% median coverage, ~$68M over 24 months). Leadership has to choose a
     commit level and a prioritization bar, not just a hiring number.
   - **Productize:** hold harvest at 7–9% (optimal under current settings, so it costs nothing).
   - **Measure** for 2 quarters: hours saved per pattern-based engagement once the library has 60+
     assets, greenfield reuse, and whether harvest hours come from bench or delivery.
   - **Decision rule, agreed now:** if pattern-based coverage is ≥ ~40% (or greenfield builds reuse
     ≥ 60% as much as pattern-based ones), move harvest to 12%.

## 10. How to run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python warehouse/build.py      # builds fde.duckdb and prints a summary
.venv/bin/python -m pytest tests -q
.venv/bin/python -m model.run            # model report: plan, Monte Carlo, drivers, scenarios, planner
.venv/bin/streamlit run app/streamlit_app.py   # dashboard at http://localhost:8501
```
