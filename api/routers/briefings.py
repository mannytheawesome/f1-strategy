"""Race listings and the LLM-backed pre-race / post-race briefings."""

import os

from fastapi import APIRouter, HTTPException

from data.live import _get, _cache_get, _cache_set

router = APIRouter()


def _regen_allowed(regenerate: bool, token: str | None) -> bool:
    """The site is public; regenerate=true triggers a paid LLM call, so when
    ADMIN_TOKEN is configured it must be supplied. Automatic (re)generation
    for uncached/stale briefings is unaffected — it's bounded by the number
    of real races, not by visitors."""
    if not regenerate:
        return False
    admin = os.environ.get("ADMIN_TOKEN")
    return (not admin) or token == admin


@router.get("/api/races")
def race_list(year: int = 2026):
    """Completed race/sprint sessions for the year, newest first."""
    try:
        sessions = _cache_get(f"race_list:{year}")
        if sessions is None:
            raw = _get("sessions", year=year)
            from datetime import datetime, timezone
            from dateutil.parser import parse as parse_dt
            now = datetime.now(timezone.utc)
            sessions = []
            for s in sorted(raw, key=lambda x: x.get("date_start", ""), reverse=True):
                if s.get("session_type", "").lower() != "race":
                    continue
                end = s.get("date_end")
                if not end:
                    continue
                end_dt = parse_dt(end)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                if end_dt > now:
                    continue
                sessions.append({
                    "session_key":  s["session_key"],
                    "meeting_key":  s.get("meeting_key"),
                    "session_name": s.get("session_name"),
                    "country_name": s.get("country_name"),
                    "circuit_short_name": s.get("circuit_short_name"),
                    "date_start":   s.get("date_start"),
                    "year":         s.get("year"),
                })
            _cache_set(f"race_list:{year}", sessions, 1800)
        return {"year": year, "races": sessions}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/prerace_briefing")
def prerace_briefing(meeting_key: int, total_laps: int = None,
                     regenerate: bool = False, token: str = None):
    """
    Race-morning strategy briefing for a meeting, built ONLY from sessions
    that ran before the grand prix (FPs, sprint, qualifying). Regenerates
    automatically as new sessions complete over a weekend.
    """
    from engine.prerace import get_prerace_briefing
    try:
        return get_prerace_briefing(meeting_key, total_laps,
                                    regenerate=_regen_allowed(regenerate, token))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/next_meeting")
def next_meeting(year: int = 2026):
    """The meeting whose grand prix hasn't run yet but which already has at
    least one completed session — i.e. the weekend currently in progress."""
    try:
        cached = _cache_get(f"next_meeting:{year}", max_age=600)
        if cached is not None:
            return cached
        from datetime import datetime, timezone
        from dateutil.parser import parse as parse_dt
        now = datetime.now(timezone.utc)
        raw = _get("sessions", year=year)
        meetings: dict[int, dict] = {}
        for s in sorted(raw, key=lambda x: x.get("date_start", "")):
            mk = s.get("meeting_key")
            if mk is None:
                continue
            m = meetings.setdefault(mk, {"meeting_key": mk,
                                         "country_name": s.get("country_name"),
                                         "circuit_short_name": s.get("circuit_short_name"),
                                         "race_date": None, "race_done": False,
                                         "completed_sessions": []})
            end = s.get("date_end")
            done = False
            if end:
                end_dt = parse_dt(end)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                done = end_dt < now
            is_gp = (s.get("session_type", "").lower() == "race"
                     and "sprint" not in s.get("session_name", "").lower())
            if is_gp:
                m["race_date"] = s.get("date_start")
                m["race_done"] = done
            elif done:
                m["completed_sessions"].append(s.get("session_name"))
        # race_date required: filters out test meetings, which have no GP
        candidates = [m for m in meetings.values()
                      if m["race_date"] and not m["race_done"] and m["completed_sessions"]]
        candidates.sort(key=lambda m: m["race_date"])
        result = {"meeting": candidates[0] if candidates else None}
        _cache_set(f"next_meeting:{year}", result, 600)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/briefing")
def briefing(session_key: int, regenerate: bool = False, token: str = None):
    """
    Full race briefing: structured data pack (results, stints, deg curves,
    SC events, notable stats) plus LLM-written narrative sections. Generated
    once per session and cached to disk.
    """
    from engine.briefing import get_briefing
    try:
        return get_briefing(session_key, regenerate=_regen_allowed(regenerate, token))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
