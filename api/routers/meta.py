"""Session metadata and read-only auth diagnostics."""

import os

from fastapi import APIRouter, HTTPException

from data.live import get_session, get_latest_session, get_laps, get_auth_diagnostics

router = APIRouter()


@router.get("/api/session")
def current_session(session_key: int = None):
    try:
        if session_key:
            return get_session(session_key)
        return get_latest_session()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/debug/openf1_auth")
def openf1_auth_debug():
    """Read-only diagnostics for the OpenF1 OAuth flow — presence/length and
    last attempt outcome only, never the actual credential or token values."""
    return get_auth_diagnostics()


@router.get("/api/debug/anthropic_auth")
def anthropic_auth_debug():
    """Presence/shape of ANTHROPIC_API_KEY plus a free count_tokens probe to
    validate it — never returns the key itself."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    out = {
        "key_set": bool(key),
        "key_length": len(key),
        "key_prefix_ok": key.startswith("sk-ant-"),
        "probe": None,
    }
    if key:
        try:
            import anthropic
            client = anthropic.Anthropic()
            client.messages.count_tokens(
                model="claude-fable-5",
                messages=[{"role": "user", "content": "ping"}])
            out["probe"] = "ok"
        except Exception as e:
            out["probe"] = f"failed: {str(e)[:200]}"
    return out


@router.get("/api/session/total_laps")
def session_total_laps(session_key: int):
    """Returns the total number of completed laps for a session."""
    try:
        laps = get_laps(session_key)
        total = max((l["lap_number"] for l in laps), default=0)
        return {"session_key": session_key, "total_laps": total}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/debug/live_capture_status")
def live_capture_status():
    """Whether data/live_tyre_scheduler.py's background thread is alive, which
    session(s) it's actively capturing right now, and what's been checkpointed
    to disk so far -- added to verify the live-timing tyre-flag capture
    (data/live_timing_feed.py) end-to-end against a real live session, since
    neither piece exposes any other way to observe it from outside the
    process."""
    import threading

    from data.live_tyre_scheduler import _capturing
    from data.live_timing_feed import load_captured_flags, CACHE_DIR

    scheduler_alive = any(
        t.name == "tyre-capture-scheduler" and t.is_alive()
        for t in threading.enumerate()
    )

    captured_sessions = []
    if os.path.isdir(CACHE_DIR):
        for fname in sorted(os.listdir(CACHE_DIR)):
            if not fname.endswith(".json"):
                continue
            key = fname[:-5]
            session_key = int(key) if key.isdigit() else key
            flags = load_captured_flags(session_key) or {}
            captured_sessions.append({
                "session_key": session_key,
                "drivers": len(flags),
                "stints": sum(len(v) for v in flags.values()),
            })

    return {
        "scheduler_alive": scheduler_alive,
        "capturing_now": sorted(_capturing),
        "captured_sessions": captured_sessions,
    }


@router.get("/api/debug/live_capture_detail")
def live_capture_detail(session_key: int):
    """Raw per-driver captured flags for one session, straight from
    load_captured_flags -- for inspecting what a captured_sessions count in
    live_capture_status actually consists of (e.g. a stint count that looks
    too low/high for a real session)."""
    from data.live_timing_feed import load_captured_flags

    flags = load_captured_flags(session_key)
    if flags is None:
        return {"session_key": session_key, "found": False}
    return {"session_key": session_key, "found": True, "flags": flags}
