"""
Championship standings, shared between /api/standings (api/routers/briefings.py)
and the pre-race pack's championship context (engine/prerace.py).

compute_standings used to live only in the API route; moved here so the
pre-race builder can use the exact same real computation (summed from
OpenF1's own per-session `points` field, not a self-implemented points
table) instead of duplicating it -- see compute_standings' own docstring
for why that matters for sprint weekends and mid-season team changes.
"""
from datetime import datetime, timezone

from dateutil.parser import parse as parse_dt

from data.live import (_cache_get, _cache_set, _cached_get, get_drivers,
                       get_season_sessions, HIST_TTL_FINAL)

STANDINGS_CACHE_TTL = 1800


def compute_standings(year: int) -> dict:
    """Drivers' and constructors' championship standings, summed from
    OpenF1's own per-session `points` field across every completed Race
    and Sprint session this year -- not a self-implemented points table,
    so sprint scoring is exactly whatever OpenF1 itself applied, no
    separate rule table to keep in sync. A mid-season team change is
    attributed correctly for constructors (points credited to whichever
    team a driver was actually driving for that weekend); the driver-level
    `team`/`team_colour` shown is just their most recent one, for display."""
    cached = _cache_get(f"standings:{year}")
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    raw = get_season_sessions(year)
    scoring_keys = []
    for s in raw:
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
        scoring_keys.append(s["session_key"])

    driver_points: dict[int, float] = {}
    driver_acr: dict[int, str] = {}
    driver_team: dict[int, str] = {}
    driver_colour: dict[int, str] = {}
    team_points: dict[str, float] = {}
    team_colour: dict[str, str] = {}

    for sk in scoring_keys:
        try:
            results = _cached_get(f"session_result:{sk}", "session_result",
                                  HIST_TTL_FINAL, session_key=sk)
            drivers = get_drivers(sk, HIST_TTL_FINAL)
        except Exception:
            continue
        for r in results:
            num = r.get("driver_number")
            pts = r.get("points") or 0
            if num is None or not pts:
                continue
            driver_points[num] = driver_points.get(num, 0) + pts
            d = drivers.get(num, {})
            if d.get("name_acronym"):
                driver_acr[num] = d["name_acronym"]
            team = d.get("team_name")
            if team:
                driver_team[num] = team
                driver_colour[num] = d.get("team_colour")
                team_points[team] = team_points.get(team, 0) + pts
                team_colour.setdefault(team, d.get("team_colour"))

    drivers_standings = sorted(
        [{"driver_number": n, "acronym": driver_acr.get(n, str(n)),
          "team": driver_team.get(n), "team_colour": driver_colour.get(n),
          "points": pts}
         for n, pts in driver_points.items()],
        key=lambda x: -x["points"])
    for i, d in enumerate(drivers_standings, 1):
        d["position"] = i

    constructors_standings = sorted(
        [{"team": team, "team_colour": team_colour.get(team), "points": pts}
         for team, pts in team_points.items()],
        key=lambda x: -x["points"])
    for i, c in enumerate(constructors_standings, 1):
        c["position"] = i

    result = {"year": year, "drivers": drivers_standings,
              "constructors": constructors_standings}
    _cache_set(f"standings:{year}", result, STANDINGS_CACHE_TTL)
    return result


def season_race_progress(year: int) -> dict:
    """{completed, total, remaining} Grand Prix race count for the season
    (sprints excluded -- they don't advance the calendar's round count,
    same convention race_list/round_number already uses in
    api/routers/briefings.py). `remaining` includes a race currently in
    progress or not yet started."""
    now = datetime.now(timezone.utc)
    raw = get_season_sessions(year)
    total = 0
    completed = 0
    for s in raw:
        if s.get("session_type", "").lower() != "race":
            continue
        if "sprint" in s.get("session_name", "").lower():
            continue
        total += 1
        end = s.get("date_end")
        if not end:
            continue
        end_dt = parse_dt(end)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        if end_dt <= now:
            completed += 1
    return {"completed": completed, "total": total,
            "remaining": max(0, total - completed)}
