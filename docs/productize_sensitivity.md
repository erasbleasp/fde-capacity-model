# Productize Sensitivity — does 12% harvest time pay off?

**Question:** With calibrated inputs, raising harvest time from 7% to 12% roughly breaks even over
24 months. Is that robust, or an artifact of the reuse settings that are judgment calls?

**Method:** `analysis/productize_sensitivity.py` compares Productize (12%) against Base (7%) under
the same settings, varying one judgment setting at a time, then in combination. Whenever a setting
changes the starting reuse level, k is re-fitted so the model still starts at the measured 9%
reuse ratio, so every variant stays consistent with the history. The headline measure is **extra
engagements delivered over 24 months** (Base delivers about 295).

```bash
.venv/bin/python -m analysis.productize_sensitivity
```

## Answer

**It's not robust. The verdict depends on one number nobody has measured yet: the reuse ceiling**,
the most effort assets can ever cover on pattern-based work. It's 0.35 today, which is judgment.

| Reuse ceiling | Extra engagements (24 mo) | Breakeven month | Day-90 change (year 2) |
|---|---|---|---|
| 0.20 | −14 (−5%) | never | −3.7 pts |
| 0.25 | −12 (−4%) | never | −3.1 pts |
| **0.35 (current)** | **−4 (−1%)** | **never** | **−1.2 pts** |
| 0.45 | +9 (+3%) | 11 | +0.8 pts |
| 0.60 | +41 (+12%) | 9 | +3.3 pts |

Swing in extra engagements across each setting's tested range:

| Judgment setting | Range tested | Swing | What moves it |
|---|---|---|---|
| **Reuse ceiling** (`assets.reuse_max`) | 0.20–0.60 | **55** | Productize pays only if assets can cover ≥ ~40% of pattern-based effort |
| Greenfield reuse factor | 0.2–1.0 | 21 | Needs ≥ 0.6: greenfield work is most of the effort, so assets must help there too |
| Harvest from slack (new) | 0–100% | 19 | If half the extra harvest comes from bench time, Productize wins by +5 and breaks even in month 6 |
| Greenfield shift per reuse | 0–2.0 | 14 | How fast reuse turns new demand into cheaper pattern-based work |
| Harvest yield | 0.5–1.4 | 9 | *Higher* yield hurts Productize: Base's library saturates sooner anyway |
| Asset decay | 2–8%/mo | 7 | Faster decay helps Productize: Base can't coast on an old library |

**Combined, each setting one plausible step toward Productize** (ceiling 0.45, greenfield factor
0.6, shift 1.2, decay 6%, half of extra harvest from slack): **+50 engagements (+15%), breakeven
in month 5, Day-90 +5 pts in year 2, cost per engagement −13%.**

**Paired Monte Carlo** (same input draws for both, 2,000 trials):

| Settings | P(Productize delivers more) | Extra engagements P10 / P50 / P90 |
|---|---|---|
| Current | 16% | −8 / −4 / +1 |
| Favorable combination | 100% | +31 / +44 / +51 |

**Best harvest level:**
- Under current settings, the optimum is **7–9%**, which is about where the team already is.
  At 3% the team loses about 13 engagements, and above 12% it loses ground.
- Under the favorable combination, more harvest keeps paying up to about 15%, with diminishing returns after 12%.

## What it means for the story

The model didn't refute productizing. It showed that **whether productizing pays depends on how much
work assets can actually cover, and that hasn't been measured**. With only a small library and
18 months of history, the data can't tell 0.35 from 0.45. The ceiling also interacts with whether
greenfield builds can use assets and whether harvest time comes out of delivery or bench hours.

That suggests a recommendation, not just a finding:

1. **Hold harvest at 7–9% now.** That's optimal under current settings, so it costs nothing to keep.
2. **Measure the ceiling.** For the next 2 quarters, track hours saved per pattern-based engagement
   once the library has 60+ assets, and whether harvest hours come from bench or delivery.
3. **Pre-commit to the decision rule.** If measured coverage on pattern-based work is ≥ ~40% (or
   greenfield builds reuse ≥ 60% as much as pattern-based ones), move to 12%. The model says that's
   worth about +9 to +50 engagements over 24 months.

## Caveats

- Single-value comparisons hold every other input at its value. The Monte Carlo varies them but
  does not re-fit k per trial, so draws where k and the ceiling move independently start the
  horizon above or below the measured 9% reuse.
- Random hires, exits, and arrivals are off in the paired Monte Carlo. Their draws depend on the
  model's state, so the two runs lose their pairing, which adds about ±35 engagements of noise
  unrelated to harvest.
- `overhead.harvest_from_slack` is a new setting (default 0, the current behavior). It's
  structural judgment: the history shows about 16% of deployable time unassigned, so some slack exists.
