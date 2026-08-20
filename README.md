# F1 Strategy Predictor

A live/historical Formula 1 timing and strategy web app built on the
[OpenF1](https://openf1.org/) API. FastAPI backend, vanilla-JS frontend, no
build step.

Two front doors:

- **Strategy briefings** (`/`) — Claude-written pre-race decision frameworks
  and post-race debriefs, grounded strictly in OpenF1 numbers.
- **Live timing board** (`/live`) — real-time position/gap/sector board with
  tyre state, degradation predictions, pit windows, and a what-if simulator.

## Prediction accuracy

Backtested over 81 races (2023-2026), 243 checkpoints at 25/50/75% race
distance:

| Race distance | Winner-hit | Podium (of 3) | Mean abs. position error |
|---|---|---|---|
| 25% | 78% | 2.30 | 1.83 |
| 50% | 83% | 2.43 | 1.54 |
| 75% | 94% | 2.57 | 1.07 |

Overall: **84.8% winner-hit**, MAE 1.48 positions.

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

## Architecture

```
frontend/   briefing.html/.css/.js — briefings SPA (served at "/")
            index.html/.css/.js    — live timing board SPA (served at "/live")
api/        FastAPI app, routers grouped by domain (timing, analysis, strategy, briefings)
data/live.py  OpenF1 client: OAuth, polling, in-memory cache
engine/     predictor.py   — lap-by-lap race simulation engine (the accuracy core)
            degradation.py — tyre degradation curves
            strategy.py    — 1-stop / 2-stop strategy generator
            prerace.py     — pre-race briefing data pack
            briefing.py    — post-race debrief data pack + LLM narrative
            whatif.py      — counterfactual race re-simulation
backtest_full.py  full-history collect/evaluate/sweep harness (no HTTP, the
                  primary tool for validating engine changes)
```

## Testing / verifying accuracy

```bash
python backtest_full.py collect     # cache raw OpenF1 data (slow, resumable)
python backtest_full.py evaluate    # run the engine at 25/50/75% distance, report metrics
python backtest_full.py sweep       # grid-search tunables
python audit_strategies.py          # structural sanity check on generated plans
```

## Deployment

Deployed on [Railway](https://railway.app) (nixpacks, `uvicorn api.main:app`).

---

See `CLAUDE.md` for detailed engineering notes, tuning history, and
conventions.
