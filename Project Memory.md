# Project Memory — FDE Capacity Model & Dashboard

A running record of decisions, actions taken, and what's next. Updated at the end of each
working session. The full build spec lives in [PLAN.md](PLAN.md); metric definitions live in
[docs/metric_dictionary.md](docs/metric_dictionary.md).

**Goal:** a working FDE capacity model and dashboard to demo for Anthropic's
[GTM Strategy & Operations, FDE](https://job-boards.greenhouse.io/anthropic/jobs/5427938008) role,
filling a resume gap: "can build a capacity or staffing model from scratch, explain every
assumption in it, and pull the data yourself with SQL."

**Status (as of 2026-10-22, end of Session 1):** Phase 1 of 5 complete, pushed to
[github.com/erasbleasp/fde-capacity-model](https://github.com/erasbleasp/fde-capacity-model) (private).

**Next session starts with:** Phase 2, the model engine (`model/engine.py`). See the checklist under What's next.

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

### What the data shows (useful in the demo)
- About 30% of requests that fit were declined in the last 6 months because the team was full, even with about 12% of FDE time unassigned.
- The reuse ratio went from about 5% to about 9% after harvest time rose from 3% to 7% in January 2026. The library holds about 38 assets.
- Day-90 productization is about 69% across mature cohorts. Spend is about 5× pre-kickoff 6 months after go-live.
- Headcount is 40 (20 FDE, 14 Senior FDE, 6 Eng Manager). Time to fill is about 70 days (P50). Measured attrition is about 23%, which is noisy on a team this size.

## What's next

- [x] **Push to GitHub**: private repo `erasbleasp/fde-capacity-model`
- [ ] Make the repo public before linking it in the application
- [ ] **Phase 2: model engine** (`model/engine.py`)
  - [ ] Read `config/assumptions.yaml`; monthly steps over 24 months by segment × region
  - [ ] Demand, supply (hiring, attrition, ramp, manager span), overhead, partners, flywheel, Day-90
  - [ ] NumPy with a trials dimension; tests: zero spread ⇒ Monte Carlo = single value; same seed ⇒ same output; zero hires and zero attrition ⇒ flat headcount
- [ ] **Phase 2b: Monte Carlo** (`model/montecarlo.py`, `model/engagement.py`)
  - [ ] Draw from the distributions (triangular, lognormal, beta) plus the growth ↔ greenfield correlation
  - [ ] Percentiles, P(target), confidence-vs-resources sweep, Monte Carlo tornado
  - [ ] Single-engagement go-live simulator (P50/P80/P90 by staffing level, with and without assets)
- [ ] **Phase 3: dashboard pages 1–3** (Scorecard, Supply, Outcomes) in Streamlit
- [ ] **Phase 4**: Confidence page, Scenarios, Excel export, Data & Definitions page
- [ ] **Phase 5**: deploy to Streamlit Community Cloud, 1-page memo, rehearse the demo script, optional Ask Claude panel

### Open questions
- Commits are authored as `jaeger wells <jaegerwells2024@u.northwestern.edu>`, but the GitHub account is `erasbleasp`. Add that email to the GitHub account (Settings → Emails) or change the Git email, so commits show as yours.
- Whether to add economics (fees, margin) beyond cost per engagement and consumption lift

## How to resume

```bash
cd "/Users/jaeger/Claude/Projects/FDE model demo"
.venv/bin/python warehouse/build.py      # rebuild fde.duckdb (not committed)
.venv/bin/python -m pytest tests -q      # expect 35 passed
```
