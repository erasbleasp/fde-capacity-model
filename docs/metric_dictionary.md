# Metric Dictionary

Every number on the dashboard is defined here: what it means, the exact formula, where it comes
from in SQL, and the judgment calls behind it. Where a definition could be gamed, the
"Decisions" line says which way it was settled and why.

Conventions
- **Weeks** are 40-hour FDE weeks. A month is 4.33 weeks.
- **Staffing weeks** (forward model): one FDE assigned full time to an engagement for one week.
  Model capacity, demand, and gap are all in staffing weeks.
- **As-of date** for the history is 2026-09-30. "Mature" means old enough to be judged
  (e.g. a kickoff cohort is mature for Day-90 once kickoff + 90 days ≤ as-of).
- **Time tracking starts at history start (2025-04-01).** Engagements that kicked off earlier have
  incomplete hours, so their reuse ratio is NULL and they're excluded from duration fits.
- **P50 / P80 / P90**: the value that 50% / 80% / 90% of Monte Carlo trials come in at or under
  (for a cost or a duration) — i.e. P80 is the number to commit to if you want to be right 4 times
  in 5.

---

## Master metrics

### Day-90 Productization Rate
**What it answers:** Of the engagements we start, how many reach real production use fast?

**Formula:**
```
Day-90 rate(cohort) = # engagements in cohort with prod_date − kickoff_date ≤ 90 days
                      ─────────────────────────────────────────────────────────────
                      # engagements that kicked off in the cohort (incl. cancelled)
```
- **Cohort** = kickoff month (or quarter).
- **Live in production** (`prod_date`) = first date the system serves real end users *and* the
  account's consumption has been above the production threshold for 2 consecutive weeks.
  In the made-up data this is simply the recorded `prod_date`.
- **Source:** `v_day90_cohorts`, `v_cycle_times`.

**Decisions**
- *Clock starts at kickoff, not contract signature.* Signature → kickoff is a staffing-queue
  problem and is tracked separately (Queue wait) so the two failure modes aren't mixed.
- *Cancelled engagements stay in the denominator.* Dropping them would reward cancelling slow
  engagements.
- *Only mature cohorts are reported.* An immature cohort is shown greyed out, not as a low number.
- *Partner-led engagements are included* and can be split out with a filter.

**Diagnostics:** % live by day 30 / 60 / 90 per cohort; split by type, segment, region,
FDE-led vs partner-led, and asset use (yes/no).

### Reusable-Asset Ratio (effort-weighted)
**What it answers:** How much of our delivery work is already done before we show up?

**Formula:**
```
Reuse ratio(period) =            Σ effort_hours_saved
                      ───────────────────────────────────────────────
                      Σ actual deploy hours + Σ effort_hours_saved
```
over engagements **closed** in the period (so the hours are complete).
- `effort_hours_saved` is recorded per `asset_usage` row: the estimated hours the asset replaced.
  In practice, estimated at engagement close by the lead FDE against a reference scope.
- **Source:** `v_reuse_monthly`.

**Decisions**
- *Effort-weighted, not count-based.* "Used at least one asset" is easy to inflate with trivial
  assets; hours saved isn't.
- *Measured at close*, so it lags. The engagement-count version (below) is the leading indicator.

**Diagnostics**
- **Asset attach rate** = % of engagements (by kickoff month) using ≥ 1 asset.
- **Harvest yield** = assets created per closed FDE-led engagement.
- **Partner adoption** = % of active assets used in ≥ 1 partner-led engagement in the trailing 6 months
  (the posting's "patterns partners reuse").
- **Active asset library** = assets created and not deprecated as of month end.

---

## Demand

| Metric | Formula | Source |
|---|---|---|
| **Gross requests** | count of `fde_requests` by `requested_date` month | `v_demand_monthly` |
| **Attach rate** | accepted ÷ requests | `v_demand_monthly` |
| **Declined – fit** | declined because the use case isn't a fit for FDE (wrong stage, no exec sponsor, etc.) | `v_demand_monthly` |
| **Declined – capacity** | a fit, but declined because the team was full | `v_demand_monthly` |
| **Gross demand (staffing weeks)** | Σ requests × fit rate × type share × effort per engagement_type | model |
| **Type mix** | Greenfield (new build) / Pattern-based (built from an existing pattern) / Expansion (second use case at a live account) | `v_demand_monthly` |

*Declined – capacity* is the cleanest signal of unmet demand; it's what hiring would have captured.

## Supply

| Metric | Formula | Source |
|---|---|---|
| **Headcount (HC)** | FDEs employed at month end (all roles) | `v_headcount_monthly` |
| **Attrition (annualized)** | exits in period ÷ average HC × (12 ÷ months in period) | `v_headcount_monthly` |
| **Time to fill** | `filled_date − opened_date` for filled reqs | `v_time_to_fill` |
| **Ramp factor** | share of a fully ramped FDE's deployable time, by month of tenure | `v_ramp` |
| **Effective HC** | Σ heads × ramp factor | model |
| **Gross capacity** | HC × weeks × 40 hours | `v_overhead_mix` |
| **Deployable capacity** | gross − PTO − presales − internal − harvest | `v_overhead_mix` |
| **Partner capacity** | partner FDE-equivalent weeks × efficiency factor | model |

## Utilization & overhead

Hours categories in `time_entries`:

| Category | Meaning |
|---|---|
| `deploy` | Billable / customer-facing build work on an engagement |
| `presales` | Scoping, solution design, deal support before signature |
| `internal` | Hiring interviews, training, enablement, management, ramp-up |
| `harvest` | Turning engagement work into catalogued reusable assets |
| `pto` | Vacation, holidays, sick |
| `bench` | Available for deployment but not assigned |

| Metric | Formula |
|---|---|
| **Utilization** | deploy ÷ (all hours − PTO) |
| **Overhead share (by category)** | category hours ÷ (all hours − PTO) |
| **Bench rate** | bench ÷ (all hours − PTO) |

**Decision:** PTO is excluded from the utilization denominator so holiday months don't look like
under-utilization. Harvest counts as overhead *today* — the model shows its return later.

## Delivery cycle

| Metric | Formula | Source |
|---|---|---|
| **Queue wait** | `kickoff_date − signed_date` | `v_cycle_times` |
| **Time to production** | `prod_date − kickoff_date` | `v_cycle_times` |
| **Engagement length** | `closed_date − kickoff_date` (includes ~2-week handoff) | `v_cycle_times` |
| **Duration fit** | lognormal: median = exp(mean(ln d)), σ = stdev(ln d), per type, completed engagements only | `v_duration_fit` |
| **Blocker rate** | share of engagements with a customer-side blocker | `v_cycle_times` |
| **Cancel rate** | cancelled ÷ kicked off (mature cohorts) | `v_day90_cohorts` |

**Caveat:** the duration fit uses completed engagements only, which under-weights long
engagements still in flight (right-censoring). Recent cohorts are excluded from the fit to limit
this; Phase 2 can switch to a survival-based fit.

## Capacity balance (model outputs)

| Metric | Formula |
|---|---|
| **Coverage ratio** | (FDE capacity + partner capacity usable on eligible work) ÷ demand *taken on* arriving this month, in staffing weeks |
| **Declined by policy** | fit requests turned down up front by the prioritization lever (Greenfield intake < 100%); counted apart from capacity declines |
| **Fit demand served** | engagements started ÷ fit requests before any policy, over 24 months — read next to coverage whenever intake < 100% |
| **Capacity gap** | capacity − demand (negative = short) |
| **Backlog** | fit demand not yet started (engagements); 50% walks away each month as capacity declines |
| **Expected wait** | backlog ÷ starts per month (Little's Law), in months |
| **Hires needed** | ramped ICs that would close this month's gap: shortfall ÷ (4.33 × target utilization). Excludes time to fill and ramp, so act on it ~5 months early |
| **Model reuse ratio** | effort-weighted reuse on engagements *starting* this month (the measured metric is at close and lags by about one engagement) |

## Outcomes & economics

| Metric | Formula | Source |
|---|---|---|
| **Consumption lift** | account spend in months 1–6 after go-live ÷ spend in the 3 months before kickoff | `v_consumption_post_golive` |
| **Partner share** | partner-led engagements ÷ all kicked off | `v_cycle_times` |
| **Cost per engagement** | loaded FDE cost × FDE weeks + partner cost × partner weeks | model |

## Monte Carlo terms

| Term | Meaning |
|---|---|
| **Trial** | One run of the full model with every uncertain input drawn from its distribution |
| **P(target)** | share of trials that meet a target, e.g. P(coverage ≥ 90% in Q3) |
| **Fan chart band** | P10–P90 range across trials for each month |
| **Confidence-vs-resources curve** | P(target) as a function of one lever (hires/qtr or partner weeks), all else held at plan |
| **Commit level** | the percentile leadership plans to (default P80) |
