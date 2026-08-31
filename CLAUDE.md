# CLAUDE.md — F1 Strategy Predictor

Agent-facing context for this repo. This is the single source of truth; it
supersedes the old `progress.md` (now removed).

---

## What it is

A live/historical **F1 timing + strategy web app** built on the OpenF1 API.
FastAPI backend + plain vanilla-JS frontend. Two front doors:

1. **Strategy briefings** (`frontend/briefing.html`, served at `/`) — the
   product's main face. LLM-written (Claude) **pre-race** decision frameworks
   and **post-race** debriefs, grounded strictly in OpenF1 numbers.
2. **Live timing board** (`frontend/index.html`, served at `/live`) — real-time
   position/gap/sector board with tyre state, degradation predictions, pit
   windows, and a what-if simulator.

Deployed on **Railway** (nixpacks, `uvicorn api.main:app`).

## Current focus / north star

**Prediction accuracy.** The priority is improving the simulation/predictor
engine (`engine/predictor.py`) and validating it via the backtest harness.
Everything else (briefings UI, live board) is supporting surface. When making
changes, prefer ones that are measurable against the backtest.

Current backtested accuracy (`cache/backtest_results.json`, 81 races,
2023–2026, 243 checkpoints) — winner-hit / podium-of-3 / mean absolute
position error:

| Race distance | Winner | Podium | MAE |
|---|---|---|---|
| 25% | 78% | 2.30 | 1.83 |
| 50% | 83% | 2.43 | 1.54 |
| 75% | 94% | 2.57 | 1.07 |

Overall: 84.8% winner-hit, MAE 1.48 over 243 checkpoints. Win-probability
Brier score 0.0149, podium-probability Brier 0.0479 (lower is better; see
Testing) — these are new, see the Monte Carlo calibration note below.

Re-run and beat these before claiming an accuracy improvement (see Testing).

**Monaco and Las Vegas were silently misclassified as normal (non-street)
circuits everywhere — production and backtest — until 2026-08-11.**
`STREET_CIRCUITS` matched `"monaco"` and `"las_vegas"` (underscore), but
OpenF1's real `circuit_short_name` values are `"Monte Carlo"` and
`"Las Vegas"` (space); neither ever matched. Every Monaco checkpoint in the
backtest cache had `street=False` up to that point. Fixed in
`engine/circuits.py` by adding the real spellings (old aliases kept, harmless
if unused). Impact was concentrated exactly where expected — street-circuit
metrics went from winner 81%/MAE 1.68 (n=48, missing Monaco) to winner
88%/MAE 1.59 (n=60, Monaco correctly included) — with only a small move in
the overall numbers since Monaco is 12 of 243 checkpoints. Re-sweeping
afterward moved the street optimum 0.75 -> 0.85 (see below); Monaco's extreme
overtaking difficulty was pulling the whole street cohort's ideal weight up
once it was actually being counted.

A second, related bug: `SC_RATE_CIRCUIT` (per-circuit safety-car rate,
`engine/predictor.py`) had the same problem plus a casing bug — `"Catalunya"`
(capitalized) never matches its own lowercased self, and `"albert_park"` /
`"bahrain"` don't match the real `circuit_short_name` values (`"Melbourne"` /
`"Sakhir"` and `"Kuala Lumpur"`, the latter a pre-existing OpenF1 mislabeling
of some Bahrain sessions). Only 6 of 26 real circuits were ever actually
matching this table; the rest silently fell back to `SC_RATE_DEFAULT`. Fixed
2026-08-11 with the same researched rates, corrected keys only. Measured
impact on the Monte Carlo Brier score was negligible (SC events are rare
enough per lap that this barely moves win/podium probability) — kept as a
correctness fix for the `sc_probability()` stat shown on the live board, not
for a backtest-measurable gain.

**SC window timing.** The per-lap SC hazard was flat — same probability on
lap 2 as lap 55 — despite real SC/VSC deployments clustering hard at race
starts. Measured 2026-08-18 by running `detect_sc` on the FULL race laps (not
the usual laps-to-now) for all 81 cached races: 18 of 69 total SC/VSC events
fell in the opening 5% of race distance (4.44 events/race/unit-distance) vs
0.66 for the rest of the race — a ~5.2x spike, and 18 observed against ~3.5
expected under a flat rate is too large a gap to be noise. The other five
buckets checked across the remaining 95% (5-15% through 85-100%) were flat/
noisy with no trend (0.56-0.74, ~9 events each) — matching the sample-size
wall the per-circuit DNF table hit, so only two buckets were fit, not a finer
curve. Added `SC_OPENING_WINDOW_FRAC=0.05` / `SC_OPENING_MULT=5.2` in
`engine/predictor.py`; `SC_REST_MULT` is derived (not independently fit) so
the reshape integrates to 1 over the full race and provably cannot change the
total expected SC count per race — it only corrects *when* the already-tuned
`SC_RATE_CIRCUIT`/street/default rates land. `_sc_p_no()` replaces the flat
`(1-rate)**remaining` in both `sc_probability()` and `run_monte_carlo`'s SC
lottery. Winner-hit/MAE are unaffected (fixed before Monte Carlo runs, as
always) and the Brier score barely moves (0.0149→0.0150 win, 0.0479 podium,
within run-to-run noise) — same finding as the SC_RATE_CIRCUIT fix above,
since the MC lottery only checks *whether* an SC falls in the remaining race,
not when. The real payoff is `sc_probability()`'s own accuracy: P(SC) in the
first 3 laps of a 70-lap race goes from 0.02 (flat model) to 0.054 (windowed)
— a ~2.7x correction concentrated where it belongs instead of smeared flat
across the whole race.

Fixing this also surfaced a latent bug in `_sc_refund()` (`engine/prerace.py`,
the pre-race "early-yellow refund" briefing stat): it queried a truncated
lookahead window by passing the window length itself as `total_laps` — safe
under the old flat model (position-independent), but wrong once hazard
depends on real race position, since laps 2-12 of a truncated 12-lap "race"
no longer land inside the true opening spike of the actual ~70-lap race.
`sc_probability()` gained an explicit `window_laps` parameter so `total_laps`
always stays the genuine race distance; `_sc_p_no()` takes a separate
`window_end`. Fixed the one call site that relied on the truncation
(`_sc_refund`) — nearly doubled its estimate for a 70-lap race, first 12 laps
(0.105 -> 0.197), since laps 2-4 are now correctly priced at the opening rate
instead of the flat rest-of-race rate.

`track_position_weight` was re-swept three times: 2026-08-10 (pre quali-prior
fix), 2026-08-11 (post quali-prior fix, pre Monaco fix), and 2026-08-11 again
(post Monaco fix). `normal` has held at 0.5 throughout. `street` moved
0.6 (original) -> 0.75 -> 0.85, with the last move driven entirely by Monaco
finally being counted in the street cohort — checked up to 1.0 to confirm
0.85 is a real peak (winner-hit 84.8% at 0.85 vs 84.0% at 0.9, 83.5% at 1.0),
not a grid-edge artifact. Every re-sweep has picked the config that maximises
winner-hit first, MAE second among ties — the pure-MAE optimum has
consistently been ~1 point of winner-hit worse for a marginal MAE gain, and
this product is graded on winner-hit. The value lives in one place,
`engine.circuits.{STREET,NORMAL}_TRACK_POSITION_WEIGHT` — `engine/prerace.py`
and `backtest_full.py` used to hardcode their own stale copies; both now
import the constants, so a future re-sweep only requires editing
`engine/circuits.py`.

**DNF modelling.** The flat `DNF_RATE = 0.04` used in the Monte Carlo pass
(`run_monte_carlo`, `engine/predictor.py`) understated real risk by >3x —
measured from OpenF1 `session_result`'s `dnf`/`dsq` flags across the 81-race
cache, the true field-wide rate is 12.9% per driver-start. Fixed 2026-08-11:
`DNF_RATE_DEFAULT = 0.129`, applied flat. A per-circuit table was also built
(Melbourne 0.235 down to Monza 0.050) and tried, since `SC_RATE_CIRCUIT`
already does this for safety cars — it measurably *worsened* the win Brier
score (0.0148 -> 0.0153) despite no gain elsewhere. Each circuit only has 3-4
races (60-82 driver-starts) in the cache, too thin to fit real circuit-level
variation from; the table was mostly noise. Deliberately not reintroduced —
see `engine/predictor.py` history if revisiting with a larger cache. The DNF
check was also previously applied at the same full-race odds regardless of
laps remaining (a driver 2 laps from the flag carried the same DNF chance as
one on the formation lap); now scaled by remaining-lap fraction, matching how
the SC lottery already worked.

This DNF fix is the reason `backtest_full.py evaluate` now reports a Brier
score at all — winner-hit/podium/MAE are fixed before `run_monte_carlo` runs
(`predicted_position` is set from the deterministic sort), so they are blind
to *any* change inside Monte Carlo. There was previously no way to validate
a DNF or SC-lottery change; `evaluate_weekend` now also scores
`win_probability`/`podium_probability` against actual outcomes via Brier
score, closing that gap. Old flat 0.04 DNF: win Brier 0.0149, podium Brier
0.0495. New flat 0.129: win Brier ~0.0148-9, podium Brier 0.0479 — a real,
if modest, calibration improvement, and the only lever here Brier score
endorsed.

`backtest_full.py`'s `evaluate`/`sweep` never passed `quali_times` into
`build_pace_model`, unlike every production caller (`api/routers/strategy.py`,
`engine/whatif.py`, `engine/briefing.py`). Qualifying pace is blended in as a
prior specifically so the model isn't relying on a handful of noisy heavy-fuel
laps early in a race — exactly the checkpoints (25%/50% distance) this file
called out as the model's weak spot. The harness was silently benchmarking a
crippled build. Fixed 2026-08-11: `enumerate_weekends` now also captures each
weekend's `Qualifying` session key (excluding `Sprint Qualifying`, which has a
different `session_name`), `load_weekend` fetches its laps and computes best
lap per driver, and `evaluate_weekend` passes it through. Winner-hit jumped
81.1% -> 84.4% and MAE 1.51 -> 1.48 overall, with the largest gains exactly at
25% (74% -> 78%) and 50% (79% -> 83%) distance — this was measurement error,
not a real engine change.

`track_position_weight` was re-swept 2026-08-10 (before the quali-prior fix)
and again 2026-08-11 (after) on the full 81-race cache (`python
backtest_full.py sweep`, grid over street x normal weight). Both times the
normal value's optimum (holding winner-hit at its max while minimising MAE
among ties) landed on 0.5, unchanged from the pre-fix value — current defaults
(`street=0.75, normal=0.5`) are confirmed optimal post-fix too (MAE 1.481,
winner 84.4%, tied for best winner-hit in the grid). The pure-MAE optimum
(`street=0.65, normal=0.5`, MAE 1.479) was rejected both times: it trades
~1 point of winner-hit for a marginal MAE gain, and winner-hit is the metric
this product is graded on. The value lives in one place,
`engine.circuits.NORMAL_TRACK_POSITION_WEIGHT` — three other files
(`engine/prerace.py` x2, `backtest_full.py`) had hardcoded their own stale
copies of 0.75/0.6 instead of importing it; all three now call
`track_position_weight(circuit)` / import the constants, so a future re-sweep
only requires editing `engine/circuits.py`.

These supersede a 74.5%-winner / 1.56-MAE baseline. The gain came from fixing
degradation estimation (see below), verified on identical checkpoints (n=171):
winner 74.9% -> 80.1%, MAE 1.540 -> 1.494, with the largest gain at 50% distance
(68.4% -> 75.4% winner) — the weak spot this file previously called out.

Degradation is fitted PER STINT, not pooled across drivers. A stint is one car
on one fuel programme, so a slope fitted inside it measures wear; pooling mixed
low-fuel qualifying simulations on fresh tyres with high-fuel long runs on old
ones and read that as degradation, saturating the 0.30 s/lap clamp on most
weekends. Only laps within `DEG_LONGRUN` (1.02x the stint's best, >=8 clean laps)
count as representative running, so practice cool-down laps are excluded, and
stint slopes are aggregated by weighted median rather than mean.

A compound nobody ran long (SOFT is often only used on a qualifying simulation)
has no wear signal. Rather than fit that data anyway — which produced a garbage
slope pinned to `MAX_DEG` — its rate is derived from a compound that WAS
measured at the same event via `DEG_RATIO` (SOFT 1.75x MEDIUM, HARD 0.6x),
floored at `DEG_UNMEASURED` and falling back to `DEG_PRIOR` only if nothing was
measured. This lifted stop-count agreement with what teams actually ran from 55%
to 61% exact.

`DEG_UNMEASURED` is the p75 of measured rates, not the median, on purpose: a
compound nobody could run long is self-selecting evidence that it wears hard
here. Using the median flattered SOFT into 86% of optimal plans against the 27%
of races teams actually raced it in.

Tyre availability is now part of the search. `optimize_strategy(available=...)`
takes the new sets left per compound and refuses to fit a tyre the driver does
not hold; the pre-race sweep feeds it the field's median remaining stock (from
`engine/tyre_inventory.py`, which counts qualifying, not just practice) and skips
start compounds nobody has. At Spa the top 10 hold 10 new Hards but only 2 new
Softs, and the optimum moves from SOFT-MEDIUM to MEDIUM-HARD — matching what
teams actually run there.

The lap-0 projection goes further and plans each car on ITS OWN garage:
`simulate_race(inventory={driver_number: {compound: sets left}})` passes each
driver's stock to their strategy search, and a driver who cannot start on the
paper compound is started on one they hold. A driver who saved a Soft is planned
onto it; a team-mate who spent theirs in Q3 is not. Both `available` and
`inventory` default to None, so the prediction path and backtest are unaffected.

**`_long_run_pace()` (`engine/prerace.py`) had no clean-lap filter.** User-
reported 2026-08-21: the pre-race "real pace order" table and the lap-0
"Grid → flag" projection both looked badly wrong at Spain 2026 — Hamilton
(P2 on the grid, went on to win) was missing from the projection's top 10
entirely, with Norris shown at an 89% win probability. Traced to
`_long_run_pace`: it fed every lap of a qualifying >=6-lap stint into the
per-driver median with no outlier filtering beyond pit-out/yellow-flag laps —
practice stints mix genuine push laps with slower non-representative ones
(traffic, installation-style laps, backing off) that aren't flagged either
way. For Hamilton specifically this produced a **+5.08s/lap** pace delta
(rank 21st of 28), which `_run_projection` feeds directly into the Monte
Carlo pace model — explaining exactly why he'd vanish from the forecast.
Fixed by adding the same idea `predictor._stint_deg_samples` already uses
for degradation fitting (keep only laps within a ratio of the stint's own
best lap) plus dropping each stint's in-lap (which `_stint_deg_samples`
already does but this function didn't) — but NOT the same ratio.
`DEG_LONGRUN`'s 1.02 is tuned for isolating a wear *slope*, where the fitted
laps need to be nearly flat; `_long_run_pace` measures a single pace
*level* across a whole stint, which legitimately drifts a few percent from
wear. Applying 1.02 here dropped Hamilton from the table entirely (10 of 28
drivers survived) despite him winning the race. Checked candidate ratios
directly against this session's raw laps: 1.05 already recovers him
(-0.04s/lap) with 20/28 coverage; 1.10 (`PACE_ORDER_CLEAN_RATIO`) gives full,
clean coverage (25/28, sensible order, no outliers); 1.15 already re-admits
one (a driver jumping to an implausible -3.7s/lap) — 1.10 was the widest
safe margin found. Post-fix, Hamilton ranks 6th (-1.24s/lap) and the
projection shows him P2 with a real podium share; Antonelli (P3 on the grid)
was also missing from the pace table before (rank 13, cut by the frontend's
top-10 display) and now ranks 8th, inside it. Not covered by the backtest
harness — `backtest_full.py` never calls into `engine/prerace.py` at all, so
this had no automated test to catch it; validated by hand against the one
reported race plus a ratio sweep on its real lap data.

Also fixed alongside: `frontend/briefing.js`'s grid card was hardcoded to
`d.grid.slice(0, 10)` despite the backend already returning the full field
(20 cars) — a separate, purely cosmetic truncation, not a calculation bug.

Not a bug, by design: the "strategies on paper" table shows only the single
fastest plan at each forced stop count (1/2/3), not an exhaustive list, and
`optimize_strategy`'s `SOFT_SPLASH_MAX=15` deliberately forbids a long final
stint on a softer compound (e.g. Medium-Hard-**Soft** as a full-length
closer) unless it's short enough to be a genuine splash-to-the-flag — real
teams essentially never run a long stint on the faster-degrading compound
that late. A user report expecting to see that ordering as a "viable
option" reflects this intentional constraint, not a defect.

---

## How to run

```bash
cd /Users/mannytheawsome/Documents/f1-strategy
uvicorn api.main:app --reload --port 8000
```
- Open `http://localhost:8000/` for briefings, `/live` for the timing board.
- Port stuck? `lsof -ti :8000 | xargs kill -9`
- `pip install -r requirements.txt` (FastAPI, uvicorn, numpy, scipy, requests,
  paho-mqtt, anthropic).

### Credentials (`.env`, gitignored)
- `OPENF1_USERNAME` / `OPENF1_PASSWORD` — **OpenF1 live data is a paid tier.**
  The free tier is historical-only (blanked from 30 min before to 30 min after
  a session). `data/live.py` auto-loads `.env` at import and exchanges creds for
  an OAuth2 bearer token, refreshed automatically. Real env vars (Railway) win.
- `ANTHROPIC_API_KEY` — for briefing narrative generation. If absent, briefings
  still return the full data pack with `narrative=None` (graceful degrade).
- Never log or echo credential values. Diagnostics store outcomes only
  (`/api/debug/openf1_auth`, `/api/debug/anthropic_auth`).

---

## Architecture

```
frontend/
  briefing.html/.css/.js — briefings SPA (front door, served at "/")
  index.html/.css/.js    — live timing board SPA (served at "/live")
api/
  main.py                — app setup, CORS, router wiring, frontend serving (thin)
  helpers.py             — session-mode / driver serialisation / prediction block
  routers/               — routes grouped by domain:
    meta.py              — session metadata, auth diagnostics
    timing.py            — live/replay board, locations, sectors, intervals
    analysis.py          — FP/quali analysis, tyre inventory, pre-race strategy
    strategy.py          — strategy generation, prediction engine, what-if
    briefings.py         — race listings, pre-race + post-race briefings
data/live.py             — OpenF1 client: OAuth, polling, in-memory cache, build_state()
engine/
  predictor.py           — lap-by-lap race simulation engine (the accuracy core)
  degradation.py         — tyre deg curves via linear regression on session laps
  strategy.py            — 1-stop / 2-stop strategy generator (PlanStint = planned segment)
  circuits.py            — street-circuit set + track-position-weight (shared)
  fp_analysis.py         — FP stint classification + DEG/LAP rates
  quali_analysis.py      — quali ranking, gap to P1, theoretical best
  tyre_inventory.py      — new-set counts across the meeting weekend
  prerace.py             — pre-race (forward-looking) briefing data pack
  briefing.py            — post-race debrief data pack + LLM narrative
  whatif.py              — counterfactual "what-if" race re-simulation
backtest_full.py         — full-history collect/evaluate/sweep harness (no HTTP)
backtest.py              — HTTP-based backtest against a running server
monitor_*.py, mqtt_monitor.py — background live-session monitors / anomaly loggers
cache/                   — disk cache of raw OpenF1 data + backtest_results.json (gitignored)
briefings/               — cached generated briefings, prerace_<key>.json (gitignored)
```

Two `Stint`-like concepts, kept deliberately separate: `data.live.Stint` is a
stint a driver **actually ran**; `engine.strategy.PlanStint` is a **planned**
segment of a candidate strategy. Two tyre-curve types also coexist by design:
`degradation.TyreDegradation` (single-session, feeds the live pit-window) and
`predictor.DegCurve` (weighted multi-session, feeds the race simulation).

### Data flow
OpenF1 → `data/live.py` (fetch + cache + `build_state()`) → `engine/*`
(deg curves, pace model, simulation, strategy) → `api/routers/*` → frontend.

### The predictor (accuracy core — `engine/predictor.py`)
Pipeline: `build_deg_curves` (blend FP1/2/3 + race into per-compound curves) →
`build_pace_model` (per-driver age-corrected pace delta) → `optimize_strategy`
(DP over pit_lap × compound to minimise race time) → `simulate_race` (run all
drivers, produce ranked forecasts) → `calc_undercut` + `detect_sc` /
`sc_probability`. Surfaced via `GET /api/predict`.

Key tunables (all in `predictor.py`, tuned on the backtest):
- `PIT_LOSS=22.0`s, `STOP_RISK=6.0`s/stop, `MIN_STINT=8`, `SOFT_SPLASH_MAX=15`
- `DNF_RATE_DEFAULT=0.129` (flat; measured from OpenF1 `session_result`, see
  above — a per-circuit table was tried and rejected, too noisy), `FUEL_RATE=
  0.035` s/lap, `FUEL_WEAR_COUPLING=0.3`, `CLIFF_ACCEL=0.045`
- `FP_WEIGHTS = {FP1:0.3, FP2:1.0, FP3:0.9, RACE:3.0}`
- `COMPOUND_DELTA = {SOFT:-0.6, MEDIUM:0.0, HARD:+0.4}` vs fresh Medium
- `SC_RATE_DEFAULT=0.0067`, `SC_RATE_STREET=0.0120`, `SC_RATE_CIRCUIT` (12
  circuits, keys fixed 2026-08-11 — see above), `SC_LAP_MULT=1.35`
- `SC_OPENING_WINDOW_FRAC=0.05`, `SC_OPENING_MULT=5.2` — opening-lap SC hazard
  spike, measured 2026-08-18 (see above); `SC_REST_MULT` is derived from these
  two, not independently tuned
- **`track_position_weight=0.5`** (0.85 for street circuits), from
  `engine/circuits.py`: final finish time is `w·position_time + (1-w)·pace_time`.
  This blend was the biggest accuracy lever in the sweep — early in a race,
  current track position predicts the finish better than pace simulation alone.

### Session modes (frontend auto-switches on `session_mode`)
| Mode | Left panel | Key columns |
|---|---|---|
| RACE | Strategy chart + pit window | POS, GAP, INT, LAP, COMPOUND, AGE, S1–S3, ΔPOS |
| FP | Stint analysis per compound | BEST LAP, COMPOUND, AGE, DEG/LAP, S1–S3 |
| QUALI | Theoretical best summary | BEST, GAP, COMPOUND, THBEST, S1–S3 |

---

## API endpoints (`api/routers/`)
Session/data: `/api/session`, `/api/session/total_laps`, `/api/live`,
`/api/replay?session_key&lap`, `/api/sectors`, `/api/intervals_live`,
`/api/locations`, `/api/track_layout`, `/api/races`, `/api/next_meeting`.
Analysis: `/api/fp_analysis`, `/api/quali_analysis`, `/api/tyre_inventory`,
`/api/strategies`, `/api/predict`, `/api/pre_race_strategy`,
`/api/driver/{n}/laps`, `POST /api/whatif`.
Briefings: `/api/prerace_briefing`, `/api/briefing`.
Debug: `/api/debug/openf1_auth`, `/api/debug/anthropic_auth`.

---

## Conventions & gotchas

### Caching (respect the rate limit)
- `HIST_TTL=3600s` for historical data (never changes) — this is what keeps us
  under OpenF1's ~30 req/min limit. `LIVE_TTL=10s` for live sessions.
- Replay is fully cached after first load; subsequent laps are pure in-memory
  filtering (no OpenF1 calls). Don't add per-lap network fetches.
- Backtest harness (`backtest_full.py`) has its own resumable disk cache in
  `cache/` and calls the engine **directly, without HTTP** — the accuracy path.

### OpenF1 quirks
- All endpoints return lists — always sort/filter client-side.
- Location endpoint `date_gt` filter is broken; fetch per-driver without a date
  filter for historical.
- Upstream can be slow — request timeout is 30s.
- Sanitise stint rows at the source (`data/live.py`) — live nulls otherwise
  break every downstream consumer.

### F1 domain logic
- `is_race_session` gate: retirement/interval logic runs **only in RACE/SPRINT**.
  In FP/Quali, rank by best lap — otherwise a slow first lap triggers false
  retirements.
- Reference driver for strategy = the one who completed the most laps (winner),
  not the lap-1 leader.
- True tyre age = `tyre_age_at_start + (lap - stint_lap_start)` — handles
  returned/scrubbed sets. Regression needs `DEG_MIN_LAPS` to be trusted.
- New set = `tyre_age_at_start == 0`. Standard allocation: Hard 2 / Medium 3 /
  Soft 8 (sprint: Soft 6).
- Strategy generator is dry-compound only (SOFT/MEDIUM/HARD); if current stint
  < `MIN_CURRENT_STINT=3` (e.g. formation lap on inters), reset to SOFT age 0.
- Compound colours: Soft=red, Medium=yellow, Hard=white, Inter=green, Wet=blue.

### Briefings
- Narrative is generated **once** per session by Claude and cached to disk
  (`briefings/`). The model writes prose grounded in the data pack — it must not
  invent numbers. Bump `PACK_VERSION` when the data pack shape changes so cached
  briefings regenerate.
- Pre-race packs deliberately **exclude the grand prix itself**, so a pre-race
  briefing can be generated retrospectively ("what the data said Sunday morning")
  and graded against what actually happened (the scorecard).

### Frontend (both are hand-written vanilla JS, no build step)
- Live board updates rows via CSS `transform: translateY()` — no DOM wipe.
  Sector cells update individually. `isLiveSession` gates fast polling so
  finished races don't hammer the API.
- Strategy chart is fixed at race start (`strategyFetched` flag) — don't
  regenerate it every render.
- All four of `/live`'s pollers (the 5s `fetchData` tick, and the 2s
  `fetchSectors`/`fetchIntervals`/`fetchLocations`) are gated on
  `!document.hidden`, fixed 2026-08-18. `fetchLocations` in particular had no
  `isLiveSession` gate at all (only `replayMode` — it deliberately still shows
  a snapshot for finished sessions), so simply leaving `/live` open on ANY
  session, live or long-finished, polled OpenF1 every 2s forever even in a
  backgrounded tab. A `visibilitychange` listener triggers one immediate
  refetch on refocus so the view isn't stale after being backgrounded.
  Verified in-browser: patching `window.fetch` to count matching calls and
  forcing `document.hidden` via `Object.defineProperty` showed polling fully
  paused while hidden and resumed immediately on refocus.

---

## Testing / verifying accuracy

The backtest harness is the primary tool — always validate engine changes here.

```bash
python backtest_full.py collect     # phase 1: cache raw OpenF1 (slow, rate-limited, resumable)
python backtest_full.py evaluate    # phase 2: run engine at 25/50/75% distance, compute metrics
python backtest_full.py sweep       # phase 3: grid-search tunables (e.g. track_position_weight)
```
- Evaluate calls the engine directly (no server needed) at 25/50/75% race
  distance for every cached race. Metrics: winner-hit, podium intersection,
  top-10 intersection, MAE over finishers (retirements after the prediction lap
  are excluded — not predictable from pace/strategy), plus a win/podium
  **Brier score** for the Monte Carlo probability outputs.
- The Brier score is the only metric that exercises `run_monte_carlo` —
  `predicted_position` (winner-hit/podium/MAE) is fixed by the deterministic
  sort *before* Monte Carlo runs, so a change to `DNF_RATE_DEFAULT`, the SC
  lottery, or pace noise (`sigma` in `run_monte_carlo`) is invisible to those
  three metrics no matter how wrong it is. Use Brier score (lower is better)
  to validate anything inside `run_monte_carlo`; use winner-hit/MAE for
  anything in `optimize_strategy`/`simulate_race`'s deterministic path.
- `backtest.py` is the alternate HTTP path (needs a running server on `:8001`).
- The harness sanitises stint rows exactly as `data.live.get_stints` does, so it
  measures the engine on the same repaired data production sees. Evaluating raw
  OpenF1 stints (with their 1-lap fragments) quietly inflates stop counts.
- `python audit_strategies.py` checks every cached weekend's generated plans for
  structural sanity and flags saturated deg fits.
- Compare against the headline table above; a change that lowers MAE / raises
  winner-hit across fractions is a real improvement.
- For UI/live behaviour, use **replay mode** (`/api/replay?session_key&lap`) to
  step a finished race lap-by-lap without live credentials.

---

## Roadmap / open work

### Prediction accuracy (priority)
- [x] Re-run `sweep` to re-tune `track_position_weight` and other knobs on the
      full 2023–2026 cache; commit the new defaults with before/after metrics.
      Done 2026-08-10, re-swept twice more on 2026-08-11 (quali-prior fix,
      then Monaco-classification fix): `normal` 0.6 -> 0.5, `street`
      0.6 -> 0.75 -> 0.85.
- [x] Improve early-race accuracy (25%/50% winner-hit was stuck at 74%/79% vs
      90% at 75%). Done 2026-08-11 — root cause was the backtest harness
      itself: it never fed `quali_times` into `build_pace_model`, unlike every
      production caller. Fixing that (not an engine change) moved 25%/50% to
      78%/83%. Still the model's relative weak point vs 75% (94%), so more
      genuine engine gains may exist here, but the easy measurement bug is
      fixed.
- [x] Better DNF / reliability modelling beyond the flat `DNF_RATE=0.04`. Done
      2026-08-11: measured true rate (12.9%) from OpenF1 `session_result`,
      replaced the flat constant, and scaled the Monte Carlo DNF check by
      remaining race distance. Also built the Brier-score infrastructure
      needed to validate this class of change at all (see Testing) — winner-
      hit/MAE can't see anything inside `run_monte_carlo`. A per-circuit DNF
      table was tried and rejected: it measurably worsened win Brier score
      (sample too thin per circuit, 3-4 races each). Flat rate only.
- [x] Sharper SC modelling. Done 2026-08-11 + 2026-08-18. 2026-08-11: found and
      fixed `SC_RATE_CIRCUIT`'s matching bugs (only 6/26 circuits were ever
      actually matching — see above) and wired the Monte Carlo SC lottery to
      use the real per-circuit table instead of a street/normal binary.
      2026-08-18: added the opening-lap hazard spike (`SC_OPENING_WINDOW_FRAC`/
      `SC_OPENING_MULT`, see above) closing out the window-timing gap this item
      previously flagged as open. Both fixes moved the Brier score negligibly
      (SC is rare enough per lap, and the MC lottery only checks whether an SC
      falls in the remaining race, not when) — kept for `sc_probability()`'s
      own accuracy, which the Brier score can't see either.
- [x] Validate deg-curve blending weights (`FP_WEIGHTS`) against per-track
      backtest error. Done 2026-08-11, no code change. Coordinate-wise sweep
      (each weight x0/x0.5/x1.5/x2, others held at current values, full
      81-race cache): current `{FP1:0.3, FP2:1.0, FP3:0.9, RACE:3.0}` sits at
      a genuine local optimum — no single-axis perturbation beats 84.8%
      winner-hit. `RACE` dominance is load-bearing (zeroing it drops winner-
      hit to 82.3%, MAE 1.480 -> 1.536); `FP1`/`FP3` barely move anything
      even at x0 or x2; `FP2` is at a sweet spot (both directions are flat-
      to-worse). Per-track MAE does vary for real (0.95 Suzuka to 2.30
      Zandvoort), but every circuit has only 6-12 checkpoints (2-4 races) in
      this cache — the same sample size that made the per-circuit DNF table
      overfit above. Fitting per-track `FP_WEIGHTS` from this cache would
      hit the identical wall; would need materially more seasons cached, or
      a shrinkage/pooling approach, to attempt responsibly.

### Product / UI
- [x] Wire `/api/tyre_inventory` into the FP/Race left panel (backend done). Done
      2026-08-17: the panel markup, CSS, and render function already existed but
      nothing actually called them for the common case — `fetchLeftPanel`'s
      inventory fetch used the global `sessionKey`, which is `null` on the
      default live session (no explicit key entered), and the only call site for
      RACE/SPRINT was `render()`'s mode-*change* branch, which never fires when
      a session loads directly into RACE (the default `currentMode`). Fixed by
      adding a dedicated `fetchInventory()` gated on leader-lap change (same
      pattern already used for the prediction panel, which had hit this exact
      class of bug before — see its "setMode may not have fired" comment),
      fed the actual resolved `session.session_key` from live data instead of
      the raw input field. Verified in-browser via replay mode against a cached
      Imola race (`session_key=9987`): inventory panel now populates on load and
      updates lap-to-lap.
- [ ] Track map: per-driver position dots on a circuit SVG (blocked on OpenF1
      location endpoint reliability).
- [ ] Live-session validation across a full weekend (Quali + Race) for all three
      mode layouts.
- [x] Three pre-race charts, user-requested 2026-08-21 with reference images:
      team race-sim pace, pit-strategy Gantt with pit windows, tyre-availability
      breakdown. All three needed new backend fields (`engine/prerace.py`,
      `PACK_VERSION` 16 -> 17):
      - `team_pace`: per-team gap to the fastest team, re-based from
        `_long_run_pace`'s per-driver deltas (quicker of each team's two cars).
      - `strategies[].pit_windows`: for each pit stop, the `[lo, hi]` lap range
        around the optimal stop — new `_pit_window()`, holding every other
        stop fixed and re-evaluating via `predictor._stint_time` as the one
        stop's lap shifts either way. **Shipped with a scale bug**, caught
        2026-08-22 from a user screenshot after deploy: it originally reused
        `LIVE_MARGIN_S` (10s), which prices a whole extra PIT STOP against
        staying out — right for comparing 1-/2-/3-stop plans, wrong for a
        single stint-boundary shift, where each lap only costs a fraction of
        a second of degradation. On a race with a flat deg curve this let the
        window balloon to ~28 of 44 laps, visually erasing the middle stint's
        colour entirely. Fixed with `PIT_WINDOW_MARGIN_S=2.0` (scaled for the
        single-stop question) plus a hard `PIT_WINDOW_MAX_SHIFT=3` lap cap so
        no degenerate curve (e.g. a compound with ~zero measured wear) can
        blow it out regardless of the time-sensitivity math — verified against
        a synthetic near-flat curve, and proved analytically that adjacent
        windows can no longer overlap and erase a middle stint (`max_shift=3`
        vs `MIN_STINT=8` guarantees at least 2 laps stay visible either way).

        **Second bug, same function, caught 2026-08-23 from another user
        screenshot** (post-deploy of the fix above): a 1-stop strategy ending
        in a short splash stint (`optimize_strategy`'s fallback path, used
        when no legal MIN_STINT-respecting plan exists — e.g. tyre stock too
        constrained — which allows a final stint down to 1-3 laps) rendered
        with NO visible pit-window segment at all, not even a narrow one.
        `_pit_window`'s `time_at()` unconditionally required both adjacent
        stints to be `>= MIN_STINT`; for a genuine 3-lap splash the baseline
        itself (shift=0) already failed that check, so `time_at(0)` returned
        `None` and the window collapsed to zero width — invisible, not
        loudly wrong. Fixed by flooring each side at
        `min(MIN_STINT, base_len)` instead of a flat `MIN_STINT`, so a
        strategy's own already-committed stint length is never rejected,
        while a splash still can't be probed shorter than it already is.
        Verified against a direct reproduction of the reported shape (HARD
        69 laps -> SOFT 3-lap splash): window went from `[69,69]` (invisible)
        to `[66,69]` (window extends earlier, correctly can't extend later
        since the splash is already at its practical minimum); re-checked the
        three normal (non-splash) windows from the first fix were unchanged.
      - `grid[].tyres`: full per-driver new/used set counts per compound (not
        just the existing top-10 boolean summary). "Used" is capped at the
        compound's total allocation — `DriverInventory.used` is a raw stint
        count that can exceed it (some drivers show e.g. 9 "new" SOFT stints
        against an 8-set allocation, most likely a red-flag-split stint or
        restart double-counted as a second fresh set by OpenF1's lap/stint
        data) — caught by executing the actual frontend chart functions
        against real Spain-2026 data in JavaScriptCore before shipping, not by
        eyeballing the numbers. **Superseded 2026-08-23 — see the regulation-
        accurate rewrite below; this per-compound-allocation cap wasn't tight
        enough once the real race-day pool (7, or 6 for Q3) turned out to be
        much smaller than the full weekend allocation.**
      Frontend: `frontend/briefing.js` gained three chart-builder functions,
      added as new customizable sections in `renderPrerace` (they respect
      show/hide/reorder like every other section). Compound and team colours
      reuse the app's existing real-world F1 identity encodings (compound
      colours from `stintbar`/`degCurveCard`, team colours from `grid`) rather
      than a generic categorical palette — deliberate, since these are
      domain-standard colours any F1-literate user already reads by hue.
      Verified by executing the real chart functions (not a mock) against the
      real API response in JavaScriptCore (`osascript -l JavaScript`) and
      inspecting the generated HTML directly — the Claude-in-Chrome browser
      extension was disconnected for this session, so no live-browser/visual
      screenshot check was done; layout/CSS should still get an in-browser
      pass next time the extension is available.

- [x] **Tyre allocation + strategy-candidate redesign, 2026-08-23.** User
      compared the three new charts against a reference F1 strategy site and
      found two of them substantively wrong, not cosmetic. Rather than guess
      at a fix, pulled the actual FIA 2026 Sporting Regulations (Article B6,
      `fia_2026_f1_regulations_-_section_b_sporting_-_iss_05_-_2026-02-27.pdf`
      from fia.com) to find the real rules:
      - **B6.2.4**: full weekend allocation — Standard (non-sprint) Hard 2 /
        Medium 3 / Soft 8 (13 total, unchanged, already correct). Alternative
        (sprint) is Hard 2 / **Medium 4** / Soft 6 (12 total) —
        `ALLOCATION["sprint"]["MEDIUM"]` had been 3, wrong.
      - **B6.3.8a** (Standard) / **B6.3.9a** (Alternative): teams must
        electronically return sets at fixed weekend checkpoints regardless of
        whether they were ever used — Standard returns 2 after FP1, 2 after
        FP2, 2 after FP3 (6 of 13 gone before Quali); Alternative returns 1
        after FP1, 1 after the Sprint, 3 after Quali (5 of 12 gone). Both
        leave **7 sets** for Qualifying + Race, not the full weekend
        allocation — a hard cap the model had no concept of at all.
      - **B6.3.8a.i**: one set of the mandatory Q3 (softest) spec is reserved
        and can't be used or returned before Q3; whoever actually reaches Q3
        must hand back a second set right after, leaving Q3 qualifiers with
        **6** instead of 7. Grid position <= 10 is the closest proxy this
        pipeline has to real Q3 participation (exact Q3 entry can differ,
        e.g. grid penalties) — used everywhere `q3_drivers` is threaded
        through.
      - The regulation does NOT fix which specific compounds get returned —
        team's own choice, and unobservable from OpenF1 stint data (shows
        what was used, never what was returned unused). `used` sets are the
        one thing that IS observable and can't be walked back (once opened,
        a set stays with the driver) — see `engine/tyre_inventory.py`'s
        `DriverInventory.reconciled()`, which replaced the old flat
        `remaining() = allocation - used` with a two-stage reconciliation:
        cap `used` at the per-compound allocation first (same OpenF1
        double-counting artifact as before, just applied earlier), then cap
        the **new** (never-fitted) budget at `race_day_pool - used`, split
        proportionally by largest-remainder rounding so the integers land
        exactly on the pool. This function is shared by three call sites
        (`api/routers/analysis.py`'s live `/api/tyre_inventory`,
        `engine/whatif.py`, `engine/prerace.py`) — fixing it here fixed all
        three consistently, though only `prerace.py` threads a real
        `q3_drivers` set through (the other two don't have quali/grid
        position in scope, a documented, minor simplification — they still
        get the correct *total* pool, just not the Q3-specific -1).

        **Caught a self-inflicted regression while shipping this**: the
        strategy search's `field_stock`/`driver_stock` (gates which
        compound a car can legally start/pit onto) used `.remaining()`
        (new-only). Once new-remaining was correctly tightened to the real
        7/6-set pool, most cars by race day show almost no *new* sets left
        — their stock is mostly *used* ones — and gating on new-only stock
        made every compound's median show 0, so the search found **zero**
        legal strategies at all (a much worse regression than the bug being
        fixed). Real regulation (B6.3.3: "sets of the same dry-weather
        specification may be mixed after Qualifying") confirms a used set is
        just as legally fittable as a new one — added
        `DriverInventory.total_held()` (new+used) and pointed the strategy
        search's stock checks at that instead. Caught by testing against
        real data immediately after the tyre fix, not assumed to be fine.

      **Strategy candidates**: the `for stops in (1,2,3): for start_c in
      DRY:` loop in `build_prerace_data` already tried every (stop count,
      starting compound) combination via `optimize_strategy` — it just kept
      only the single fastest result per stop count, discarding the rest.
      Changed to keep every legal combination (deduped by
      `(stops, compound_sequence)`, sorted fastest-first, capped at 5 — the
      reference site's convention). `engine/strategy.py`'s
      `generate_strategies` (used by the live what-if panel) was considered
      and rejected for this: it always resets to a SOFT start whenever
      `current_compound not in DRY_COMPOUNDS`, which is exactly the pre-race
      lap-0 case, so it can never explore a Medium- or Hard-start candidate
      — the existing `optimize_strategy`-based loop was the right base to
      extend, not a different generator.

      This surfaced a **pre-existing sign bug** in `_stop_decision`'s
      crossover math (`extra_pit_cost_s`/`fresh_rubber_saving_s`), not new
      but far more likely to show now: it assumed `runner` (the next
      different-stop-count candidate) always had MORE stops than `best` (the
      fastest overall) — true only when the fewest-stop plan happens to also
      be fastest. With every starting compound now explored, it's much more
      common for the fastest plan overall to be the higher-stop one (fresher
      rubber outweighing the extra pit time), which flipped the sign
      (`extra_pit_cost_s: -22.0`, nonsensical). Fixed by working out which of
      `best`/`runner` actually carries the extra stop(s) rather than
      assuming it's always `runner`, and added an `extra_stop_worth_it` flag
      so the frontend sentence reads correctly in both directions (`briefing.js`'s
      strategy-card text).

      Also floored `_pit_window`'s zero-width edge case (a candidate whose
      tyres are so poorly matched to the stint that even a 1-lap shift blows
      the 2s margin, e.g. a "not on the table" candidate) to a 1-lap minimum
      for display — a genuinely zero-width green segment renders identically
      to a rendering bug, and this project already shipped that exact bug
      twice this week.

      **What this fixes vs. what it can't**: regulation-accurate totals and
      genuine strategy variety, verified against real 2023-2026 cached data
      (both a standard weekend — Spain, meeting_key 1287 — and a sprint
      weekend — Silverstone, meeting_key 1289 — checked separately since the
      pool math differs). It will NOT necessarily match the reference site's
      exact numbers bit-for-bit: its methodology is unknown, and which
      specific compounds a team returns unused during the weekend isn't
      observable from OpenF1 telemetry at all — only the total remaining
      pool is derivable with confidence from the regulation text itself.
      Not covered by the backtest harness or `audit_strategies.py` (the
      latter calls `optimize_strategy` directly via its own loop, not
      through any of the changed `prerace.py`/`tyre_inventory.py` code) —
      validated by hand against real cached races instead.

      **Follow-up bug, same day, caught from a live screenshot after
      deploying the above**: EVERY driver showed zero HARD sets available,
      including drivers who never touched a Hard in practice at all. The
      proportional-cap approach above was the cause — it split the leftover
      "new" budget proportionally by each compound's raw allocation SIZE
      (8/3/2), which systematically favours SOFT for whatever scarce budget
      remains and starves HARD (the smallest allocation) even when HARD's
      own `used` is 0. A driver who opened several fresh Softs and Mediums
      in practice, once their shared 6/7-set pool was mostly consumed by
      those, had nothing left in the "budget" for their completely untouched
      Hards — mathematically consistent with the earlier design, but wrong:
      Hards you never touched should not evaporate because you used other
      compounds.

      Replaced the shared-pool-with-proportional-split model with **fixed
      per-compound effective allocations**: HARD and MEDIUM keep their full
      raw allocation unconditionally (`effective_allocation - used`, no pool
      interaction at all); the mandatory in-weekend returns are modelled as
      landing entirely on SOFT instead of being spread across all three.
      This isn't a coin flip — two things in the regulation itself point
      the same way: Article B6.3.8a.ii separately guarantees 2 sets of the
      mandatory RACE specification(s) can never be returned early (Hard
      and/or Medium are what typically get nominated, never Soft), and
      Article B6.1.2b defines the Q3-forfeited spec as "always being the
      softest of the three" — so even the ONE compound-specific detail the
      regulation does give us points at Soft, not a neutral split.
      `MANDATORY_RETURNS = {"standard": 6, "sprint": 5}` plus
      `Q3_SOFT_REDUCTION = 1` land on SOFT's effective allocation only;
      `effective_allocation.values()` sums to exactly the same 7/6 pool as
      before by construction, so the total-pool guarantee wasn't lost, just
      recomputed correctly.

      Trade-off, stated plainly: in unusual cases (e.g. a driver who's
      genuinely burned through an atypically high number of real Soft sets)
      the displayed total can now come in slightly above 7/6, since Medium
      and Hard are no longer capped against the shared pool at all. Accepted
      deliberately — the alternative (the previous design) reliably produced
      a *realistic-looking but wrong* number (protected compounds hitting
      zero) in the common case, which is worse than an *unusual* total in a
      rare one. Re-verified against the same real Spain-2026 grid: every one
      of the 20 drivers now shows a non-zero Hard total (was 0 for all 20
      under the previous version), and the untouched-driver/Q3/sprint unit
      tests from the first pass were re-run and still land exactly on 7/6.

      **Third bug, 2026-08-24, caught from user domain knowledge** ("a
      medium and soft is usually used for a free practice... 2 mediums are
      used for the sprint qualifying" — a specific, checkable claim, not a
      vague complaint): on a sprint weekend (Silverstone, meeting_key 1289),
      nearly every driver showed SOFT `used` maxed out at the full 6-set
      sprint allocation. Traced directly against real stint data rather than
      guessed at: NOR's Qualifying session ALONE showed 4 separate SOFT
      stints all marked `tyre_age_at_start=0` (fresh), and cross-referencing
      against the `pit` endpoint confirmed 6 genuine pit-lane visits during
      that one session — so this wasn't `_merge_stint_fragments` missing
      anything (that already handles same-physical-tyre continuation
      correctly; these were genuine separate pit visits). NOR's season-long
      new-SOFT count came to 7, exceeding the 6-set sprint allocation
      outright — a physical impossibility, proving at least some of these
      "fresh" flags don't correspond to genuinely new physical sets. Real
      explanation: teams commonly return to the garage between qualifying
      runs and go back out on the SAME set, and OpenF1 resets the reported
      age anyway rather than continuing it — `tyre_age_at_start==0` is not a
      reliable "this is a new set" signal on its own, especially in
      Qualifying's tight, multi-run window.

      Fixed in `compute_inventory`'s counting loop: at most ONE
      `tyre_age_at_start==0` stint per (driver, compound) counts as a
      genuinely new set **per session** — later same-session, same-compound
      "fresh" stints are treated as re-fitting that same already-opened set,
      not opening another. This also directly matches the user's own stated
      domain expectation (singular "a medium and soft... for A [one] free
      practice") rather than being a separate, independently-chosen
      heuristic. Re-verified against the same Silverstone grid: SOFT `used`
      dropped from a uniform 6 across nearly the whole field to a realistic
      1-3 spread; MEDIUM now shows `used: 2` for most of the field, matching
      the user's stated SQ1+SQ2 pattern almost exactly.

      **Separately investigated, not fixed — a distinct, non-bug finding**:
      the user also asked why no Medium→Hard or Soft→Hard 1-stop candidate
      appears (real strategy calls apparently favour a Hard finish). Traced
      directly by calling `optimize_strategy` for every starting compound at
      `force_stops=1`: it's not a stock/legality gate — Hard-start's own
      best 1-stop is Hard→**Soft** (4925.3s), beaten by Soft-start's
      Soft→Medium (4914.4s) and Medium-start's Medium→Soft (4915.5s). The
      model consistently finds ending on Soft fastest, for every starting
      compound, given the currently fitted degradation curves for this
      specific race: Soft's fitted `deg_rate` is 0.0658s/lap against Medium's
      0.0250 and Hard's 0.0175 — only ~2.6-3.75x steeper, not dramatic
      enough to outweigh Soft's ~0.6-1.0s/lap fresher pace over a ~26-lap
      closing stint at this deg level. That Soft curve rests on only 27 laps
      of data, all from the Sprint race itself (the only long-run source a
      sprint weekend has — no FP2/FP3 to cross-check against, unlike a
      normal weekend) — thin by this project's own established standard for
      when a fitted rate should be trusted (see the DNF/SC per-circuit
      tables rejected elsewhere in this file for resting on a thinner sample
      than that). Deliberately NOT changed: `build_deg_curves` is shared,
      backtest-validated core prediction logic (84.8% winner-hit, tuned and
      measured against 81 races) — adjusting its confidence/weighting for
      sprint-weekend data sparsity needs real backtest validation, not a
      one-race anecdote, and is out of scope for a same-session fix. Left
      as an open question for the user: is a low-confidence-driven adjustment
      (e.g. treating a single-session deg fit more conservatively) worth
      pursuing as a proper, backtested change, or should surprising-but-
      measured outputs like this stand as-is?

      **Resolved, 2026-08-26, by doing the backtest this entry asked for.**
      First checked how widespread the underlying data-sparsity concern
      actually is: scanned all 22 sprint weekends in the cache for their
      fitted SOFT curve. `build_deg_curves` already has real safeguards
      against exactly this (median-not-mean fitting so one bad stint can't
      skew a curve, cross-compound ratio backfill when a compound got no
      long run, a confidence `*` marker on every adjusted curve) — it isn't
      naive. ~7 of 22 hit the full `DEG_UNMEASURED` fallback (no compound
      measured at all that weekend); Silverstone's case was a third,
      thinner-but-real bucket: an actual regression WAS fit from 27 laps,
      landed implausibly low, and got clamped by the existing
      `MIN_DEG["SOFT"]=0.06` floor.

      Then tested the concrete, reversible version of "treat thin fits more
      conservatively": swept `MIN_DEG["SOFT"]` (0.06/0.08/0.10/0.12/0.15)
      against the full 81-race backtest, each value a completely fresh
      `evaluate` run (n=246 checkpoints throughout). Result was
      unambiguous and monotonic in the WRONG direction — every single
      metric got worse as the floor rose, with no local improvement at any
      tested value:

      | MIN_DEG SOFT | winner-hit | MAE | win Brier | podium Brier |
      |---|---|---|---|---|
      | 0.06 (current) | 85.0% | 1.473 | 0.0149 | 0.0477 |
      | 0.08 | 85.0% | 1.479 | 0.0149 | 0.0482 |
      | 0.10 | 84.6% | 1.482 | 0.0152 | 0.0481 |
      | 0.12 | 83.7% | 1.494 | 0.0155 | 0.0490 |
      | 0.15 | 82.9% | 1.513 | 0.0159 | 0.0501 |

      Conclusion: 0.06 is already at (or past) the right side of this
      tradeoff — raising it to suppress Silverstone-style "Soft favoured
      everywhere" outputs would trade real, measured accuracy for a purely
      cosmetic gain (more strategy-row variety on one chart). No code
      change made. The missing Medium/Soft→Hard 1-stop for Silverstone is a
      genuine, now-validated model finding — Soft's real fitted
      degradation at this track and sample size doesn't support ending a
      stint on anything else — not a bug or an undertuned constant.

      **Follow-up, 2026-08-30/31: does track temperature or grip evolution
      explain the remaining inaccuracy?** The user pushed back on the
      MIN_DEG conclusion above — a professional strategy site shouldn't be
      this noisy — and asked specifically whether track temperature or
      weather was factored into degradation fitting. Checked directly:
      confirmed `_stint_deg_samples`/`build_deg_curves` use ONLY lap time
      vs tyre age (plus a fuel-burn correction) — no temperature, humidity,
      or weather input anywhere, despite `get_weather_summary` already
      existing in the codebase (used only for the briefing's narrative
      text, never fed into the regression).

      *Temperature, pooled across circuits*: correlated each race's fitted
      deg_rate against its own track_temp_avg across all genuinely-measured
      (unadjusted, ≥15-point) curves in the cache. MEDIUM (n=48, the only
      compound with enough sample size to trust): Pearson r=0.283 — a real
      but modest signal (~8% of variance). Binning by temperature band
      showed a genuine ~2x mean-degradation increase from the coolest
      (15-25°C, mean 0.050) to hottest (40-46°C, mean 0.112) bands, but
      with within-band standard deviations nearly as large as the
      between-band gaps — real signal, swamped by comparable noise.

      *Direct predictive test (not just correlation)*: for every cached
      race, compared a degradation curve fitted from FP1/FP2/FP3 ONLY (no
      race data — mimicking exactly what a real pre-race briefing has to
      work with) against the ground-truth curve fitted from the RACE
      session alone, then tested whether correcting the FP-only fit by
      (race track_temp − FP session track_temp) × a MEDIUM-derived slope
      brought it closer to the race's real number. Result: **it didn't.**
      MEDIUM baseline MAE 0.0507 vs temp-adjusted MAE 0.0533 (n=42) —
      WORSE, and the correction only reduced error in 12 of 42 races
      (29%). A thin, real correlation applied as a blanket correction adds
      as much noise as it removes.

      *Redone properly after a methodology fix*: found the pooled analysis
      was contaminated — 13 of 64 (compound, race) pairs came from
      sessions where `rainfall=True` was recorded, meaning the "ground
      truth" degradation number for those races reflects mixed/wet running
      conditions, not real dry-tyre wear, and pooling every circuit
      together erases each circuit's own baseline abrasiveness (a "hot"
      day at Silverstone and a "hot" day at Bahrain aren't the same
      physical situation). Excluded the rain-contaminated rows and
      recomputed using WITHIN-CIRCUIT temperature deviation (each race's
      temp vs that circuit's own historical mean, same for deg_rate) —
      correlation nearly doubled to r=0.525 (n=34), a real methodological
      improvement. Re-ran the direct predictive test with this improved,
      circuit-relative correction anyway: baseline MAE 0.0515 vs adjusted
      MAE 0.0670 (n=26) — STILL worse, improved in only 6/26 races (23%).
      The biggest baseline errors in the dataset (Suzuka 2023, Spa 2023,
      Catalunya 2026 — FP-only fits of 0.27, 0.23, 0.30 s/lap against real
      race values of 0.08, 0.06, 0.14) are cases where the FP fit itself
      is already implausibly saturated for reasons unrelated to
      temperature (thin practice sample hitting `build_deg_curves`'s own
      MAX_DEG-adjacent saturation behaviour, already documented and
      audited elsewhere in this file) — no temperature term fixes an
      already-broken FP fit; scaling a bad number by a correction factor
      just relocates the error rather than shrinking it.

      *Track/tyre grip evolution*: checked whether this — a larger,
      already-acknowledged confound (`FP_WEIGHTS`'s own comment: "fuel
      burn-off and track evolution make FP deg rates 2-3x higher than what
      actually materialises in the race") — is separable and fixable.
      It isn't, with the data OpenF1 provides. A first attempt (pooling
      near-fresh-tyre laps, `tyre_age<=2`, across a whole FP2 session and
      checking for a lap-time trend) came back with large but
      DIRECTION-INCONSISTENT shifts across races (+4 to +8s "slower" in
      some, −8 to −16s "faster" in others) — the signature of a bigger,
      different confound: OpenF1 has no fuel-load field, and practice
      sessions mix separately-refuelled low-fuel qualifying-sim runs with
      high-fuel race-sim long runs. Applying the existing `FUEL_RATE`
      correction (`fuel_correction = FUEL_RATE * lap_number`) across a
      whole session — as opposed to within one continuous stint, where it
      already correctly applies — would itself be wrong, since it assumes
      monotonic fuel burn from session start, which practice refuelling
      breaks. Checked the raw `/v1/weather` schema directly for anything
      resembling a grip measurement: only `air_temperature`,
      `track_temperature`, `humidity`, `pressure`, `rainfall`,
      `wind_speed`/`wind_direction` — nothing else. No independent grip or
      fuel-load signal exists in this data source to build a corrected
      version against.

      **Conclusion, backed by two independently-controlled predictive
      tests, not just correlation eyeballing**: track temperature is a
      real, physically-sensible, twice-confirmed effect, but it explains a
      minority of the variance and a direct correction measurably HURTS
      accuracy on the one compound with enough sample to trust either way
      it was tried (pooled and within-circuit). Grip evolution is likely a
      genuinely bigger effect (per the code's own long-standing comment)
      but isn't cleanly separable from fuel-load swings using OpenF1's
      available fields, and the current per-STINT (never per-session)
      fitting design already avoids the worst version of this confound by
      construction — whatever evolution happens within one continuous
      stint's fuel-monotonic window just folds into the fitted `deg_rate`,
      indistinguishable from wear, same as any other unmeasurable factor
      would. Neither line of investigation identified a fixable code
      change. The dominant, actually-actionable error source remains thin
      FP sample size on specific races producing an implausibly saturated
      fit (Suzuka 2023, Spa 2023, Catalunya 2026 all independently
      surfaced as the worst cases in this investigation) — a data-volume
      problem already handled as gracefully as the current architecture
      allows (median-not-mean fitting, cross-compound ratio backfill,
      MAX_DEG-adjacent floors/caps, confidence markers), not a missing
      temperature or grip covariate. No code changed as a result of this
      investigation.

      **Actual root cause found, 2026-08-31: a missing-candidate bug, not
      an uncertainty problem.** Asked to build a confidence/caveat UI for
      the degradation numbers, traced the strategy-candidate loop first to
      find where to attach it — and found `optimize_strategy` has no way
      to force a specific ENDING compound, only the starting compound and
      stop count (`force_stops`). `prerace.py`'s candidate loop iterates
      `(stops, start_c)` and lets the DP freely pick whichever compound
      sequence is fastest for the rest. So for a Medium-start 1-stop, the
      DP already silently compares Medium→Soft vs Medium→Hard internally
      and keeps only the winner — a close alternative like Medium→Hard is
      never even generated as its own option, let alone shown or hidden by
      confidence. This is the real reason "the fastest Medium→Hard 1-stop
      doesn't even show up" (the complaint that started this whole
      investigation): it isn't a missing row filtered out afterward, it's
      a row that was never computed in the first place.

      Fix: added `force_end_compound: str | None = None` to
      `optimize_strategy` (`engine/predictor.py`) — purely additive/opt-in,
      every existing call site passes nothing and is completely
      unaffected; a new `end_ok()` gate filters the final compound in each
      of the 0/1/2/3-stop search branches. `prerace.py`'s candidate loop
      now iterates `end_c in DRY` for 1-stop and 2-stop (forcing each
      legal ending in turn, so a genuinely different sequence gets its own
      row; the DP's own free-choice pick still comes out identical to one
      of the forced iterations, so nothing is lost, and `seen_signatures`
      dedups automatically). 3-stop deliberately keeps its original single
      unconstrained call — see performance note below.

      Verified against real Silverstone 2026 data: `['MEDIUM','HARD']` now
      appears in the strategies list (`time_delta=10.9`, alongside
      `['SOFT','HARD']` at `9.2`), where before neither ending on HARD
      showed up as a distinct row for a Medium start at all. Re-ran the
      full 81-race structural validation (mirroring the sixth-revision
      tyre-model check): 0 violations, and mean distinct ending compounds
      shown per race rose to 2.81 of 3 possible — most races now genuinely
      show candidates ending on all three compounds, not just whichever
      one the DP happened to prefer. `audit_strategies.py` still passes
      structurally.

      **Performance note, investigated properly rather than assumed.**
      Tripling the search (1-stop/2-stop now run 3x each) initially looked
      expensive in the full-cache validation script (~11-15s/race before
      this change -> ~37s/race after). Measured this properly rather than
      trusting that number: isolated the PURE compute cost (network
      pre-cached, same process, second call to `build_prerace_data`) and
      found it's actually only ~2.2s per race — the ~37s figure was
      dominated by the validation script's own repeated fresh network
      fetches across 82 back-to-back races, not by this change's real
      marginal cost. Kept the 3-stop branch on its original single
      unconstrained call anyway (a defensible simplification on its own
      merits — it's already the priciest branch, a coarse-step
      quadruple-nested loop, and forced-suboptimal 3-stop variants almost
      never make the top-5-fastest cut shown in the final table), but the
      production impact of this whole change is minor, not the 2.5-3x hit
      the raw validation-script timing first suggested.

      **Resurfacing caveat, 2026-08-31: user's broader worry about live
      conditions (weather, track surface, other series' rubber) prompted
      one more concrete check.** Temperature and grip evolution were
      already ruled out earlier in this thread; recent circuit
      resurfacing hadn't been. Researched actual public resurfacing
      events for circuits in the cache (no OpenF1 field covers this at
      all) and found a clean, well-documented case: Spa-Francorchamps,
      resurfaced June 2024, before that year's Belgian GP. Directly
      measured the FP-vs-race degradation gap across all 4 cached Spa
      years: 2024 (first race on the new surface) showed a MEDIUM gap of
      +0.1765 — roughly 4x 2025's +0.0432, and 2026 was back to
      essentially zero (−0.0086). Ruled out rain as a confound (2024 was
      dry; 2023 and 2025, both smaller-gap years, were actually rain-
      affected). A second check (Miami, resurfaced ahead of its 2023 GP)
      showed the same DIRECTION but far more weakly and noisily, and half
      the sample was rain-contaminated — real effect, same conclusion as
      temperature: physically genuine, but only 2 usable examples across
      the whole cache, nowhere near enough to fit a numerical correction
      responsibly.

      Built a caveat instead of a correction: `engine/circuits.py` now has
      `RESURFACING_EVENTS` (a small, manually-curated dict of circuit ->
      the season its new surface first raced, currently Spa 2024, Miami
      2023, Shanghai 2024's post-COVID return, Lusail 2023's
      "transformative renovation," Suzuka 2026's West Course work — each
      verified against real news coverage, not general impression) and
      `resurfacing_caveat(circuit, year)`, which returns a fading warning:
      strong in the event year itself, weaker the following year (matching
      what Spa's own data showed), nothing from two years on. Wired into
      `build_prerace_data` as a new `resurfacing_caveat` pack field (bumped
      `PACK_VERSION` 17->18) and rendered as a `.notice` warning at the top
      of the pre-race "Tyre degradation model" card — the post-race
      debrief pack never gets this field, since by then real race data
      already exists and the caveat no longer applies. Verified end-to-end
      against real Suzuka 2026 data (the correct strong caveat came back
      through the full pipeline) and unit-tested directly (6 new tests in
      `tests/test_circuits.py`, covering fade timing, substring matching,
      and the no-year/no-match cases).

      **Intermediate-tyre modelling gap, 2026-08-31, found chasing "explore
      other accuracy angles."** Split the backtest by rain-affected vs dry
      races and found a real, persistent winner-hit gap (63-84% wet vs
      79-91% dry across 25/50/75% checkpoints) that never closed as more
      real race data arrived — unlike temperature/resurfacing, which mostly
      self-corrected once real race laps dominated the fit. Traced the
      cause directly: `engine/predictor.py` had ZERO references to
      INTERMEDIATE or WET anywhere — the core simulation, degradation
      fitting, and strategy DP worked exclusively with
      `DRY = ["SOFT","MEDIUM","HARD"]`. Three confirmed gaps, not one:
      1. `_stint_deg_samples` silently dropped every INTERMEDIATE stint —
         no wet degradation curve was ever fitted from real data, however
         much genuine wet running a race had.
      2. `build_pace_model` DID include intermediate laps in the raw pace
         signal, but applied ZERO tyre-age correction to them
         (`curves.get(c)` returned `None` for a compound with no curve) —
         tyre-wear noise leaked straight into the driver pace-delta.
      3. `_stint_lap_times` silently defaulted an intermediate's baseline
         pace to the SAME as a dry Medium
         (`COMPOUND_DELTA.get(compound, 0)` -> 0 for an unrecognised
         compound) whenever no curve existed — flatly wrong whenever the
         model has to simulate a driver actually on wet-weather rubber.

      Checked sample size before building anything (this project's own
      standard, given per-circuit DNF/FP_WEIGHTS were rejected earlier for
      too few examples): 199 genuine long-run INTERMEDIATE stints (4090
      laps) across the cache — comparable to many already-trusted DRY
      curves. Full WET: only 5 stints (66 laps), nowhere near enough, so
      deliberately NOT given its own fitted curve.

      Fix: widened `_stint_deg_samples`'s compound filter to include
      INTERMEDIATE alongside DRY (fixes #1); this alone fixes #2 and #3 for
      free, since both already read `curves.get(c)` generically rather
      than hardcoding DRY names — once `curves` actually contains a real
      "INTERMEDIATE" entry, the existing age-correction and baseline logic
      just works. Added `INTERMEDIATE_MIN_DEG = 0.02` (the real fitted
      weighted-median slope came back NEGATIVE, -0.0275 s/lap — within one
      continuous inter stint the track is usually drying out fast enough to
      swamp genuine tyre wear, unlike a dry stint where conditions are
      comparatively stable across the same timescale; the existing
      `max(deg, 0.0)` floor already catches the sign flip, this adds a
      small additional floor so the optimiser never treats an intermediate
      as literally zero-wear/infinite-life). Added a real, clearly-flagged
      `COMPOUND_DELTA["INTERMEDIATE"] = 8.0` fallback for when NO real inter
      data exists yet in the current race — explicitly documented as a
      judgment call, not a fitted number (an inter's pace also depends on
      how wet the track currently is, which isn't fittable as one fixed
      constant the way SOFT/HARD's dry offsets are); used only as a
      last-resort default, overridden the moment any real wet running
      exists. Guarded the DRY-only cross-compound-ratio backfill
      (`measured` renamed `measured_dry`) so an unmeasured dry compound can
      never get backfilled from an INTERMEDIATE curve — `DEG_RATIO` has no
      such key, which would have raised `KeyError`.

      Verified directly: real 2024 Canada data (a genuine wet race) now
      fits INTERMEDIATE at 83 points, HIGH confidence, baseline 87.77s vs
      dry Medium's 77.73s — a real, race-specific ~10s wet-pace penalty,
      not a guess. Confirmed DRY curves are bit-for-bit IDENTICAL whether
      or not intermediate stints are also present in the same input (both
      by direct diff on real 2023 Hungary data and a dedicated unit test) —
      zero regression risk to the validated dry-compound path. 10 new
      tests in `tests/test_intermediate_degradation.py`.

      **Backtest result — reported honestly, including a mistake made
      along the way.** First compared wet-vs-dry backtest metrics before
      and after this fix and reported a clear improvement (73.7% -> 77.2%
      wet winner-hit). That comparison was WRONG: the "before" baseline was
      read directly from `cache/backtest_results.json` without
      regenerating it, and that file had been left, by an earlier same-day
      `MIN_DEG` sweep script, reflecting its LAST-tested (worst-performing,
      `MIN_DEG["SOFT"]=0.15`) value — the sweep's `trap restore` only reset
      the source file, never re-ran `evaluate` to regenerate a genuinely
      clean results file afterward. Caught the error by re-running the
      IDENTICAL post-fix code twice (bit-for-bit reproducible results,
      ruling out Monte Carlo noise as an explanation for the apparent
      "improvement"), then git-stashed the fix entirely and regenerated a
      TRUE clean baseline (confirmed `MIN_DEG["SOFT"]=0.06` correctly
      restored first) for a genuine apples-to-apples comparison. The real
      result: wet winner-hit 77.19% both before and after (identical to 4
      decimal places), dry winner-hit 86.31% both before and after, wet MAE
      1.333 before vs 1.378 after (negligibly worse, not better). No
      measurable backtest benefit either way — unlike the temperature
      correction, which measurably HURT accuracy when tested properly, this
      one shows no measured harm either.

      Kept anyway (explicit user decision, given the honest evidence): the
      three underlying bugs are real and independently confirmed (direct
      code reading, not guessed), and the fix means the model now uses real
      wet-condition data instead of silently dropping it or assuming a wet
      tyre paces identically to a dry Medium — correct on its own terms.
      Best available explanation for the flat backtest read: `winner`/`mae`
      are scored at fixed 25/50/75%-of-race-distance checkpoints, but this
      fix's most valuable piece (a real baseline when projecting a driver's
      FUTURE stint on intermediates) only matters for a checkpoint that
      falls while conditions are STILL wet — a race whose rain came early
      and dried out well before 25% distance would never exercise that
      forward-looking path at any of the three scored checkpoints, even
      though the fix is doing the right thing. Not proven, flagged as the
      leading hypothesis rather than fact.

      **Fourth bug, same day, caught by the user re-deriving the regulation
      math by hand**: after the third fix above, MEDIUM and HARD showed
      `new+used` summing to MORE than their own allocation for several
      drivers (e.g. MEDIUM at 4 when only 3 sets exist all weekend) — a
      plain arithmetic contradiction, not a judgement call, and the user
      caught it immediately. Root cause: the "effective allocation" model
      from the second fix gave HARD and MEDIUM their FULL raw allocation
      UNCONDITIONALLY (to stop them being diluted to zero), which
      guarantees `used[MEDIUM]+new[MEDIUM] == 3` and `used[HARD]+new[HARD]
      == 2` ALWAYS, regardless of the 6/7-set pool — 5 sets locked in no
      matter what, plus whatever SOFT's real (often higher) usage adds on
      top, routinely totalling 8-9. Fixing the second bug had silently
      broken the total-pool guarantee the very first fix established.

      This needed a design that satisfies BOTH constraints at once, which
      neither of the previous two attempts did:
      1. `used` per compound is an observed floor (can't reduce).
      2. Total held, summed across all three compounds, must equal the
         race-day pool EXACTLY (not "at most") — the regulation removes a
         fixed number of sets, no more, no less.
      Replaced the per-compound "effective allocation" with the ORIGINAL
      shared `race_day_pool` (reverting most of the second fix's structure)
      but with corrected distribution logic: the pool's leftover "new"
      budget is handed out to compounds in ASCENDING `used` order — the
      LEAST-used compound gets first claim on whatever's left (protecting
      an untouched Hard from dilution, fixing bug #1), and only once that's
      satisfied does the budget move to the next-least-used compound
      (usually Soft last, since it's normally the most-used) — rather than
      proportional-by-allocation-SIZE (bug #1's original mistake) or
      unconditional-by-compound (this bug's mistake). Ties (multiple
      compounds at the same `used`, most commonly all untouched) split
      their shared slice of the budget proportionally rather than whichever
      sorts first grabbing it all.

      Re-verified against the full field of both previously-checked real
      races (Spain standard weekend, Silverstone sprint weekend): all 20
      drivers on each now sum to EXACTLY 6 (Q3/top-10) or 7 (rest of field)
      — zero violations, checked programmatically, not by eye. The specific
      drivers from the user's screenshot (NOR/VER/LAW) now show clean 6-set
      totals matching a real Q3 pool exactly.

      **Fifth revision, same day, caught against a genuine external
      reference**: the user found F1's own race-morning "Strategy Guide"
      article for the 2026 Hungarian GP, which publishes a per-driver
      tyre-availability chart. Directly compared against it (not by eye —
      fetched the real page, cross-checked its prose against our numbers):
      our top Q3 drivers (NOR, HAM, LEC, VER, RUS) were all showing 0 new
      Hard AND 0 new Medium, while F1's own chart showed most of them
      holding 1-2 new sets of each in reserve. Root cause: the fourth fix's
      shared `race_day_pool` (6/7 sets total, enforced as a hard ceiling)
      was itself the wrong model — Article B6.3.8a's mandatory in-weekend
      returns cap how many sets CAN survive to race day, but a driver who
      barely touches a compound in practice doesn't lose it to that cap;
      the pool-ceiling design forced heavy Soft users' practice mileage to
      crowd out completely untouched Hards and Mediums regardless, which is
      exactly backwards from how real tyre economy works. (Also traced,
      before this fix: OpenF1 provided no way to check where the F1.com
      numbers actually came from — confirmed by testing every plausible
      public source: the OpenF1 API itself has no tyre-nomination endpoint
      at all (`tyre_sets`, `tyre_allocation`, `nominated_tyres`, etc. all
      404), and F1.com's own generic pre-weekend tyre article, Mercedes's
      team site, and a third-party tyre-strategy site all publish only the
      flat default allocation, never a per-driver breakdown. F1's Strategy
      Guide chart is analyst reporting/estimation, not a fetchable dataset.)

      Replaced the whole race-day-pool/greedy-distribution system (the
      entire third and fourth fixes' machinery) with the simplest model
      that still respects a hard physical fact — `used` can never exceed a
      compound's own allocation — and nothing else: **remaining = full
      weekend allocation (13 sets standard / 12 sprint, per Article B6.2.4)
      minus genuinely-opened sets for that compound, per compound,
      independently**. No shared pool, no proportional capping, no
      least-used-first distribution across compounds. This directly matches
      the user's own worked example from earlier in the session (subtract
      each FP session's usage from the 13-set total as the weekend goes,
      arriving at "4 new softs for quali... a medium and a hard for the
      race") rather than the regulation-derived pool-ceiling reading this
      file had been defending across three prior fixes.

      Re-verified against real Hungary 2026 data (meeting_key 1291, all
      pre-race sessions including live-fetched Qualifying stints, since
      quali wasn't in the local dev cache): NOR's and HAM's Hard/Medium
      counts now land on exactly what F1.com's own chart shows (Hard new=2,
      Medium new=1 for NOR; Hard new=2, Medium new=0/used=3 for HAM) — the
      first time this model has matched an external reference on a specific
      compound rather than just being internally self-consistent. Soft
      still diverges for heavy-Soft-usage drivers (this model's per-session
      dedup still gives NOR 4 genuinely-opened Soft sets across
      FP1/FP2/FP3/Quali; F1.com's chart implies fewer) — most likely because
      real teams sometimes carry the SAME physical Soft set across multiple
      sessions, which OpenF1's `tyre_age_at_start` can't distinguish from a
      genuinely new set once it resets at a session boundary. That's a data
      ceiling (no physical tyre-set ID exists in the public feed), not a
      reconciliation-math bug — flagged here rather than patched, since
      three previous "fixes" to this exact file were each a plausible-
      looking patch to a model whose foundation, not its arithmetic, was
      wrong.

      **Sixth revision, same day, caught by the user's domain knowledge
      directly refuting the "data ceiling" conclusion above**: the fifth
      revision's Soft gap wasn't a telemetry limitation. The user stated the
      actual mechanic directly: a top runner fits a genuinely NEW Soft every
      session (no cross-session reuse — confirmed independently by lap-time
      evidence: NOR's fresh-flagged stints in FP1/FP2/FP3/Quali each showed
      consistent, non-degrading ~78-79s pace, which a reused/worn tyre
      physically cannot produce), AND "used" in F1's chart specifically
      means "opened but still race-viable," not "opened, period." A Soft
      fitted for a Qualifying segment runs ~3-4 laps and stays essentially
      fresh; one opened for a Practice run gets meaningfully worn and drops
      out of race-day availability entirely — a length-based classification,
      not a session-count one.

      Root cause of the gap: this file was still counting "how many sets
      were opened" and treating every opened set as available. Real
      strategists split that into three buckets — never opened (new),
      opened-but-still-viable (used, i.e. what the chart calls "used"), and
      opened-and-worn (gone from availability, but still consumes
      allocation) — and the only sound way to sort an opened set into the
      last two buckets from OpenF1 data is by how many laps it actually
      ran, not by which session it was opened in.

      Replaced the per-session-count model with per-set lap accounting:
      `DriverInventory` now tracks `used` (opened, ≤`SHORT_STINT_LAPS` laps
      so far, still available) separately from `discarded` (opened,
      >`SHORT_STINT_LAPS` laps, gone from availability but still charged
      against the compound's allocation) — `new` is the allocation minus
      both. Building each physical set's total mileage needed one more
      correction, found by testing the naive "no cap, every fresh flag is
      its own group" version against real data first: it correctly split
      Qualifying (NOR's real Quali stints: one 7-lap Q1 group plus three
      independent 3-lap groups for Q2 and two Q3 attempts — length alone
      sorts the worn one from the three fresh ones, no segment-counting
      needed), but wrongly split Practice, where OpenF1 fragments ONE
      physical tyre into multiple `tyre_age_at_start==0` stints across
      pit-lane in/out cycles within the same run (verified: NOR's FP1 showed
      3 separate fresh flags for what pace evidence says is one 13-lap
      tyre) — counting each as an independent group misclassified a
      genuinely worn set as three short "still fresh" fragments. Fix: a
      non-Qualifying session caps at one real group per compound (later
      fresh flags fold in as continuations, same as any non-fresh stint);
      Qualifying gets no cap at all, since it's genuinely three elimination
      segments under one session_key and length alone correctly separates
      real sets from artifacts there.

      Re-verified against real Hungary 2026 data end-to-end (through the
      actual API, not just a unit test): NOR now matches F1.com's own chart
      exactly on Soft-used (3), Medium-new (1), and Hard-new (2) — the
      first exact match on the compound that four prior revisions couldn't
      reproduce. Re-checked the original Silverstone 2026 sprint-weekend
      pathological case that motivated the very first per-session dedup
      (NOR's sprint Quali previously producing a physically-impossible
      7-set Soft count against a 6-set allocation): now 0 violations across
      all 20 drivers, with Soft usage correctly capped at the 6-set
      allocation rather than needing a separate artifact guard. Full-field
      sanity re-run on both races: `used + discarded + new` sums to exactly
      the full weekend allocation for every driver, every compound, zero
      exceptions. `audit_strategies.py` still passes structurally (unrelated
      to this file, as before).

      **Seventh bug, same day: Cadillac silently missing from team_pace and
      the tyre chart.** Not a bug in either chart — both already handled a
      team with no data correctly (`_team_pace`'s `no_data` fallback has
      existed since the charts redesign). The actual cause was one line
      upstream in `build_prerace_data`'s grid construction: `grid = [...][:20]`,
      a hardcoded slice sized for the pre-2026 20-car field (10 teams). 2026
      added Cadillac as an 11th team, making 22 cars — if both of one team's
      drivers finished/qualified outside the top 20, that team's cars were
      silently cut from `grid` entirely, before `_team_pace` or the tyre
      chart ever ran, so the team didn't even appear as "no data" — it just
      wasn't there, with nothing to explain why. Confirmed directly: Hungary
      2026's `grid` had exactly 20 entries and `team_pace` had exactly 10
      teams, both missing Cadillac outright, even though real long-run pace
      data existed for at least one of their drivers.

      Fix: removed the `[:20]` cap. `if d.position` already bounds the list
      to genuinely classified drivers, so no separate size cap is needed —
      the list is however large the real field is. Re-verified: Hungary
      2026's grid now has 22 entries, both Cadillac drivers appear with real
      tyre data, and Cadillac appears in `team_pace` with a real (non-
      `no_data`) gap figure. Re-ran the full 81-race structural validation
      from the sixth revision afterward: 0 violations across all 81 races
      (68 succeeded on the first pass, the other 13 — all pre-2026, 20-car
      fields — failed on a transient local network drop and passed clean on
      retry), confirming the fix doesn't disturb any pre-2026 race's grid
      size. `audit_strategies.py` still passes structurally.

### Refactor / cleanup (deferred)
- [ ] Consider merging `degradation.TyreDegradation` and `predictor.DegCurve`
      into one curve type. Deferred: their builders take different inputs and
      feed different subsystems, so a merge changes behaviour on the live/
      strategy path (not covered by the backtest fingerprint). Do it only with a
      test that exercises `build_degradation_curves` + `predict_drivers`.
- [ ] `build_state` (data/live.py, ~180 lines) and `build_prerace_data`
      (prerace.py, ~200 lines) are the remaining oversized functions — left
      un-split because they can't be verified offline without OpenF1 access.

### Docs — where detail is still thin
- [ ] `engine/predictor.py` internals deserve a dedicated design note (the DP in
      `optimize_strategy`, the position/pace blend math).
- [ ] Briefing prompt design + `PACK_VERSION` history are undocumented.
- [x] No automated test suite yet — only the backtest harness and manual
      replay. Done 2026-08-26: added `tests/` (pytest). Unit tests for
      `engine/tyre_inventory.py` (synthetic stints, no network) reconstruct
      the exact bugs found and fixed this session — same-session tyre
      fragmentation, the Qualifying no-cap case, the allocation-exceeded
      bug — so a regression on any of them fails a test, not just a manual
      screenshot check. Unit tests for `_pit_window`/`_team_pace` cover the
      pit-window-cap and Cadillac no-data cases the same way. A separate
      `integration` marker (skipped by default, run with `pytest -m
      integration`) hits `build_prerace_data` against real cached 2026
      meetings for the Cadillac grid-slice regression and strategy
      structural checks — kept out of the default run so `pytest` alone
      stays fast and network-free.

---

## Notes for future sessions
- Keep this file current: when you change a tunable default, an endpoint, or a
  cache TTL, update the relevant section here in the same change.
- `cache/`, `briefings/`, `recordings/`, `*.log`, and `.env` are gitignored.
- Don't commit credentials or generated briefing/cache artifacts.
