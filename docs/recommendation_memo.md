# FDE capacity: what to commit to for next half

**To:** FDE leadership · **From:** Jaeger Wells · **Date:** 24 October 2026  
**Model:** [live dashboard](https://jwells-fde-capacity-model.streamlit.app/) · [code](https://github.com/erasbleasp/fde-capacity-model) · *Data are made up for a demo; none of it is Anthropic data.*

## Bottom line

FDE requests are growing about 6% a month (13 a month now, ~50 by September 2028), and the current
plan covers about **61%** of the demand we take on. None of the plans below has better than even odds of
90% coverage next half (April–September 2027). I recommend a **blended capacity plan with a prioritization rule,
committed at P80**, and treating productization as a bet to measure before we scale it.

## What the model says

- **Hiring alone is too slow.** Time to fill plus ramp is about five months. At today's 2.3 hires a
  month there is an 8% chance of averaging 90% coverage next half; at 6 a month it is still only 41%.
- **Saying no to some Greenfield work delivers more.** Taking on 80% of fit Greenfield requests starts
  **300 engagements instead of 285** over 24 months, for the same cost. Greenfield work is about
  three times the effort of pattern-based work, and partners can't take it.
- **Productization is unproven, not wrong.** Raising harvest time from 7% to 12% roughly breaks even
  (it wins in 16% of paired trials). The result hinges on one unmeasured number, the share of an
  engagement reusable assets can cover; across its plausible range it swings from −14 to +41 engagements.
- **Demand is the biggest uncertainty.** Moving the growth assumption from its P10 to its P90 swings
  next half's coverage from 70% to 50%, more than any supply input.

| Plan (Apr–Sep 2027) | Coverage P50 (P10–P90) | Chance ≥ 80% | Engagements, 24 mo | Cost, 24 mo |
|---|---|---|---|---|
| Current plan | 61% (43–88%) | 17% | 285 | $46.4m |
| Hire-heavy (4.6 hires/mo) | 76% (55–108%) | 43% | 374 | $63.0m |
| Prioritize (80% Greenfield intake) | 73% (53–105%) | 37% | 300 | $46.6m |
| **Blended** (3.5 hires/mo, 45 partner wks, 80% Greenfield) | **88% (63–127%)** | **65%** | **373** | **$59.7m** |

## Recommendation

1. **Adopt the Blended plan:** 3.5 hires a month, 45 partner weeks a month, and take on 80% of fit
   Greenfield requests. It delivers about as many engagements as Hire-heavy for $3.3m less, at a lower
   cost per engagement than today ($160k vs $163k).
2. **Commit at P80, not the median.** Under Blended we can commit to **72% coverage** next half (vs 49%
   today), and set SOW dates at P80: a Greenfield build with 2 FDEs goes live in 136 days; a third FDE
   cuts that to 106 days and raises the chance of being live by day 90 from 37% to 62%.
3. **Open the next reqs in APAC,** where FDE coverage is about 40% against about 58% in AMER and EMEA.
4. **Hold harvest time at 7–9% and measure the reuse ceiling for two quarters**: hours saved per
   pattern-based engagement once the library passes 60 assets, and whether harvest hours come from
   bench time or delivery. **Decision rule, agreed now:** if assets cover ≥ 40% of pattern-based
   effort, move harvest to 12%.
5. **Validate the demand forecast before locking the hiring plan;** it moves the answer most.

*Method: an 18-month synthetic history in DuckDB, calibrated through SQL views into a 24-month driver
model, run as 2,000 Monte Carlo trials. Every input, its source and its range are on the dashboard's
Data & definitions page.*
