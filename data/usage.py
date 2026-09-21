"""Lightweight self-hosted site analytics: page views, which race briefings
get opened, and which features get used. Plain SQLite, no external service --
this is a personal-scale hobby project, not something that needs a real
analytics pipeline. Visitor identity is a random id the browser generates
and stores in localStorage (see frontend/briefing.js and frontend/index.js),
never an IP address or any other PII -- there's nothing sensitive here
beyond the DB file itself, which the admin endpoints gate behind ADMIN_TOKEN.

DB_PATH defaults to a local `var/` directory (gitignored) so it works out of
the box for development. In production this must point at a mounted
persistent volume (Railway's filesystem is otherwise wiped on every
redeploy) via the ANALYTICS_DB_PATH env var -- see CLAUDE.md for the exact
Railway setup steps.
"""
import os
import sqlite3
import threading
from datetime import datetime, timezone, timedelta

DB_PATH = os.environ.get("ANALYTICS_DB_PATH", "var/analytics.db")
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    dirname = os.path.dirname(DB_PATH)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            visitor_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            page TEXT,
            label TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
    return conn


def record_event(visitor_id: str | None, event_type: str | None,
                 page: str | None = None, label: str | None = None) -> None:
    """Insert one event. Silently no-ops on a malformed call -- this is fed
    by a public, unauthenticated endpoint, so it must never raise into the
    caller over bad input, only over a genuine storage failure."""
    if not visitor_id or not event_type:
        return
    # Defensive truncation: an unauthenticated endpoint should never let one
    # bad payload grow a row (or the DB) without bound.
    visitor_id = str(visitor_id)[:64]
    event_type = str(event_type)[:32]
    page = str(page)[:32] if page else None
    label = str(label)[:200] if label else None
    ts = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO events (ts, visitor_id, event_type, page, label) VALUES (?, ?, ?, ?, ?)",
                (ts, visitor_id, event_type, page, label))
            conn.commit()
        finally:
            conn.close()


def get_stats(days: int = 30) -> dict:
    """Aggregated view for the admin dashboard: visitor counts (all-time,
    today, last 7 days), pageviews by page, the most-viewed races, the
    most-used features, a daily time series for the last `days` days, and
    the 50 most recent raw events."""
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    today = now.date().isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()

    with _lock:
        conn = _connect()
        try:
            total_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            total_visitors = conn.execute(
                "SELECT COUNT(DISTINCT visitor_id) FROM events").fetchone()[0]
            visitors_today = conn.execute(
                "SELECT COUNT(DISTINCT visitor_id) FROM events WHERE ts >= ?",
                (today,)).fetchone()[0]
            visitors_7d = conn.execute(
                "SELECT COUNT(DISTINCT visitor_id) FROM events WHERE ts >= ?",
                (week_ago,)).fetchone()[0]

            pageviews_by_page = [
                {"page": r[0] or "unknown", "count": r[1]}
                for r in conn.execute(
                    "SELECT page, COUNT(*) FROM events WHERE event_type='pageview' "
                    "GROUP BY page ORDER BY COUNT(*) DESC")]

            top_races = [
                {"label": r[0], "count": r[1]}
                for r in conn.execute(
                    "SELECT label, COUNT(*) FROM events "
                    "WHERE event_type='race_view' AND label IS NOT NULL "
                    "GROUP BY label ORDER BY COUNT(*) DESC LIMIT 20")]

            top_features = [
                {"label": r[0], "count": r[1]}
                for r in conn.execute(
                    "SELECT label, COUNT(*) FROM events "
                    "WHERE event_type='feature' AND label IS NOT NULL "
                    "GROUP BY label ORDER BY COUNT(*) DESC LIMIT 20")]

            daily = [
                {"date": r[0], "pageviews": r[1], "unique_visitors": r[2]}
                for r in conn.execute(
                    "SELECT substr(ts, 1, 10) as day, COUNT(*), COUNT(DISTINCT visitor_id) "
                    "FROM events WHERE ts >= ? AND event_type='pageview' "
                    "GROUP BY day ORDER BY day", (since,))]

            recent = [
                {"ts": r[0], "event_type": r[1], "page": r[2], "label": r[3]}
                for r in conn.execute(
                    "SELECT ts, event_type, page, label FROM events "
                    "ORDER BY ts DESC LIMIT 50")]
        finally:
            conn.close()

    return {
        "total_events": total_events,
        "total_visitors": total_visitors,
        "visitors_today": visitors_today,
        "visitors_7d": visitors_7d,
        "pageviews_by_page": pageviews_by_page,
        "top_races": top_races,
        "top_features": top_features,
        "daily": daily,
        "recent": recent,
    }
