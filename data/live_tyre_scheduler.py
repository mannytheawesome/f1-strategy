"""
Background job that starts a live tyre-flag capture (data.live_timing_feed)
the moment a session goes live, so the real declared New/used flag gets
recorded automatically -- no one has to notice a session started and run
capture_live_tyres.py by hand, which defeats the point of a site that's
supposed to just work for whoever visits it.

Runs in its own daemon thread for the life of the process (same pattern as
data/warmer.py and data/recalibrator.py), started from api/main.py's
FastAPI lifespan hook. Checks every CHECK_INTERVAL_S whether any session in
the current season's calendar is live right now; if one is and nothing is
already capturing it, launches data.live_timing_feed.capture_session for
it in its own thread (it has its own asyncio loop, so it needs its own OS
thread rather than sharing this one). That capture call already runs until
the session ends or a backstop duration elapses, so this scheduler's only
job is noticing a session started and not double-starting it -- the
capture itself is self-contained.
"""
import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone

from dateutil.parser import parse as parse_dt

CHECK_INTERVAL_S = 60     # how often to look for a session going live
# Start a little before the official start time -- cars are sometimes on
# track for installation laps before the session is officially "Started",
# and missing the first couple of minutes of a 60-90 minute session isn't
# worth risking by waiting for a perfectly-timed trigger.
STARTUP_GRACE_S = 120

_capturing: set[int] = set()
_lock = threading.Lock()


def _live_session_now(sessions: list[dict]) -> dict | None:
    now = datetime.now(timezone.utc)
    for s in sessions:
        start_str, end_str = s.get("date_start"), s.get("date_end")
        if not start_str or not end_str:
            continue
        try:
            start_dt, end_dt = parse_dt(start_str), parse_dt(end_str)
        except Exception:
            continue
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        if start_dt - timedelta(seconds=STARTUP_GRACE_S) <= now <= end_dt:
            return s
    return None


def _run_capture(session_key: int) -> None:
    from data.live_timing_feed import capture_session
    try:
        asyncio.run(capture_session(session_key))
    except Exception:
        pass   # connection dropped or similar -- the session is still
               # marked live next tick, but we won't retry mid-session;
               # whatever got checkpointed before the drop still stands
    finally:
        with _lock:
            _capturing.discard(session_key)


def _tick() -> None:
    from data.live import get_season_sessions
    try:
        sessions = get_season_sessions(datetime.now(timezone.utc).year)
    except Exception:
        return   # OpenF1 hiccup -- try again next tick

    live = _live_session_now(sessions)
    if not live:
        return
    session_key = live.get("session_key")
    if not session_key:
        return

    with _lock:
        if session_key in _capturing:
            return
        _capturing.add(session_key)

    threading.Thread(target=_run_capture, args=(session_key,),
                     daemon=True, name=f"tyre-capture-{session_key}").start()


def scheduler_loop() -> None:
    while True:
        _tick()
        time.sleep(CHECK_INTERVAL_S)


def start_background_tyre_capture() -> None:
    threading.Thread(target=scheduler_loop, daemon=True,
                     name="tyre-capture-scheduler").start()
