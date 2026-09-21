"""Public event tracking + admin-only aggregated stats for the site's
lightweight self-hosted analytics (see data/usage.py for the storage layer
and why it exists)."""
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from data.usage import record_event, get_stats

router = APIRouter()


class TrackEvent(BaseModel):
    visitor_id: str | None = None
    event_type: str | None = None
    page: str | None = None
    label: str | None = None


@router.post("/api/track")
def track(event: TrackEvent):
    """Fire-and-forget event logging from the frontend (sent via
    navigator.sendBeacon, so it can't block the page or surface an error to
    the visitor). record_event already no-ops on missing fields."""
    record_event(event.visitor_id, event.event_type, event.page, event.label)
    return {}


def _admin_allowed(token: str | None) -> bool:
    """Unlike briefing regeneration (api/routers/briefings.py's
    _regen_allowed, which defaults OPEN when ADMIN_TOKEN isn't configured),
    stats access defaults CLOSED -- visitor data shouldn't become public
    just because nobody got around to setting a token."""
    admin = os.environ.get("ADMIN_TOKEN")
    return bool(admin) and token == admin


@router.get("/api/admin/stats")
def admin_stats(days: int = 30, x_admin_token: str | None = Header(default=None)):
    if not _admin_allowed(x_admin_token):
        raise HTTPException(status_code=403, detail="invalid or missing admin token")
    return get_stats(days=days)
