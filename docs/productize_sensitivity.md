# Productize Sensitivity — does 12% harvest time pay off?

**Question:** raising harvest time from 7% to 12% roughly breaks even or loses over 24 months. Is that
robust, or an artifact of the reuse settings that are judgment calls?

**Method:** `analysis/productize_sensitivity.py` compares Productize (12%) against Base (7%) under the
same settings, varying one judgment setting at a time, then in combination. Whenever a setting changes
the starting reuse level, k is re-fitted so the model still starts at the measured 9% reuse ratio. The
headline measure is **extra engagements started over 24 months** (Base starts about 271).

```bash
.venv/bin/python -m analysis.productize_sensitivity
```

*v2 (24 Oct 2026): judgment priors now set independently of the data generator (reuse ceiling 0.30,
Greenfield reuse factor 0.5, Greenfield shift 0.5, staffing exponent 0.6, partner efficiency 0.7),
demand level from the trend fit, staffing match calibrated at 82%. Numbers below are from v2.*

## Answer

**It's not robust. The verdict depends on one number nobody has measured: the reuse ceiling** — the
most effort assets can ever cover on pattern-based work (0.30 today, judgment). The second lever is
whether extra harvest time comes out of delivery hours or unassigned (bench) time.

| Reuse ceiling | Extra engagements (24 mo) | Breakeven month |
|---|---|---|
| 0.15 | −14 (−6%) | never |
| 0.20 | −13 (−5%) | never |
| **0.30 (current)** | **−8 (−3%)** | **never** |
| 0.40 | 0 | never |
| 0.50 | +9 (+3%) | 13 |

| Judgment setting | Range tested | Extra engagements | What moves it |
|---|---|---|---|
| **Reuse ceiling** | 0.15–0.50 | −14 to +9 | Productize needs assets to cover ≥ ~40% of pattern-based effort |
| Harvest from slack | 0–100% | −8 to +9 | If half the extra harvest comes from bench time, it breaks even (month 10) |
| Greenfield reuse factor | 0.25–1.0 | −12 to 0 | Greenfield is most of the effort, so assets must help there too |
| Greenfield shift per reuse | 0–1.5 | −11 to 0 | How fast reuse turns new demand into cheaper pattern-based work |
| Harvest yield | 0.5–1.4 | −12 to −6 | *Higher* yield hurts: Base's library saturates sooner anyway |
| Asset decay | 2–8%/mo | −10 to −5 | Faster decay helps Productize a little |

Two biggest together (extra engagements): with a 0.40 ceiling and half of extra harvest from bench
time, +9; with a 0.50 ceiling and half from bench, +20.

**Each setting one plausible step toward Productize** (ceiling 0.40, Greenfield factor 0.75, shift 1.0,
decay 6%, half of extra harvest from slack): **+32 engagements (+11%), breakeven in month 6, Day-90 +5
pts in year 2, cost per engagement −10%.**

**Paired Monte Carlo** (same input draws for both, 2,000 trials, process noise off):

| Settings | P(Productize starts more) | Extra engagements P10 / P50 / P90 |
|---|---|---|
| Current | 3% | −11 / −8 / −3 |
| Favorable combination | 100% | +23 / +30 / +37 |

**Best harvest level:** under current settings, **5–7%** (about where the team is; 12% costs ~8
engagements, 20% costs ~30). Under the favorable combination, more harvest keeps paying to ~15%.

## What it means

The model didn't refute productizing; it showed the payoff depends on **how much work assets can
actually cover and where harvest hours come from — neither has been measured.** So:

1. **Hold harvest at 5–7%** — optimal under current settings.
2. **Measure for two quarters:** hours saved per pattern-based engagement once the library passes 60
   assets, and whether harvest hours come from bench time or delivery.
3. **Decision rule, agreed now:** if assets cover **≥ 40%** of pattern-based effort, or ≥ 30% with at
   least half of harvest hours coming from bench time, move harvest to 12%.

## Caveats

- Single-value comparisons hold every other input at its value. The Monte Carlo varies them but does
  not re-fit k per trial.
- Process noise is off in the paired Monte Carlo (random hires/exits/arrivals desynchronize between
  the two runs and add noise unrelated to harvest).
- `overhead.harvest_from_slack` is structural judgment (default 0); the history shows unassigned time
  exists, so some slack is plausible.
