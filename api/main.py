"""
F1 Strategy Predictor — FastAPI backend
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from data.live import (
    build_state, get_latest_session, get_session, get_laps, get_stints, get_drivers,
    DriverState, Stint, HIST_TTL, _get, _cache_get, _cache_set, LIVE_TTL,
    get_track_layout, get_quali_times,
)
from engine.degradation import build_degradation_curves, predict_drivers
from engine.strategy import generate_strategies
from engine.fp_analysis import analyse_fp, _field_compound_summary
from engine.quali_analysis import analyse_quali
from engine.tyre_inventory import compute_inventory
from engine.predictor import (
    detect_sc, sc_probability, build_deg_curves, build_pace_model,
    simulate_race, forecast_to_dict, curves_to_dict, optimize_strategy,
    DRY, PIT_LOSS,
)


def _session_mode(session: dict) -> str:
    """Normalise OpenF1 session_type → FP | QUALI | RACE | SPRINT."""
    t = session.get("session_type", "").lower()
    name = session.get("session_name", "").lower()
    if t == "race" and "sprint" not in name:
        return "RACE"
    if t == "race":
        return "SPRINT"
    if t == "qualifying":
        return "QUALI"
    if t == "practice":
        return "FP"
    return "RACE"

app = FastAPI(title="F1 Strategy Predictor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_predictions(session_key: int, state: dict, current_lap: int, total_laps: int) -> dict:
    # No predictions if the race hasn't started or is already finished
    if current_lap <= 0 or current_lap >= total_laps:
        return {}
    laps_raw   = get_laps(session_key, HIST_TTL)
    stints_raw = get_stints(session_key, HIST_TTL)
    curves     = build_degradation_curves(laps_raw, stints_raw)
    preds      = predict_drivers(state, curves, current_lap, total_laps)
    return {num: {
        "laps_remaining": p.laps_remaining,
        "pit_earliest":   p.pit_earliest,
        "pit_latest":     p.pit_latest,
        "status":         p.status,
        "deg_rate":       round(p.deg_rate, 4),
        "confidence":     p.confidence,
    } for num, p in preds.items()}


def _serialise_driver(d: DriverState) -> dict:
    stint = d.current_stint
    ls = d.last_sectors
    bs = d.best_sectors
    return {
        "driver_number": d.driver_number,
        "acronym": d.acronym,
        "team": d.team,
        "team_colour": d.team_colour,
        "position": d.position,
        "grid_position": d.grid_position,
        "positions_delta": d.positions_delta,
        "retired": d.retired,
        "gap_to_leader": d.gap_to_leader,
        "interval": d.interval,
        "current_lap": d.current_lap,
        "compound": stint.compound if stint else None,
        "tyre_age": d.tyre_age,
        "stint_number": stint.stint_number if stint else None,
        "last_lap_time": d.last_lap_time,
        "last_sectors": {"s1": ls.s1, "s2": ls.s2, "s3": ls.s3},
        "best_sectors": {"s1": bs.s1, "s2": bs.s2, "s3": bs.s3},
        "track_x": d.track_x,
        "track_y": d.track_y,
        "stints": [
            {
                "stint_number": s.stint_number,
                "compound": s.compound,
                "tyre_age_at_start": s.tyre_age_at_start,
                "lap_start": s.lap_start,
                "lap_end": s.lap_end,
            }
            for s in d.stints
        ],
        "lap_times": d.lap_times,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/session")
def current_session(session_key: int = None):
    try:
        if session_key:
            return get_session(session_key)
        return get_latest_session()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/live")
def live_state(session_key: int = None):
    """
    Returns the full strategy state for all drivers.
    Call this every 5s from the frontend.
    """
    try:
        if session_key is None:
            session = get_latest_session()
            session_key = session["session_key"]
        else:
            session = get_session(session_key)

        state = build_state(session["session_key"], session=session)
        current_lap = max((d.current_lap for d in state.values()), default=0)
        total_laps  = max((l["lap_number"] for l in get_laps(session["session_key"], HIST_TTL)), default=current_lap)
        preds = _build_predictions(session["session_key"], state, current_lap, total_laps)
        drivers = sorted(state.values(), key=lambda d: (d.position is None, d.position or 99))
        serialised = [_serialise_driver(d) for d in drivers]
        for d in serialised:
            d.update(preds.get(d["driver_number"], {}))
        return {"session": session, "session_mode": _session_mode(session), "drivers": serialised}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/track_layout")
def track_layout(session_key: int = None):
    """
    Returns a polyline tracing the circuit, derived from one lap of one
    driver's telemetry. Cached for the session — fetch once on session load.
    """
    try:
        if session_key is None:
            session = get_latest_session()
            session_key = session["session_key"]
        points = get_track_layout(session_key)
        return {"points": points}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/replay")
def replay_state(session_key: int, lap: int):
    """
    Returns session state as it was at the end of the given lap.
    Used for race replay mode.
    """
    try:
        session = get_session(session_key)
        all_laps   = get_laps(session_key, HIST_TTL)
        total_laps = max((l["lap_number"] for l in all_laps), default=lap)
        state      = build_state(session_key, include_locations=False, session=session, max_lap=lap)
        preds      = _build_predictions(session_key, state, lap, total_laps)
        drivers    = sorted(state.values(), key=lambda d: (d.position is None, d.position or 99))
        serialised = [_serialise_driver(d) for d in drivers]
        for d in serialised:
            d.update(preds.get(d["driver_number"], {}))
        return {"session": session, "session_mode": _session_mode(session),
                "lap": lap, "total_laps": total_laps, "drivers": serialised}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/fp_analysis")
def fp_analysis(session_key: int):
    try:
        session      = get_session(session_key)
        session_name = session.get("session_name", "")
        laps_raw     = get_laps(session_key, HIST_TTL)
        stints_raw   = get_stints(session_key, HIST_TTL)
        drv_raw      = get_drivers(session_key, HIST_TTL)
        summaries    = analyse_fp(laps_raw, stints_raw, drv_raw, session_name=session_name)
        return {
            "session": session,
            "session_mode": _session_mode(session),
            "drivers": [s.to_dict() for s in summaries],
            "compound_field_summary": _field_compound_summary(summaries),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/pre_race_strategy")
def pre_race_strategy(session_key: int, total_laps: int = 71):
    """
    Pre-race strategy forecast from FP data.
    Builds deg curves from all available FP sessions for this meeting and
    returns the top 1-stop and 2-stop strategies across all starting compounds,
    so teams/analysts can plan before the race starts.

    total_laps: circuit lap count (defaults to 71 for Austria / Red Bull Ring).
    """
    try:
        session     = get_session(session_key)
        meeting_key = session.get("meeting_key")
        circuit     = session.get("circuit_short_name", "")

        # Gather all FP sessions in this meeting
        all_sessions_raw = sorted(
            _get("sessions", meeting_key=meeting_key),
            key=lambda s: s.get("date_start", "")
        )
        fp_sessions = [s for s in all_sessions_raw
                       if s.get("session_type", "").lower() == "practice"]
        fp_names = ["FP1", "FP2", "FP3"]

        fp_data = []
        for i, fp_s in enumerate(fp_sessions[:3]):
            try:
                fp_data.append((
                    fp_names[i],
                    get_laps(fp_s["session_key"], HIST_TTL),
                    get_stints(fp_s["session_key"], HIST_TTL),
                ))
            except Exception:
                pass

        if not fp_data:
            raise HTTPException(status_code=404, detail="No FP data available yet")

        curves   = build_deg_curves(fp_data)
        sc_prob  = sc_probability([], 0, total_laps, circuit)

        # Field baseline from available compound baselines
        baselines = [c.baseline for c in curves.values() if c.baseline > 0]
        field_bl  = sum(baselines) / len(baselines) if baselines else 90.0

        # Generate optimal 1-stop and 2-stop for each starting compound
        strategies = []
        for start_c in DRY:
            strat = optimize_strategy(
                current_lap=0,
                total_laps=total_laps,
                current_compound=start_c,
                current_age=0,
                pace_delta=0.0,
                curves=curves,
                field_baseline=field_bl,
                needs_compound_change=True,
            )
            stops = len(strat.pits_remaining)
            compounds_seq = [start_c] + [p.compound for p in strat.pits_remaining]
            stint_lengths = []
            prev = 0
            for p in strat.pits_remaining:
                stint_lengths.append(p.lap - prev)
                prev = p.lap
            stint_lengths.append(total_laps - prev)
            strategies.append({
                "start_compound":  start_c,
                "stops":           stops,
                "compound_sequence": compounds_seq,
                "pit_laps":        [p.lap for p in strat.pits_remaining],
                "stint_lengths":   stint_lengths,
                "total_time":      round(strat.total_time_from_now, 2),
            })

        # Sort by total time — best strategy first
        strategies.sort(key=lambda s: s["total_time"])

        return {
            "session_key":   session_key,
            "meeting_key":   meeting_key,
            "circuit":       circuit,
            "total_laps":    total_laps,
            "sc_probability": sc_prob,
            "fp_sessions_used": [fp_names[i] for i in range(len(fp_data))],
            "deg_curves":    curves_to_dict(curves),
            "strategies":    strategies,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/quali_analysis")
def quali_analysis(session_key: int):
    try:
        session    = get_session(session_key)
        laps_raw   = get_laps(session_key, HIST_TTL)
        stints_raw = get_stints(session_key, HIST_TTL)
        drv_raw    = get_drivers(session_key, HIST_TTL)
        summaries  = analyse_quali(laps_raw, stints_raw, drv_raw)
        return {
            "session": session,
            "session_mode": _session_mode(session),
            "drivers": [s.to_dict() for s in summaries],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/tyre_inventory")
def tyre_inventory(session_key: int):
    """
    Returns remaining new tyre sets per driver for the meeting containing
    this session. Counts new sets (tyre_age_at_start=0) opened across all
    sessions up to and including the given session_key.
    """
    try:
        session    = get_session(session_key)
        meeting_key = session.get("meeting_key")

        # Get all sessions in this meeting, ordered by date
        from data.live import _cached_get as cached_get
        all_sessions = cached_get(
            f"meeting_sessions:{meeting_key}", "sessions", HIST_TTL,
            meeting_key=meeting_key
        )
        all_sessions = sorted(all_sessions, key=lambda s: s["date_start"])

        # Collect sessions up to and including the current one
        relevant_sessions = []
        for s in all_sessions:
            relevant_sessions.append(s)
            if s["session_key"] == session_key:
                break

        # Detect sprint weekend (has a session named "Sprint")
        session_names = [s.get("session_name", "") for s in all_sessions]
        is_sprint = any("sprint" in n.lower() for n in session_names
                        if "qualifying" not in n.lower())

        # Fetch stints for each relevant session
        stints_by_session = []
        for s in relevant_sessions:
            sk = s["session_key"]
            try:
                stints = cached_get(f"stints:{sk}", "stints", HIST_TTL,
                                    session_key=sk)
                stints_by_session.append(stints)
            except Exception:
                stints_by_session.append([])

        drivers_raw = get_drivers(session_key, HIST_TTL)
        inventory   = compute_inventory(stints_by_session, drivers_raw, is_sprint)

        return {
            "session_key": session_key,
            "meeting_key": meeting_key,
            "sessions_counted": [s["session_name"] for s in relevant_sessions],
            "is_sprint": is_sprint,
            "drivers": [d.to_dict() for d in inventory],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/session/total_laps")
def session_total_laps(session_key: int):
    """Returns the total number of completed laps for a session."""
    try:
        from data.live import get_laps
        laps = get_laps(session_key)
        total = max((l["lap_number"] for l in laps), default=0)
        return {"session_key": session_key, "total_laps": total}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/sectors")
def live_sectors(session_key: int = None):
    """
    Live-only: returns the current (possibly partial) lap sector times per driver.
    Uses the cached full lap list and picks the highest lap_number per driver.
    For historical sessions returns empty (sectors already embedded in /api/live).
    """
    try:
        if session_key is None:
            session = get_latest_session()
            session_key = session["session_key"]
        else:
            session = get_session(session_key)

        # Only meaningful for live sessions
        from dateutil.parser import parse as parse_dt
        from datetime import timedelta
        end_str = session.get("date_end", "")
        if end_str:
            end_dt = parse_dt(end_str)
            if end_dt.tzinfo is None:
                from datetime import timezone
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            from datetime import datetime, timezone
            if (datetime.now(timezone.utc) - end_dt).total_seconds() > 300:
                return {}   # historical — frontend already has sector data

        cache_key = f"sectors_live:{session_key}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        # For a live session, fetch only the very latest laps (last 30s)
        from datetime import datetime, timezone, timedelta
        date_gt = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        recent_laps = _get("laps", session_key=session_key, date_gt=date_gt)

        latest: dict[int, dict] = {}
        for lap in recent_laps:
            num = lap["driver_number"]
            if num not in latest or lap["lap_number"] > latest[num]["lap_number"]:
                latest[num] = lap

        result = {
            str(num): {
                "lap_number": lap["lap_number"],
                "s1": lap.get("duration_sector_1"),
                "s2": lap.get("duration_sector_2"),
                "s3": lap.get("duration_sector_3"),
                "complete": lap.get("lap_duration") is not None,
            }
            for num, lap in latest.items()
        }
        _cache_set(cache_key, result, LIVE_TTL)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/intervals_live")
def intervals_live(session_key: int = None):
    """
    Fast-polling endpoint — returns latest gap_to_leader and interval per driver.
    Cached for 3 seconds. Used to update gap columns without full state rebuild.
    """
    try:
        if session_key is None:
            session = get_latest_session()
            session_key = session["session_key"]

        cache_key = f"intervals_live:{session_key}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        rows = _get("intervals", session_key=session_key)
        latest: dict[str, dict] = {}
        for r in rows:
            num = str(r["driver_number"])
            if num not in latest or r["date"] > latest[num]["date"]:
                latest[num] = r

        result = {
            num: {
                "gap_to_leader": r.get("gap_to_leader"),
                "interval": r.get("interval"),
                "date": r.get("date"),
            }
            for num, r in latest.items()
        }
        _cache_set(cache_key, result, 3)  # 3-second cache
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/strategies")
def race_strategies(session_key: int = None, lap: int = None):
    """
    Generate 4-5 race strategies for the current leader.
    Works for both live and replay modes.
    """
    try:
        if session_key is None:
            session = get_latest_session()
            session_key = session["session_key"]
        else:
            session = get_session(session_key)

        all_laps   = get_laps(session_key, HIST_TTL)
        stints_raw = get_stints(session_key, HIST_TTL)
        total_laps = max((l["lap_number"] for l in all_laps), default=0)
        max_lap    = lap or total_laps
        curves = build_degradation_curves(all_laps, stints_raw)

        # Build state at the requested lap for strategy calculation
        state = build_state(session_key, include_locations=False,
                            session=session, max_lap=max_lap)

        # Reference driver = driver with P1 in the FINAL race state (not lap-1 leader)
        # Find by whoever completed the most laps (race winner)
        laps_by_driver: dict[int, int] = {}
        for lap in all_laps:
            n = lap["driver_number"]
            laps_by_driver[n] = max(laps_by_driver.get(n, 0), lap["lap_number"])
        race_winner_num = max(laps_by_driver, key=laps_by_driver.get) if laps_by_driver else None

        # Use the race winner's current state for strategy reference
        leader = None
        if race_winner_num and race_winner_num in state:
            leader = state[race_winner_num]
        if leader is None or not leader.current_stint:
            # fallback: first non-retired driver with a stint
            leader = next(
                (d for d in sorted(state.values(), key=lambda d: d.position or 99)
                 if not d.retired and d.current_stint),
                None
            )
        if leader is None:
            return {"strategies": []}

        strats = generate_strategies(
            current_lap     = leader.current_lap,
            total_laps      = total_laps,
            current_compound = leader.current_stint.compound,
            current_tyre_age = leader.tyre_age or 0,
            curves          = curves,
        )
        return {
            "session_key": session_key,
            "lap": max_lap,
            "total_laps": total_laps,
            "reference_driver": leader.acronym,
            "strategies": [s.to_dict() for s in strats],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/predict")
def predict(session_key: int = None, lap: int = None):
    """
    Full race prediction: lap-by-lap simulation, optimal strategy per driver,
    undercut analysis, SC detection, predicted finishing positions.
    """
    try:
        if session_key is None:
            session = get_latest_session()
            session_key = session["session_key"]
        else:
            session = get_session(session_key)

        meeting_key = session.get("meeting_key")
        circuit     = session.get("circuit_short_name", "")

        # FP sessions in this meeting (for weighted deg curves)
        all_sessions_raw = sorted(
            _get("sessions", meeting_key=meeting_key),
            key=lambda s: s.get("date_start", "")
        )
        fp_sessions = [s for s in all_sessions_raw
                       if s.get("session_type", "").lower() == "practice"]
        fp_names = ["FP1", "FP2", "FP3"]

        fp_data = []
        for i, fp_s in enumerate(fp_sessions[:3]):
            try:
                fp_data.append((
                    fp_names[i],
                    get_laps(fp_s["session_key"], HIST_TTL),
                    get_stints(fp_s["session_key"], HIST_TTL),
                ))
            except Exception:
                pass

        all_laps   = get_laps(session_key, HIST_TTL)
        stints_raw = get_stints(session_key, HIST_TTL)
        drivers_raw = get_drivers(session_key, HIST_TTL)

        total_laps = max((l["lap_number"] for l in all_laps), default=0)
        max_lap    = lap or total_laps
        laps_to_now = [l for l in all_laps if l["lap_number"] <= max_lap]

        # Race laps (so far) carry the highest weight — actual race deg is the
        # ground truth; FP sessions only provide the prior
        if _session_mode(session) in ("RACE", "SPRINT") and len(laps_to_now) > 60:
            fp_data.append(("RACE", laps_to_now, stints_raw))

        curves = build_deg_curves(fp_data)

        sc_events  = detect_sc(laps_to_now)
        sc_prob    = sc_probability(sc_events, max_lap, total_laps, circuit)
        quali_times = get_quali_times(meeting_key) if meeting_key else {}
        pace_model = build_pace_model(laps_to_now, sc_events, drivers_raw, curves,
                                      stints_raw, quali_times=quali_times or None)

        # Current driver state
        state = build_state(session_key, include_locations=False,
                            session=session, max_lap=max_lap)
        drivers_sorted = sorted(
            state.values(),
            key=lambda d: (d.position is None, d.position or 99)
        )
        serialised = [
            {
                "driver_number": d.driver_number,
                "acronym":       d.acronym,
                "position":      d.position,
                "compound":      d.current_stint.compound if d.current_stint else "MEDIUM",
                "tyre_age":      d.tyre_age or 0,
                "gap_to_leader": d.gap_to_leader,
                "interval":      d.interval,
                "retired":       d.retired,
                "compounds_used": list({s.compound for s in d.stints}),
                "current_lap":   d.current_lap,
            }
            for d in drivers_sorted
        ]

        is_street = any(c in circuit.lower() for c in ["monaco", "baku", "singapore", "jeddah", "las_vegas", "miami"])
        track_pos_weight = 0.75 if is_street else 0.6

        forecasts = simulate_race(
            serialised, max_lap, total_laps, curves, pace_model, sc_events,
            track_position_weight=track_pos_weight,
        )

        return {
            "session_key": session_key,
            "lap":         max_lap,
            "total_laps":  total_laps,
            "circuit":     circuit,
            "sc_events": [
                {"start_lap": e.start_lap, "end_lap": e.end_lap, "type": e.type}
                for e in sc_events
            ],
            "sc_probability_remaining": sc_prob,
            "deg_curves": curves_to_dict(curves),
            "pace_model": {
                str(n): {
                    "acronym":      p.acronym,
                    "pace_delta":   round(p.pace_delta, 3),
                    "pace_std":     round(p.pace_std, 3),
                    "laps_counted": p.laps_counted,
                }
                for n, p in pace_model.items()
            },
            "forecasts": [forecast_to_dict(f) for f in forecasts],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/driver/{driver_number}/laps")
def driver_laps(driver_number: int, session_key: int = None):
    """All lap times for one driver — used for the lap time chart."""
    try:
        if session_key is None:
            session = get_latest_session()
            session_key = session["session_key"]
        state = build_state(session_key)
        if driver_number not in state:
            raise HTTPException(status_code=404, detail="Driver not found")
        d = state[driver_number]
        return {
            "driver_number": driver_number,
            "acronym": d.acronym,
            "laps": [{"lap": lap, "time": t} for lap, t in d.lap_times],
            "stints": [
                {
                    "compound": s.compound,
                    "lap_start": s.lap_start,
                    "lap_end": s.lap_end,
                }
                for s in d.stints
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# Serve frontend
@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")
