# Project Memory — FDE Capacity Model & Dashboard

A running record of decisions, actions taken, and what's next. Updated at the end of each
working session. The full build spec lives in [PLAN.md](PLAN.md); metric definitions live in
[docs/metric_dictionary.md](docs/metric_dictionary.md).

**Goal:** a working FDE capacity model and dashboard to demo for Anthropic's
[GTM Strategy & Operations, FDE](https://job-boards.greenhouse.io/anthropic/jobs/5427938008) role,
showing the posting's ask: "can build a capacity or staffing model from scratch, explain every
assumption in it, and pull the data yourself with SQL."

**Status (as of 2026-10-24, end of Session 4):** Phases 1–4 complete and Phase 5's core done: six-page
dashboard **live at [jwells-fde-capacity-model.streamlit.app](https://jwells-fde-capacity-model.streamlit.app/)**,
1-page recommendation memo ([Markdown](docs/recommendation_memo.md) · [PDF](docs/recommendation_memo.pdf)),
demo script on the live pages (PLAN.md §9). Repo public at
[github.com/erasbleasp/fde-capacity-model](https://github.com/erasbleasp/fde-capacity-model).

**Next session starts with:** whatever is left of Phase 5 — rehearse the demo (a dry run with Claude
playing interviewer is an option), link the dashboard and memo from the application / personal site,
and decide on the optional Ask Claude panel (needs your own API key as a Streamlit secret plus a
spending cap). See What's next.

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
| 18 | ~~GitHub repo is private for now~~ — superseded by 39 | — |
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
| 31 | **Report numbers show 2 decimal places** (user preference) | 3 decimals made counts read like `24.000`. |
| 32 | **Every tile and target uses one window: months 7–12 (Apr–Sep 2027)** | Day-90 and reuse used months 10–12; one window keeps the tiles and the report consistent. |
| 33 | **Dashboard = Streamlit multipage app; a filter row (scenario + hires, harvest, partner levers) sits above every page and scopes all of it** | One set of controls, numbers always agree across pages. Pages live in `app/views/` (a `pages/` folder triggers Streamlit's own sidebar). |
| 34 | **Charts follow the dataviz skill's method**: validated palette, legend or direct labels plus a table view on every chart, no dual axes (the flywheel is three small charts), status = icon + label | Readable for colorblind viewers and without hover; the method is what the skill checks. |
| 35 | **Added `mean_days_to_prod` (blockers included)** for actual-vs-forecast charts | The forecast "median" excluded blockers and dropped ~11 days at the forecast start; the mean matches the warehouse definition. |
| 36 | **Visual design adapted from The Economist's visual style guide (v1.2, May 2017)** — design-system.economist.com was blocked from this environment | Red tag + rule, bold title with units subtitle, right-hand axis labels, black baseline, shaded FORECAST panels, red reference lines, number boxes on #E9EDF0, serif masthead. |
| 37 | **Brand deviations**: yellow one step darker (#C89608); green and purple dropped (grey at every step, fail CVD) → greys for categories past four; Fira Sans / Fira Sans Condensed / Source Serif 4 stand in for licensed fonts; no logo; README says "not affiliated" | Every palette passes the dataviz validator (adjacent and all-pairs); no impersonation. |
| 38 | **Host on Streamlit Community Cloud**, linked or embedded from a personal site — not Vercel | Streamlit needs a long-running Python server with websockets; Vercel and static site hosts can't run it. Free, redeploys on push. |
| 39 | **Repo made public** (supersedes 18) | Simplest deploy path; lets interviewers read the code behind the dashboard. Nothing sensitive in the repo. |
| 40 | **Dashboard cache: Monte Carlo results as float32, 8 lever settings max (~90 MB)** | One run was ~22 MB; 24 cached settings risked ~500 MB on a free host. |
| 41 | **Prioritization lever `demand.intake` (Greenfield intake slider, 4th lever in the filter row)**: fit requests turned down up front are "declined by policy", tracked apart from capacity declines | The recommendation needs a prioritization option (posting: "scenarios for hiring and prioritization"). At 80% Greenfield intake the team starts more engagements (300 vs 285) for the same cost. |
| 42 | **Coverage is measured against demand taken on; "fit demand served" is shown beside it** | Turning demand down raises coverage by definition; the second measure keeps the comparison honest. |
| 43 | **New scenarios: Prioritize (80% Greenfield intake) and Blended (3.5 hires/mo, 45 partner weeks, 80% Greenfield intake)** | Blended: 88% median coverage, 65% chance of ≥80%, 373 engagements, +$13m over 24 months, lower cost per engagement. |
| 44 | **Confidence page has its own controls (coverage target, commit level P50/P80/P90)**; confidence curves use 1,000 paired trials per point | Page-scoped questions; same draws at every point so curves move only with the lever. |
| 45 | **No free-form SQL box on the public app** — the SQL tab shows a fixed list of views | A query box on a public server could read files on it. |
| 46 | **Excel export (openpyxl)**: README, assumptions, monthly plan, Monte Carlo P10/P50/P90, scenarios, SQL calibration, for the current settings | Decision 10 promised a finance-auditable export. |
| 47 | **Scenario comparison simulates each scenario once** (`scenario_table(extra=...)`) | First load of Scenarios / Data pages halved (1.24 s → 0.62 s locally); identical output. |
| 48 | **Streamlit watches `model/`, `warehouse/`, `config/` (folderWatchList) and `watchdog` is installed** | A push left stale `model/` code in memory on Streamlit Cloud (TypeError); a requirements change forced the restart. Fallback: Manage app → Reboot. |
| 49 | **Memo: Markdown is the source; the PDF is built by `scripts/build_memo_pdf.py` (WeasyPrint, falls back to headless Brave/Chrome)** | One source can't drift. Headless Brave was blocked by the command sandbox, so WeasyPrint was installed (Homebrew); `markdown` is a dev-only dependency. |
| 50 | **Answer to "reset the 90% target?": commit at P80 instead** — 72% coverage under Blended (49% today) | No plan in the memo has better-than-even odds of 90% next half. |

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

### Session 3 — 2026-10-23
- Report (`model/run.py`) switched to 2 decimal places.
- Built **Phase 3, the Streamlit dashboard** (`app/`): entry file with masthead and filter row;
  `data.py` (cached model runs, warehouse queries, builds `fde.duckdb` if missing); `ui.py` (design
  tokens, chart helpers, number boxes, table views); pages Scorecard, Supply, Outcomes in `app/views/`.
- Loaded the dataviz skill, validated the palette, checked every page in the browser, and fixed:
  deprecated arguments, label collisions, wrapping tiles, rotated quarter labels, and the
  days-to-production mismatch (decision 35).
- Added `tests/test_app.py` (every page renders; scenario switch moves the levers). **59 tests passing.**
- Restyled the dashboard on The Economist's chart style guide (decisions 36–37). The theme first
  crashed silently (Streamlit takes one font per URL); caught via the server log and fixed.
- Installed poppler (Homebrew) to read the style guide PDF.
- Prepared for Streamlit Community Cloud: README, deploy notes, leaner cache (decision 40); verified
  from a fresh copy on Python 3.12 (clean install, 59 tests, real server, warehouse built on launch).
- Made the repo public, user deployed to
  [jwells-fde-capacity-model.streamlit.app](https://jwells-fde-capacity-model.streamlit.app/); checked
  all three live pages match local numbers; added the link to README and PLAN.md.

### Session 4 — 2026-10-24
- Read Project Memory.md; repo clean, 59 tests passing.
- Added the **prioritization lever** (`demand.intake`, Greenfield intake slider) to the engine,
  assumptions and filter row, with policy declines, fit requests and fit demand weeks as outputs;
  added **Prioritize** and **Blended** scenarios; 3 new engine tests.
- Built **Phase 4** pages: **Confidence** (target + commit-level controls, P(target) boxes,
  confidence-vs-resources curves for hiring and partners, FDEs short at P50/P80/P90, engagement
  planner with SOW dates, tornado), **Scenarios** (dot-and-whisker comparisons, cost vs engagements,
  scorecard), **Data & definitions** (Excel download, assumptions with sources and live SQL values,
  SQL views with live rows, calibration, metric dictionary). New `app/export.py`.
- Checked every page in the browser; fixed tornado legend overlap, scenario label collisions,
  rounded "Now" marker. **66 tests passing.**
- Committed and pushed Phase 4 (`9123bf0`); verified live. Then halved the scenario comparison's work
  (`9131f6f`); the live app kept stale model code and errored, fixed with folderWatchList + watchdog
  (`431486c`) and verified live.
- Wrote the **1-page recommendation memo** (`docs/recommendation_memo.md` + PDF via
  `scripts/build_memo_pdf.py`); every number checked against a fresh model run.
- Rewrote PLAN.md §9 as a ~10-minute **demo script on the live pages**, with likely interview
  questions; README links the memo.

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
- FDE coverage by region (months 7–12): AMER ~58%, EMEA ~58%, **APAC ~40%** — where the next reqs should go.
- Prioritize (80% Greenfield intake): 300 engagements vs 285 for the same $46m; coverage of demand taken on 73%.
- Blended: coverage 88% (P10–P90 63–127%), 65% chance of ≥80%, 373 engagements, $59.7m (+$13m), $160k per engagement vs $163k; commit-at-P80 coverage 72% vs 49% today.
- Confidence vs hiring (90% target): 2.3/mo → 8%, 6 → 41%, 8 → 61%. FDEs short: 38 at P50, 57 at P80.
- Base figures shifted slightly after the intake lever was added (it draws its own random numbers): coverage odds 10% → 9%.

## What's next

- [x] **Push to GitHub**: private repo `erasbleasp/fde-capacity-model`
- [x] Make the repo public
- [x] **Phase 2: model engine** (`model/engine.py`)
- [x] **Phase 2b: Monte Carlo** (`model/montecarlo.py`, `model/engagement.py`)
- [x] Productize sensitivity analysis and reframed demo story
- [x] **Phase 3: dashboard pages 1–3** (Scorecard, Supply, Outcomes), Economist-style design
- [x] Deploy to Streamlit Community Cloud (pulled forward from Phase 5)
- [x] **Phase 4**: Confidence, Scenarios (+ Prioritize, Blended, Greenfield intake lever), Data & definitions, Excel export
- [ ] **Phase 5**
  - [x] 1-page recommendation memo (Markdown + PDF)
  - [x] Demo script rewritten on the live dashboard pages, with likely questions
  - [ ] Rehearse the demo (optionally a dry run with Claude playing the interviewer)
  - [ ] Link the dashboard and memo from the application / personal site
  - [ ] Optional: Ask Claude panel explaining scenario differences (needs your Anthropic API key as a Streamlit secret + a spending cap)

### Open questions
- Whether to add economics (fees, margin) beyond cost per engagement and consumption lift
- Dark mode for the dashboard (needs its own validated palette steps)

## How to resume

```bash
cd "/Users/jaeger/Claude/Projects/FDE model demo"
.venv/bin/python warehouse/build.py      # rebuild fde.duckdb (not committed)
.venv/bin/python -m pytest tests -q      # expect 66 passed
.venv/bin/python -m model.run            # model report (~2 s)
.venv/bin/streamlit run app/streamlit_app.py   # dashboard at http://localhost:8501
# live: https://jwells-fde-capacity-model.streamlit.app/ (redeploys on every push to main)
.venv/bin/python -m analysis.productize_sensitivity   # Productize sensitivity (~16 s)
.venv/bin/python scripts/build_memo_pdf.py   # rebuild the memo PDF (needs: pip install markdown; brew install weasyprint)
```
