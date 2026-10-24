# Backtest — does the model forecast a history it hasn't seen?

**Why:** the warehouse is made-up data from a generator, so recovering the generator's settings
only proves the pipeline works (the "circular validation" critique). A backtest tests the model's
*structure*: the generator is a weekly, engagement-by-engagement simulation with queues and staffing
fragmentation; the model is a monthly flow with calibrated distributions. If the structure is
wrong, it shows up as forecasts that miss.

**How** (`analysis/backtest.py`, run with `.venv/bin/python -m analysis.backtest`):
1. Snapshot the warehouse as of **31 Mar 2026**: delete or blank everything dated later, so the SQL
   views see only what was known then.
2. Re-centre every `calibrated_from` input on its snapshot SQL value; judgment inputs keep their
   priors; re-fit k to the snapshot's reuse ratio. Decisions known after the cutoff (the hiring pace,
   7% harvest time) are given to the model as inputs.
3. Forecast **Apr–Sep 2026** with 2,000 trials and score each measure against what actually happened:
   months inside the P10–P90 band (≈80% if well calibrated), and where the actual 6-month result
   falls in the forecast's distribution.

## Result (current model)

| Measure | Scored on | Actual | Forecast P10 / P50 / P90 | Actual's percentile | Months in band |
|---|---|---|---|---|---|
| Requests | 6-month total | 74 | 48 / 61 / 78 | 85th | 2 of 6 |
| Engagements started | 6-month total | 44 | 33 / 39 / 45 | 83rd | 4 of 6 |
| Declined, team full | 6-month total | 25 | 3 / 10 / 23 | 93rd | 5 of 6 |
| Headcount | month-6 level | 40 | 38 / 44 / 49 | 22nd | 6 of 6 |
| FDE utilization | month-6 level | 0.56 | 0.35 / 0.48 / 0.52 | > 99th | 3 of 6 |
| Asset library | month-6 level | 38 | 34 / 42 / 51 | 29th | 4 of 6 |
| Day-90 | pooled, 20 engagements | 80% | 58% / 66% / 72% | > 99th | 1 of 4 |

**Months inside the P10–P90 band: 62%** (target ≈ 80%). The model is **overconfident and leans
pessimistic**: every miss is in the direction of more demand, more work done and faster delivery
than forecast.

## What the backtest changed

The first run (before these fixes) scored 62% too, with requests at the 94th percentile and capacity
declines at the 99th:

- **Demand level from the trend, with an honest range.** The model used the trailing 6-month average
  as "requests per month now". Fitted on 12 noisy months, the level came in ~20% below what followed,
  and the ±23% range was centred on that single estimate. Now: the trend-fit level at the as-of month,
  with a range from the fit's standard error (full history: 16 a month, P10–P90 about 11.6–22.1,
  against 13 from the trailing average).
- **Abandon rate 0.5 → 0.75.** The model let half of unserved demand wait; in the history requests
  are declined at the decision. *Because the backtest informed this input, it is no longer an
  out-of-sample test for it.*

## What it still says the model gets wrong

- **No seasonality.** At a 31 March cutoff the "recent months" window spans December, so PTO
  (12%) and planned allocation (73%) are calibrated low and capacity is under-forecast — utilization
  lands above the band. A seasonal profile, or calibration windows that skip holiday months, would fix it.
- **Small-sample delivery rates.** Day-90 is forecast at 66% and came in at 80%: the snapshot saw
  high cancellation (13%) and blocker (35%) rates from only a few cohorts. These rates need pooling
  over more history (or partial pooling toward a prior) before they're trusted.
- **Monthly demand is lumpier than Poisson.** Single months swung from 5 to 19 requests; the model's
  month-to-month spread is too narrow even where the 6-month total is right.

## What it does not prove

It is still made-up data: the backtest shows the model's structure can forecast a differently built
history, not that either matches a real FDE team. The real test is the same procedure on real data.
