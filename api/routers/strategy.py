"""Race strategy generation, the full prediction engine, and the what-if
counterfactual simulator."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from data.live import (
    build_state, get_latest_session, get_session, get_laps, get_stints,
    get_drivers, get_quali_times, get_sc_laps_from_race_control,
    get_avg_pit_loss, get_weather_summary, get_yellow_laps, _get, HIST_TTL,
)
from engine.degradation import build_degradation_curves
from engine.strategy import generate_strategies
from engine.predictor import (
    detect_sc, sc_probability, build_deg_curves, build_pace_model,
    simulate_race, forecast_to_dict, curves_to_dict, SCEvent,
)
from engine.circuits import track_position_weight
from api.helpers import _session_mode

router = APIRouter()


@router.get("/api/strategies")
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


@router.get("/api/predict")
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

        # SC detection: prefer official race control flags, fall back to lap-time heuristic
        rc_events  = get_sc_laps_from_race_control(session_key, HIST_TTL)
        if rc_events:
            sc_events = [SCEvent(e["start_lap"], e["end_lap"], e["type"]) for e in rc_events]
        else:
            sc_events = detect_sc(laps_to_now)

        sc_prob    = sc_probability(sc_events, max_lap, total_laps, circuit)
        quali_times = get_quali_times(meeting_key) if meeting_key else {}

        # Use actual measured pit loss if available
        pit_loss = get_avg_pit_loss(session_key, HIST_TTL)

        pace_model = build_pace_model(laps_to_now, sc_events, drivers_raw, curves,
                                      stints_raw, quali_times=quali_times or None,
                                      exclude_laps=get_yellow_laps(session_key, HIST_TTL))

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

        track_pos_weight = track_position_weight(circuit)

        forecasts = simulate_race(
            serialised, max_lap, total_laps, curves, pace_model, sc_events,
            track_position_weight=track_pos_weight,
            pit_loss=pit_loss,
            circuit=circuit,
        )

        weather = get_weather_summary(session_key, HIST_TTL)

        return {
            "session_key": session_key,
            "lap":         max_lap,
            "total_laps":  total_laps,
            "circuit":     circuit,
            "sc_events": [
                {"start_lap": e.start_lap, "end_lap": e.end_lap, "type": e.type}
                for e in sc_events
            ],
            "sc_source":   "race_control" if rc_events else "heuristic",
            "sc_probability_remaining": sc_prob,
            "pit_loss_used": pit_loss,
            "weather": weather,
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


class WhatIfStint(BaseModel):
    compound: str
    lap_start: int
    lap_end: int
    tyre_age: int = 0   # fitted-set age: 0 = new, >0 = used/scrubbed


class WhatIfRequest(BaseModel):
    session_key: int
    driver_number: int
    stints: list[WhatIfStint]


@router.post("/api/whatif")
def whatif(req: WhatIfRequest):
    """
    Counterfactual simulation: re-run a finished race with ONE driver's stint
    plan replaced by the given plan; all other drivers keep their actual
    strategies. Returns baseline vs modified forecasts and the actual result.
    """
    from engine.whatif import run_whatif
    try:
        return run_whatif(req.session_key, req.driver_number,
                          [s.model_dump() for s in req.stints])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
