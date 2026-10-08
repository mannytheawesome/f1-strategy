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

### Site analytics (`/admin`), added 2026-09-14
User-requested self-hosted analytics: how many people are visiting, and
which races/features they interact with most. Deliberately not a
third-party service (Plausible/GA/etc.) — this is a personal-scale hobby
project, and a plain SQLite table is enough.

- **Public side**: `frontend/briefing.js` and `frontend/index.js` each carry
  a small `track(event_type, page, label)` helper (duplicated, not shared —
  matches this project's existing "no build step" convention). Visitor
  identity is a random UUID generated client-side and kept in
  `localStorage` (`f1_visitor_id`) — never an IP address or any other PII.
  Events fire via `navigator.sendBeacon` so they can never block the page
  or surface an error to a visitor, even if the endpoint is down. Tracked:
  `pageview` (briefing/live, on load), `race_view` (label = country name,
  fired the moment a race card is clicked — not gated on the briefing
  actually loading), `feature` (labels: `whatif_open`, `customize_layout`,
  `standings`).
- **Storage**: `data/usage.py`, a single `events` table
  (ts, visitor_id, event_type, page, label). `record_event` no-ops on a
  missing visitor_id/event_type and truncates oversized fields rather than
  raising — `/api/track` is public and unauthenticated, so malformed input
  must never be able to break or bloat the DB.
- **Admin dashboard**: `frontend/admin.html`/`.css`/`.js`, served at `/admin`
  (not linked from anywhere public, gated by ADMIN_TOKEN at the API layer,
  not by obscurity). Prompts once for the token, stores it in
  `localStorage`, sends it as an `X-Admin-Token` header on every
  `/api/admin/stats` call. Shows: total/today/7-day unique visitors,
  pageviews by page, most-viewed races, most-used features, a daily
  pageview chart, and a raw recent-events log.
- **Auth default is the OPPOSITE of `_regen_allowed`**: briefing
  regeneration (`api/routers/briefings.py`) defaults OPEN when ADMIN_TOKEN
  isn't configured (harmless — it just costs an LLM call). Stats access
  (`_admin_allowed` in `api/routers/usage.py`) defaults CLOSED when
  ADMIN_TOKEN isn't set — visitor data must never become accidentally
  public just because nobody got around to setting a token.
- **Persistence — requires a manual one-time Railway step.** Railway's
  filesystem resets on every redeploy (this project deploys often), so
  `ANALYTICS_DB_PATH` must point at a mounted persistent volume in
  production or the dashboard resets to zero on the next push. Volumes
  aren't configurable via `railway.toml` — they're a dashboard/CLI
  resource:
  1. Railway dashboard → this service → **Settings → Volumes → New Volume**.
  2. Mount path: `/data`.
  3. Add a service variable: `ANALYTICS_DB_PATH=/data/analytics.db`.
  4. Redeploy.
  Locally (and until the volume is set up in prod) it defaults to
  `var/analytics.db`, gitignored, resets whenever that file is deleted.
- 15 new tests (`tests/test_usage_analytics.py`): event recording
  (including the malformed-input no-ops and truncation), stats aggregation
  (top races/features don't leak into each other, unique-visitor counting,
  recency ordering), and the admin-auth default-closed behavior.

---

## Architecture

```
frontend/
  briefing.html/.css/.js — briefings SPA (front door, served at "/")
  index.html/.css/.js    — live timing board SPA (served at "/live")
  admin.html/.css/.js    — analytics dashboard (ADMIN_TOKEN-gated, "/admin")
api/
  main.py                — app setup, CORS, router wiring, frontend serving (thin)
  helpers.py             — session-mode / driver serialisation / prediction block
  routers/               — routes grouped by domain:
    meta.py              — session metadata, auth diagnostics
    timing.py            — live/replay board, locations, sectors, intervals
    analysis.py          — FP/quali analysis, tyre inventory, pre-race strategy
    strategy.py          — strategy generation, prediction engine, what-if
    briefings.py         — race listings, pre-race + post-race briefings
    usage.py             — POST /api/track (public), GET /api/admin/stats
data/live.py             — OpenF1 client: OAuth, polling, in-memory cache, build_state()
data/usage.py            — self-hosted site analytics (SQLite; see "Site analytics")
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
Analytics: `POST /api/track` (public), `GET /api/admin/stats` (ADMIN_TOKEN via
`X-Admin-Token` header) — see "Site analytics" below.
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
- **Disk-persistent cache (added 2026-09-21).** `data/live.py`'s
  `_cache`/`_cache_get`/`_cache_set` was purely in-memory, so every Railway
  redeploy wiped it and forced a fresh OpenF1 fetch burst on the next
  requests — this project deploys often, so that burst was happening
  routinely, not just occasionally. Added a disk-backed L2 layer (SQLite,
  `HTTP_CACHE_DB_PATH`, defaults to `var/http_cache.db` locally) that
  `_cache_get` falls through to on an in-memory miss, and `_cache_set`
  writes through to for anything with `ttl >= HIST_TTL` (skips the frequent
  10s live-polling writes, which gain nothing from surviving a restart).
  Production needs `HTTP_CACHE_DB_PATH=/data/http_cache.db` set (same
  Railway volume as the analytics DB, see "Site analytics" above) or this
  reverts to ephemeral-only.
- **`HIST_TTL_FINAL` (~10 years — "forever" in practice).** User-requested:
  as visitor traffic grows, don't keep re-fetching data for races that will
  never change again. NOT a safe default everywhere — a session-scoped
  cache key (e.g. `laps:{session_key}`) doesn't know whether it was first
  populated while that session was still live, so blindly raising the
  global `HIST_TTL` would risk permanently freezing a partial mid-race
  snapshot the moment a live viewer's request happened to populate it.
  Only wired into call sites that are already provably scoped to a
  long-completed session: `engine/briefing.py` (post-race debriefs, by
  definition only for finished races) and `api/routers/briefings.py`'s
  `race_list`/`standings` (both already filter to `date_end` in the past
  before touching per-session data, including the `session_result` fetch,
  which is now routed through `_cached_get` instead of a bare, uncached
  `_get` call — previously this ran on EVERY cache-rebuild of the season
  schedule/standings, one OpenF1 call per completed race in the season,
  regardless of whether anything had actually changed). Deliberately left
  `engine/prerace.py` on the regular `HIST_TTL` — a "completed" FP/quali
  session there can be as recent as `date_end` a few seconds in the past,
  and OpenF1 can lag briefly finalising a session's last laps, so granting
  those effectively-forever trust felt like the wrong safety margin without
  separately verifying a buffer window. The outer `race_list`/`standings`
  response cache itself (`_cache_set(..., 1800)`) was deliberately left at
  30 minutes, not `HIST_TTL_FINAL` — that's what makes a newly-completed
  race actually appear in the schedule promptly; only the *per-race* lookups
  inside it (drivers/session_result for races already known to be over) got
  the forever treatment.
- Verified end-to-end against the real dev server: cold-start `/api/races`
  ~9.9s (full OpenF1 fetch across the season) → after a killed-and-restarted
  process (simulating a redeploy) ~4.4s (session_result/drivers reused from
  disk, only the season's `sessions`/`meetings` lists and the outer
  race_list/standings response actually re-fetch/rebuild) → same-process
  repeat ~0.02s (pure in-memory hit). 8 new tests
  (`tests/test_live_cache.py`) plus `tests/test_races_and_standings.py`'s
  fixtures updated to isolate `data.live`'s module-global cache state
  between tests (a real test-isolation gap this surfaced: several existing
  tests reuse `meeting_key=1`, so without resetting `_cache`/`_stale`
  between tests, a fetch-failure test could silently see "stale" data an
  earlier test's successful fetch left behind, instead of genuinely
  exercising the failure path).
- **Follow-up, same day, from a user audit ("are all the systems
  optimized... no routes doing unnecessary processes").** Found two more
  real gaps by actually re-checking rather than assuming the above was the
  whole story:
  1. `race_list`, `standings`, and `next_meeting` each independently called
     `_get("sessions", year=year)` raw and uncached (`race_list` also
     fetched `meetings` separately) — and `frontend/briefing.js`'s init
     fires all three together on every single page load. Added
     `_season_sessions(year)`/`_season_meetings(year)` helpers
     (`_cached_get`, 10-minute TTL — short enough to catch a newly-added
     race promptly) and pointed all three call sites at them, so one
     visitor's page load now shares a single fetch instead of up to three.
  2. Because these route handlers are sync `def` (FastAPI runs them in a
     thread pool, not the event loop), the three endpoints can genuinely
     race on the same cache key — the fix above only helps if requests
     happen to land sequentially, not concurrently. Confirmed this with a
     direct threading test before fixing: 5 concurrent callers for one key,
     no lock, 5 real fetches. Added a per-cache-key `threading.Lock` in
     `_cached_get` (`_fetch_locks`, keyed by cache key) — a second caller
     for a key already being fetched now blocks and re-checks the cache
     instead of duplicating the OpenF1 call. Re-ran the same test after the
     fix: 5 concurrent callers, 1 real fetch, ~0.3s instead of ~1.5s.
  Deliberately did NOT add locking around the *outer* `race_list:{year}`/
  `standings:{year}`/`next_meeting:{year}` response caches themselves (only
  the shared sub-fetches inside them) — under concurrent cold requests
  they can still each redundantly re-*assemble* their response, but that's
  cheap local Python work, not the expensive OpenF1 network I/O the lock
  above already protects; not worth the extra complexity for CPU cycles.
  Also audited every other raw `_get(` call site across `api/`, `engine/`,
  and `data/` (grep for `_get("sessions"`/`_get("meetings"` and similar) —
  the remaining ones (`engine/whatif.py`, `engine/briefing.py`,
  `api/routers/{analysis,strategy}.py`, `api/routers/timing.py`'s
  fallback-session lookup) are all scoped to a specific session/meeting a
  visitor has to actively open, not fired on every pageview the way
  race_list/standings/next_meeting are — so they scale with how many
  distinct races people look at, not with total traffic, and were left as
  they are rather than chased for a much smaller marginal win. 2 new tests
  (`TestSharedSeasonListCaching` in `tests/test_races_and_standings.py`,
  `test_concurrent_requests_for_the_same_cold_key_dedupe_to_one_fetch` in
  `tests/test_live_cache.py`); `tests/test_next_meeting.py`'s fixtures also
  needed the same `data.live`-module isolation fix as
  `test_races_and_standings.py` once `next_meeting` started sharing the
  same caching path. Full suite 123/123 passing.

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
- [x] The lap-0 pre-race win/podium projection (what the "Race Briefings"
      page shows before a race) had never been backtested — every accuracy
      figure ever reported (the 84.8% winner-hit number, etc.) only
      evaluated predictions made AFTER the race started
      (`backtest_full.py`'s `EVAL_FRACTIONS = [0.25, 0.50, 0.75]`), using
      real in-race data. Found and fixed 2026-09-13 (sixteenth issue, see
      log): built `backtest_prerace_projection.py`, found the pre-race
      projection badly overconfident (14% winner-hit, top pick given
      70-90% almost every race, actual winner given ~0% in most misses).
      Root cause: every driver's pace uncertainty was a flat, hardcoded
      constant — worse, the existing `pace_std` field was completely
      vestigial, never read anywhere. Fixed by adding a real, laps-counted-
      based uncertainty (`pace_bias_std_s_per_lap`) into `run_monte_carlo`.
      Win/podium Brier score improved ~15% on re-test; judge this by Brier
      score, not winner-hit rate, which actually rewards overconfidence
      when it pays off by luck.
- [x] RUS is the actual winner in 4 of 14 backtested 2026 races, none
      predicted by the model. Flagged 2026-09-13, investigated 2026-09-14:
      NOT RUS-specific. Compared FP-pace-rank vs grid position across all
      16 completed 2026 races for RUS/VER/NOR/HAM: RUS does show the
      largest gap (mean +1.69 positions, FP pace ranks him worse than he
      qualifies), but VER (+1.14) and NOR (+1.31) show the same-direction
      pattern at similar magnitude -- only HAM differs (-0.57). An earlier
      5-race partial sample had suggested this was RUS-specific and NOR
      was the opposite; that read didn't survive the full 16-race check
      and was wrong -- worth remembering before trusting a small sample
      again. Read as a genuine, general phenomenon (front-runners often
      don't show true race pace in FP) rather than a fixable measurement
      bug -- no code change made. Re-run `_completed_2026_races()` +
      `build_prerace_data` per driver (see chat history 2026-09-14) if
      revisiting with a full season's data later.
- [x] The "Expected Pit Stop Strategies" table ranked candidates on pure
      lap-time optimization only, with `track_position_weight` (how much
      staying out is worth where passing is hard) computed and used in the
      race-outcome projection elsewhere on the page but never reaching
      this table's own ranking. Found 2026-09-12 investigating a Monaco
      strategy complaint (see "Prediction accuracy" narrative log, twelfth
      issue). Done 2026-09-12 (fourteenth issue, same log): added
      `_track_position_cost`, validated against real median stop counts
      across 48 dry races (street 1.14 avg, normal 1.68 avg) rather than a
      first-principles guess (a probabilistic version was tried and
      rejected — see the log entry for why). Monaco's top-2 are now clean
      1-stops as expected; exact pit-lap timing within that 1-stop is
      still not a perfect match and is logged as a smaller follow-up
      below, not blocking this item.
- [x] Undercut/overcut (`_undercut_power`) and weather rain-risk
      (`_weather_outlook`) both computed real numbers but only fed
      narrative text, never the strategy ranking — same architectural gap
      as track position (see fourteenth issue). Done 2026-09-12 (fifteenth
      issue): undercut/overcut wired in as a pit-window lean indicator
      (◂/▸) rather than a ranking change — it's inherently a two-car
      question the single-car paper table has no opponent to simulate
      against; weather surfaced as `weather_outlook.strategy_caveat`, a
      `resurfacing_caveat`-style `.notice`, not blended numerically into
      the dry-only search.
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

      **Eighth bug, same day, user-reported 2026-09-10: "there is no way
      Audi or Racing Bulls has the top pace from free practice."** Traced to
      Shanghai 2026 (meeting 1280, a sprint weekend): Ferrari/Mercedes/Audi/
      Racing Bulls ranked P1-P4 in `team_pace`, ahead of Red Bull (P8), with
      McLaren showing `no_data: True` outright. Root cause is NOT a bug in
      `_long_run_pace`'s filters — they're doing exactly what they're
      supposed to — it's that the metric silently treats every clean sample
      as equally trustworthy, and two things made this weekend's samples very
      unequal: (1) McLaren's only FP1 running alternated push laps (~93s)
      with 100-155s laps almost perfectly (`93.7, 125.6, 93.7, 125.3, 93.3,
      126.3, 155.0, 154.4`) — the signature of practice starts, not a long
      run — so the existing 1.10x clean-lap ratio filter correctly rejected
      nearly all of it, and their 6-lap Sprint stint lost 2 laps to pit-out +
      the exclusive stint-bound convention, landing at 4 usable points,
      below the 5-per-stint floor: zero net samples, confirmed by pulling
      the raw lap times directly. Contrast Racing Bulls' LAW, whose FP1 laps
      were `99.4, 99.0, 100.5, 99.3, 99.3, 99.3, 99.6` — a textbook long run.
      (2) `_long_run_pace` pools genuine FP long runs and Sprint Race stints
      into the same sample with no distinction, even though a Sprint stint's
      length is a strategy artifact (how many stops that team chose) and its
      pace reflects traffic/defending/tyre management, not a clean pace
      level — confirmed directly: simulating the pipeline with Sprint Race
      excluded still left McLaren absent (so that's not what hides them) but
      cut the field from 14 drivers to 7, and Audi (BOR) still outranked Red
      Bull (VER) even without any Sprint contribution. Also found HAM
      ranking P1 overall pace off just 5 laps, delta -5.887s — an outlier no
      genuine long run produces, visible only because thin samples get no
      distinguishing treatment.

      No fix recovers McLaren's pace — the underlying practice data for a
      clean read genuinely doesn't exist this weekend, an inherent sprint-
      weekend limitation given only one FP session. What's fixable, and
      what was built: `_long_run_pace` now flags each driver row
      `low_confidence` (sample < `PACE_MIN_CONFIDENT_LAPS`=8 laps — chosen
      to catch HAM's 5-lap outlier while not flagging genuine 8+ lap runs)
      and `race_pace_only` (every contributing session is Sprint Race, no
      Practice lap survived at all — chosen over a stricter "any Sprint
      contribution" flag because a driver with both FP and Sprint laps in
      their sample does have a genuine pace anchor). `_team_pace` propagates
      both from each team's faster-ranked driver so the team-level chart
      carries the same caveat. Frontend (`briefing.js`): both the "real pace
      order" table and the team pace chart render a hoverable ⚠ next to any
      flagged row, explaining why in a tooltip, rather than presenting every
      ranking with equal authority. Re-run against live Shanghai 2026 data
      confirms the mechanism: Ferrari (P1 team) is flagged `low_confidence`
      (carried by HAM's 5-lap sample), Audi/Racing Bulls/Alpine/Haas/
      Williams/Aston Martin are flagged `race_pace_only`, Red Bull is flagged
      `low_confidence` (7 laps, just under the floor) — every team beating
      expectations in the ranking now visibly carries the reason why, while
      Mercedes and Cadillac (genuinely well-sampled) show clean. `PACK_VERSION`
      18 -> 19. 7 new tests added (`tests/test_prerace_charts.py`,
      `TestTeamPace` propagation cases + `TestLongRunPaceConfidenceFlags`
      mechanism cases); full suite 49/49 passing.

      **Ninth bug, found live-checking the eighth fix across more races.**
      Silverstone 2026 (also a sprint weekend) confirmed the flags don't
      over-fire on genuinely good data — clean expected order, only Aston
      Martin flagged. But Hungary 2026 turned up a different issue: the
      real pace order table's P2 was `FOR` (Leonardo Fornaroli), McLaren's
      reserve driver, off an 11-lap Practice 1 sample from the mandatory
      rookie FP1 session — ranked ahead of both actual McLaren race
      drivers, despite never qualifying or starting the race. Confirmed
      `_team_pace` was already unaffected (it only aggregates acronyms
      present in `grid`, which is built from qualifying and excludes any
      driver who didn't qualify), but the driver-level `long_run_pace`
      table had no such filter — anyone with a large enough practice
      sample appeared in it regardless of whether they were racing.
      Fixed by adding an optional `grid_acronyms` filter to
      `_long_run_pace`, applied before the field median is computed (not
      just at display time), so a reserve's session can no longer pull the
      baseline every real driver's pace_delta is measured against; wired
      the `build_prerace_data` call site to pass the actual grid's
      acronyms. Re-verified against live Hungary 2026 data: FOR no longer
      appears anywhere in `long_run_pace`, ranks close up cleanly (LEC
      moves from #3 to #2), and no other row's data changed. `PACK_VERSION`
      19 -> 20. 1 new test (`test_reserve_driver_dropped_from_pace_table`);
      full suite 50/50 passing.

      **Tenth and eleventh bugs, live during the 2026 Madrid GP weekend
      (first race checked end-to-end after qualifying since the ninth
      fix).** (10) User-reported UI bug: qualifying best-lap times in
      "Where the lap lives" rendered as raw seconds (`91.824`) instead of
      the expected `1:31.824` — `frontend/briefing.js`'s quali-sectors card
      called `.toFixed(3)` directly on `best_lap`/`theoretical` with no
      minute split, unlike the long-run tables elsewhere on the same page
      which already had one. Added a local `fmtLap()` helper (M:SS.sss,
      no leading `0:` for sub-minute values) and applied it to both full
      lap-time columns; sector times and "left on table" are deltas that
      never cross 60s, left as plain seconds. (11) User-reported, more
      substantial: Madrid 2026 qualifying showed HAM/LEC/VER's "tyres
      available for race" MEDIUM column at 0 used, 0 new, despite each
      having visibly started Qualifying on a Medium for a 6-lap Q1 stint.
      Root cause confirmed against real stint data
      (`engine/tyre_inventory.py`): each had already discarded (genuinely
      worn) one Medium from an FP1 long run and one from an FP2 long run —
      2 of their 3-set allocation gone — and the Q1 stint's exact 6 laps
      landed 1 lap past `SHORT_STINT_LAPS=5` (tuned off Soft banker-lap
      patterns, 3-4 laps), so it was ALSO discarded rather than counted as
      still-viable, wiping the full allocation to zero available. A 6-lap
      Q1 opener on a Medium is normal track-position/banker running, not
      a worn tyre. Raised `SHORT_STINT_LAPS` to 6 — re-verified this
      doesn't touch either FP Medium group (15 and 18 laps, both still
      correctly discarded) or the Hungary NOR calibration case (Quali
      softs 3-4 laps, well under either threshold) — and re-ran against
      live Madrid data: all three now show MEDIUM `{used: 1, new: 0}`,
      correctly reflecting one race-viable set instead of none.
      `PACK_VERSION` 20 -> 21. 1 new test
      (`test_six_lap_qualifying_medium_stint_stays_used_and_available`);
      full suite 51/51 passing.

      **Follow-up on the eleventh fix, same day: the single-constant fix was
      itself a symptom of a real structural problem.** User pushed back —
      "is there still an issue with the algorithm, we've spent a lot of time
      debugging this" — a fair question given how many times `SHORT_STINT_LAPS`
      had already been tuned reactively. Investigated properly instead of
      reassuring: discovered Qualifying stint data had **never been cached
      anywhere in this codebase before** — `_long_run_pace` and every backtest
      caller explicitly skip Qualifying, so this threshold had only ever been
      checked against whichever 1-2 races a user happened to look at (Hungary,
      then Madrid), never against a real distribution. Pulled 30 real
      Qualifying sessions across 2023-2026 (first time this data has existed
      in the cache) and built the actual "real tyre group length" distribution
      per compound: SOFT (n=1976) has a clean two-cluster shape — 3-4 laps
      (banker attempts, 800+543) then a genuine dip at 5 laps (126) before a
      second, more-worn cluster at 6-7 (208+173, two-flying-lap attempts on
      one set) — meaning the ORIGINAL `SHORT_STINT_LAPS=5` was already
      correctly calibrated for Soft, and the eleventh fix's global bump to 6
      would have wrongly reclassified that entire 381-stint second cluster as
      still-fresh. MEDIUM (n=12) confirmed it's almost never used in
      Qualifying at all, and 11 of those 12 real samples were 3-4 laps —
      Madrid's 6-lap stint is the only 6-lap Medium in the whole real
      dataset, a genuine but statistically rare case, not the norm. HARD
      (n=3) has essentially no real sample to calibrate from at all.
      Root cause: `SHORT_STINT_LAPS` was a single constant shared across
      three compounds with genuinely different wear physics, being tuned
      one anecdote at a time — any fix to one compound's edge case was
      guaranteed to either under- or over-correct the others. Fixed by
      splitting it into a per-compound dict (`{"SOFT": 5, "MEDIUM": 6,
      "HARD": 6}`) — Soft keeps its separately-calibrated, evidence-backed
      value; Medium and Hard share a looser one since they physically
      tolerate more mileage before meaningful wear and don't have enough
      real Qualifying sample to justify inventing a more precise split
      between them. Re-verified: Madrid's HAM/LEC/VER still correctly show
      MEDIUM `{used: 1, new: 0}`; full suite re-run to confirm nothing
      Soft-related regressed. `PACK_VERSION` 21 -> 22. 2 new tests
      (`test_medium_and_hard_get_a_looser_threshold_than_soft` plus the
      existing Madrid test updated for the dict); full suite 52/52 passing.
      **Lesson for future single-constant fixes in this file:** before
      bumping a threshold shared across multiple real-world categories
      (compounds, circuits, session types), check whether the categories
      have enough of their own historical data cached to calibrate
      independently, rather than assuming one anecdote generalizes.

      **Twelfth issue, same day, user-reported: Monaco 2026's "Expected
      Pit Stop Strategies" top picks were a 63-lap Hard stint before a
      15-lap Medium, or a 17-lap Medium before a 61-lap Hard — absurd
      single-stint lengths, with the user expecting a clean 1-stop around
      lap 29-39 instead.** Traced to two independent, real bugs, both
      confirmed against real data before touching code:

      1. **HARD's deg curve was contaminated by track evolution.** Its
         entire long-run sample came from FP1 alone — nobody ran Hards in
         FP2 or FP3 at all. Pulled the raw laps: a real 21-lap FP1 Hard
         stint's clean laps actually got FASTER over the run (79.9s ->
         78.0s), track evolution outweighing genuine wear within the
         session. The raw fitted slope came back at/below zero, and the
         old flat `MIN_DEG["HARD"]=0.010` floor let it stay there — a 13x
         gap below Medium's independently (FP1+FP2) measured 0.13 s/lap,
         versus `DEG_RATIO`'s genuinely cross-compound-measured ~0.6x norm.
         Confirmed not Monaco-specific: 23 of 74 cached meetings (31%)
         have this same FP1-only-Hard pattern. Fixed by adding a relative
         sanity floor in `build_deg_curves` — a compound's fitted rate
         can't fall below `DEG_RATIO_FLOOR_FRACTION` (0.4) of what
         `DEG_RATIO` predicts from Medium's own measured rate. Monaco's
         HARD moved 0.01 -> 0.0312. Chose 0.4 empirically: swept 0.4-1.0
         against the real cached FP data and found fractions above ~0.8
         start overriding SOFT's own genuinely-good, independently-
         measured rate too (its own ratio floor exceeds its real fitted
         value), which would repeat the exact same class of mistake in
         the other direction — so 0.4 was picked as clearly safe rather
         than tuned to hit a specific target pit lap.
      2. **Non-sprint weekends never used the real per-circuit pit loss
         at all.** `engine/pit_loss.py` has a per-circuit table measured
         from 2,083 real clean stops across 2023-2026 (16.8s Montreal to
         28.3s Imola) — already wired into `backtest_full.py` and
         `audit_strategies.py`, but `build_prerace_data`'s pit_loss line
         only ever called it for sprint weekends (`get_avg_pit_loss`
         measuring the sprint's own stops); every non-sprint race — the
         large majority of the calendar — silently fell through to a
         flat `PIT_LOSS=22.0` constant instead. Monaco's real measured
         value is 18.1s (n=102), notably LOWER than the flat default
         (correcting an assumption that Monaco's awkward pit entry makes
         it one of the more expensive stops — the lane itself is short,
         and the real data says otherwise). An overstated pit loss makes
         every extra stop look pricier than it is, biasing the whole
         calendar (not just Monaco) toward under-stopping. Fixed by
         wiring `pit_loss_for(circuit)` into the non-sprint branch; the
         now-unused flat `PIT_LOSS` import was removed from `prerace.py`
         entirely (kept in `predictor.py` for other callers).

      Verified against real Monaco 2026 data: `pit_loss` now reads 18.1
      (`circuit_measured`, was 22.0/`default`), HARD's deg_rate reads
      0.0312 (was 0.01), and the previous 63-lap/61-lap single-stint
      options dropped out of the top strategies entirely.

      **What's still open, reported honestly rather than tuned away:**
      with both fixes applied, the model's top-ranked Monaco strategy is
      now a 2-stop plan, not the clean 1-stop the user expected as the
      top pick. Investigated with real historical Monaco data before
      concluding anything: 2025's dry race showed every front-runner
      taking 2+ stops (NOR won on Medium->Hard->Hard, first stop ~lap 18)
      — strong circumstantial evidence of a mandatory-minimum-stops rule
      that season, which the user confirmed was a 2025-only experiment,
      not current for 2026. Checked 2023's dry-portion-only data instead
      (2024 was wet-affected, 2025 rule-distorted) and found a genuinely
      wide natural spread — some drivers ran a single 44-54+ lap stint
      with no incentive to pit early, others pitted as early as lap 18 —
      not a single clean answer either direction. Also confirmed
      `track_position_weight` (how much staying out is worth at a circuit
      where passing is nearly impossible) is only applied in the race
      *projection* elsewhere on the page, never in the strategy candidate
      ranking itself shown in this table — a real, separate architectural
      gap (the table is pure lap-time optimization) rather than a further
      constant to tune. Given the user's own explicit frustration about
      time already spent, chose not to keep blindly adjusting
      `DEG_RATIO_FLOOR_FRACTION` to chase a specific top-2 ranking without
      more evidence that doing so reflects reality rather than just
      matching a prior. Left as an open, documented question rather than
      a forced fix: whether the strategy-ranking table should blend in
      track-position value the way the projection does is a genuine
      product/design decision, not a bug with a clear right answer from
      the data alone.

      `PACK_VERSION` 22 -> 23. 11 new tests (`tests/test_deg_ratio_floor.py`
      — 3 tests including a regression guard that a well-measured SOFT is
      never touched; `tests/test_pit_loss.py` — 8 tests including a wiring
      guard that `prerace.py` no longer imports the flat constant at all).
      Full suite 63/63 passing.

      **Thirteenth issue, same investigation thread, user-confirmed gap:
      `_long_run_pace` (the "real pace order" driver-pace calculation)
      pooled every completed session's clean laps with equal weight** —
      FP1 (barely rubbered in, genuinely slower) counted exactly as much
      as FP2 (the representative session). This is a DIFFERENT code path
      from `build_deg_curves`'s degradation-RATE fitting, which already
      down-weights FP1 to 0.3 via `FP_WEIGHTS` (validated on the full
      backtest back in August) — that weighting was simply never applied
      to the pace-LEVEL calculation at all. Fixed by reusing the same
      `FP_WEIGHTS`/`_weighted_median` machinery: `_long_run_pace` now
      rebuilds the same positional FP1/FP2/FP3/RACE session mapping
      `build_prerace_data` already uses for `fp_data`, tags each lap
      sample with its session's weight, and takes a weighted median
      instead of a flat one. Demonstrated the real effect with a
      synthetic two-driver case: a driver with a contaminated 95s FP1
      stint and a genuine 85s FP2 stint previously landed at the raw
      midpoint (90.0, `statistics.median`) — an exact tie with a clean
      90.0 FP2-only reference driver, hiding that they were actually
      faster. Weighted, their median correctly lands much closer to 85.0
      and they rank ahead. Re-verified against live Madrid 2026 data — no
      crash, sensible reordering (TSU/SAI moved up, LEC dropped out of the
      top 10 as their FP1-heavy sample lost relative weight).
      `PACK_VERSION` 23 -> 24. 2 new tests
      (`tests/test_prerace_charts.py::TestLongRunPaceSessionWeighting`);
      full suite 65/65 passing.

      This was the first of three workstreams opened from the same user
      request ("explore more options... track position value, and others
      too") — the other two (a real track-position cost in the strategy
      ranking; checking whether undercut/overcut and weather risk already
      feed that ranking) are logged separately below as they complete.

      **Fourteenth issue, same thread: added a real track-position cost to
      the strategy ranking.** Investigated the other two pieces from the
      same request first: `_undercut_power` computes a real
      undercut/overcut verdict but only feeds the narrative
      ("the_undercut") section, never the ranking; `_weather_outlook`'s
      `rain_risk` similarly only softens narrative language, never
      influences the (always-dry) strategy search. Same underlying gap in
      all three cases — `optimize_strategy` is a clean, well-tested, purely
      dry, purely lap-time-based search, and everything else (track
      position, undercut/overcut, weather, SC/VSC) lives in separate,
      disconnected displays that never feed back into it. Built the
      track-position piece first since it's what was actually driving
      Monaco's ranking bug.

      Before writing any formula, checked real data (user's explicit ask):
      wrote `stop_count_correlation.py` — median real stop count per
      circuit across 48 clean dry races (2023-2026), segmented by the
      existing `track_position_weight`. Clean, consistent result: street
      circuits (0.85) average 1.14 real stops per circuit, every normal
      circuit (0.50) averages 1.68 — Monaco itself lands at 1.33 (n=3).
      This confirmed the user's claim precisely and gave a real target to
      validate against.

      Tried a first-principles probabilistic model first (laps remaining
      after a stop ÷ `BATTLE_WINDOW_LAPS` = independent chances to convert
      `pass_threshold_s_per_lap` into a pass) and rejected it: it gave
      Monaco an implausible ~89% chance of recovering a lost position once
      enough laps remained, which doesn't match real experience there —
      overtaking difficulty at a track like Monaco doesn't meaningfully
      "reset" every 5 laps the way independent-trials math assumes.
      Documented that dead end rather than shipping it.

      Shipped instead: `_track_position_cost(stops, circuit, pit_loss)` —
      a new helper in `engine/prerace.py`, reusing only already-calibrated
      units (`track_position_weight`, backtest-calibrated against the
      81-race cache; `pit_loss`, now circuit-measured per the twelfth
      issue) with one disclosed judgment-call scale constant
      (`POSITION_RISK_SCALE = 0.6`), applied to every stop beyond the
      mandatory first one. Added directly into each candidate's
      `total_time` before the strategies list is sorted/truncated, so
      `_stop_decision`'s downstream "why is this the optimal stop count"
      narrative stays self-consistent with the table instead of
      contradicting it. Exposed as a new `track_position_cost_s` field per
      strategy (same transparency pattern as `sc_refund_s`).

      Verified against real Monaco 2026 data: the top two strategies are
      now clean 1-stops (Medium->Hard, pit lap 22; Hard->Medium, pit lap
      63), with both 2-stop candidates demoted to 3rd/4th carrying a
      visible +9.2s position-cost penalty — matching the ranking SHAPE the
      user described. Pit-lap timing (22, not the user's suggested 29-39)
      is still not an exact match; tried pairing a higher Hard-degradation
      floor fraction with this fix to see if it would close that gap
      cleanly, but it widens the underlying pace gap between 1-stop and
      2-stop enough that the same position-cost scale is no longer
      sufficient — re-coupling the two constants risks the same
      whack-a-mole pattern flagged after the eleventh issue, so left
      alone rather than chased further. Sanity-checked Silverstone
      (normal `track_position_weight`, real pit_loss correctly sprint-
      measured at 30.9s) — no crash, no 2-stop candidates were pace-close
      enough to reach the top 5 there regardless of the new cost, so this
      pass didn't get a positive-case confirmation (a normal circuit where
      a 2-stop legitimately still wins) — worth checking again on a future
      race where one is pace-competitive.

      `PACK_VERSION` 24 -> 25. 6 new tests
      (`tests/test_track_position_cost.py`, covering the mandatory-first-
      stop exemption, street-vs-normal scaling, and the exact formula).
      Also added `stop_count_correlation.py` at the repo root as a
      reusable, re-runnable validation script — re-run it and re-derive
      `POSITION_RISK_SCALE` if the circuit split ever looks wrong for a
      specific track rather than hand-tuning the constant again. Full
      suite 71/71 passing.

      **Fifteenth issue, same thread: closed out the undercut/overcut and
      weather pieces, both scoped narrower than track position rather than
      forced into the same ranking mechanism.** Undercut/overcut
      (`_undercut_power`) is fundamentally a two-car, reactive question --
      "pitting first jumps a rival" only means something relative to a
      specific opponent's assumed strategy, which the single-car paper
      table has no opponent to simulate against. Rather than invent an
      opponent model, wired its existing `verdict` (undercut/overcut/
      neutral, already computed) into `pitStrategyGanttCard` as a lean
      indicator on each already-shown pit window — ◂ when the undercut is
      favoured (lean toward the early end), ▸ when the overcut is (lean
      late), nothing when neutral. Doesn't touch ranking or `total_time` at
      all, purely tells the reader which side of an already-equal-time
      window a real team would actually pick and why.

      Weather: added `weather_outlook["strategy_caveat"]`, a new key
      alongside the existing `note`/`implication` (which are written for
      the doors/grid-value section specifically, not the strategy table),
      rendered as the same `.notice` ⚠ pattern already used for
      `resurfacing_caveat`. No numeric blending into the dry-only search —
      same reasoning as `resurfacing_caveat`: the honest answer to "what
      happens in the wet" isn't a deterministic timing adjustment, it's
      "expect this table to be overridden". Verified against real Monaco
      2026 data (rain genuinely fell in practice this weekend — a real
      `"high"` case, not synthetic) and the real undercut verdict there
      (`"undercut"`, net +4.2s).

      Also surfaced `track_position_cost_s` (from the fourteenth issue)
      directly in the Gantt row label for the first time — it existed in
      the data pack already but had no frontend display.

      `PACK_VERSION` 25 -> 26. 4 new tests (`tests/test_weather_caveat.py`).
      Full suite 75/75 passing. This closes out the three-workstream
      request that opened with the thirteenth issue (FP1 weighting, track
      position cost, undercut/overcut + weather).

      **Sixteenth issue, biggest finding of the session: the pre-race
      win/podium projection had never been backtested at all, and turned
      out to be badly overconfident.** User asked "how did the race
      prediction go for Madrid" — actual winner ANT was given ~0% win
      probability, predicted P6; HUL, who actually finished P10, was given
      the #2 win-probability slot. Investigating why surfaced something
      much bigger: `backtest_full.py`'s `EVAL_FRACTIONS = [0.25, 0.50,
      0.75]` means every accuracy figure ever reported for this project
      (the 84.8% winner-hit number, etc.) only ever evaluated predictions
      made AFTER the race started, using real in-race lap/gap/stint data.
      The lap-0, FP/quali-only projection — what the "Race Briefings" page
      actually shows before a race — had zero backtest coverage.

      Built `backtest_prerace_projection.py` (results cached to
      `cache/backtest_prerace_results.json`) to test it directly: called
      `build_prerace_data` for all 16 completed 2026 races (14 evaluable —
      Bahrain and Saudi Arabia failed on a cascading OpenF1 429 that
      emptied `sources` entirely, a data-fetch reliability issue, not a
      modeling one) and compared the projected win/podium probabilities
      against real results. **14% winner-hit (2/14), avg podium match
      1.21/3, avg position MAE 3.24** — and critically, the model's top
      pick got 70-90% win probability almost every race while the actual
      winner was given ~0% in most misses. Not random noise: confidently
      wrong, every time.

      Root cause, traced through the actual code rather than assumed:
      `_run_projection` (engine/prerace.py) built every driver's
      `DriverPace` with a flat, hardcoded `pace_std=0.3`, and worse —
      `pace_std` turned out to be a **completely vestigial field**, never
      read anywhere in the whole codebase. `simulate_race` separately
      computes a `confidence` label (HIGH/MEDIUM/LOW) from real
      `laps_counted`, but that too was display-only, never affecting the
      math. `run_monte_carlo`'s actual pace-noise term (`sigma = 0.4 *
      sqrt(remaining)`) is a single flat scalar applied identically to
      every driver — legitimate as a model of generic race-day randomness
      (traffic, mistakes), but it was the ONLY uncertainty in the whole
      simulation, meaning a driver's raw `pace_delta` (however it was
      measured) got treated as ground truth with 100% confidence
      regardless of whether it came from 5 laps or 20.

      Fixed by adding a second, genuinely new uncertainty source rather
      than just wiring up the existing (misconceived) `pace_std` field.
      The key insight: pace-estimate uncertainty is a *systematic bias* —
      if a driver's true race pace differs from their measured
      `pace_delta` by some amount, that error compounds the same way every
      remaining lap, so it should scale LINEARLY with laps remaining, not
      as sqrt(laps) the way `sigma`'s lap-to-lap random-walk noise
      correctly does. Added `pace_bias_std_s_per_lap` to `DriverForecast`,
      computed in `simulate_race` from real `laps_counted` (`PACE_BIAS_BASE
      + PACE_BIAS_THIN_K / sqrt(laps)` — 0.05 s/lap floor even for a
      well-sampled driver, since practice pace never perfectly predicts
      race pace; scaling up sharply for thin samples), and drawn as ONE
      gaussian bias per Monte Carlo run per driver (not per-lap noise),
      scaled by remaining laps, in `run_monte_carlo`.

      Re-ran the exact same backtest after the fix: winner-hit dropped to
      7% (1/14) — Brier score, not hit-rate, is the correct way to judge
      this, since hit-rate rewards overconfidence when it happens to pay
      off by luck. By Brier score, which IS the proper scoring rule for a
      probabilistic forecast: win Brier improved 0.1342 -> 0.1144, podium
      Brier 0.2516 -> 0.2127 (~15% better on both), MAE 3.24 -> 2.98, avg
      podium hits 1.21 -> 1.36. Several actual winners went from ~0% to a
      plausible-but-not-dominant probability (Netherlands' RUS 1.0% ->
      17.4%, Austria's RUS 0.2% -> 6.6%, Italy's ANT 1.0% -> 6.0%) — the
      model stopped confidently ruling out the real answer, even where it
      still doesn't pick it as the favourite. One honest caveat: both
      backtest runs used unseeded Monte Carlo, so some race-to-race
      movement is sampling noise on top of the real effect — trust the
      consistent aggregate direction over any single race's exact numbers
      (Madrid itself barely moved, for instance).

      PACE_BIAS_BASE/PACE_BIAS_THIN_K are judgment calls, not independently
      fitted — no ground truth exists for "true pace uncertainty" to fit
      against. Re-validate any future change to them against
      `backtest_prerace_projection.py`, not by eyeballing whether the
      numbers look reasonable.

      Also flagged, not yet investigated: RUS is the actual winner in 4 of
      these 14 races, none predicted by the model even after this fix —
      worth checking separately whether that's this season's fictional
      Mercedes being genuinely hard to read from practice data, or a
      specific, repeatable blind spot in how RUS/Mercedes pace gets
      measured.

      `PACK_VERSION` 26 -> 27. 4 new tests (`tests/test_pace_confidence.py`,
      including a direct check that an apparently-fast thin-sample driver
      no longer locks up win probability the way a flat-uncertainty model
      would). Full suite 79/79 passing.

      **Seventeenth issue, found while investigating the RUS pattern above:
      a rate-limited session fetch inside `_long_run_pace` was already
      tolerated but left no trace that it happened.** Caught directly:
      running the identical Austria 2026 query twice gave two different
      answers for RUS (pace_rank 7/delta -1.07 vs the reproducible pace_rank
      8/delta -0.907) purely because one run's session fetch got 429'd and
      was silently caught by the existing `except Exception: continue` —
      defensible on its own (a partial field beats a hard crash) but
      invisible, so a rate-limited call quietly produced a worse-informed
      result indistinguishable from a clean one. Fixed by adding an
      optional `fetch_failures` out-parameter to `_long_run_pace`, wired
      through `build_prerace_data` to a new `pace_data_incomplete` pack
      field (`None` when nothing failed), rendered as a `.notice` warning
      naming the affected session(s) — same transparency pattern as every
      other caveat this session (`resurfacing_caveat`,
      `weather_outlook.strategy_caveat`). Backward compatible: the
      parameter defaults to `None` and every existing call site is
      unaffected. `PACK_VERSION` 27 -> 28. 3 new tests
      (`tests/test_prerace_charts.py::TestLongRunPaceFetchFailures`,
      including one confirming omitting the parameter still doesn't raise).
      Full suite 82/82 passing.

      **Eighteenth issue, closing out the RUS investigation: the earlier
      finding was wrong, and the honest correction matters more than the
      original claim.** The prior entry's 5-race sample (Australia, China,
      Japan, Miami, Spain -- Bahrain/Saudi/Canada had failed or were
      missing) showed RUS's FP-pace-rank-vs-grid gap always non-negative
      while NOR looked like the mirror opposite. Re-ran across the full,
      confirmed 16-race season (the seventeenth issue's fetch-failure
      tracking came back clean on every race this time -- no
      `pace_data_incomplete` warnings at all, a good sign the underlying
      data itself was solid this run). With the complete data: RUS's mean
      gap is +1.69, but NOR (+1.31) and VER (+1.14) show the SAME
      direction at similar magnitude -- only HAM differs (-0.57). RUS is
      not uniquely affected; he's the most pronounced case of a pattern
      shared by 3 of the 4 drivers checked. The earlier 5-race read was a
      real methodological lesson, not just a footnote: a small sample
      agreeing with itself is not the same as a real, isolated effect, and
      it's worth re-running with fuller data before trusting a striking-
      looking pattern, exactly the discipline this file has tried to hold
      to all session. No code change -- read as a genuine, general
      phenomenon (front-runners often don't show true race pace in FP
      long runs) rather than a fixable measurement bug. Closes the
      roadmap item under "Prediction accuracy."

      **Nineteenth issue, 2026-09-22, user-reported by directly comparing our
      "Tyres available for race" chart against F1.com's own race-morning
      chart for Monza 2026: our totals per driver ranged 5-10 sets, F1's
      ranged a tight 6-7 across the whole field.** First ruled out the pit-
      stop strategy chart the user also flagged in the same report — re-ran
      `build_prerace_data(1293)` and its 5 pit windows (`[19,25]`, `[35,40]`,
      `[21,27]`, `[28,34]`, `[35,40]`) matched F1's chart exactly; that one
      was a pure label collision (every row read "Strategy 1-stop" because
      all 5 candidates genuinely are 1-stop plans — not a data bug). The
      tyre chart was real: traced VER's worst outlier (shown holding 2/2
      HARD, F1.com showed 1) to zero recorded FP1 stints (and zero laps) for
      driver_number 3 in OpenF1's raw data. Root cause: Monza FP1 had four
      teams run their FIA-mandated rookie/reserve outing (Red Bull/IWA for
      VER, Alpine/ARO for GAS, Williams/BRO for ALB, Cadillac/HER for PER) —
      a different driver_number drove that one session in the same car, and
      `compute_inventory` tracks purely by driver_number, so the substitute's
      tyre usage was invisible to VER/GAS/ALB/PER's inventories entirely,
      inflating their shown availability. Confirmed team_name is the only
      safe pairing key — driver-number proximity is actively misleading here
      (HER/25 subs for PER/11, not the numerically-closer VER/3). Added
      `engine.tyre_inventory.remap_fp1_substitutes(stints, session_drivers,
      primary_drivers)`: for a session, diffs the primary weekend roster
      against that session's own roster, pairs each extra (substitute)
      number to a missing (regular) number sharing the same `team_name`
      (skipped if the pairing is ambiguous — two missing drivers on one
      team in the same session), and rewrites `driver_number` on that
      session's stints before they reach `compute_inventory`. Wired into
      `build_prerace_data` (`engine/prerace.py`): each non-grid-source
      session now also fetches that session's own `get_drivers` (cheap,
      `HIST_TTL`-cached) and remaps before appending to `stints_by_session`.
      Re-verified against live Monza data: GAS and ALB now match F1.com's
      totals exactly (were off by 2 and 2); VER's shown HARD dropped from
      2 to 1, matching F1.com exactly (total sets off by 1, down from 3).
      PER unchanged (his substitute's stint was short enough to land in
      "used," not "discarded" — a genuine case, not a remaining bug). 5 new
      tests (`TestFP1SubstituteRemap`); full suite 128/128 passing.

      **Twentieth issue, same day, follow-up on the same user report: the
      pit-strategy chart's MEDIUM->HARD row also disagreed with F1.com —
      window 19-25 (pure-pace optimum lap 22) vs F1.com's published 22-28.**
      First hypothesis (SOFT/MEDIUM `MIN_DEG` floors too aggressive for an
      ultra-low-deg circuit) was checked against REAL race-measured Monza
      degradation (2023-2026 race stints, fuel-corrected) and DISPROVEN:
      measured MEDIUM (+0.064s/lap) and HARD (+0.055s/lap) were both HIGHER
      than the floors, the opposite direction needed — raising them would
      have pushed the prediction earlier, not later. Rather than tune on
      the one Monza anecdote, built `backtest_pit_timing.py`: for every
      completed 2026 race, compare `optimize_strategy`'s predicted pit lap
      for a given compound sequence against every REAL driver who ran a
      genuine one-stop (excluding a pit lap < 8, added after the first run
      showed six different Monza drivers all "pitting" on lap 3 — a mass
      Turn-1 incident, not six independent strategy calls) with that exact
      sequence. Result across 39 real MEDIUM->HARD one-stop finishers
      (Australia, Suzuka, Spa, Spain): pure-pace prediction was LATER than
      the real stop in 37/39 cases, median 7 laps. SOFT->HARD showed no
      such bias (n=3, median +1 lap). Root cause: `optimize_strategy` has
      no concept of undercut/track-position risk at all — every car is
      optimized as if racing alone, but real strategists (and evidently
      F1.com's own guide) pit a MEDIUM starter earlier than the pure
      lap-time optimum to defend against being undercut, since a MEDIUM
      starter is usually mid-pack and more exposed to that threat than a
      SOFT starter running up front. Checked whether the existing
      `_undercut_power` signal (`net_undercut_s`) could scale this
      per-circuit instead of using one flat number — it didn't correlate
      with the real bias size across the 4 races (Australia had the
      LARGEST real-world bias despite the WEAKEST undercut signal), so
      used a flat, empirically-measured correction instead (the same
      approach `pit_loss_for()` already takes for its circuit-measured
      pit-loss average): `MEDIUM_START_UNDERCUT_SHIFT_LAPS = 6` (rounded
      down from the 7-lap median to stay conservative on a 4-race sample),
      applied in `build_prerace_data` via new
      `engine.prerace._shift_medium_start_earlier`, scoped specifically to
      1-stop candidates starting MEDIUM with a non-softer ending compound
      — excluding MEDIUM->SOFT deliberately, since shifting that split
      earlier would push the final SOFT splash stint's length past
      `SOFT_SPLASH_MAX`, making the DP's own chosen sequence illegal.
      Re-verified against live Monza data: MEDIUM->HARD now shows pit lap
      25, window [22, 28] — an exact match to F1.com's published number,
      though the correction was calibrated on the cross-race backtest, not
      tuned to hit this one figure. Re-ran the backtest after the fix as a
      sanity check (partially in-sample, 3 of the same 4 races): mean bias
      for MEDIUM->HARD fell from -7.46 to -1.76 laps. `PACK_VERSION` 29 ->
      30. 8 new tests (`TestMediumStartUndercutShift` unit tests plus 2 new
      Monza integration tests); full suite 132/132 passing (unit), 5/5
      passing (integration).

      **Twenty-first issue, same day, follow-up: is the flat 6-lap shift
      itself right, or just an average that happens to fit 4 circuits?**
      User asked directly whether prior years' data could calibrate this
      per circuit instead of leaning on one global number, "so it's
      accurate first time around" for circuits never manually checked.
      Built `calibrate_undercut_shift.py`: a LEAN version of the same
      backtest (skips build_prerace_data's team-pace/Monte-Carlo/narrative
      work entirely, computing only degradation curves + one
      `optimize_strategy` call) run across every completed race at every
      circuit, 2023-2026 (96 meetings). Result was a real surprise: roughly
      HALF the well-sampled circuits (n>=10 real matched MEDIUM->HARD
      one-stop finishers) need a LATER correction, not earlier — Mexico
      City's real one-stoppers pit 10 laps *later* than the pure-pace
      optimum, Miami's 2 laps later, Austin's 3.5, Hungaroring's 5, Imola's
      7 — directly contradicting the "MEDIUM starters always defend the
      undercut" read from the original 4-race sample, which turned out to
      have been an unlucky, all-early-biased subset (Australia, Suzuka,
      Spa, Spain). Also surfaced a genuine tension with the twentieth
      issue's own result: Monza's OWN full history (n=20, 2023-2025 only —
      2026 Monza's real one-stops were still the Lap-1-incident-contaminated
      ones filtered out entirely) gives a shift of only +1 lap, not +6 — the
      flat correction's exact match to F1.com's published window for Monza
      was a coincidence of averaging OTHER circuits' bias, not a real
      Monza-specific signal. Flagged this directly to the user (screenshot
      match vs 20 real historical data points) rather than silently keeping
      whichever number looked better; user chose the rigorous per-circuit
      number over preserving the one exact screenshot match. Small samples
      were genuinely wild, not just noisy-but-close — Monte Carlo's n=3
      implied a 32-lap shift — so a circuit needs n>=10 real matched
      drivers to get its own figure; 13 circuits qualify (Miami n=43 down
      to Hungaroring n=10), everything else (including brand-new circuits)
      falls back to the field-median default of 4.0 laps. New module
      `engine/undercut_shift.py` (`CIRCUIT_UNDERCUT_SHIFT` dict +
      `undercut_shift_for()`), mirroring `engine/pit_loss.py`'s existing
      circuit-measured-average pattern exactly. `_shift_medium_start_earlier`
      now takes an explicit signed `shift_laps` (positive = earlier,
      negative = later) instead of a hardcoded constant. Re-verified Monza:
      MEDIUM->HARD now shows pit lap 30 (down from the unshifted pure-pace
      31, using Monza's own +1 lap figure), window [27, 33] — no longer an
      exact F1.com match, and that's the honest, correct outcome given the
      evidence. `PACK_VERSION` 30 -> 31. Tests rewritten for the new signed,
      per-circuit signature (`TestMediumStartUndercutShift`,
      `TestUndercutShiftLookup` — including a test asserting the
      calibration table contains BOTH signs, guarding against silently
      reverting to an early-only assumption); full suite 139/139 passing
      (unit), 5/5 passing (integration).

      **Twenty-second issue, same day, user question: are degradation
      rates different for a used vs a genuinely fresh tyre?** Checked
      with real 2026 race data, matched tyre age (3-8 laps), normalised
      within each race so circuit pace cancels out. Degradation RATE:
      no meaningful difference for SOFT (fresh median 0.040 s/lap vs
      resumed 0.037, n=55/27) — HARD/MEDIUM's resumed samples were too
      thin (n=2, n=7) to say anything. BASELINE pace: a real, consistent
      finding — a resumed (previously-fitted, refitted) SOFT runs ~1.5s
      FASTER than a fresh one at the same nominal age, in 5/5 races with
      enough data in both groups (Canada, Barcelona, Austria, Hungary,
      Netherlands; mean -1.83s), likely the initial graining/bedding-in
      phase a genuinely fresh tyre hasn't been through yet. MEDIUM showed
      no such effect (4 races, mixed signs, median +0.14 — essentially
      flat); HARD only had 1 usable race, too thin to trust either way.
      `build_deg_curves` previously pooled fresh and resumed stints into
      one baseline fit — biased faster than a genuinely fresh tyre's real
      pace, exactly what `optimize_strategy` always simulates (every
      candidate stint starts at age 0). Tagged each `_stint_deg_samples`
      row with `age0 == 0` (fresh) and scoped the baseline weighted-median
      to fresh-only samples, leaving the degradation-rate fit pooling
      everything as before (matches the rate-showed-no-difference
      evidence). A naive, unconditional version of this immediately broke
      on real Monza data: MEDIUM's curve had exactly ONE fresh 8-lap
      sample in the whole strict pool (most FP long runs continue an
      already-opened tyre, not a fresh one), and that one sample was
      itself a noisy outlier — its baseline was ~4 seconds below every
      other sample, and fresh-only filtering made it the ENTIRE baseline,
      overriding 7 other reasonable samples. Fixed by requiring at least
      2 independent fresh stints before trusting fresh-only, falling back
      to the full pool otherwise. Re-checked the fix's actual real-world
      reach across Spa/Suzuka/Hungary/Monza's FP data: the >=2 threshold
      almost never fires in practice — FP long-run data is dominated by
      resumed/continuation stints, genuinely fresh 8+-lap long runs are
      rare, so this correction is mostly a no-op for standard weekends'
      FP-only curves right now. Reported that honestly rather than
      claiming a bigger practical win than the evidence supports — the
      fix is correct, tested, and safe, and would engage more where fresh
      long-run data is actually plentiful (a sprint race session, weighted
      highest via `FP_WEIGHTS`, or the separate live-race system in
      `engine/degradation.py`, not touched by this change and structured
      quite differently — flagged as a natural next step, not done here).
      5 new tests (`tests/test_deg_curve_fresh_vs_resumed.py`, including a
      dedicated regression test for the single-fresh-sample-outlier bug);
      full suite 144/144 passing (unit), 5/5 passing (integration).
      `PACK_VERSION` 31 -> 32.

      **Twenty-third issue, 2026-09-24, user-reported: Baku 2026 FP1 "not
      showing up" on the live-timing board.** Confirmed live: `/live` with
      FP1's session_key sat on "Connecting…" indefinitely; a direct call to
      our own `/api/live?session_key=...` succeeded but took ~11s on a cold
      cache (fast, ~0.2s, once warm). Root cause: OpenF1 restricts public
      API access to an ENTIRE meeting -- including already-completed
      sessions like FP1 -- while any other session in that event is
      currently live (confirmed directly: an unauthenticated call to
      OpenF1 for this meeting returned `401 Live F1 session in progress.
      Global API access (including past sessions) is restricted...` while
      FP2 was live). Our disk cache already shields users from this once
      populated (`data.live._ttl_for_session` gives a completed session a
      long TTL), but nobody had loaded FP1's board yet that weekend, so
      the first real user paid the cold-start cost with the live board's
      "Connecting…" state giving no indication anything was happening --
      indistinguishable from broken. Built `data/warmer.py`: a daemon
      background thread (started from `api/main.py`'s FastAPI `lifespan`
      hook, this app's first use of one) that checks every 2 minutes
      whether any session in the current race weekend ended recently and
      pre-fetches its `build_state` (the same call `/api/live` makes) so
      the cache is already warm before a real user asks. A session is
      re-checked every tick until it's past the same 300s settle window
      `_ttl_for_session` itself uses (matches the point that function
      switches from its own short live-TTL to the long historical one),
      then marked warmed and skipped thereafter; failures (OpenF1 hiccups)
      are swallowed and retried next tick rather than crashing the loop.
      10 new tests (`tests/test_warmer.py`, no real network/threads/sleep
      -- pure decision-logic tests via monkeypatched dependencies); full
      suite 154/154 passing (unit), 5/5 passing (integration). No
      PACK_VERSION bump -- this doesn't change any computed value, only
      when the cache for it gets populated.

      **Twenty-fourth issue, 2026-09-25/26, user pushed back hard on the
      race prediction: "surely Russell should be the favorite, he
      completely destroyed the field in quali."** Checked the real Baku
      grid against the projection and the user was completely right: RUS
      took pole by 0.84s over P2 (a big margin) but was projected only P2
      with 15.0% win probability, BEHIND a driver — BEA — who qualified
      P11, +2.2s off pole, yet was given the field's HIGHEST win
      probability (24.4%) and a predicted P1 finish. Traced it to
      `_run_projection`: it feeds `pace_rows`' FP-long-run `pace_delta`
      straight into the Monte Carlo with zero regard for that same row's
      own `low_confidence` flag. BEA's entire race-pace signal was 5 laps
      from Practice 3 only (`low_confidence: true`), which happened to
      read -2.73s/lap — by far the best in the field — and nothing
      weighed against it. Contrast RUS: -1.25s/lap off a properly-sampled
      10 laps across FP1+FP2, not low-confidence, but still LESS extreme
      than BEA's noisy 5-lap reading, so the unblended number let a small
      sample dominate an entire grid position's worth of real, demonstrated
      form. `engine.predictor.build_pace_model` already solves exactly
      this for the LIVE system (blends a qualifying-lap prior against
      thin race-lap samples, weighted by `QUALI_PRIOR_LAPS`) but
      `_run_projection` is a separate, standalone function that never
      called it. Rather than restructure to share that machinery (two
      independently-tuned pace models, real risk of unrelated regressions
      elsewhere in the pipeline), mirrored the same blending approach
      locally: added `_parse_grid_gap` (reads the real qualifying gap
      already sitting on `grid` -- no extra fetch) and `_blend_pace_delta`
      (identical weighted-average formula to `build_pace_model`'s quali
      blend, `QUALI_GRID_PRIOR_LAPS = 10` matching its `QUALI_PRIOR_LAPS`),
      applied against each driver's gap-to-FIELD-MEDIAN (not gap-to-pole,
      to match `pace_delta`'s existing "vs field median" convention
      elsewhere). Re-verified against live Baku data: BEA's blended delta
      moved from -2.73 to -0.94 (his grid slot sits almost exactly at the
      field's own median gap, so the prior correctly pulls him to "about
      average," not "fastest car on track") and now projects P8, 2.8% win;
      RUS's moved from -1.25 to -1.77 (his big quali margin makes him MORE
      favoured, not less, exactly as it should) and now projects P1, 32.8%
      win — the clear favourite, matching what actually happened on
      track. 14 new tests (`tests/test_projection_quali_blend.py`: pure
      unit tests for both new helpers plus an end-to-end synthetic-grid
      test asserting a dominant pole-sitter beats a thin noisy outlier,
      checked stable across 5 repeated runs given the Monte Carlo
      involved); full suite 164/164 passing (unit), 5/5 passing
      (integration, one transient real-network 429 confirmed to pass on
      retry). `PACK_VERSION` 32 -> 33.

      **Twenty-fifth issue, 2026-09-26, user follow-up after the race:
      "what about the tyre strategy."** Checked the pre-race strategy
      chart's top-ranked candidates against what the real 22-car field
      actually ran: not one driver used HARD tyres at Baku, at all -- the
      whole race was SOFT/MEDIUM only -- yet the chart's top TWO ranked
      one-stops were both HARD-based (`HARD->SOFT` and `SOFT->HARD`), and
      `SOFT->MEDIUM` (what roughly half the real field actually drove) was
      ranked dead last, "not on the table" at +21.6s. Root cause: HARD's
      baseline, fit from a thin 15-point/3-stint FP sample, read 0.19s
      FASTER than MEDIUM's -- physically backwards, since a harder
      compound never generates more peak grip on a fresh lap -- but the
      existing `EXPECTED_OFFSET`/`OFFSET_TOLERANCE` clamp (`build_deg_curves`,
      `engine/predictor.py`) only corrects a deviation bigger than 1.0s
      from the expected +0.4s/-0.6s offsets, so this smaller-but-still-
      backwards reading slipped through untouched. Confirmed not
      Baku-specific by checking Spa and Suzuka's own curves: both had
      raw HARD readings extreme enough (>1.0s off) that the EXISTING
      clamp already forced them to exactly `MEDIUM + 0.4` -- the ordering
      violation itself is a real, recurring pattern the tolerance check
      was never built to catch; Baku was just the first case low-grade
      enough to expose the gap. Added a direct ordering guard right after
      the tolerance clamp -- HARD's baseline may never sit below MEDIUM's,
      nor SOFT's above it, regardless of how small the gap is -- mirroring
      the deg_rate monotonicity check that already exists a few lines
      below it in the same function. Re-verified against live Baku data:
      HARD's baseline corrected to `MEDIUM + 0.4` as intended, and
      `SOFT->MEDIUM` jumped from "not on the table" (+21.6s) to a genuine
      top-3 "in play" candidate (+0.7s) -- matching what half the real
      field actually drove. HARD-based candidates still edge out slightly
      on pure pace even after the fix (HARD's deg_rate is genuinely low),
      which may be a separate, softer real-world-conservatism gap the
      model doesn't capture (teams avoiding an unfamiliar/unraced compound
      even when the linear model says it's close) -- left as a known
      open question, not chased further this session. 5 new tests
      (`tests/test_baseline_ordering.py`); full suite 169/169 passing
      (unit), 5/5 passing (integration, one transient real-network 429
      confirmed to pass on retry). `PACK_VERSION` 33 -> 34.

      **Twenty-sixth issue, 2026-09-27, user question led to a direct
      ask: "automatic recalibration."** Asked whether race pace/tyre
      strategy get remodelled fresh each race -- answer was nuanced: the
      per-race prediction itself always rebuilds from that weekend's own
      FP/quali data, but the per-circuit `undercut_shift` numbers
      (`engine/undercut_shift.py`) were a frozen snapshot from a one-off,
      manually-run script (`calibrate_undercut_shift.py`) -- Baku's own
      result wouldn't feed back into Baku's own number without someone
      re-running it by hand and hand-editing the hardcoded dict. User
      asked for genuine automation. Refactored the script's logic into
      `engine/undercut_calibration.py` (importable, same per-race-cache-
      then-aggregate approach, same `MIN_SAMPLES=10` safety rail the
      original calibration was manually given after finding a real n=3
      case implying a wild 32-lap shift -- the script itself had drifted
      to a looser, unshipped `n>=3` threshold, fixed to match what
      actually shipped) and added `data/recalibrator.py`, a daemon thread
      (mirrors `data/warmer.py`'s existing pattern exactly) started from
      `api/main.py`'s lifespan hook that reruns the calibration once a
      day. It's genuinely incremental: the persisted per-race cache means
      a daily tick only ever evaluates races that completed since the
      last run, not the full 2023-2026 sweep every time. Real operational
      catch before shipping: the module's persisted output defaulted to a
      bare `var/...` path, but production's actual persistent volume is
      only reachable through `HTTP_CACHE_DB_PATH`/`ANALYTICS_DB_PATH`'s
      own explicit Railway env vars (`/data/...`) -- a bare `var/` default
      would have silently lived in the ephemeral container filesystem and
      been wiped on every redeploy, defeating the entire point. Fixed by
      deriving the default directory from `HTTP_CACHE_DB_PATH` itself
      (already correctly pointed at the volume in production), so the
      calibration data persists automatically with zero new Railway
      configuration required. `engine/undercut_shift.py`'s hardcoded
      `CIRCUIT_UNDERCUT_SHIFT` dict stays in the codebase as the bootstrap
      default -- what a fresh deploy uses before the background job has
      produced its own file, or if that file is ever missing/corrupt;
      `undercut_shift_for()` prefers the live file whenever it exists.
      Migrated the already-computed local calibration data
      (`cache/undercut_shift_results.json`, gitignored, from the earlier
      manual run) into the new persisted location rather than
      re-fetching all ~90 historical races from scratch. No PACK_VERSION
      bump -- doesn't change what a fresh generation computes, only keeps
      one of its inputs current over time (same reasoning as the
      twenty-third issue's cache-warmer). 19 new tests
      (`tests/test_undercut_calibration.py`,
      `tests/test_recalibrator.py`, plus 2 new/updated tests in
      `tests/test_prerace_charts.py`'s undercut-shift-lookup coverage,
      now properly isolated from whatever `var/undercut_shift.json`
      happens to exist on the machine running them); full suite 185/185
      passing (unit), 5/5 passing (integration).
- [ ] Consider merging `degradation.TyreDegradation` and `predictor.DegCurve`
      into one curve type. Deferred: their builders take different inputs and
      feed different subsystems, so a merge changes behaviour on the live/
      strategy path (not covered by the backtest fingerprint). Do it only with a
      test that exercises `build_degradation_curves` + `predict_drivers`.
- [ ] `build_state` (data/live.py, ~180 lines) and `build_prerace_data`
      (prerace.py, ~200 lines) are the remaining oversized functions — left
      un-split because they can't be verified offline without OpenF1 access.

### Product / UI — front page (2026-08-31 hero redesign, 2026-09-14 round two)
First redesign round (uncommitted-history note: this file wasn't updated at
the time) added the hero section (next-race banner, live countdown, flag
emoji, `/api/next_meeting`'s `in_progress` field) and auto-loaded either the
in-progress weekend's pre-race briefing or the most recent race's debrief on
page load.

**Round two, 2026-09-14, user feedback against a reference F1.com-style
season-calendar screenshot**: five explicit sub-requests. (1) Header banner
restyled from a flat red bar to a dark bar with a red bottom accent + left
brand mark, Oswald wordmark — kept deliberately understated since the hero
below already carries the strong red treatment. (2) Countdown/hero kept
as-is (explicitly approved, not touched). (3) Sidebar race items now show
the real weekend name (`meeting_official_name` from OpenF1's `meetings`
endpoint, new `official_name` field on `/api/races`) plus a compact top-3
podium (new `podium` field: acronym, team_colour, gap_to_leader, from
`session_result` — sprint sessions get an empty podium so one race weekend
doesn't show two competing top-3s). (4) New `GET /api/standings` endpoint
sums OpenF1's own per-session `points` field across every completed Race-
type session (sprints included, since OpenF1 types them `session_type:
"race"` too) — no self-implemented scoring table; constructor points are
attributed to whichever team a driver actually drove for that session, so a
mid-season team change is handled correctly, unlike the driver-level
`team`/`team_colour` which is just the most recent one for display. Rendered
as the new default landing view in `#briefing` (two-column drivers/
constructors card, `renderStandings` in `briefing.js`), reachable any time
via a "🏆 CHAMPIONSHIP STANDINGS" button pinned above the race list. (5)
Auto-load-on-page-load was explicitly removed — `loadRaces()` no longer
picks an `autoItem`/tries to auto-open a briefing; the page now calls
`loadStandings()` on load instead, so the right panel always starts on the
standings overview rather than either an empty prompt or a briefing the
user didn't ask for.

11 new tests (`tests/test_races_and_standings.py`) covering official-name/
podium population, sprint-session empty podium, a `session_result` fetch
failure not crashing the whole race list, multi-race point summation,
mid-season constructor attribution, and the zero-point-finish edge case.
Full suite 95/95 passing (`-m "not integration"`).

**Round three, 2026-09-21: a "how professional does this look" honesty
check, then a visual polish pass.** User asked directly; rather than just
reassure, actually loaded the live site and gave a specific critique: the
analytical content (deg curves, race-trace charts, what-if simulator) reads
as genuinely credible, but three things undercut it — (1) every briefing
showed a raw "Narrative unavailable (no API key configured)" string, which
turned out to be inaccurate too (checked `/api/debug/anthropic_auth`
directly: the key *is* configured, the Anthropic account is out of credit —
a billing issue, not a code bug, left for the user to fix), (2) the
`railway.app` subdomain, (3) no trust/about content anywhere, (4) the
Courier-New-monospace-everywhere aesthetic reads as "engineering dashboard"
rather than "finished product" to a general audience. User chose to skip
the custom domain for now and asked for a genuine style shift on (4)
("bigger shift toward a polished product feel... refined palette, less
monospace in body copy... staying data-dense") plus the trust content (3).

- **Trust/about footer**, added to `briefing.html`, `index.html` (shorter
  version): what the site is (independent, not affiliated with F1/FIA/any
  team), how predictions are made, and an honest accuracy caveat —
  deliberately did NOT cite the flattering 84.8%-winner-hit in-race number
  (that's for checkpoints with real lap data already in hand); the
  lap-0 pre-race-only projection this site's briefing pages actually lead
  with has a much lower winner-hit rate (see the sixteenth issue above) —
  citing the wrong number in the site's own trust copy would have
  undermined the very thing it's meant to build. Framed honestly instead
  ("calibrated to avoid false confidence rather than chase a flattering
  hit-rate"). Also credits OpenF1 as the data source.
- **Typography**: added Inter (Google Fonts) as the base body/UI font
  across all three pages, replacing `'Courier New', monospace` as the
  default. Monospace (JetBrains Mono) is now reserved for genuinely
  tabular/numeric content via `font-variant-numeric: tabular-nums` plus
  explicit `font-family` on the specific elements that need digit
  alignment (countdown, table numeric cells, chip/date labels) — general
  UI chrome, section headers, buttons, and prose read as a normal
  proportional typeface now. `index.css`'s live timing board deliberately
  kept `.board-wrap` itself on monospace (a dense real-time grid of
  positions/gaps/sector times genuinely needs columns to line up) while
  still moving its surrounding page chrome to the sans font — CLAUDE.md's
  existing "live board is frozen, not the differentiated part" framing is
  why this page got a lighter touch than the briefings front door.
- **Card/section polish**: `.card`/`#race-list`/`.standings-card`/gate
  cards gained `border-radius: 8px` + a subtle box-shadow (elevation
  instead of flat bordered boxes); `.card h2` and similar section titles
  dropped `text-transform: uppercase` + heavy letter-spacing in favour of
  sentence-case + a solid font-weight — this hits ~20+ section headers per
  page for free since the text content itself (`"Race simulation pace — by
  team"`, `"The trade, calculated"`, etc.) was already written in natural
  case in `briefing.js`, only the CSS was forcing it upper. Small
  structural labels (table column headers, `SCHEDULE`, round/date chips)
  deliberately kept as small-caps eyebrow labels — that's a legitimate,
  still-modern pattern, not the thing that read as "terminal."
- No backend changes this round — pure CSS/HTML, so the existing 123-test
  suite is the regression check, not new tests. Verified visually across
  all three pages (briefing front door, live board, admin gate) in-browser
  before shipping, including that canvas-drawn chart labels (driver codes,
  axis ticks) were unaffected by the CSS change, since those come from
  their own JS-set canvas font, not the stylesheet.

**Round four, same day: cheap technical polish, user asked "what else
should I work on" and approved doing all four found.**
- **Favicon**: none existed (browsers showed the generic default icon) --
  added `frontend/favicon.svg`, a minimal on-brand mark (dark rounded
  square, red angled bar echoing the header's `.brand-mark`), wired into
  all four HTML pages via `<link rel="icon">`.
- **Raw error messages were leaking to visitors.** `briefing.js` displayed
  `e.message` directly in three places -- for a failed fetch that's
  literally the backend's `HTTPException(detail=str(e))` string, e.g. a
  raw `requests.exceptions.HTTPError` from an upstream OpenF1 429, shown
  verbatim on a live page (this exact failure mode happened earlier in
  this session during testing). Added a `friendlyErrorMessage(label, e)`
  helper: logs the real error to the console for debugging, shows visitors
  a plain "something went wrong, try again" instead. Deliberately scoped
  to `briefing.js` only -- `index.js`'s equivalent messages are already
  clean (`HTTP {status}`, not raw exception text) and that page is the
  documented lower-priority one; `admin.js` is a private, ADMIN_TOKEN-
  gated tool where the detail is actually useful, not a public-facing
  polish issue.
- **No custom 404 page** -- a bad/stale URL returned bare
  `{"detail":"Not Found"}` JSON with no styling or way back to the site.
  Added `frontend/404.html` (reuses `briefing.css`'s existing header/card/
  footer language) plus a `StarletteHTTPException` handler in
  `api/main.py` that serves it, with a real 404 status, for any
  non-`/api/` path -- `/api/*` 404s (and every other HTTPException the
  routers already raise) keep the exact same `{"detail": ...}` JSON shape
  as before, since this app's own frontend JS parses `.detail` off error
  responses and existing API consumers/tests shouldn't see a shape change.
- **No social preview or meta description** -- pasting the link anywhere
  showed nothing useful. Added `<meta name="description">` +
  Open Graph/Twitter card tags to `briefing.html` (the front door) and
  `index.html`; skipped on `admin.html` (already `noindex, nofollow`,
  no reason to make it more shareable) and didn't add an `og:image` --
  no designed banner asset exists yet, and a preview with just title +
  description is still a real improvement over nothing.
- No new tests (pure HTML/config-level additions); existing 123-test suite
  passing confirms no regression. Verified in-browser: favicon serves
  (200), the 404 page renders styled with a real 404 status, `/api/*`
  404s are unchanged JSON, no console errors.

**Round five, same day: a real accessibility audit, not a guess.** User
asked "can you take a look at the accessibility" — measured actual WCAG
contrast ratios (Python, the real relative-luminance formula) and checked
what's genuinely keyboard/screen-reader operable, rather than eyeballing
it.

- **Contrast failures, measured**: `--muted` (#555) on `--bg`/`--surface`
  came out at 2.57:1 / 2.33:1 -- WCAG AA needs 4.5:1 for normal text, and
  `--muted` is the secondary-text color used ~46 times across the three
  stylesheets (meta-rows, table headers, timestamps). Replaced with
  `#828282` (4.5-5.0:1 on both). Section headings in `--red`/`--purple`
  measured 4.08:1 / 3.50:1 at their actual rendered size (14px/13px --
  neither hits WCAG's "large text" exemption threshold, which needs ~19px
  bold or ~24px regular). Rather than change the shared `--red`/`--purple`
  brand variables (which would also re-color every button/border/hero
  accent -- a much bigger, unrequested visual change), added
  `--red-text`/`--purple-text` lightened variants (#f70030/#b33dff, both
  4.5+:1 on `--bg`) used ONLY where these colors are actual text, not
  backgrounds/borders/accent-color (buttons already pair red/purple
  backgrounds with white text, which independently passes). The 56px bold
  "404" numeral was left on the original `--red` -- genuinely large enough
  to qualify for the relaxed 3:1 threshold, verified before leaving it.
- **Core interactions were keyboard/screen-reader unusable**: every race
  card in the schedule and every driver row (which opens the what-if
  editor) was a bare `<div>`/`<tr>` with only an `onclick` -- no
  `tabindex`, no `role`, not reachable by Tab at all. This is the site's
  primary navigation, not an edge case. Added a `makeActivatable(el,
  handler)` helper in `briefing.js` (`role="button"`, `tabindex="0"`,
  click handler, and a keydown handler firing the same handler on
  Enter/Space) and applied it at all three sites. Verified for real, not
  just by reading the code: tabbed through the page and confirmed a
  visible focus ring lands on each race card in order, pressed Enter and
  confirmed it loaded the briefing exactly like a click; separately
  dispatched a synthetic `KeyboardEvent('keydown', {key:'Enter'})` directly
  at a `tr.clickable` driver row and confirmed the what-if editor opened.
  Added a global `:focus-visible` outline (red on the two public pages,
  purple on admin, matching each page's own accent) -- there was no custom
  focus style at all before, so even the elements that WERE already
  focusable (buttons, links) had only the browser's inconsistent default.
- **Form inputs relied on placeholder text alone** (admin token input,
  live board's session-key input, lap-replay slider, replay-speed select)
  -- placeholder disappears the moment someone types and isn't reliably
  announced as a persistent label by every screen reader. Added a
  `.sr-only` utility class (visually hidden, still in the accessibility
  tree) plus real `<label for="...">` elements for the token/session
  inputs, and `aria-label` directly on the slider/select (a `<label>`
  needs static text to point at; the slider's adjacent "LAP N" display is
  dynamic, so `aria-label="Replay lap"` was the more honest fit there).
- **Deliberately NOT touched**: the what-if editor's drag-based pit-stop
  track (`.seg`/`.seg-age` in `briefing.js`) is still mouse/touch-only.
  Making a genuinely drag-based interaction keyboard-operable needs real
  interaction-design work (what does Enter/arrow-keys even mean on a drag
  handle without redesigning the control), not a five-minute tabindex
  bolt-on like the rest of this pass -- flagged here rather than shipped
  half-done.
- No new automated tests (this is CSS-variable + HTML-attribute level, not
  new logic to unit-test); existing 123-test suite passing confirms no
  regression, and the keyboard-activation behavior itself was verified for
  real in-browser as described above, not just asserted.

### Qualifying simulation pace chart, 2026-10-02
User request (inspired by a similar chart seen elsewhere): added "Qualifying
simulation pace — by team" alongside the existing "Race simulation pace —
by team" card on the pre-race briefing. New `engine.prerace._quali_sim_pace()`
mirrors `_long_run_pace`'s shape (both feed the same `_team_pace` helper) but
reads FP **hotlap** stints (1-2 timed laps, `fp_analysis.FPStint.
classification == "HOTLAP"`) instead of 6+-lap long runs, and takes each
driver's single best lap across practice sessions rather than a weighted
median — qualifying is about your fastest lap, not an average pace level.
Built from practice sessions only, same as `_long_run_pace` — deliberately
never reads the real Qualifying session, so it's a genuine pre-qualifying
prediction, checkable against the real result once it happens, not a
readout of it. New pack fields `quali_sim_pace`/`quali_team_pace`/
`quali_sim_data_incomplete`. `PACK_VERSION` 34 -> 35. `frontend/briefing.js`'s
`teamPaceCard()` now takes a `'race'|'quali'` preset instead of hardcoding
race-pace copy, so both charts share one renderer.

Backtested immediately (`backtest_quali_sim_pace.py`, ground truth is
`pack["grid"]`, already built from the real Qualifying session for any
completed weekend — no separate fetch needed). Across 14 evaluable 2026
qualifying sessions (3 skipped — 2 with no FP hotlap data that weekend, 1
OpenF1 429): pole-team hit rate 43% (6/14), pole-driver hit rate 29%
(4/14), but team-level rank correlation (Spearman) averaged 0.806 and
driver-level 0.714 — the model is much better at ordering the whole field
correctly than at calling the exact fastest team/driver. Checked the misses
before concluding anything, since the first read looked like a specific
blind spot: Mercedes took real pole in 11 of the 14 races this season (a
genuinely dominant qualifying run), and the model does lean Mercedes most
often too (predicted 8/14), correctly catching 6 of Mercedes' 11 real poles
— not a team-specific miss, just the expected difficulty of picking an
exact winner from FP-only data when one team is this dominant.

### Real weather forecast (not just a retrospective rain read), 2026-10-05
User-reported: the Bahrain GP (meeting 1308) started genuinely wet, overriding
the entire dry paper-strategy table, while `weather_outlook` had said "low"
risk pre-race. Not a bug in the old logic -- `_weather_outlook`'s own
docstring already said "a rain PRIOR, not a forecast (OpenF1 only exposes
observed weather)": it could only ever look backward at FP1-3 (which really
were dry) and at historical wet-proneness (Bahrain isn't on that list). There
was no signal that looked forward to the race itself, because none existed.

Added `engine/weather_forecast.py`: a real forecast via Open-Meteo (free, no
API key for non-commercial use), with a `CIRCUIT_COORDS` lat/lon table for
every circuit (same key convention as `CIRCUIT_LAPS`) and a short-TTL
(30 min) in-memory cache. `get_rain_forecast(circuit, race_datetime_iso)`
returns the hourly forecast slot closest to the race's own start time, or
`None` on any failure (unknown circuit, API error, past date with no
forecast data) -- same graceful-degrade convention as `get_weather_summary`.
Uses `requests`, not raw `urllib` -- this surfaced a real local-environment
gap (this machine's python.org build has no system CA bundle wired into
urllib's default SSL context, so `backtest_full.py`'s own urllib-based
`fetch()` fails on any live call here with `CERTIFICATE_VERIFY_FAILED`;
`requests` bundles `certifi` and isn't affected). Not fixed in
`backtest_full.py` itself -- out of scope for this change, flagged here in
case it resurfaces.

`_weather_outlook` (`engine/prerace.py`) now takes an optional
`race_datetime` and blends the forecast in: `rain_risk` is the max of the
forecast signal and the old practice/history signal (a confident low
forecast doesn't erase a wet-prone circuit's own known volatility --
Spa's microclimate is notoriously unpredictable -- but a strong forecast
DOES elevate risk even at a normally-dry circuit with bone-dry practice
sessions, the actual Bahrain case). Thresholds: >=50% forecast -> "high",
>=20% -> "elevated", below that treated as noise against the model's own
baseline uncertainty. `note`/`strategy_caveat` now cite the real forecast
percentage when it's driving the risk level, not just a generic sentence.

Fed the forecast into `run_monte_carlo` too (`engine/predictor.py`), via a
new `rain_probability` parameter (every existing caller defaults to 0.0 --
today's unchanged dry behaviour) that blends `sc_rate` toward a measured wet
rate. Measured first, not guessed (`measure_wet_weather_rates.py`, kept at
the repo root as a reusable script, same pattern as `stop_count_correlation.
py`): 67 dry + 19 wet races from the 2023-2026 cache, "wet" = any weather
sample flagged `rainfall=True` during the race. Real result: SC/VSC events
per race 0.76 dry vs 1.26 wet, a genuine 1.66x (`WET_SC_RATE_MULTIPLIER`).
Also checked a DNF-rate multiplier on the same split, since wet racing
*feels* like it should cause more mechanical/crash retirements -- the
measured rate came back flat (0.133 dry vs 0.131 wet, 0.98x), so no DNF
adjustment was added. Counterintuitive, but trusted over the intuition --
same discipline as the per-circuit DNF table rejected earlier in this file
for fitting noise instead of a real effect.

`build_prerace_data` fetches the forecast once (race's own `date_start`)
and threads `rain_probability` through `_project_race` -> `_run_projection`
-> `simulate_race` -> `run_monte_carlo`; `_weather_outlook` fetches it
independently for the same reason `_pit_window` and `_team_pace` already
don't share a single source of truth across every pack field -- different
consumers (simulation vs a display caption), same cached function
underneath so in practice they agree. `PACK_VERSION` 35 -> 36.

Verified end-to-end against real data: Bahrain (now in the past) correctly
returns a graceful near-zero-signal result (Open-Meteo has no forecast for
a date that's already gone); Singapore (4 days out at the time, real
upcoming race) returned a genuine 77% rain probability, correctly elevating
`weather_outlook` to "high" with a specific percentage-citing caveat, even
though no FP session exists for that weekend yet to have seen rain. 20 new
tests (`tests/test_weather_forecast.py`, `tests/test_weather_caveat.py`'s
new `TestForwardLookingForecast`, `tests/test_rain_probability.py`); full
suite 221/221 passing.

### Intermediate tyre support was incomplete end-to-end, 2026-10-05
User-reported on the Bahrain GP debrief (meeting 1308, the same race whose
real rain this session's weather-forecast fix was built around): stints
rendered wrong, Intermediates weren't showing, and the what-if editor
wouldn't allow them. Three separate, real bugs, not one:

1. **Backend validation rejected Intermediate outright.**
   `engine/whatif.py`'s `_validate_edited` treated any non-DRY compound as
   unsupported -- so even VER's own real, unedited stints (Intermediate for
   1 lap, then Soft to the flag) failed the moment the what-if editor
   auto-loaded them, before any edit. The actual simulation math
   (`engine.predictor._lap_t`/`_stint_time`) was already compound-agnostic
   and a real INTERMEDIATE degradation curve was already being fitted --
   only this gate was blocking it. Fixed to accept INTERMEDIATE (still
   rejecting WET -- no fitted curve exists for it, not enough real data,
   same stance as `engine/predictor.py`'s own documented position). Also
   fixed the "at least two different dry compounds" rule to correctly waive
   itself when wet-weather tyres were used at all (the real regulation,
   and exactly VER's case: only one dry compound, Soft, used all race). Also
   fixed the tyre-inventory check, which only ever tracks the FIA's dry
   allocation (`engine.tyre_inventory`) and has no Intermediate/Wet key at
   all -- it was defaulting to 0 available and rejecting every Intermediate
   stint with a false "not enough tyres" error; now skipped for non-dry
   compounds, which have nothing meaningful to check there.
2. **No CSS for Intermediate/Wet stint-bar segments.** `.c-SOFT`/`.c-MEDIUM`/
   `.c-HARD` existed; `.c-INTERMEDIATE`/`.c-WET` didn't, so any stint-bar
   segment (the debrief's results table, the what-if editor's drag track --
   both build their class name as `c-${compound}`) with a wet compound
   rendered with no background at all, invisible against the card. Added
   `--inter`/`--wet` CSS variables (real F1 colours: green/blue) and the
   matching classes.
3. **Three separate hardcoded SOFT/MEDIUM/HARD-only colour maps in
   `briefing.js`**, each an incomplete copy of a FOURTH one
   (`CHART_COMP`, used by the RSS-style per-race charts) that already had
   the correct Intermediate/Wet colours -- a real, longstanding
   inconsistency within the same file, not something this race newly
   broke. Consolidated into one shared `COMPOUND_COLOUR` constant.
   Also fixed the degradation-curve chart, which iterated a dry-only
   `COMPOUNDS` list and silently dropped a real fitted INTERMEDIATE curve
   from the plot entirely.

Separately, the what-if editor's click-to-cycle-compound logic
(`COMPOUNDS[(COMPOUNDS.indexOf(c)+1) % COMPOUNDS.length]`, two call sites)
used the same dry-only list -- cycling a stint could never reach
Intermediate, and worse, clicking an EXISTING Intermediate stint (`indexOf`
returns -1) silently snapped it to Soft on the very first click. Added a
separate `WHATIF_COMPOUNDS = [...DRY, "INTERMEDIATE"]` for the two places a
user can cycle an existing stint's compound. Deliberately NOT used for the
"+ add stop" button's own default-next-compound logic (a different call
site, same original array) -- auto-suggesting Intermediate as a new
addition when splitting a stint would be a surprising default; a user who
wants an added stint on Intermediates can still get there by adding a dry
stop first, then cycling it.

Verified end-to-end: the real production debrief data for this race now
renders every driver's genuine Intermediate stint with the correct green
segment, and POSTing VER's actual unmodified real-race stints (Intermediate
1 lap -> Soft -> Soft) to `/api/whatif` -- previously an immediate
rejection -- now returns a real 200 with a full simulated field. 6 new
backend tests (`tests/test_whatif_intermediate.py`); full suite 227/227
passing.

### `stints` was missing real pit stops entirely, confirmed against Pirelli's own graphic, 2026-10-05
Same-day follow-up, same race (meeting 1308): user compared the debrief's
own stint-bar chart against Pirelli's official published pit-stop graphic
for this race and the shapes didn't match -- several drivers' bars showed
one long, uninterrupted stint where Pirelli showed 2-3 separate ones.

Root-caused directly, not guessed: OpenF1's `stints` endpoint has **no row
at all** for some of this race's real, same-compound pit stops -- confirmed
independently via OpenF1's own separate `pit` endpoint (the real pit-lane
timing log, a completely different data source) and Pirelli's graphic, both
agreeing. The race winner's real laps-33 and laps-43 stops are completely
absent from his `stints` rows, which show one unbroken 46-lap stint from
lap 10 to the flag; `stints` alone silently undercounted `stops` by 2 for
him and by 1 for at least three other drivers checked (LEC's lap-28 stop,
HAD's lap-31, LAW's lap-30, HAM's lap-31 -- all confirmed the same way).

Added `get_pit_stops()` (`data/live.py`, same caching pattern as every other
historical endpoint) and `_split_stints_on_missing_pit_stops()`, now wired
into `get_stints()` itself so every consumer (the debrief, the live board,
prerace tyre inventory, what-if) benefits uniformly: for each driver, any
real pit lap that falls strictly inside an existing stint's span with no
boundary already reflecting it gets a new split inserted there (same
compound either side -- `stints` gave us no information about what was
actually fitted, and the real pit visit is itself strong evidence of a new
physical set, so `tyre_age_at_start` resets to 0 for the new second half).

**First version over-corrected and had to be walked back.** A blunt
exact-match check (did a new stint start at exactly `pit_lap + 1`?)
inserted redundant, spurious splits for pit stops that were ALREADY
correctly reflected but by a boundary landing a lap or two later than the
naive check expected -- found by comparing the whole field's total stop
count against the real pit log's own total (73) and Pirelli's stated total
(72): the first version produced 96, clearly over-splitting. Traced to one
specific driver's real lap-33 stop already being captured by an existing
boundary at lap 35, not 34 -- the exact-match check saw "34 is not a known
boundary" and fragmented a real stint into a genuine piece plus a
nonsensical 1-lap sliver. Fixed with `PIT_BOUNDARY_TOLERANCE_LAPS = 2`: a
pit lap within 2 laps of the stint's own start or end it falls inside is
treated as already accounted for, not genuinely missing.

**A second, separate, NOT-yet-resolved pattern was found during this
investigation, and is being reported honestly rather than papered over:**
after the tolerance fix, the field's total stop count still read 95
against the real pit log's 73 -- a near-universal "+1" per driver. Traced
to 20 of this race's 22 classified/retired drivers all showing an
artificial-looking exactly-1-lap "first stint" before their real starting
compound takes over, with **zero corresponding entry in the real pit log
for any of them** -- a 1-lap pit stop is not physically possible, so this
is not a genuine pit visit. The pattern is too uniform across the field to
be 22 independent real events; the leading hypothesis is that `stints`
initially reports some kind of pre-race-declared/placeholder compound for
exactly lap 1 before self-correcting from lap 2 once real telemetry
confirms the actual tyre, but this is NOT confirmed -- deliberately not
"fixed" by guessing, since silently deleting a real first lap's data would
be worse than leaving a known-uncertain artifact visible. Left as an open
item for a future session: it inflates every affected driver's `stops` by
exactly 1 and shows as a near-invisible one-lap colour sliver at the very
start of every stint bar.

9 new tests (`tests/test_stint_pit_reconciliation.py`, including a direct
regression test reproducing the over-correction bug); full suite 236/236
passing (unit), 6/6 passing (integration).

**Follow-up, same day: the "1-lap phantom first stint" mystery above was
explained, but deliberately NOT fixed.** User supplied the missing context
directly: the formation lap was red-flagged (`race_control`'s own
"STARTING PROCEDURE SUSPENDED" event, 48 minutes before "SESSION STARTED").
A red-flagged start lets teams change tyres on the grid, not through the
pit lane -- which is exactly why `pit` has zero record of it, and why the
pattern is near-universal (most of the field took the free tyre change).

Proposed fix: trust the first stint's compound through to the first REAL
(pit-log-confirmed) stop, discarding whatever short compound reading sits
between them. Checked this against two drivers' real Pirelli data before
building it, and found the pattern is NOT uniform: the race winner's
Pirelli row shows ONE continuous colour to his first real stop (lap 9) --
his "Soft, laps 2-9" reading is a genuine mislabelling, and the fix is
correct for him. But Leclerc's Pirelli row shows TWO colours before his
own first real stop (lap 3) -- a genuine Soft-then-Intermediate sequence
from the grid during the same suspension, and the identical-looking
"short stint, different compound, no pit-log entry" shape in our raw data
is, for him, completely real. The two cases are indistinguishable from
`stints`/`pit`/`race_control` alone; telling them apart required reading
Pirelli's own published graphic by eye, which isn't available
programmatically for the other ~18 drivers.

Applying the fix uniformly would correctly repair the winner's data while
silently erasing Leclerc's genuine Intermediate stint and replacing it
with a wrong compound -- a worse error than the one being fixed. Decided,
with the user, to leave this alone rather than ship a correction that's
right for some drivers and wrong for others with no way to tell which is
which. Revisit only if a reliable per-driver signal turns up (team radio,
a different OpenF1 field, or anything else that can confirm the true
compound independently of `stints` itself) -- don't re-attempt the blanket
"trust the first entry" rule without one.

### Debrief narrative redesigned: interleaved beats, not 6 separate prose blocks, 2026-10-06
User-reported: the debrief narrative was "just a big blob of text" and asked
for it to be "more engaging" -- then, when offered a choice between visual
polish, restructuring into scannable beats, or a full redesign interleaving
narrative with data, explicitly picked the most ambitious option: weave each
narrative piece directly into the data section it describes rather than
clustering prose blocks elsewhere on the page.

Old `NARRATIVE_SCHEMA` (`engine/briefing.py`) had 6 free-form string fields
(`race_story` 250-400 words, `tyre_story`, `the_stops`, `strategy_verdicts`,
`prior_check`) rendered as standalone `proseCard`s, each sitting right after
a real, already-well-structured table (`stops_graded`, `prerace_scorecard`)
that it mostly just re-narrated in paragraph form -- redundant with the table
and with each other (a driver's stop would get mentioned in `race_story`,
`the_stops`, *and* `strategy_verdicts` across three different paragraphs).

New schema: `headline` (unchanged) + `lede` (one-sentence hook, shown under
the headline) + `beats` (4-7 short objects, each `{acronym, tag, stat, text}`
pinned to one driver and one real number -- a stop's `gain_s`, a `pace_delta`,
a grid-to-finish swing; `tag` is one of stop/drive/tyres/strategy/crash_out)
+ three short (<=60-word) intro fields -- `tyre_verdict`, `stops_verdict`,
`prior_check` -- that render as a single paragraph directly above the
degradation chart / stops-graded table / prerace-scorecard table respectively,
instead of a disconnected block. `race_story` and `strategy_verdicts` are
gone entirely: that content now lives in `beats`, which folds what were two
overlapping narrated lists (the race's key moments and the best/worst
strategy calls) into one ranked, driver-tagged feed, cutting the duplication
rather than just reformatting it.

`frontend/briefing.js`: new `beatsCard()` renders the beats feed as a "Key
moments" card (pushed first in the customizable `sections` array, right
after the fixed results table/what-if editor); `degCurveCard()` gained an
optional third `verdict` param rendered as a `.verdict-intro` paragraph; the
stops-graded and prior-check cards each gained the same inline intro
paragraph above their table. The five old standalone narrative sections
(`race-story`, `tyre-story`, `stops-story`, `strategy-verdicts`,
`prior-check-story`) were removed outright, not hidden -- `applyLayout`
already drops any saved layout id that no longer matches a current section,
so no migration was needed for existing visitors' saved layouts.

Gotcha caught before shipping: `validate_tyre_claims` (the hallucination
guardrail that confirms every tyre-sequence claim like "HARD-HARD-HARD"
against a real driver's `compound_sequence`) only joined the narrative's
*top-level string* values into one blob to scan. `beats` is a list of dicts,
so a hallucination buried in a beat's `text` would have been invisible to
the checker with no error or warning -- a real regression, not hypothetical.
Fixed by adding `_all_strings()`, which recurses through dicts/lists to
collect every string leaf, and using that instead. Covered by
`tests/test_narrative_validation.py` (a hallucination inside a beat is
caught; a real compound sequence inside a beat is not falsely flagged).

`PACK_VERSION` 11 -> 12 (schema shape changed, so cached narratives need
regenerating). Verified end-to-end locally: built a real data pack via
`build_briefing_data` against cached session 11731 (no Anthropic key
available in the local shell, so narrative content was hand-written to the
real schema shape rather than LLM-generated), served it through the actual
FastAPI + frontend stack, and screenshotted the rendered page -- the lede,
key-moments feed, and all three inline verdicts rendered in their intended
positions with no leftover standalone prose cards.

Scope note: this redesign only touched the post-race debrief
(`renderBriefing`). The pre-race briefing (`renderPrerace`) has its own,
different narrative-adjacent fields and was out of scope here -- revisit
only if asked to extend the same treatment there.

### Phantom grid-side stint boundaries from the red-flagged start, resolved via a full-field Pirelli cross-check, 2026-10-06
Follow-up to the "stints was missing real pit stops" entry above, same race
(2026 Bahrain GP, meeting 1308). User-reported: Hamilton's debrief showed his
real 31-lap opening SOFT stint as SOFT(1)+MEDIUM(2-31) -- a phantom compound
change with no real pit-lane visit anywhere near it (his real stops were laps
31 and 43). The earlier entry had deliberately left this *class* of problem
alone because the one check available then (VER vs LEC) showed the identical
local shape -- a short, pit-log-unconfirmed stint before a longer one -- could
be either a genuine compound (LEC) or a mislabel (VER), with no way to tell
which from `stints`/`pit`/`race_control` alone.

The user then supplied Pirelli's official pit-stop graphic for the *entire*
field (not one driver), which made the general fix possible: cross-referencing
every driver's real pit-lane log (`data.live.get_pit_stops`, independent of
`stints`) against Pirelli's chart confirmed `pit`'s lap numbers match Pirelli
exactly for every driver -- i.e. `pit` *is* reliable ground truth here, and
the missing piece was never a lack of ground truth, just a fix that only
worked in one direction. The existing `_split_stints_on_missing_pit_stops`
(2026-10-05) only adds a boundary for a confirmed-real stop `stints` is
missing; nothing undid the opposite error -- a boundary `stints` reports that
no real pit-lane visit backs at all (this race's suspended formation lap let
every team swap tyres on the grid, which `stints` logs as its own row despite
no pit-lane transit ever happening). 20 of 22 drivers had at least one such
phantom boundary.

Added `data.live._merge_stints_without_matching_pit_stop`: collapses a stint
boundary with no real pit lap within `PIT_BOUNDARY_TOLERANCE_LAPS`, keeping
the earlier stint's compound and tyre age. Runs in `get_stints` *after*
`_split_stints_on_missing_pit_stops` (split first, so a real stop hidden
inside an over-long raw stint -- get_pit_stops' documented case -- is revealed
before the merge pass decides which remaining boundaries are phantom; got
this backwards on the first pass, which let the merge swallow Hamilton's real
lap-31 stop into one 42-lap SOFT stint before the split had a chance to carve
it out). Matching is a one-to-one nearest assignment, not "any boundary
within tolerance" -- with stints this short, a single real pit lap can sit
within tolerance of two adjacent boundaries at once (Leclerc's lap-1 and
lap-3 boundaries are both within 2 laps of his real lap-3 stop; a loose check
confirmed both and left his genuine phantom lap-1 split standing instead of
merging it). Verified field-wide against Pirelli's graphic: every driver's
stop count now matches exactly, and the field's total collapsed from a
previously-reported 95 down to 73 -- an exact match for `pit`'s own
independent total, not just a rough improvement.

This does not re-attempt the rejected "trust the first entry" compound-
identity fix: it never relabels a compound on a boundary a real pit stop
*does* confirm (Leclerc's genuine lap-3 stop and his real second compound are
untouched), so it can't repeat that fix's mistake of guessing identity where
the data doesn't resolve it -- it only ever decides whether a boundary nothing
confirms should exist at all.

**Found but NOT fixed, a separate bug**: cross-checking the same Pirelli
graphic surfaced a second, different problem this change doesn't touch --
a wrong compound label on a stint whose boundary IS pit-log-confirmed (so the
boundary-merge logic correctly leaves it alone, since it only ever touches
unconfirmed boundaries). Confirmed cases: LEC's laps 4-9 read SOFT in
`stints` but Pirelli shows INTERMEDIATE for that exact pit-log-confirmed
window; PIA's laps 3-9 read HARD but Pirelli shows INTERMEDIATE; GAS's laps
~10-25 read SOFT but Pirelli shows MEDIUM. All three are the stint
*immediately following* the chaotic red-flag opening, suggesting the same
root incident corrupts the compound sensor/reporting for a few laps after
the restart, not just during the stoppage itself -- but this is a distinct
failure mode from the boundary problem above, and needs its own
investigation (same "verify field-wide against Pirelli" approach would
likely work, just not done yet) before attempting a fix. `PACK_VERSION`
12 -> 13 to force cached debriefs to rebuild against the corrected stints.

### Opening-stint compound gaps filled for a second race, two false alarms ruled out, 2026-10-06
User asked to check the 2026 Australian GP (meeting 1279, session 11234) for
the same kind of issue. Two leads investigated and ruled out as real bugs
before finding the one that was:

- Field-wide stop count (34 ours vs 36 real `pit` visits) initially looked
  like under-counting for ALO and STR, the mirror image of the Bahrain bug.
  Both were false alarms: ALO's apparent second stop (lap 13) has
  `stop_duration: None` and a 972-second `lane_duration` against a ~20-30s
  field norm -- not a tyre change, and his own tyre-age telemetry (age 2 at
  lap 13 exactly matches a set fitted at lap 11) proves it's the same
  physical tyre carried through; the existing age-continuity merge in
  `_merge_stint_fragments` already handles this correctly. STR's "missing"
  lap-46 stop is explained by his own lap-by-lap timing data (a third,
  independent endpoint) stopping dead at lap 43 -- `58 total laps - 15 laps
  behind = 43` exactly, meaning his race effectively ended there (same
  incident as his own 1081-second pit-lane anomaly) and he was classified
  under the percentage-of-distance rule, not a stint-data gap. A real fix
  was drafted and tested for this (gate `_merge_stint_fragments`'s
  short-sliver heuristic on the real pit log) before realising the premise
  was wrong, and was reverted rather than shipped on unproven risk.
- The real bug: 6 drivers' (RUS, GAS, OCO, ALB, LAW, PER) opening stint has
  `compound: null` in OpenF1's raw `stints` response -- confirmed via the
  raw API response, not just the sanitiser's "UNKNOWN" fallback -- each with
  `tyre_age_at_start: 2` (a used/scrubbed set, not a live-backfill gap).
  Pirelli's graphic (user-supplied) confirms MEDIUM for all six. Added
  `KNOWN_COMPOUND_GAPS` in `data/live.py`: a verified-ground-truth table
  keyed by `(session_key, driver_number, stint_number)`, consulted only
  when `compound` is null -- it can never override a compound OpenF1
  actually reported, so it carries none of the risk the rejected "trust the
  first entry" fix had. `PACK_VERSION` 13 -> 14.

Lesson for next time this pattern shows up: a `pit`-endpoint entry is not
always a real tyre-changing stop (`stop_duration` vs `lane_duration` vs an
abnormal duration matters), and a driver's own `laps` data is worth checking
independently before concluding a stint-data gap is a bug rather than the
race's own result (retirement, lapped-and-classified, a penalty) explaining
it.

### Auto-generated what-if scenario: quantified counterfactual, not just prose, 2026-10-08
User asked for more narrative depth and more graphics, citing Ruth Buscombe's
Substack strategy writeups (named "rules" backed by historical patterns and
re-simulated alternate strategies with real numbers, e.g. "S-H-H wins 59% of
the time"). Agreed scope: both the debrief and the pre-race briefing need
this, starting with the debrief since it could reuse proven infrastructure
already in the codebase rather than build new simulation wiring.

Added `engine.briefing._build_whatif_scenario`: takes the worst-graded real
pit stop from `stops_graded` and re-times it a few laps either way, each
candidate re-run through the FULL race simulation via
`engine.whatif.run_whatif` -- the exact same engine (and the exact same
`whatifTraceSVG` chart) already driving the manual what-if editor, just
triggered automatically instead of by a dragged slider. Reports whichever
shift the model found gains the most positions (or, failing that, closes a
clear gap without flipping the finish -- `WHATIF_MIN_GAP_S`). New pack field
`whatif_scenario`, new narrative field `whatif_verdict` (empty string if
null, same pattern as `prior_check`). `PACK_VERSION` 14 -> 15.

Real engineering snags hit and fixed before shipping (none hypothetical --
each one first produced a wrong or empty result against real session data,
found by verifying end-to-end against real sessions rather than trusting
unit tests of the new function in isolation):
- **Most early stops are the chaotic post-restart scramble, not a real
  decision**: the single worst-graded stop is very often inside the first
  few laps (the same red-flag/rolling-start chaos documented above) --
  `WHATIF_MIN_STOP_LAP` skips stops before lap 5, and the search walks the
  whole `stops_graded` list worst-to-best (bounded by `WHATIF_MAX_ATTEMPTS`,
  not a fixed top-N) rather than giving up after the single worst stop.
- **`run_whatif`'s own `total_laps` can disagree with `build_briefing_data`'s**:
  the latter deliberately drops an untimed post-flag in-lap (see the
  `_merge_stints_without_matching_pit_stop` entry above); `run_whatif`
  doesn't, so padding a lapped driver's final stint to the project's own
  `total_laps` instead of `run_whatif`'s own notion of it failed validation
  with an off-by-one "plan covers N laps, race is N+1" on a real session.
  Fixed by deriving `whatif_total_laps` the same unfiltered way `run_whatif`
  does, specifically for this padding, rather than assuming the two numbers
  match.
- **Position-only acceptance was too strict**: a real re-timed stop often
  closes several seconds without flipping the actual finishing position (no
  rival was close enough right there) -- rejecting those as "no result"
  threw away genuine, quotable findings. `WHATIF_MIN_GAP_S` accepts a clear
  gap win on its own, and the narrative wording was split into two cases
  (position change vs gap-only) instead of only ever citing a position.
- **Attempt budget, not an exhaustive search**: each candidate is a full
  race re-simulation (~0.2-1s); searching every graded stop at every offset
  for a 20+-stop race took 25+ seconds. `WHATIF_MAX_ATTEMPTS` bounds the
  total `run_whatif` calls regardless of how many stops/offsets are
  theoretically available to try.

Verified against several real 2026 sessions (not just the two already used
for the stint-reconciliation work) — found a real scenario for China 2026
(meeting 1280): re-timing LAW's lap-9 stop to lap 14 gains 1 position. Both
Bahrain and Australia legitimately return `None` (verified by hand: neither
race has a mid-race stop whose real-world timing was actually beatable by a
few laps either way) -- confirms the degrade-gracefully path is a true
negative, not a bug, before relying on `None` being safe to ship.

Scope note: this is the debrief half only. The pre-race briefing's "deeper
what-if" treatment (probability-weighted strategy comparison via Monte
Carlo, a win-rate bar chart) is agreed as the next phase, not started yet.

### Phase 2: probability-weighted strategy comparison for the pre-race briefing, 2026-10-08
Follow-up to the debrief what-if scenario above — same user request (more
depth, more graphics, citing Buscombe's "S-H-H wins 59% of the time"
framing), this time for the pre-race briefing's existing candidate-strategy
table (`strategies`, already built for `_stop_decision`'s deterministic
time-delta comparison). `_stop_decision` can say which plan is fastest on
raw pace and whether a Safety Car would flip that call, but not by how much
the actual odds move — that needs a real Monte Carlo comparison, which
didn't exist as a reusable per-candidate-strategy tool before this.

Discovered `simulate_race` already runs Monte Carlo internally on every
call (`run_monte_carlo` is called from inside it, not by external callers —
confirmed by grepping for call sites, there's exactly one, inside
`predictor.py` itself). This meant no new simulation machinery was needed:
added `override_start` / `prescribed_strategies` passthrough params to
`_run_projection` (previously every driver free-optimised; these let ONE
driver be forced onto a specific starting compound and full pit plan while
everyone else keeps running their own best strategy, same convention
`engine.whatif.run_whatif` already uses for its baseline/modified
comparison). New `engine.prerace._strategy_win_rates`: forces the pole
sitter onto each of the top `STRATEGY_WIN_RATE_CANDIDATES` (3) candidates in
turn and reads off `win_probability`/`podium_probability`/`mean_finish`
from the forecast Monte Carlo already attached. New pack field
`strategy_win_rates`; `race_shape`'s narrative instructions extended to cite
it (one probability claim, named as a real Monte Carlo result) alongside
the existing deterministic crossover language. `PACK_VERSION` 36 -> 37.

New frontend `strategyWinRateCard` (reuses the `.pace-row`/`.pace-bar`
styling `teamPaceCard` already established, not a new chart type), rendered
directly beneath "The strategies on paper" table. Verified end-to-end for a
real meeting (1280, China): pole-sitter ANT's three candidate 1-stop plans
came back 53% / 49% / 43% win probability — confirmed visually in the
browser with a synthetic narrative citing the real numbers.

Bounded the added cost deliberately: `STRATEGY_WIN_RATE_CANDIDATES = 3`, not
all 5 candidates, since each one is a full field Monte Carlo simulation
(n_runs=500 internally) — measured as a few extra seconds on top of the
pre-existing ~11-15s/race full-cache build, which this project's own DP
search already treats as an acceptable cost for real strategic candidates
that rarely overturn the top of the table anyway (see `force_end_compound`'s
3-stop-branch comment above for the same tradeoff made once already).

A real testing mistake caught before it masked anything: the unit tests'
own `DriverForecast`/`DriverStrategy` fixtures were initially missing
several of `DriverStrategy`'s required fields, which raised inside the
mocked `_run_projection` and was silently swallowed by
`_strategy_win_rates`' own `except Exception: continue` (there to tolerate
one candidate's simulation genuinely failing without killing the others) --
every "success" test quietly returned `None` and still looked like it might
pass by accident if asserted loosely. Fixed the fixtures, not the exception
handling (the broad catch is correct behaviour; the fixture was wrong).

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
- **Before changing a threshold/ratio shared across multiple real-world
  categories (compound, circuit type, session type), check whether each
  category has enough real cached data to calibrate independently before
  picking a number.** This is the standing lesson from the
  `SHORT_STINT_LAPS` saga (2026-09-12, see "Prediction accuracy" below):
  a single constant was reused across Soft/Medium/Hard, got "fixed" on one
  race's anecdote, and that fix was itself wrong because nobody had ever
  pulled the real per-compound distribution to check. If the category with
  the failing case has close to zero real historical sample (as Qualifying
  Medium stints did), don't invent precision it doesn't support — a
  coarser, evidence-backed default beats a confident-looking single number
  that was never verified. A one-time audit of every other scalar constant
  in `engine/*.py` was run this same session (`grep -n "^[A-Z_]* = [0-9]"
  engine/*.py`) and found nothing else with this specific shape (a
  classification threshold applied uniformly across physically-different
  categories) — the closest near-misses were `USED_SET_DEFAULT_AGE`
  (whatif.py, a display fallback, not a classifier, and real data broadly
  supports its current value for Soft/Medium) and `TIMED_LAP_THRESHOLD`
  (quali_analysis.py, session-relative rather than compound-relative, so
  the risk doesn't apply). Re-run that grep and re-triage if a similar bug
  shows up again elsewhere — don't assume it's isolated to tyres.
