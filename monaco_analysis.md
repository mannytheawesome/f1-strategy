# Monaco 2025 Weekend — App Performance Analysis

## Session Keys
| Session | Key |
|---|---|
| FP1 | 9972 |
| FP2 | 9973 |
| FP3 | 9974 |
| Qualifying | 9975 |
| Race | 9979 |

---

## What Worked Well

### ✅ Qualifying Mode
The quali board was accurate and showed everything it needed to:
- **Pole: NOR 69.954s** — correctly ranked
- **Theoretical best: 69.819s** (gap to pole = 0.135s) — realistic, achievable number
- Sector breakdown was clean: S1=18.170 (PIA), S2=33.180 (LEC), S3=18.469
- Gap to P1 column worked correctly across all 10 drivers
- Compound shown on best lap (all Q3 on Soft, as expected)

### ✅ Session Mode Auto-Detection
The app correctly switched between FP / QUALI / RACE layouts without manual input.

### ✅ Tyre Compound Colours
Soft=red, Medium=yellow, Hard=white all correct throughout the weekend.

### ✅ FP Stint Classification
HOTLAP / SHORT / LONG classification logic worked as expected:
- FP1/FP2: Hard and Medium long runs correctly identified
- FP3: Soft-heavy, short stints — correctly flagged as HOTLAP/SHORT

### ✅ Race Strategy Chart
Monaco 2025 race was predominantly **1-stop** (as predicted by the strategy engine):
- Most teams: Soft start → pit laps 12-22 → Hard to the end
- Notable 2-stoppers: ALB, LAW, ANT, HUL, VER (late soft splash)
- Strategy chart correctly generated S→H and S→M options

### ✅ Pit Window Predictions
Pit windows clustered around laps 16-22 (the real pit window was laps 12-22). 
Prediction was slightly conservative but in the right range.

### ✅ No False Retirements in FP/Quali
The `is_race_session` flag fix held — no drivers incorrectly marked as retired during practice or qualifying.

---

## What Needs Improvement

### ⚠️ FP1 Degradation Rates — Track Evolution
FP1 deg rates were inflated by track evolution (rubbering in), not real tyre wear:
| Compound | FP1 deg | FP2 deg | FP3 deg |
|---|---|---|---|
| Soft | +0.82s/lap | +0.10s/lap | +0.31s/lap |
| Medium | +0.54s/lap | +0.45s/lap | +0.78s/lap |
| Hard | +0.28s/lap | +0.44s/lap | — |

FP1 rates are 2-8x higher than FP2/FP3 because track grip was improving lap-by-lap.
**Fix**: Weight FP2/FP3 data more heavily than FP1 for race strategy planning.

### ⚠️ Race Deg Curve
Monaco is an unusual circuit — almost no tyre deg because there's so little high-speed cornering. The real differentiator was **undercut/overcut timing** around the pit window, not compound performance.
The current model doesn't account for this — it assumes deg drives strategy, but at Monaco traffic and timing do.

### ⚠️ Intervals / Gap Updates
At Monaco, the gap between drivers changes very slowly (train effect, no overtaking). Interval polling was technically working but the visual update felt "stuck" because the numbers genuinely weren't changing much — might need a visual indicator that data is live vs stale.

### ⚠️ Track Map
Still not working — deferred. At Monaco this would have been especially useful (narrow street circuit, track position everything).

### ⚠️ FP Hard Data in FP3
FP3 showed 0 Hard laps — correctly reflecting that teams had no Hard sets left (both used in FP1). The app didn't flag this to the user; it just showed "insufficient data". A better UX would be "No sets available" rather than silence.

---

## Race Result vs Strategy Prediction

| Driver | Predicted strategy | Actual strategy | Match? |
|---|---|---|---|
| NOR (winner) | S→H | S(19L)→H(59L) | ✅ |
| LEC (P2) | S→H | S(22L)→H(27L)→M(29L) | ⚠️ 2-stop |
| PIA (P3) | S→H | S(20L)→H(28L)→H(30L) | ⚠️ 2-stop |
| VER (P4) | S→H or S→M | S(28L)→M(49L)→S(soft splash) | ⚠️ 3-stop |
| HAM (P5) | S→H | S(18L)→H(38L)→M(22L) | ⚠️ 2-stop |

**Insight**: Monaco 2025 was more complex than a standard 1-stop. The Safety Car periods (or VSC windows) drove opportunistic pitstops. The strategy engine, which only plans from clean deg data, couldn't anticipate SC-driven strategy changes. This is a known limitation.

---

## Degradation Model Accuracy (FP → Race)

Using FP2 as the most reliable predictor of race pace:
- Soft deg: **0.10s/lap** — race was so short on softs (avg 20L) this was barely felt
- Medium deg: **0.45s/lap** — medium stints averaged 30-40L; degradation = ~13-18s of pace loss
- Hard deg: **0.44s/lap** — similar to medium at Monaco (hard tyre barely harder compound-wise on this track)

The actual race showed Hard was the preferred second compound (26 stints) vs Medium (27 stints) — near equal, which matches the FP2 deg data showing almost identical rates between the two.

---

## Summary Score

| Feature | Rating | Notes |
|---|---|---|
| Session mode detection | ✅ Works | Auto-switched correctly |
| Qualifying board | ✅ Works | Accurate ranking, gap, theoretical best |
| FP stint analysis | ✅ Works | Classification correct, deg rates reflect track state |
| Race strategy suggestions | ⚠️ Partial | 1-stop predicted, reality was more complex (SC-driven) |
| Pit window timing | ⚠️ Partial | Right range, slightly conservative |
| Intervals/gap updates | ✅ Works | Data correct; Monaco gaps naturally static |
| Tyre colours | ✅ Works | All correct |
| Retirement detection | ✅ Works | No false positives in FP/Quali |
| Track map | ❌ Missing | Deferred |
| SC/VSC awareness | ❌ Missing | Key gap in strategy model |

---

## Next Priorities (from this analysis)

1. **Safety Car awareness** — detect SC/VSC periods from lap time spikes; adjust strategy engine to flag SC as pit opportunity
2. **FP weight by session** — FP2/FP3 data should outweigh FP1 for race predictions
3. **"No sets available" flag** — when a compound had 0 laps due to allocation, show that explicitly
4. **Live/stale indicator** — show a timestamp or pulse on interval data so user knows if feed is current
5. **Track map** — unblock with a static SVG fallback showing approximate positions by lap %
