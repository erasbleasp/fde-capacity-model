# Project Memory — FDE Capacity Model & Dashboard

A running record of decisions, actions taken, and what's next. Updated at the end of each
working session. The full build spec lives in [PLAN.md](PLAN.md); metric definitions live in
[docs/metric_dictionary.md](docs/metric_dictionary.md).

**Goal:** a working FDE capacity model and dashboard to demo for Anthropic's
[GTM Strategy & Operations, FDE](https://job-boards.greenhouse.io/anthropic/jobs/5427938008) role,
filling a resume gap: "can build a capacity or staffing model from scratch, explain every
assumption in it, and pull the data yourself with SQL."

**Status (as of 2026-10-23, end of Session 2):** Phases 1 and 2 of 5 complete (warehouse, model
engine, Monte Carlo, engagement simulator), plus a Productize sensitivity analysis and a reframed
demo story. Pushed to
[github.com/erasbleasp/fde-capacity-model](https://github.com/erasbleasp/fde-capacity-model) (private).

**Next session starts with:** Phase 3, the Streamlit dashboard (Scorecard, Supply, Outcomes pages).
See the checklist under What's next.

---

## Decisions

| # | Decision | Why |
|---|---|---|
| 1 | **Two master metrics: Day-90 Productization Rate and Reusable-Asset Ratio** | They map directly to the posting's "production launches" and "patterns partners reuse." |
| 2 | **Story = hire vs. partners vs. productize; only productizing compounds** (a flywheel with a J-curve) | A demo should argue one point. Harvest time is overhead today that turns into capacity 2–3 quarters later. |
| 3 | **Day-90 clock starts at kickoff, not signature; cancelled engagements stay in the denominator; only mature cohorts are reported** | Separates staffing-queue delays from delivery speed, and prevents gaming by cancelling slow engagements. |
| 4 | **Reuse ratio is effort-weighted**: hours saved ÷ (hours spent + hours saved), measured at close | Counting "used ≥ 1 asset" is easy to inflate. The count version stays as a leading indicator. |
| 5 | **Reuse ratio reduces duration directly**: D = D_base × (1 − R) | R already measures effort covered by assets, so a separate "time saved" factor would double count. |
| 6 | **Partners can only take Pattern-based and Expansion work** | Ties partner leverage to the reuse ratio, which is the posting's "move more work to delivery partners." |
| 7 | **Added a Monte Carlo layer** (user request) | To show how certain the plan is at a given level of resourcing: P50/P80/P90, P(target), and confidence-vs-resources curves. |
| 8 | **One engine, two modes**: `run_model(params)` in NumPy takes scalars (P50) or arrays of draws (Monte Carlo) | No second code path to keep in sync. Test: with zero spread, Monte Carlo must equal the single-value run. |
| 9 | **Two Monte Carlo levels**: portfolio ("is the plan resourced?") and single engagement ("P80 go-live date for the SOW") | Covers both leadership planning and customer commitments. |
| 10 | **Tech stack: Python + DuckDB + Streamlit**, with an Excel export | Shows SQL skill (the posting asks for it). Streamlit Community Cloud gives a shareable link. Excel lets finance audit it. |
| 11 | **All data is made up**, generated from documented settings (`config/synthetic_truth.yaml`) | No access to real data. Being upfront about it is better than implying real numbers. |
| 12 | **Model defaults are calibrated from SQL views**, and a test fails if they drift | "Explain every assumption" means every number traces to a view or is labeled as judgment. |
| 13 | **26-week warm-up before the history starts**; time tracking and monthly views begin 2025-04-01 | The first run started with an empty team (April 2025 utilization near 0%). |
| 14 | **Managers are hired to hold an 8:1 span** instead of being drawn at random | Random draws produced 2 managers who both quit. The posting asks about manager spans. |
| 15 | **Customer mobilization lag (5–30 days) before kickoff** | Without it, queue wait was 0 days, which is unrealistic. |
| 16 | **In the forward model, capacity declines are an output, not an input** (the input is fit rate, ~84%) | Declines happen because of the capacity gap; treating them as an input would be circular. |
| 17 | **Inputs labeled as judgment** (wide Monte Carlo ranges): staffing exponent α, reuse ceiling, reuse half-saturation k, partner efficiency | 100 engagements can't identify them. Saying so is part of the demo. |
| 18 | **GitHub repo is private for now** (`erasbleasp/fde-capacity-model`) | Make it public once it's polished enough to link in the application. |
| 19 | **Capacity and effort are both in staffing weeks** (one FDE assigned full time for one week) | The first build mixed delivery hours with calendar weeks and understated coverage. Overhead is already inside measured durations. |
| 20 | **Overhead acts by stretching durations relative to the calibration level** (`reference_delivery_share` = 0.70) | More harvest/presales/internal time means fewer delivery hours per staffed week, so engagements take longer. |
| 21 | **Capacity vs demand is a monthly flow** (staffing weeks needed by engagements starting this month vs weeks available) | Simple and explainable. Exact in steady state; lags about one engagement length when things change fast. |
| 22 | **Unserved demand: 50% walks away each month, the rest waits** (`backlog_abandon_rate`, judgment) | Produces capacity declines and a wait time (Little's Law) instead of assuming all excess demand is lost. |
| 23 | **Reuse half-saturation k = 60, calibrated through the model** (was 40, judgment) | k = 60 reproduces the measured 9% reuse at month 0; k = 40 gave 12%. |
| 24 | **Day-90 is computed analytically** (lognormal CDF, blocker delay integrated over 5 quantiles) | Fast enough for 2,000 trials; the engagement simulator samples the same formula and agrees within 1 pt (tested). |
| 25 | **Monte Carlo includes process noise** (Poisson requests and hires, binomial exits) **but paired scenario comparisons turn it off** | Random draws depend on state, so two runs lose their pairing and pick up about ±35 engagements of noise unrelated to the lever. |
| 26 | **Tornado = P10-to-P90 swing per input**, plus Spearman variance drivers from the Monte Carlo | The swing version is the easiest to explain; the Monte Carlo version catches what moves the spread. |
| 27 | **New judgment setting `overhead.harvest_from_slack`** (default 0 = current behavior) | Tests whether extra harvest time comes out of delivery hours or unassigned (bench) time. |
| 28 | **Story reframed: productizing hinges on the unmeasured reuse ceiling** | At current settings 12% harvest breaks even (wins 16% of paired trials); the ceiling alone swings it −14 to +41 engagements. Recommendation: hold harvest at 7–9%, measure the ceiling for 2 quarters, pre-commit to a decision rule (go to 12% if pattern-based coverage ≥ ~40% or greenfield reuse ≥ 60% of pattern-based). |
| 29 | **Capacity recommendation framed as commit level + prioritization**, not just a hiring number | No lever mix tested reaches 90% coverage next half (4.6 hires/mo + 45 partner weeks gives ~35% odds). Matches the posting's "scenarios for hiring and prioritization." |
| 30 | **Scenarios defined in `config/scenarios.yaml`**: Base, Hire-heavy (4.6 hires/mo), Partner-leverage (45 weeks/mo), Productize (12% harvest) | Overrides on assumptions.yaml keyed by dotted path; overriding an uncertain input pins it. |

## Actions taken

### Session 1 — 2026-10-22
- Read the job posting and pulled out the key requirements (capacity/staffing models, SQL, KPIs and scorecard, partner economics, Claude Code).
- Drafted the model design (inputs, equations, outputs), dashboard layout, and demo script. Added the Monte Carlo layer at the user's request.
- Wrote **PLAN.md** (build spec) and **docs/metric_dictionary.md**.
- Built the **made-up data warehouse**:
  - `warehouse/generate.py`: weekly simulation of requests, decisions, staffing, kickoffs, slips, cancellations, attrition, hiring, PTO, time entries, asset harvest and decay, and consumption.
  - `warehouse/schema.sql`: 11 raw tables. `warehouse/views.sql`: 17 views, including `v_calibration`.
  - `warehouse/build.py`: generate → load into DuckDB → create views → print the calibration (about 1 second).
- Wrote **config/assumptions.yaml**: forward-model inputs, each with a value, distribution, source, and note.
- Wrote **tests**: 35 passing (integrity, metric definitions, truth recovery, assumption drift).
- Ran `git init` and made the first commit on `main`.
- Installed the GitHub CLI (Homebrew), logged in as `erasbleasp`, set Git to use that login, and created the private repo `fde-capacity-model`. Pushed `main`.
- Session ended with all work committed and pushed; tests at 35 passing.

### Session 2 — 2026-10-23
- Read Project Memory.md, confirmed the repo was clean, rebuilt the warehouse (35 tests passing).
- Added engine inputs to `config/assumptions.yaml` (greenfield share as uncertain, backlog abandon
  rate, hiring region mix, senior share of hires, ICs still ramping, `per_engagement` flags) and
  created `config/scenarios.yaml`.
- Built **Phase 2**:
  - `model/params.py`: loads assumptions, applies overrides, draws inputs through a Gaussian copula
    (demand growth ↔ greenfield share at 0.5 rank correlation).
  - `model/engine.py`: `run_model()`, 24 monthly steps (supply, capacity, cycle time, demand,
    allocation, outcomes, flywheel). ~10 ms per run; 2,000 trials in ~0.1 s.
  - `model/montecarlo.py`: P(target), fan bands, confidence-vs-resources curves, tornado, variance
    drivers, scenario table.
  - `model/engagement.py`: single-engagement go-live simulator and staffing table.
  - `model/run.py`: plain-text report (`python -m model.run`).
- Fixed the staffing-weeks unit mismatch, calibrated k = 60, and corrected a loose test.
- Wrote `tests/test_model.py` (20 tests): zero spread ⇒ Monte Carlo = single value, same seed ⇒ same
  output, flat headcount with no hires/attrition, hires land after time to fill, manager span,
  flow identities, partners never serve Greenfield, month 0 matches history, levers move the right
  way, correlation, draw bounds, simulator matches engine. **55 tests passing.**
- Found that Productize (12% harvest) roughly breaks even, then ran a **sensitivity analysis**
  (`analysis/productize_sensitivity.py`, write-up in `docs/productize_sensitivity.md`): one setting
  at a time with k re-fitted, two-way grid, favorable combination, paired Monte Carlo, harvest curve.
- Added the commit email to the `erasbleasp` GitHub account; confirmed all commits now link to it.
- Rewrote PLAN.md's story (section 1) and 9-minute demo script (section 9) around the reframed
  story, with every number checked against model output. Updated PLAN.md's model section and the
  metric dictionary to match the engine.

### What the data shows (useful in the demo)
- About 30% of requests that fit were declined in the last 6 months because the team was full, even with about 12% of FDE time unassigned.
- The reuse ratio went from about 5% to about 9% after harvest time rose from 3% to 7% in January 2026. The library holds about 38 assets.
- Day-90 productization is about 69% across mature cohorts. Spend is about 5× pre-kickoff 6 months after go-live.
- Headcount is 40 (20 FDE, 14 Senior FDE, 6 Eng Manager). Time to fill is about 70 days (P50). Measured attrition is about 23%, which is noisy on a team this size.

### What the model shows (base plan, made-up data)
- Month 0 matches the history: Day-90 0.64 (0.69 measured), reuse 0.09, FDE utilization 0.58, headcount 41.
- Requests grow ~6%/month (13 → ~50); hiring at 2.3/month takes headcount 41 → ~77. Coverage ~62% → ~40%.
- P(coverage ≥ 90%, months 7–12) ≈ 10%. Confidence curve: 2 hires/mo → 7%, 4 → 22%, 6 → 41% (≈5-month hiring lag).
- Demand inputs drive the uncertainty: monthly growth alone is ~45% of the variance in coverage.
- Hire-heavy: coverage ~76%, +$16M over 24 months. Partner-leverage: ~66%, +32 engagements, +$5M.
- Productize: reuse +3 pts, coverage and Day-90 flat; the reuse ceiling decides whether it pays (see decision 28).
- Greenfield with 2 FDEs: P50 ~99 days, P80 ~136, 37% live by day 90; a third FDE → P80 ~106, 62%, for ~16% more staffing weeks.

## What's next

- [x] **Push to GitHub**: private repo `erasbleasp/fde-capacity-model`
- [ ] Make the repo public before linking it in the application
- [x] **Phase 2: model engine** (`model/engine.py`)
- [x] **Phase 2b: Monte Carlo** (`model/montecarlo.py`, `model/engagement.py`)
- [x] Productize sensitivity analysis and reframed demo story
- [ ] **Phase 3: dashboard pages 1–3** (Scorecard, Supply, Outcomes) in Streamlit
  - [ ] Add `streamlit` and `plotly` to requirements; app reads the model and the DuckDB views
  - [ ] Show coverage as a 3-month rolling view (monthly demand is noisy) with P10–P90 bands
- [ ] Add a **Blended** scenario and a **prioritization lever** (fit rate / which types to accept) for the recommendation step
- [ ] **Phase 4**: Confidence page, Scenarios, Excel export, Data & Definitions page
- [ ] **Phase 5**: deploy to Streamlit Community Cloud, 1-page memo, rehearse the demo script, optional Ask Claude panel

### Open questions
- Whether to add economics (fees, margin) beyond cost per engagement and consumption lift
- Whether the 90% coverage target should be reset, given no lever mix reaches it next half
- `model/run.py` prints counts with 3 decimals (e.g. 24.000); tidy the formatting

## How to resume

```bash
cd "/Users/jaeger/Claude/Projects/FDE model demo"
.venv/bin/python warehouse/build.py      # rebuild fde.duckdb (not committed)
.venv/bin/python -m pytest tests -q      # expect 55 passed
.venv/bin/python -m model.run            # model report (~2 s)
.venv/bin/python -m analysis.productize_sensitivity   # Productize sensitivity (~16 s)
```
