# FDE capacity: what to commit to for next half

**To:** FDE leadership · **From:** Jaeger Wells · **Date:** 24 October 2026  
**Model:** [live dashboard](https://jwells-fde-capacity-model.streamlit.app/) · [code](https://github.com/erasbleasp/fde-capacity-model) · *Data are made up for a demo; none of it is Anthropic data.*

## Bottom line

FDE demand (about 16 requests a month, trend-fitted) is outrunning capacity: if it keeps growing about
6% a month, today's plan serves **about 45%** of next half's demand (April–September 2027) and the best
combination of levers I tested about 65%. So the real decision is **which demand to serve**, and that
needs a value per engagement this model doesn't have yet. I recommend a blended plan with a
prioritization rule, committed at P80, plus three measurements before any bigger bet.

## What the model says

- **It hinges on growth.** At 6% a month demand roughly quadruples in 24 months; at 3%, the Blended plan
  covers about 83% instead of about 65%. The plans below rank the same on coverage either way.
- **Hiring alone is too slow.** Time to fill plus ramp is about five months; even 8 hires a month gives a
  19% chance of 90% coverage next half.
- **Better matching may be the cheapest lever.** About a fifth of ramped FDE delivery time sits
  unassigned while ~30% of fit requests were declined for capacity: a skills, region or timing mismatch,
  not spare capacity. Assigning 90% instead of 82% starts 23 more engagements for about the same spend,
  before counting what better matching would cost.
- **Turning down some Greenfield work frees capacity,** but the model counts every engagement as equal:
  at 80% Greenfield intake it starts 283 engagements instead of 268, yet serves only 40% of all fit
  demand (vs 38%). Whether that's wise depends on what Greenfield work is worth.
- **Productization is unproven.** At 12% harvest it starts ~8 fewer engagements; it pays only if assets
  can cover ≥ ~40% of pattern-based effort, which nobody has measured.

| Plan (Apr–Sep 2027) | Coverage of demand taken on, P50 (P10–P90) | Fit demand served | Chance ≥ 80% | Engagements, 24 mo | Cost, 24 mo |
|---|---|---|---|---|---|
| Current plan | 45% (31–65%) | 38% | 2% | 268 | $46.5m |
| Better matching (90% assigned) | 49% (34–71%) | 42% | 4% | 291 | $46.6m |
| Hire-heavy (4.6 hires/mo) | 55% (39–81%) | 51% | 11% | 357 | $62.9m |
| **Blended** (3.5 hires/mo, 45 partner wks, 80% Greenfield) | **65% (46–93%)** | **52%** | **22%** | **361** | **$59.7m** |

## Recommendation

1. **Adopt Blended** (3.5 hires a month, 45 partner weeks a month, 80% Greenfield intake) and **commit at
   P80**: 51% coverage of demand taken on, not the median. Put P80 dates in SOWs: a Greenfield build with
   2 FDEs goes live in 134 days; a third FDE cuts that to 108 and lifts day-90 odds from 38% to 60%.
2. **Fix matching before adding more heads:** find out whether unassigned time is skills, region or
   timing, and target 90% of delivery time assigned.
3. **Value engagements by type** (fees, and consumption: spend runs ~5× pre-kickoff six months after
   go-live) before tightening Greenfield intake further.
4. **Hold harvest at 5–7% and measure the reuse ceiling** for two quarters. Decision rule, agreed now:
   if assets cover ≥ 40% of pattern-based effort, move harvest to 12%.
5. **Validate the demand forecast first;** its level and growth move the answer most.

## What this model can't tell you

Made-up data validates the method, not the world; on six held-out months the P10–P90 bands caught 62% of
outcomes (target 80%), erring cautious. Regions are pooled, so APAC's low FDE-to-demand ratio (29% vs 43%)
is a question to check, not a finding. Ramp is fixed however fast we hire, partners scale instantly with
no minimum commitments, and recruiting costs are missing, so hiring and partners look better than they are.
