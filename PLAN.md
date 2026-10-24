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
  recommendation_memo.md      # 1-page memo (source); recommendation_memo.pdf is built from it
scripts/
  build_memo_pdf.py           # Markdown -> styled HTML -> PDF (WeasyPrint, or headless Brave/Chrome)
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
  export.py                # Excel workbook: README, assumptions, monthly plan, Monte Carlo, scenarios, calibration
  views/                   # scorecard, supply, outcomes, confidence, scenarios, definitions
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
- **Prioritization lever** (`demand.intake`): share of fit requests of each type taken on; the rest are
  turned down up front ("declined by policy", counted apart from capacity declines). Greenfield
  intake is the slider: Greenfield is ~3× the effort of pattern-based work and partners can't take it,
  so at 80% intake the team *starts more engagements* (~300 vs ~285 over 24 months) for the same cost.
  Coverage is measured against the demand taken on; "fit demand served" reports the share of all fit
  demand actually started.
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

**Built (Phase 4).** The filter row gained a fourth lever, **Greenfield intake** (the prioritization lever).

4. **Confidence** — page controls for the coverage target (60–100%) and commit level (P50/P80/P90).
   Boxes: chance of each target, coverage you can commit to, hires/month needed for that confidence,
   FDEs short at the commit level. **Confidence-vs-resources curves** for hires/month (0–8) and partner
   weeks (0–80), 1,000 paired trials per point, current setting marked; FDEs short over time at
   P50/P80/P90; **engagement planner** (type, asset library on/off, kickoff date → share live by day
   for three staffing levels, and a "dates to put in the SOW" table with the P80 go-live date);
   **tornado** of the ten inputs that swing coverage most.
5. **Scenarios** — Base, Hire-heavy, Partner-leverage, Productize, **Prioritize** (80% Greenfield
   intake) and **Blended** (3.5 hires/mo, 45 partner weeks, 80% Greenfield intake), plus the current
   filter-row settings: dot-and-whisker charts for coverage, Day-90 and reuse; cost vs engagements
   delivered; a scorecard table (coverage with P10–P90, P(≥90%), P(≥80%), fit demand served,
   engagements, policy vs capacity declines, people, cost, cost per engagement).
6. **Data & definitions** — **Download the model (Excel)** (README, assumptions, monthly plan, Monte
   Carlo P10/P50/P90, scenarios, SQL calibration, for the current settings); every input with its
   distribution, source view and today's SQL value; each SQL view's code beside its live rows
   (read-only, fixed list of views — no free-form SQL on a public app); calibration; metric dictionary.
7. *(Stretch)* **Ask Claude** — plain-language explanation of scenario differences via the Claude API.

Known limits: light theme only (dark mode not yet stepped and validated); fonts load from Google
Fonts, so offline viewing falls back to system fonts; forecast Day-90 starts a few points below the
recent cohort average (within cohort noise).

## 8. Phases

| Phase | Deliverable | Status |
|---|---|---|
| 1 | Plan, metric dictionary, assumptions with distributions, data generator, DuckDB tables + views, tests | **done** |
| 2 | Vectorized model engine + tests (zero spread ⇒ Monte Carlo = single-value; same seed ⇒ same output) | **done** |
| 2b | Monte Carlo runner, engagement simulator, percentile summaries | **done** |
| 3 | Dashboard pages 1–3 | **done** |
| 4 | Confidence page, scenarios (+ Prioritize, Blended, intake lever), tornado, Excel export, definitions page | **done** |
| 5 | 1-page memo (Markdown + PDF), demo script on the live pages, optional Ask Claude panel (deploy already done) | memo + script **done**; Ask Claude open |

## 9. Demo script (~10 minutes, on the live dashboard)

Live: https://jwells-fde-capacity-model.streamlit.app/ — **open it 5 minutes early** (it sleeps when
idle). Start on **Base**, all sliders at their defaults. Hand over the 1-page memo
(`docs/recommendation_memo.pdf`) at the end. Numbers below are from the current made-up data.

1. **Scorecard — the problem (1.5 min).** Define the two master metrics in one breath: Day-90 clock
   starts at kickoff and cancelled engagements stay in the denominator; reuse is effort-weighted.
   Then the tiles: coverage **61%**, a **9% chance** of 90% next half. "Demand is outrunning
   capacity": requests grow ~6%/month. Waterfall: 213 headcount weeks → 168 FDE weeks after ramp
   and the 15% buffer → 184 with partners, against 313 of demand.
2. **Supply — where the people are (1 min).** Headcount 40 → ~79 by Sep 2028 at today's hiring.
   **FDE coverage by region: APAC ~40% vs ~58% in AMER and EMEA** — where the next reqs go. "Where
   FDE time goes": harvest stepped from 3% to 7% in Jan 2026.
3. **Outcomes — what engagements produce (1 min).** Day-90: ~69% on actual cohorts, ~67% forecast.
   Flywheel as three small charts (no dual axes): library 38 → ~180, reuse 9% → ~20%, engagements
   getting shorter. Customer spend runs **5.1×** pre-kickoff by month 6 after go-live.
4. **Confidence — how sure are we (2 min).** Target 90%, commit level P80.
   - Confidence vs hiring: 2.3 hires/month → **8%**, 6 → **41%**, 8 → **61%**. "Hiring can't fix next
     half on its own; time to fill plus ramp is ~5 months." Partner capacity tops out near 20%.
   - FDEs short: **38 at P50, 57 at P80** — "the gap between those lines is the price of certainty."
   - Engagement planner, Greenfield, kickoff 2 Nov: 2 FDEs → P80 **136 days (17 Mar 2027)**; a third
     FDE → 106 days and day-90 odds **37% → 62%**. "Put the P80 date in the SOW."
   - Tornado: demand growth leads. "The forecast is worth validating before the hiring plan."
5. **Scenarios — the options (2 min).** Prioritize: taking 80% of Greenfield starts **300
   engagements vs 285 for the same cost** (Greenfield is ~3× the effort; partners can't take it).
   Show it live: drag **Greenfield intake** to 80% and watch coverage move. Blended: **88% median
   coverage, 65% chance of ≥80%, 373 engagements, +$13m**, and a lower cost per engagement
   ($160k vs $163k).
6. **Productize — the model challenged my hypothesis (1 min).** I expected productizing to compound.
   At 12% harvest it roughly breaks even (wins 16% of paired trials); the unmeasured reuse ceiling
   swings it from −14 to +41 engagements (`docs/productize_sensitivity.md`). So: hold harvest at
   7–9%, measure the ceiling for two quarters, and agree the decision rule now (≥ 40% → go to 12%).
7. **Data & definitions — every number traces back (30 s).** Filter to "Judgment or lever" to show
   what isn't calibrated; open the `v_calibration` SQL beside its rows; download the Excel model.
8. **Close (30 s).** The memo's five recommendations: Blended plan, commit at P80 (72% coverage),
   APAC reqs, measure-then-decide on productization, validate the demand forecast first.

**Likely questions**
- *Why made-up data?* No access to real data; the generator's settings are documented and the SQL
  calibration recovers them (tests check it), so the method is what's on show.
- *Coverage above 100% at P90?* Some trials have less demand than capacity; the band is honest about it.
- *Why does the Day-90 forecast start below recent cohorts?* Cohorts of 6–19 engagements swing
  50–83%; the forecast is the expected rate for the planned mix, inside that noise.
- *Biggest simplification?* Capacity vs demand is a monthly flow (exact in steady state, lags about
  one engagement when things change fast); unserved demand abandons at a judged 50%/month.
- *First thing you'd do with real data?* Fit demand growth properly, measure the reuse ceiling, and
  get partner efficiency from real partner-led engagements — the three inputs the tornado and the
  sensitivity analysis say matter most.

## 10. How to run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python warehouse/build.py      # builds fde.duckdb and prints a summary
.venv/bin/python -m pytest tests -q
.venv/bin/python -m model.run            # model report: plan, Monte Carlo, drivers, scenarios, planner
.venv/bin/streamlit run app/streamlit_app.py   # dashboard at http://localhost:8501
```

### Deploying (Streamlit Community Cloud)

- Live at https://jwells-fde-capacity-model.streamlit.app/ (redeploys on every push to `main`).
- Entry file: `app/streamlit_app.py`; branch `main`; Python 3.12 (Community Cloud's default —
  tested from a fresh clone with all 59 tests passing).
- Dependencies come from `requirements.txt`; theme and fonts from `.streamlit/config.toml` at the
  repo root. No secrets needed.
- `fde.duckdb` isn't committed: the app builds it on first launch (~1 s).
- Memory: Monte Carlo results are cached as float32 (~11 MB per lever setting), 8 settings at most.
