"""Shared helpers used across route modules: session-type normalisation,
driver serialisation, and the tyre-degradation prediction block that both the
live and replay endpoints attach to each driver.
"""

from data.live import DriverState, get_laps, get_stints, HIST_TTL
from engine.degradation import build_degradation_curves, predict_drivers


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
