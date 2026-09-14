"""Race listings and the LLM-backed pre-race / post-race briefings."""

import os

from fastapi import APIRouter, HTTPException

from data.live import _get, _cache_get, _cache_set, get_drivers, HIST_TTL

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
    """Completed Grand Prix weekends for the year, newest first, with the
    official weekend name (OpenF1's own `meeting_official_name`, e.g.
    "FORMULA 1 HEINEKEN CHINESE GRAND PRIX 2026" -- not something built
    up here) and the top-3 podium. A sprint isn't its own race weekend --
    it's folded into its Grand Prix's entry as a `sprint` sub-object
    (session_key/date only, no separate podium) rather than listed as a
    second, competing card."""
    try:
        sessions = _cache_get(f"race_list:{year}")
        if sessions is None:
            raw = _get("sessions", year=year)
            from datetime import datetime, timezone
            from dateutil.parser import parse as parse_dt
            now = datetime.now(timezone.utc)
            official_name = {m["meeting_key"]: m.get("meeting_official_name")
                             for m in _get("meetings", year=year)}

            by_meeting: dict = {}
            # A sprint (Saturday) normally completes before its own Grand
            # Prix (Sunday) has even started, let alone finished -- iterating
            # newest-first means we'd hit the sprint before the (still
            # incomplete, so not-yet-in `by_meeting`) race exists. Held here
            # and reconciled after the main loop so a sprint that outpaces
            # its own race mid-weekend still shows up somewhere.
            orphan_sprints = []

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
                mk = s.get("meeting_key")
                is_sprint = "sprint" in s.get("session_name", "").lower()

                if is_sprint:
                    sprint_entry = {"session_key": s["session_key"],
                                    "date_start": s.get("date_start")}
                    if mk in by_meeting:
                        by_meeting[mk]["sprint"] = sprint_entry
                    else:
                        orphan_sprints.append((mk, s, sprint_entry))
                    continue

                podium = []
                try:
                    results = sorted(
                        [r for r in _get("session_result", session_key=s["session_key"])
                         if r.get("position") and r["position"] <= 3],
                        key=lambda r: r["position"])
                    drivers = get_drivers(s["session_key"], HIST_TTL)
                    for r in results:
                        d = drivers.get(r["driver_number"], {})
                        podium.append({
                            "position": r["position"],
                            "acronym": d.get("name_acronym", "?"),
                            "team_colour": d.get("team_colour"),
                            "gap_to_leader": r.get("gap_to_leader"),
                        })
                except Exception:
                    pass
                by_meeting[mk] = {
                    "session_key":  s["session_key"],
                    "meeting_key":  mk,
                    "session_name": s.get("session_name"),
                    "country_name": s.get("country_name"),
                    "circuit_short_name": s.get("circuit_short_name"),
                    "date_start":   s.get("date_start"),
                    "year":         s.get("year"),
                    "official_name": official_name.get(mk),
                    "podium": podium,
                    "sprint": None,
                }

            for mk, s, sprint_entry in orphan_sprints:
                if mk in by_meeting:
                    by_meeting[mk]["sprint"] = sprint_entry
                    continue
                # The Grand Prix genuinely hasn't finished yet -- show the
                # sprint on its own rather than drop it.
                by_meeting[f"sprint-only-{mk}"] = {
                    "session_key":  s["session_key"],
                    "meeting_key":  mk,
                    "session_name": s.get("session_name"),
                    "country_name": s.get("country_name"),
                    "circuit_short_name": s.get("circuit_short_name"),
                    "date_start":   s.get("date_start"),
                    "year":         s.get("year"),
                    "official_name": official_name.get(mk),
                    "podium": [],
                    "sprint": None,
                }

            sessions = sorted(by_meeting.values(), key=lambda x: x["date_start"], reverse=True)
            _cache_set(f"race_list:{year}", sessions, 1800)
        return {"year": year, "races": sessions}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/standings")
def standings(year: int = 2026):
    """Drivers' and constructors' championship standings, summed from
    OpenF1's own per-session `points` field across every completed Race
    and Sprint session this year -- not a self-implemented points table,
    so sprint scoring is exactly whatever OpenF1 itself applied, no
    separate rule table to keep in sync. A mid-season team change is
    attributed correctly for constructors (points credited to whichever
    team a driver was actually driving for that weekend); the driver-level
    `team`/`team_colour` shown is just their most recent one, for display."""
    try:
        cached = _cache_get(f"standings:{year}")
        if cached is not None:
            return cached
        from datetime import datetime, timezone
        from dateutil.parser import parse as parse_dt
        now = datetime.now(timezone.utc)
        raw = _get("sessions", year=year)
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
                results = _get("session_result", session_key=sk)
                drivers = get_drivers(sk, HIST_TTL)
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
        _cache_set(f"standings:{year}", result, 1800)
        return result
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
    """The next meeting on the calendar, whose grand prix hasn't run yet.
    `in_progress` distinguishes two cases the frontend needs to treat
    differently: True means at least one session has completed, so a
    pre-race briefing can actually be built (FP/quali data exists) --
    False means it's purely a future date with nothing to build from yet
    (build_prerace_data would just raise "no completed sessions"), so the
    frontend should show a countdown, not try to load a briefing."""
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
                                         "completed_sessions": [],
                                         "is_sprint_weekend": False})
            end = s.get("date_end")
            done = False
            if end:
                end_dt = parse_dt(end)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                done = end_dt < now
            name = s.get("session_name", "")
            if "sprint" in name.lower() and "qualifying" not in name.lower():
                m["is_sprint_weekend"] = True
            is_gp = (s.get("session_type", "").lower() == "race"
                     and "sprint" not in name.lower())
            if is_gp:
                m["race_date"] = s.get("date_start")
                m["race_done"] = done
            elif done:
                m["completed_sessions"].append(name)
        # race_date required: filters out test meetings, which have no GP.
        all_gps = [m for m in meetings.values() if m["race_date"]]
        all_gps.sort(key=lambda m: m["race_date"])
        total_rounds = len(all_gps)
        # Sorted ascending, so [0] is unambiguously the next GP on the
        # calendar -- whether or not any of its sessions have run yet.
        upcoming = [m for m in all_gps if not m["race_done"]]
        chosen = upcoming[0] if upcoming else None
        if chosen:
            round_number = next(i for i, m in enumerate(all_gps, 1)
                                if m["meeting_key"] == chosen["meeting_key"])
            chosen = dict(chosen, in_progress=bool(chosen["completed_sessions"]),
                         round_number=round_number, total_rounds=total_rounds)
        result = {"meeting": chosen}
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
