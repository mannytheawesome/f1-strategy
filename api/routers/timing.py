"""Live/replay timing board: full state, track positions, sectors, intervals."""

from fastapi import APIRouter, HTTPException

from data.live import (
    build_state, get_latest_session, get_session, get_laps,
    get_track_layout, get_latest_locations,
    _get, _cache_get, _cache_set, HIST_TTL, LIVE_TTL,
)
from api.helpers import _session_mode, _serialise_driver, _build_predictions

router = APIRouter()


def _resolve_default_session() -> tuple[dict, dict | None]:
    """OpenF1's 'latest' pointer flips to the NEXT session as soon as a race
    week starts, days before it has any data — which used to 502 the live
    page all week. If the latest session hasn't started yet, fall back to the
    most recent completed session and report the upcoming one separately."""
    session = get_latest_session()
    from datetime import datetime, timezone
    from dateutil.parser import parse as parse_dt
    start = session.get("date_start")
    if start:
        start_dt = parse_dt(start)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if start_dt > datetime.now(timezone.utc):
            upcoming = {"session_name": session.get("session_name"),
                        "country_name": session.get("country_name"),
                        "circuit": session.get("circuit_short_name"),
                        "date_start": start}
            cached = _cache_get("fallback_session", max_age=300)
            if cached is not None:
                return cached, upcoming
            now_iso = datetime.now(timezone.utc).isoformat()
            done = [s for s in _get("sessions", year=session.get("year"))
                    if (s.get("date_end") or "9999") < now_iso]
            done.sort(key=lambda s: s.get("date_start", ""))
            if done:
                fallback = done[-1]
                _cache_set("fallback_session", fallback, 300)
                return fallback, upcoming
    return session, None


@router.get("/api/live")
def live_state(session_key: int = None):
    """
    Returns the full strategy state for all drivers.
    Call this every 5s from the frontend.
    """
    try:
        upcoming = None
        if session_key is None:
            session, upcoming = _resolve_default_session()
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
        return {"session": session, "session_mode": _session_mode(session),
                "drivers": serialised, "upcoming": upcoming}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/locations")
def live_locations(session_key: int = None):
    """
    Lightweight driver-position feed for the track map. Polled every ~2s by
    the frontend during live sessions — far cheaper than /api/live (one
    upstream call, tiny payload) and cached 1.5s so N viewers share it.
    """
    try:
        if session_key is None:
            session = get_latest_session()
            session_key = session["session_key"]
        else:
            session = get_session(session_key)
        cache_key = f"locations_feed:{session_key}"
        cached = _cache_get(cache_key, max_age=1.5)
        if cached is not None:
            return cached
        locs = get_latest_locations(session)
        out = {
            "session_key": session_key,
            "locations": [
                {"driver_number": n, "x": l.get("x"), "y": l.get("y")}
                for n, l in locs.items()
                if l.get("x") is not None and l.get("y") is not None
                and (l.get("x") or l.get("y"))
            ],
        }
        _cache_set(cache_key, out, 1.5)
        return out
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/track_layout")
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


@router.get("/api/replay")
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


@router.get("/api/sectors")
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


@router.get("/api/intervals_live")
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


@router.get("/api/driver/{driver_number}/laps")
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
