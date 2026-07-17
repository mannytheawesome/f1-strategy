"""
OpenF1 live data client.
Polls the OpenF1 API during a session and builds a live picture of
each driver's stint/tyre state, lap times, sector times, and track position.
"""

import os
import time
import threading
import requests
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

BASE = "https://api.openf1.org/v1"
TOKEN_URL = "https://api.openf1.org/token"

# OpenF1 live data requires a paid subscription (free tier is historical-only:
# data is unavailable from 30 min before to 30 min after each session).
# Supply OPENF1_USERNAME + OPENF1_PASSWORD in Railway env vars to enable live
# access. We exchange credentials for an OAuth2 bearer token and refresh it
# automatically before it expires. Never log or expose these values.
OPENF1_USERNAME = os.environ.get("OPENF1_USERNAME", "")
OPENF1_PASSWORD = os.environ.get("OPENF1_PASSWORD", "")

# Token state — refreshed automatically, guarded by a lock for thread safety
_oauth_token: str = ""
_oauth_expires_at: float = 0.0
_oauth_lock = threading.Lock()

# Diagnostics only — never store credential values here, just outcomes.
_last_token_attempt_at: float = 0.0
_last_token_success: bool = False
_last_token_error: str = ""


def _fetch_oauth_token() -> tuple[str, int]:
    """POST credentials to OpenF1 token endpoint, return (access_token, ttl_seconds)."""
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"username": OPENF1_USERNAME, "password": OPENF1_PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["access_token"], int(data.get("expires_in", 3600))


def _get_oauth_token() -> str:
    """Return a valid bearer token, refreshing 60s before expiry."""
    global _oauth_token, _oauth_expires_at
    global _last_token_attempt_at, _last_token_success, _last_token_error
    with _oauth_lock:
        if not OPENF1_USERNAME or not OPENF1_PASSWORD:
            _last_token_attempt_at = time.time()
            _last_token_success = False
            _last_token_error = "OPENF1_USERNAME/OPENF1_PASSWORD not set"
            return ""
        if time.time() < _oauth_expires_at - 60 and _oauth_token:
            return _oauth_token
        _last_token_attempt_at = time.time()
        try:
            token, ttl = _fetch_oauth_token()
            _oauth_token = token
            _oauth_expires_at = time.time() + ttl
            _last_token_success = True
            _last_token_error = ""
            return _oauth_token
        except Exception as e:
            _last_token_success = False
            _last_token_error = str(e)[:200]
            print(f"[auth] OAuth token refresh failed: {e}")
            return _oauth_token  # return stale token if we have one


def get_auth_diagnostics() -> dict:
    """Safe-to-expose snapshot of OpenF1 auth state — never returns credential
    or token values, only presence/length/outcome, for remote debugging."""
    _get_oauth_token()  # trigger a fresh attempt if the cached token is stale
    return {
        "openf1_username_set": bool(OPENF1_USERNAME),
        "openf1_username_length": len(OPENF1_USERNAME),
        "openf1_password_set": bool(OPENF1_PASSWORD),
        "openf1_password_length": len(OPENF1_PASSWORD),
        "token_cached": bool(_oauth_token),
        "token_expires_in_s": max(0, round(_oauth_expires_at - time.time())) if _oauth_token else 0,
        "last_attempt_at": (
            datetime.fromtimestamp(_last_token_attempt_at, tz=timezone.utc).isoformat()
            if _last_token_attempt_at else None
        ),
        "last_attempt_success": _last_token_success,
        "last_attempt_error": _last_token_error,
    }


def _auth_headers() -> dict:
    token = _get_oauth_token()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}

# ---------------------------------------------------------------------------
# Simple in-memory cache — avoids re-fetching static historical data
# ---------------------------------------------------------------------------

_cache: dict = {}
_cache_lock = threading.Lock()
# OpenF1 sponsor tier allows 60 req/min. Live state needs 5 endpoints
# (laps/stints/drivers/positions/intervals) per refresh + fast interval and
# sector polling on top. TTL=10s keeps the total comfortably under budget.
LIVE_TTL = 10      # seconds — re-fetch live session data frequently
HIST_TTL = 3600    # seconds — historical data never changes

def _cache_get(key: str, max_age: float | None = None):
    """Freshness is reader-decided: an entry is served only if it is younger
    than BOTH the TTL it was stored with and the caller's max_age. This stops
    a long-TTL writer (e.g. /api/predict fetching race laps with HIST_TTL)
    from pinning hour-old data onto short-TTL readers (/api/live) during a
    live session — the bug that froze the live board mid-race."""
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        data, fetched_at, stored_ttl = entry
        limit = stored_ttl if max_age is None else min(stored_ttl, max_age)
        if time.time() - fetched_at > limit:
            if time.time() - fetched_at > stored_ttl:
                del _cache[key]
            return None
        return data

def _cache_set(key: str, data, ttl: float):
    with _cache_lock:
        _cache[key] = (data, time.time(), ttl)

def _ttl_for_session(session: dict) -> float:
    """Historical sessions get a long TTL; live sessions get a short one."""
    from dateutil.parser import parse as parse_dt
    end_str = session.get("date_end", "")
    if not end_str:
        return LIVE_TTL
    try:
        end_dt = parse_dt(end_str)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - end_dt).total_seconds() > 300:
            return HIST_TTL
    except Exception:
        pass
    return LIVE_TTL


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class Stint:
    driver_number: int
    stint_number: int
    compound: str
    tyre_age_at_start: int
    lap_start: int
    lap_end: Optional[int] = None

    @property
    def current_tyre_age(self) -> Optional[int]:
        if self.lap_end is None:
            return None
        return self.tyre_age_at_start + (self.lap_end - self.lap_start)


@dataclass
class SectorTimes:
    s1: Optional[float] = None
    s2: Optional[float] = None
    s3: Optional[float] = None


@dataclass
class DriverState:
    driver_number: int
    acronym: str
    team: str
    team_colour: str = "#ffffff"
    position: Optional[int] = None
    grid_position: Optional[int] = None
    current_lap: int = 0
    retired: bool = False
    gap_to_leader: Optional[str] = None   # e.g. "+1 LAP", "12.345", "RETIRED"
    interval: Optional[str] = None
    stints: list = field(default_factory=list)
    lap_times: list = field(default_factory=list)
    lap_sectors: list = field(default_factory=list)
    best_sectors: SectorTimes = field(default_factory=SectorTimes)
    track_x: Optional[float] = None
    track_y: Optional[float] = None

    @property
    def current_stint(self) -> Optional[Stint]:
        return self.stints[-1] if self.stints else None

    @property
    def tyre_age(self) -> Optional[int]:
        s = self.current_stint
        if s is None:
            return None
        return max(0, s.tyre_age_at_start + (self.current_lap - s.lap_start))

    @property
    def last_lap_time(self) -> Optional[float]:
        return self.lap_times[-1][1] if self.lap_times else None

    @property
    def last_sectors(self) -> SectorTimes:
        if not self.lap_sectors:
            return SectorTimes()
        _, s1, s2, s3 = self.lap_sectors[-1]
        return SectorTimes(s1=s1, s2=s2, s3=s3)

    @property
    def positions_delta(self) -> Optional[int]:
        """Positive = gained positions, negative = lost. None if retired."""
        if self.retired or self.grid_position is None or self.position is None:
            return None
        return self.grid_position - self.position


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

# Stale store: last-known-good data with no expiry. Served when OpenF1
# is down/rate-limited so a transient upstream failure never 502s a live page.
_stale: dict = {}


# Endpoints where an OpenF1 404 means "no rows for this filter yet" rather
# than a real error — the first minutes of a live session 404 on these until
# the first data lands, and that must render as an empty board, not a 502.
_EMPTY_ON_404 = {"laps", "stints", "position", "intervals", "location",
                 "race_control", "pit", "weather", "drivers"}


def _get(endpoint: str, **params) -> list:
    last_err = None
    for attempt in range(2):
        try:
            r = requests.get(f"{BASE}/{endpoint}", params=params,
                             headers=_auth_headers(), timeout=30)
            if r.status_code == 404 and endpoint in _EMPTY_ON_404:
                return []
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt == 0:
                time.sleep(1.5)
    raise last_err


def _cached_get(cache_key: str, endpoint: str, ttl: float, **params):
    hit = _cache_get(cache_key, max_age=ttl)
    if hit is not None:
        return hit
    try:
        data = _get(endpoint, **params)
    except Exception:
        with _cache_lock:
            stale = _stale.get(cache_key)
        if stale is not None:
            return stale
        raise
    _cache_set(cache_key, data, ttl)
    with _cache_lock:
        _stale[cache_key] = data
    return data


def get_latest_session() -> dict:
    rows = _cached_get("session:latest", "sessions", 30, session_key="latest")
    return rows[0]


def get_session(session_key: int) -> dict:
    rows = _cached_get(f"session:{session_key}", "sessions", HIST_TTL, session_key=session_key)
    return rows[0]


def get_drivers(session_key: int, ttl: float = HIST_TTL) -> dict[int, dict]:
    rows = _cached_get(f"drivers:{session_key}", "drivers", ttl, session_key=session_key)
    return {r["driver_number"]: r for r in rows}


def get_stints(session_key: int, ttl: float = HIST_TTL) -> list[dict]:
    return _cached_get(f"stints:{session_key}", "stints", ttl, session_key=session_key)


def get_laps(session_key: int, ttl: float = HIST_TTL) -> list[dict]:
    return _cached_get(f"laps:{session_key}", "laps", ttl, session_key=session_key)


def get_weather(session_key: int, ttl: float = HIST_TTL) -> list[dict]:
    """
    Weather snapshots for the session. Fields include: air_temperature,
    track_temperature, rainfall, humidity, wind_speed, wind_direction, pressure.
    Cached for HIST_TTL on finished sessions; caller should pass LIVE_TTL live.
    """
    return _cached_get(f"weather:{session_key}", "weather", ttl, session_key=session_key)


def get_race_control(session_key: int, ttl: float = HIST_TTL) -> list[dict]:
    """
    Official race control messages: SC deployments, VSC, yellow/red flags,
    DRS enabled/disabled, etc. Use flag field: 'SAFETY CAR', 'VIRTUAL SAFETY CAR',
    'RED', 'YELLOW', 'DOUBLE YELLOW', 'CLEAR', 'GREEN', 'CHEQUERED'.
    scope field: 'Track' (whole track) or 'Sector' (localised).
    """
    return _cached_get(f"race_control:{session_key}", "race_control", ttl, session_key=session_key)


def get_pit_data(session_key: int, ttl: float = HIST_TTL) -> list[dict]:
    """
    Measured pit stop durations per driver per lap.
    pit_duration: total time from pit entry to exit (includes stationary time).
    lane_duration: time in pit lane (slightly different metric on some circuits).
    """
    return _cached_get(f"pit:{session_key}", "pit", ttl, session_key=session_key)


def get_weather_summary(session_key: int, ttl: float = HIST_TTL) -> dict:
    """
    Aggregate weather stats for the session: min/max/avg track temp, any rainfall.
    Returns a flat dict suitable for including in API responses.
    """
    rows = get_weather(session_key, ttl)
    if not rows:
        return {}
    track_temps = [r["track_temperature"] for r in rows if r.get("track_temperature")]
    air_temps   = [r["air_temperature"]   for r in rows if r.get("air_temperature")]
    rainfalls   = [r["rainfall"]          for r in rows if r.get("rainfall") is not None]
    wind_speeds = [r["wind_speed"]        for r in rows if r.get("wind_speed") is not None]
    return {
        "track_temp_avg": round(sum(track_temps)/len(track_temps), 1) if track_temps else None,
        "track_temp_max": round(max(track_temps), 1) if track_temps else None,
        "track_temp_min": round(min(track_temps), 1) if track_temps else None,
        "air_temp_avg":   round(sum(air_temps)/len(air_temps), 1) if air_temps else None,
        "rainfall":       max(rainfalls) > 0 if rainfalls else False,
        "wind_speed_avg": round(sum(wind_speeds)/len(wind_speeds), 1) if wind_speeds else None,
        "sample_count":   len(rows),
    }


def get_sc_laps_from_race_control(session_key: int, ttl: float = HIST_TTL) -> list[dict]:
    """
    Extract SC/VSC events from official race control messages.
    Returns list of {type: 'SC'|'VSC', start_lap, end_lap} dicts,
    which can be passed directly to detect_sc or used alongside it.
    """
    messages = get_race_control(session_key, ttl)
    events = []
    active: dict[str, int | None] = {"SC": None, "VSC": None}

    for msg in sorted(messages, key=lambda m: m.get("date", "")):
        flag   = msg.get("flag", "")
        lap    = msg.get("lap_number")
        scope  = msg.get("scope", "")
        if scope != "Track":
            continue

        if flag == "SAFETY CAR":
            if active["SC"] is None:
                active["SC"] = lap
        elif flag == "VIRTUAL SAFETY CAR":
            if active["VSC"] is None:
                active["VSC"] = lap
        elif flag in ("CLEAR", "GREEN") and lap:
            for kind in ("SC", "VSC"):
                if active[kind] is not None:
                    events.append({
                        "type":      kind,
                        "start_lap": active[kind],
                        "end_lap":   lap,
                    })
                    active[kind] = None

    # Close any still-active events (red flag finish etc.)
    for kind, start in active.items():
        if start is not None:
            events.append({"type": kind, "start_lap": start, "end_lap": start + 5})

    return events


def get_yellow_laps(session_key: int, ttl: float = HIST_TTL) -> set[int]:
    """
    Lap numbers run under a TRACK-WIDE yellow or double yellow — those laps
    are slow through no fault of the tyre and should be dropped from pace and
    degradation samples. Local (sector-scope) yellows are left in: a lift
    through one sector barely moves a full lap time, and dropping them would
    throw away too much data.
    """
    try:
        messages = get_race_control(session_key, ttl)
    except Exception:
        return set()
    laps: set[int] = set()
    for m in messages:
        if (m.get("scope") == "Track"
                and m.get("flag") in ("YELLOW", "DOUBLE YELLOW")
                and m.get("lap_number")):
            laps.add(m["lap_number"])
    return laps


def get_avg_pit_loss(session_key: int, ttl: float = HIST_TTL) -> float:
    """
    Compute the actual average pit stop time for this session from measured data.
    Falls back to 22.0s (our constant) if no pit data available.
    """
    pits = get_pit_data(session_key, ttl)
    durations = [p["pit_duration"] for p in pits
                 if p.get("pit_duration") and 15 < p["pit_duration"] < 35]
    if not durations:
        return 22.0
    return round(sum(durations) / len(durations), 1)


def get_lap_timestamps(laps_raw: list[dict]) -> dict[int, str]:
    """Map lap_number → date_start for the race leader (driver with most laps or lowest number)."""
    # Build per-driver lap→date map, then pick the driver with the most laps as reference
    by_driver: dict[int, dict[int, str]] = {}
    for lap in laps_raw:
        n = lap["driver_number"]
        ln = lap["lap_number"]
        ds = lap.get("date_start")
        if ds:
            by_driver.setdefault(n, {})[ln] = ds
    if not by_driver:
        return {}
    # pick driver with most laps
    ref = max(by_driver, key=lambda n: len(by_driver[n]))
    return by_driver[ref]


def get_all_positions(session_key: int, ttl: float = HIST_TTL) -> list[dict]:
    return _cached_get(f"positions:{session_key}", "position", ttl, session_key=session_key)


def get_all_intervals(session_key: int, ttl: float = HIST_TTL) -> list[dict]:
    try:
        return _cached_get(f"intervals:{session_key}", "intervals", ttl, session_key=session_key)
    except Exception:
        return []  # FP and Sprint Qualifying sessions have no intervals endpoint


def get_latest_intervals(session_key: int, ttl: float = HIST_TTL) -> dict[int, dict]:
    rows = get_all_intervals(session_key, ttl)
    latest: dict[int, dict] = {}
    for r in rows:
        num = r["driver_number"]
        if num not in latest or r["date"] > latest[num]["date"]:
            latest[num] = r
    return latest


def get_latest_locations(session: dict) -> dict[int, dict]:
    """
    Fetch the most recent X/Y location for every driver.
    - Live sessions: single call for all drivers (small payload, ~30s window)
    - Historical sessions: one cached call per driver (date_gt filter is broken
      on the location endpoint, so we fetch all entries and keep the last one)
    """
    try:
        from dateutil.parser import parse as parse_dt
        from datetime import timedelta

        session_key = session["session_key"]
        session_end = session.get("date_end", "")
        now = datetime.now(timezone.utc)

        is_live = True
        if session_end:
            end_dt = parse_dt(session_end)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            is_live = (now - end_dt).total_seconds() < 300

        latest: dict[int, dict] = {}

        if is_live:
            # Live: fetch all drivers in one call using a 30s window
            anchor = (now - timedelta(seconds=30)).isoformat()
            rows = _get("location", session_key=session_key, date_gt=anchor)
            for r in rows:
                num = r["driver_number"]
                if num not in latest or r["date"] > latest[num]["date"]:
                    latest[num] = r
        else:
            # Historical: fetch per-driver (date_gt is broken on this endpoint)
            # Cache per-driver so we only do this once per session
            driver_nums = list(get_drivers(session_key, HIST_TTL).keys())
            for num in driver_nums:
                cache_key = f"location:{session_key}:{num}"
                cached = _cache_get(cache_key)
                if cached is not None:
                    latest[num] = cached
                    continue
                try:
                    rows = _get("location", session_key=session_key, driver_number=num)
                    if isinstance(rows, list) and rows:
                        # keep only last non-zero entry
                        nonzero = [r for r in rows if r.get("x") or r.get("y")]
                        best = (nonzero or rows)[-1]
                        _cache_set(cache_key, best, HIST_TTL)
                        latest[num] = best
                except Exception:
                    pass

        return latest
    except Exception:
        return {}


def get_quali_times(meeting_key: int) -> dict[int, float]:
    """
    Best qualifying lap time per driver for the given meeting.
    Returns {} if no qualifying session exists or data is unavailable.
    """
    try:
        all_sessions = _cached_get(f"sessions:meeting:{meeting_key}", "sessions",
                                   HIST_TTL, meeting_key=meeting_key)
        quali = next((s for s in sorted(all_sessions, key=lambda s: s.get("date_start",""))
                      if s.get("session_type","").lower() == "qualifying"), None)
        if not quali:
            return {}
        laps = _cached_get(f"laps:{quali['session_key']}", "laps",
                           HIST_TTL, session_key=quali["session_key"])
        best: dict[int, float] = {}
        for lap in laps:
            t = lap.get("lap_duration")
            n = lap.get("driver_number")
            if t and 55 < t < 200 and n:
                if n not in best or t < best[n]:
                    best[n] = t
        return best
    except Exception:
        return {}


def get_track_layout(session_key: int) -> list[dict]:
    """
    Trace the circuit outline from one driver's location telemetry over one
    full lap. Cached for the session (the layout never changes mid-session).
    Returns a downsampled list of {x, y} points, or [] if not enough data yet.
    """
    cache_key = f"track_layout:{session_key}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        laps_raw = get_laps(session_key, HIST_TTL)
        by_driver: dict[int, dict[int, str]] = {}
        for lap in laps_raw:
            n, ln, ds = lap["driver_number"], lap["lap_number"], lap.get("date_start")
            if ds:
                by_driver.setdefault(n, {})[ln] = ds
        if not by_driver:
            return []

        ref = max(by_driver, key=lambda n: len(by_driver[n]))
        lap_dates = by_driver[ref]
        lap_nums = sorted(lap_dates)
        if len(lap_nums) < 3:
            return []  # not enough laps yet to pick a clean reference lap

        idx = min(2, len(lap_nums) - 2)   # skip formation/out-lap, lap 1-2
        lap_n = lap_nums[idx]
        start_ts = lap_dates[lap_n]
        end_ts = lap_dates[lap_nums[idx + 1]]

        # date_gt/date_lt filtering is unreliable on this endpoint for
        # historical sessions, so fetch the full per-driver history and
        # filter locally — only done once per session, then cached.
        rows = _get("location", session_key=session_key, driver_number=ref)
        path = [
            (r["x"], r["y"]) for r in rows
            if r.get("date") and start_ts <= r["date"] < end_ts
            and r.get("x") is not None and r.get("y") is not None
        ]
        if len(path) < 10:
            return []

        if len(path) > 250:
            step = len(path) // 250
            path = path[::step]

        result = [{"x": x, "y": y} for x, y in path]
        _cache_set(cache_key, result, 6 * 3600)
        return result
    except Exception:
        return []


# ---------------------------------------------------------------------------
# State builder
# ---------------------------------------------------------------------------

def build_state(session_key: int, include_locations: bool = True, session: dict = None, max_lap: int = None) -> dict[int, "DriverState"]:
    """Build a full snapshot of all driver states for a given session."""
    if session is None:
        session = get_session(session_key)
    ttl = _ttl_for_session(session)
    session_type = session.get("session_type", "Race").lower()
    is_race_session = session_type in ("race",)  # only full race gets retirement/interval logic
    drivers_raw    = get_drivers(session_key, ttl)
    stints_raw     = get_stints(session_key, ttl)
    laps_raw_all   = get_laps(session_key, ttl)
    positions_raw  = get_all_positions(session_key, ttl)
    intervals_raw  = get_latest_intervals(session_key, ttl)
    locations      = get_latest_locations(session) if include_locations else {}

    # Replay mode: restrict all data to what was known at the end of max_lap
    if max_lap is not None:
        lap_timestamps = get_lap_timestamps(laps_raw_all)
        # find the timestamp when max_lap ended (start of max_lap+1, or last known)
        cutoff_ts = lap_timestamps.get(max_lap + 1) or lap_timestamps.get(max_lap)
        laps_raw = [l for l in laps_raw_all if l["lap_number"] <= max_lap]
        stints_raw = [s for s in stints_raw if s["lap_start"] <= max_lap]
        if cutoff_ts:
            positions_raw = [p for p in positions_raw if p["date"] <= cutoff_ts]
            iv_before = [iv for iv in get_all_intervals(session_key) if iv.get("date", "") <= cutoff_ts]
            intervals_raw = {}
            for iv in iv_before:
                n = iv["driver_number"]
                if n not in intervals_raw or iv["date"] > intervals_raw[n]["date"]:
                    intervals_raw[n] = iv
        locations = {}  # no live locations in replay mode
    else:
        laps_raw = laps_raw_all

    state: dict[int, DriverState] = {}

    for num, d in drivers_raw.items():
        state[num] = DriverState(
            driver_number=num,
            acronym=d.get("name_acronym", str(num)),
            team=d.get("team_name", ""),
            team_colour=d.get("team_colour") or "#ffffff",
        )

    # grid position = first position entry chronologically per driver
    grid: dict[int, dict] = {}
    for p in positions_raw:
        num = p["driver_number"]
        if num not in grid or p["date"] < grid[num]["date"]:
            grid[num] = p

    # current position = latest entry
    current_pos: dict[int, dict] = {}
    for p in positions_raw:
        num = p["driver_number"]
        if num not in current_pos or p["date"] > current_pos[num]["date"]:
            current_pos[num] = p

    for num, ds in state.items():
        ds.grid_position = grid.get(num, {}).get("position")
        ds.position = current_pos.get(num, {}).get("position")

    # stints
    for s in stints_raw:
        num = s["driver_number"]
        if num not in state:
            continue
        state[num].stints.append(Stint(
            driver_number=num,
            stint_number=s["stint_number"],
            compound=s["compound"],
            tyre_age_at_start=s.get("tyre_age_at_start", 0),
            lap_start=s["lap_start"],
            lap_end=s.get("lap_end"),
        ))

    # laps — lap times + sector times + personal best sectors
    for lap in laps_raw:
        num = lap["driver_number"]
        if num not in state:
            continue

        duration = lap.get("lap_duration")
        s1 = lap.get("duration_sector_1")
        s2 = lap.get("duration_sector_2")
        s3 = lap.get("duration_sector_3")
        lap_num = lap["lap_number"]

        if duration is not None:
            state[num].lap_times.append((lap_num, duration))
            state[num].current_lap = max(state[num].current_lap, lap_num)

        if any(v is not None for v in [s1, s2, s3]):
            state[num].lap_sectors.append((lap_num, s1, s2, s3))

        # update personal bests
        bs = state[num].best_sectors
        if s1 is not None and (bs.s1 is None or s1 < bs.s1):
            bs.s1 = s1
        if s2 is not None and (bs.s2 is None or s2 < bs.s2):
            bs.s2 = s2
        if s3 is not None and (bs.s3 is None or s3 < bs.s3):
            bs.s3 = s3

    if is_race_session:
        # ── Race-only: intervals, lapped detection, retirement ────────────────
        import re
        leader_lap = max((ds.current_lap for ds in state.values()), default=0)
        for num, iv in intervals_raw.items():
            if num not in state:
                continue
            ds = state[num]
            gap = iv.get("gap_to_leader")
            ivl = iv.get("interval")
            laps_down = leader_lap - ds.current_lap

            if isinstance(gap, str) and "LAP" in gap.upper():
                m = re.search(r'\+?(\d+)\s+LAP', gap.upper())
                claimed_laps = int(m.group(1)) if m else 0
                if laps_down > claimed_laps + 2:
                    ds.retired = True
                    ds.gap_to_leader = "RETIRED"
                    ds.position = None
                else:
                    ds.gap_to_leader = gap
            elif laps_down > 3:
                ds.retired = True
                ds.gap_to_leader = "RETIRED"
                ds.position = None
            elif isinstance(gap, (int, float)):
                ds.gap_to_leader = f"+{gap:.3f}" if gap > 0 else "LEADER"

            if isinstance(ivl, (int, float)) and not ds.retired:
                ds.interval = f"+{ivl:.3f}" if ivl > 0 else "—"

        for ds in state.values():
            if ds.gap_to_leader is None and leader_lap - ds.current_lap > 3:
                ds.retired = True
                ds.gap_to_leader = "RETIRED"
                ds.position = None

        # Formation lap retirement
        for ds in state.values():
            if ds.retired:
                continue
            if ds.current_lap <= 1 and leader_lap > 3:
                for s in ds.stints:
                    if s.lap_end is not None and s.lap_end <= 1 and len(ds.stints) == 1:
                        ds.retired = True
                        ds.gap_to_leader = "RETIRED"
                        ds.position = None
                        break

    else:
        # ── FP / Quali / Sprint Quali: no retirement detection ────────────────
        # Position comes from lap-time ranking; gap = delta to P1 best lap
        all_best: list[tuple[float, int]] = []  # (best_lap_time, driver_number)
        for num, ds in state.items():
            times = [t for _, t in ds.lap_times if t < 300]  # exclude slow laps
            if times:
                all_best.append((min(times), num))
        all_best.sort()

        for rank, (best_time, num) in enumerate(all_best, start=1):
            ds = state[num]
            ds.position = rank
            p1_time = all_best[0][0] if all_best else best_time
            ds.gap_to_leader = "LEADER" if rank == 1 else f"+{best_time - p1_time:.3f}"

    # track locations
    for num, loc in locations.items():
        if num in state:
            state[num].track_x = loc.get("x")
            state[num].track_y = loc.get("y")

    return state


# ---------------------------------------------------------------------------
# Live poller (terminal)
# ---------------------------------------------------------------------------

def poll_live(interval_s: float = 5.0, session_key: Optional[int] = None):
    if session_key is None:
        session = get_latest_session()
        session_key = session["session_key"]
    else:
        session = get_session(session_key)

    print(f"\nLive: {session['country_name']} — {session['session_name']} (key {session_key})")
    print("Press Ctrl-C to stop.\n")

    try:
        while True:
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            state = build_state(session_key, include_locations=False)
            drivers = sorted(
                state.values(),
                key=lambda d: (d.position is None, d.position or 99)
            )

            print(f"\n{'─'*80}")
            print(f"  {ts} UTC")
            print(f"{'─'*80}")
            print(f"  {'POS':<4} {'Δ':<4} {'DRV':<5} {'LAP':<5} {'COMPOUND':<12} "
                  f"{'AGE':<6} {'S1':<8} {'S2':<8} {'S3':<8} LAST LAP")
            print(f"{'─'*80}")

            for d in drivers:
                stint  = d.current_stint
                ls     = d.last_sectors
                delta  = d.positions_delta
                delta_str = (f"+{delta}" if delta > 0 else str(delta)) if delta is not None else "—"
                pos    = str(d.position) if d.position else "—"
                s1_str = f"{ls.s1:.3f}" if ls.s1 else "—"
                s2_str = f"{ls.s2:.3f}" if ls.s2 else "—"
                s3_str = f"{ls.s3:.3f}" if ls.s3 else "—"
                last   = f"{d.last_lap_time:.3f}" if d.last_lap_time else "—"
                print(f"  {pos:<4} {delta_str:<4} {d.acronym:<5} {d.current_lap:<5} "
                      f"{(stint.compound if stint else '—'):<12} "
                      f"{(str(d.tyre_age)+'L') if d.tyre_age is not None else '—':<6} "
                      f"{s1_str:<8} {s2_str:<8} {s3_str:<8} {last}")

            print(f"{'─'*80}")
            time.sleep(interval_s)

    except KeyboardInterrupt:
        print("\nStopped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="F1 live strategy monitor")
    parser.add_argument("--session", type=int, default=None)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    poll_live(interval_s=args.interval, session_key=args.session)
