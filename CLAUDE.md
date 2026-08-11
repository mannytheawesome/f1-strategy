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
- [x] Sharper SC modelling. Partially done 2026-08-11: found and fixed
      `SC_RATE_CIRCUIT`'s matching bugs (only 6/26 circuits were ever actually
      matching — see above) and wired the Monte Carlo SC lottery to use the
      real per-circuit table instead of a street/normal binary. Brier-score
      impact was negligible (SC is rare enough per lap not to move win/podium
      probability much) — kept as a correctness fix, not a measured gain.
      Actual SC *window timing* (vs. flat per-lap probability) is still open.
- [ ] Validate deg-curve blending weights (`FP_WEIGHTS`) against per-track
      backtest error.

### Product / UI
- [ ] Wire `/api/tyre_inventory` into the FP/Race left panel (backend done).
- [ ] Track map: per-driver position dots on a circuit SVG (blocked on OpenF1
      location endpoint reliability).
- [ ] Live-session validation across a full weekend (Quali + Race) for all three
      mode layouts.

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
- [ ] No automated test suite yet — only the backtest harness and manual replay.

---

## Notes for future sessions
- Keep this file current: when you change a tunable default, an endpoint, or a
  cache TTL, update the relevant section here in the same change.
- `cache/`, `briefings/`, `recordings/`, `*.log`, and `.env` are gitignored.
- Don't commit credentials or generated briefing/cache artifacts.
