# F1 Strategy Predictor — Progress

## What it is
A live/historical F1 timing and strategy web app built on the OpenF1 API (free, no auth, ~3s delay).
Runs as a FastAPI backend + plain HTML/JS frontend, served from `localhost:8000`.

---

## Architecture

```
frontend/index.html          — single-page app, vanilla JS
api/main.py                  — FastAPI routes, session mode detection
data/live.py                 — OpenF1 polling client, in-memory cache, build_state()
engine/degradation.py        — tyre deg curves via linear regression on session data
engine/strategy.py           — 1-stop / 2-stop strategy generator
engine/fp_analysis.py        — FP stint classification + DEG/LAP rates
engine/quali_analysis.py     — quali ranking, gap to P1, theoretical best
engine/tyre_inventory.py     — new-set counts across the meeting weekend
monitor_fp1.py               — background session monitor (anomaly logger)
```

**To run:**
```bash
cd /Users/mannytheawsome/Documents/f1-strategy
uvicorn api.main:app --reload --port 8000
```
If port in use: `lsof -ti :8000 | xargs kill -9`

---

## Session Modes

The frontend auto-detects session type from `session_mode` in the API response and switches layout.

| Mode  | Left panel                  | Columns shown                                   |
|-------|-----------------------------|-------------------------------------------------|
| RACE  | Strategy chart + pit window | POS, DRIVER, GAP, INT, LAP, COMPOUND, AGE, SECTOR 1-3, Δ POS |
| FP    | Stint analysis per compound | POS, DRIVER, BEST LAP, COMPOUND, AGE, DEG/LAP, S1, S2, S3 |
| QUALI | Theoretical best summary    | POS, DRIVER, BEST, GAP, COMPOUND, AGE, THBEST, S1, S2, S3 |

---

## Key Features

### Live timing board
- Rows slide in/out using CSS `transform: translateY()` — no DOM wipe
- Position delta (▲▼) shown per driver
- Tyre compound coloured: Soft=red, Medium=yellow, Hard=white, Inter=green, Wet=blue
- Sector times update cell-by-cell (no full row redraw)
- `isLiveSession` flag gates sector/interval polling so finished races don't hammer the API

### Race mode
- Gap to leader + interval update via fast `/api/intervals_live` (3s cache)
- Strategy chart fixed at race start, not re-generated on every render (`strategyFetched` flag)
- Tyre degradation predictions: status OK / SOON / OVERDUE per driver
- Pit window (earliest_lap → latest_lap) derived from session deg curve

### FP mode
- Stints classified: **HOTLAP** (1-2 laps), **SHORT** (3-5), **LONG** (6+)
- DEG/LAP column: linear regression on (true_tyre_age, lap_time) per compound
  - True tyre age = `tyre_age_at_start + (lap_number - stint_lap_start)` — handles returned tyres
  - Requires DEG_MIN_LAPS=5 for regression to be trusted
- Compound summaries sorted Soft → Medium → Hard

### Quali mode
- Best lap ranked, gap to P1
- Theoretical best = sum of driver's best S1 + S2 + S3 from any lap

### Replay mode
- Full session loaded on first request, cached in memory (HIST_TTL=3600s)
- Subsequent laps filter in-memory (no OpenF1 calls after first load — 7-12ms/lap)
- Real-time speed mode: paces replay to actual lap duration via `getLeaderLapMs()`

### Tyre inventory
- `engine/tyre_inventory.py` counts new sets opened across all sessions in the meeting
- Standard allocation: Hard=2, Medium=3, Soft=8 (sprint: Soft=6)
- New set = `tyre_age_at_start == 0` in stints data
- API endpoint: `/api/tyre_inventory?session_key=X`

---

## API Endpoints

| Endpoint | Cache | Notes |
|---|---|---|
| `GET /api/live` | LIVE_TTL=8s | Full state, predictions, session mode |
| `GET /api/replay?session_key=X&lap=N` | HIST_TTL=3600s | State at end of lap N |
| `GET /api/sectors` | LIVE_TTL=8s | Live-only partial lap sectors |
| `GET /api/intervals_live` | 3s | Fast gap/interval updates |
| `GET /api/strategies?session_key=X` | — | 1-stop/2-stop strategy options |
| `GET /api/fp_analysis?session_key=X` | HIST_TTL | FP stint breakdown + deg rates |
| `GET /api/quali_analysis?session_key=X` | HIST_TTL | Quali ranking + theoretical best |
| `GET /api/tyre_inventory?session_key=X` | HIST_TTL | New sets remaining per driver |
| `GET /api/session` | — | Latest or specified session metadata |

---

## Important Implementation Details

### `is_race_session` flag
Retirement detection is **only active in RACE/SPRINT modes**. In FP/Quali, drivers are ranked by best lap time — interval logic and retirement are disabled. Without this, a driver's first lap being slower than the leader triggered false retirements.

### Strategy generator
- `MIN_STINT=12` — minimum viable stint length
- `MIN_CURRENT_STINT=3` — if current stint < 3 laps (e.g. formation lap on inters), resets compound to SOFT, age=0
- Only generates strategies for dry compounds (SOFT/MEDIUM/HARD)
- `generate_strategies()` takes leader's current state as reference
- Reference driver = driver who completed the most laps (race winner), not lap-1 leader

### Caching
- `HIST_TTL=3600s` for historical sessions — prevents OpenF1 rate limiting (30 req/min)
- `LIVE_TTL=8s` for live sessions
- Replay fully cached after first load — subsequent laps are pure in-memory filtering

### OpenF1 quirks
- Location endpoint `date_gt` filter is broken — fetches per-driver without date filter for historical
- API timeout set to 30s (upstream can be slow)
- All endpoints return lists; always sort/filter client-side

### Tyre allocation (real F1 rules)
Standard weekend usage pattern (not enforced by code, just context):
- FP1: 1 Hard (long run) + 1 Soft (hotlap)
- FP2: 1 Medium (long run) + 1 Soft (hotlap)
- FP3: 2 Soft + 1 Medium
- Race: 1 new Hard + 1 new Medium saved; 4+ new Softs for qualifying

---

## Known Issues / Deferred

| Issue | Status |
|---|---|
| Track map (driver positions on circuit SVG) | Deferred — location endpoint issues |
| DEG/LAP negative in early FP1 | Track evolution at street circuits (esp. Monaco) — expected; acknowledged |
| Tyre inventory not yet shown in UI | Backend done (`/api/tyre_inventory`), frontend not wired |
| `Based on: [driver]` now shows race winner | Fixed in `api/main.py:398` |
| Strategy chart only fires once | Fixed — `strategyFetched` flag prevents re-generation mid-race |

---

## Tested Sessions

| Session | Key | Notes |
|---|---|---|
| Monaco 2025 FP1 | 11292 | Monitored live; DEG rates negative (track evolution — expected) |
| Monaco 2025 FP2 | 11293 | No Hard used (both sets consumed in FP1 per allocation rules) |
| Historical races | various | Replay mode tested; rate-limiting fixed via caching |
| Monaco 2025 Quali | TBD | Next test session |
| Monaco 2025 Race | TBD | Next test session |

---

## Pending / Next Steps

1. **Tyre inventory UI** — wire `/api/tyre_inventory` into the FP/Race left panel to show remaining new sets per driver
2. **Track map** — SVG overlay with per-driver position dots (blocked on OpenF1 location endpoint reliability)
3. **Live testing** — Monaco Qualifying (Saturday) and Race (Sunday) for all three mode layouts
