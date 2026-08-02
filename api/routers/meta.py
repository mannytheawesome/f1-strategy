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
