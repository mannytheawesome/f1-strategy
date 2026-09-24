"""
Background pre-warming for the live-timing board's cache.

data.live._ttl_for_session already gives a completed session a long cache
lifetime, but that cache only gets populated by whoever asks first -- and
build_state needs several sequential OpenF1 calls (drivers, stints, laps,
positions, intervals), which on a cold cache can take 10+ seconds with no
useful loading feedback on the live board -- looking broken rather than
just slow. User-reported: Baku 2026 FP1 "not showing up" while FP2 was
live and no one had loaded FP1's board yet that session.

This loop runs in a background thread for the life of the process,
checking every WARM_INTERVAL_S whether any session in the current race
weekend ended within the last WARM_WINDOW_S and pre-fetches its live-board
state, so the first real user request is always a cache hit.
"""
import threading
import time
from datetime import datetime, timezone

from dateutil.parser import parse as parse_dt

from data.live import _cached_get, get_latest_session, build_state, HIST_TTL

WARM_INTERVAL_S = 120            # how often to check for a newly-completed session
WARM_WINDOW_S = 7 * 24 * 3600    # how far back "recently ended" reaches -- a
                                  # whole weekend, so a mid-weekend restart
                                  # (a deploy) still catches every session
SETTLE_S = 300                   # matches data.live._ttl_for_session's own
                                  # short-vs-long TTL cutoff -- a session
                                  # isn't marked warmed until it's past
                                  # this, so it keeps refreshing (cheaply,
                                  # each check is a fast cache read once
                                  # actually warm) while still settling

_warmed: set[int] = set()
_warmed_lock = threading.Lock()


def _warm_recent_sessions() -> None:
    try:
        latest = get_latest_session()
        meeting_key = latest.get("meeting_key")
        if not meeting_key:
            return
        sessions = _cached_get(f"meeting_sessions:{meeting_key}", "sessions",
                               HIST_TTL, meeting_key=meeting_key)
    except Exception:
        return   # OpenF1 hiccup -- try again next tick, nothing to warm yet

    now = datetime.now(timezone.utc)
    for s in sessions:
        end_str = s.get("date_end")
        session_key = s.get("session_key")
        if not end_str or not session_key:
            continue
        with _warmed_lock:
            if session_key in _warmed:
                continue
        try:
            end_dt = parse_dt(end_str)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        age = (now - end_dt).total_seconds()
        if not (0 <= age <= WARM_WINDOW_S):
            continue   # not finished yet, or too long ago to matter
        try:
            build_state(session_key, session=s)
        except Exception:
            continue   # try again next tick
        if age > SETTLE_S:
            with _warmed_lock:
                _warmed.add(session_key)


def warm_loop() -> None:
    while True:
        _warm_recent_sessions()
        time.sleep(WARM_INTERVAL_S)


def start_background_warmer() -> None:
    threading.Thread(target=warm_loop, daemon=True, name="cache-warmer").start()
