# F1 Strategy Predictor

A Formula 1 race strategy and timing web app that predicts race outcomes,
tyre strategy, and pit windows from real telemetry — and validates every
claim it makes against 81 real races rather than eyeballing it.

**Live app:** https://f1-strategy-production.up.railway.app/

Built solo, backend and frontend, on top of the [OpenF1](https://openf1.org/)
public API. FastAPI + vanilla JS, no frontend build step, no ORM — the whole
stack is legible top to bottom.

## Two front doors

- **Strategy briefings** (`/`) — a race-morning strategy newsletter: LLM-written
  pre-race decision frameworks and post-race debriefs, generated from a
  structured data pack the model is constrained to reason over (it cannot
  invent a number that isn't already in the pack). Covers tyre strategy
  options with pit windows, per-team pace comparison, a tyre-availability
  breakdown per driver, safety-car probability, and an undercut/overcut
  read — plus a customizable layout (reorder or hide any section, persisted
  per browser).
- **Live timing board** (`/live`) — a real-time position/gap/sector board
  that mode-switches automatically between Race, Practice, and Qualifying
  layouts, with live tyre degradation predictions, pit-window forecasts, and
  a what-if simulator for testing alternate strategies against the field.

## Why this project is more than a CRUD app

The interesting engineering problem here isn't the UI — it's building a race
simulator whose predictions are actually checkable, and then checking them.

- **A real backtest harness, not a vibe check.** `backtest_full.py` replays
  81 cached races (2023-2026) at 25%, 50%, and 75% race distance, runs the
  full prediction pipeline exactly as production does (no shortcuts), and
  scores it against what actually happened. Every tuning change in this
  repo's history is justified by a before/after number from this harness,
  not intuition — see `CLAUDE.md` for the full tuning log.
- **A Monte Carlo simulation layer with its own accuracy metric.** Winner-hit
  and mean absolute position error can't see anything that happens *inside*
  a probabilistic simulation (safety-car lottery, DNF risk, pace noise) —
  they're computed before Monte Carlo ever runs. Win/podium probability is
  separately validated with a **Brier score**, the standard proper scoring
  rule for probabilistic forecasts, closing a real blind spot in the
  original harness.
- **Degradation, safety-car, and DNF models fitted from data, not guessed.**
  Per-compound tyre degradation curves are blended from FP1/FP2/FP3 and race
  laps with per-session weights tuned by grid search; DNF rate is measured
  directly from `session_result` (12.9%, not the naive flat 4% a first pass
  assumed); safety-car probability is a measured per-circuit table plus an
  opening-lap hazard spike, not a single constant.
- **Regulation-accurate tyre modelling, iterated against ground truth.** The
  tyre-availability model tracks each driver's FIA-allocation tyre sets and
  classifies every one as still race-viable or worn out **by how many laps
  it actually ran** — a 3-4 lap Qualifying banker stint stays fresh, a
  longer Practice run doesn't — rather than a naive "opened = used" count.
  Verified against F1's own published strategy-guide numbers for a real
  Grand Prix (not just internal consistency), then re-validated
  structurally across the entire 81-race cache with zero violations.

## Skills demonstrated

| Area | Where in this repo |
|---|---|
| API design & backend architecture | `api/routers/*` — FastAPI, domain-grouped routers, no ORM |
| Statistical modelling & validation | `engine/predictor.py`, `backtest_full.py` — degradation curve fitting, Monte Carlo simulation, Brier-score calibration against real outcomes |
| Data engineering | `data/live.py` — third-party API client, caching, rate-limit management, malformed-data sanitisation at the source |
| LLM integration | `engine/briefing.py` — structured-output prompting that grounds the model in a data pack to prevent hallucinated numbers |
| Domain modelling from primary sources | `engine/tyre_inventory.py` — FIA regulation text read and implemented directly, then iterated against real-world validation, not just unit tests |
| Frontend engineering | `frontend/*.js` — hand-written live-polling SPA, no framework, no build step |
| Debugging complex systems | [`CLAUDE.md`](./CLAUDE.md) — a running log of real bugs found and how each was diagnosed: a circuit-name string mismatch silently disabling street-circuit logic for two years of races, an inverted comparison in the pit-stop crossover math, a stale local cache masking a missing data source |

## Prediction accuracy

Backtested over 81 races (2023-2026), 243 checkpoints at 25/50/75% race
distance:

| Race distance | Winner-hit | Podium (of 3) | Mean abs. position error |
|---|---|---|---|
| 25% | 78% | 2.30 | 1.83 |
| 50% | 83% | 2.43 | 1.54 |
| 75% | 94% | 2.57 | 1.07 |

Overall: **84.8% winner-hit**, MAE 1.48 positions. Monte Carlo win/podium
probability: Brier score 0.0149 / 0.0479 (lower is better).

## Architecture

```
frontend/   briefing.html/.css/.js — briefings SPA (served at "/")
            index.html/.css/.js    — live timing board SPA (served at "/live")
api/        FastAPI app, routers grouped by domain:
              timing.py     — live session state, replay, sectors, track layout
              analysis.py   — FP/quali analysis, tyre inventory, predictions
              strategy.py   — strategy candidates, what-if simulator
              briefings.py  — race list, pre-race + post-race briefings
data/live.py  OpenF1 client: auth, polling, caching, stint sanitisation
engine/     predictor.py    — lap-by-lap race simulation engine (the accuracy core:
                               degradation curves -> pace model -> DP strategy
                               optimizer -> Monte Carlo simulation)
            degradation.py  — per-compound tyre degradation curve fitting
            strategy.py     — 1/2/3-stop strategy candidate generator
            tyre_inventory.py — FIA tyre-allocation tracking, per-set wear classification
            prerace.py      — pre-race briefing data pack (strategy options,
                               team pace, pit windows, SC probability)
            briefing.py     — post-race debrief data pack + LLM narrative
            whatif.py       — counterfactual race re-simulation
            circuits.py     — per-circuit characteristics (street/normal, overtaking)
backtest_full.py  full-history collect/evaluate/sweep harness (no HTTP —
                  calls the engine directly, the primary tool for validating
                  any engine change before it ships)
audit_strategies.py  structural sanity check on every generated strategy
                      candidate across the full cache
```

## Tech stack

- **Backend:** Python, FastAPI, no ORM (OpenF1 is the only data source)
- **Frontend:** Vanilla JS/HTML/CSS, no framework, no build step, no bundler
- **LLM integration:** Claude API for briefing narrative generation, given a
  structured data pack it must reason over rather than freely generate from
- **Data source:** [OpenF1](https://openf1.org/) — real F1 timing, lap,
  stint, and session data
- **Deployment:** [Railway](https://railway.app) (nixpacks, auto-deploy on push)

## Running locally

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```

Open `http://localhost:8000/` for briefings, `/live` for the timing board.

### Credentials (`.env`)

```
OPENF1_USERNAME=       # OpenF1 paid tier — live data. Free tier is historical-only.
OPENF1_PASSWORD=
ANTHROPIC_API_KEY=     # briefing narrative generation. Omit for data-only briefings.
```

## Testing / verifying accuracy

```bash
python backtest_full.py collect     # cache raw OpenF1 data (slow, resumable)
python backtest_full.py evaluate    # run the engine at 25/50/75% distance, report metrics
python backtest_full.py sweep       # grid-search tunables
python audit_strategies.py          # structural sanity check on generated plans
```

Any change to the prediction engine is expected to report a before/after
number from `evaluate` (or a Brier-score comparison for anything inside the
Monte Carlo layer) — see `CLAUDE.md` for the full history of tuning
decisions, what was tried and rejected, and why.

---

See [`CLAUDE.md`](./CLAUDE.md) for detailed engineering notes: the full
tuning history, every bug found and how it was diagnosed, and the
conventions this codebase follows.
