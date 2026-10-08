"""
Corner-by-corner wet/dry grip-sensitivity analysis via FastF1 telemetry.

OpenF1 (this project's primary data source everywhere else) has no
telemetry or corner-level data at all -- only lap times and stint
boundaries. FastF1 (github.com/theOehrly/Fast-F1) reads the same official
F1 live-timing feed but exposes full car telemetry (speed/throttle/brake/
position) plus an official per-circuit corner map with an exact track-
distance marker for every corner.

For every corner, this compares the median apex (minimum) speed across the
race's own clean dry-compound laps against its clean wet-compound laps --
an IN-RACE comparison, not cross-race, so track evolution and temperature
can't confound it. The corners with the biggest relative speed loss are
the "canaries" (the earliest, clearest tell that grip has changed); the
smallest (or negative -- faster in the "wet" bucket, usually meaning too
few/noisy samples) are "liars", a poor or misleading indicator.

Deliberately post-race only: FastF1's telemetry isn't populated until a
session is archived (unlike OpenF1, which this project also uses live),
and there's nothing to compare in a race with no wet-compound running at
all -- both cases degrade to None rather than guessing, same as every
other optional pack field in engine/briefing.py.

Session identity: FastF1 is looked up by (year, event name, session type),
not OpenF1's session_key -- (year, country_name, "R") is passed straight
through from the pack already built from OpenF1, and FastF1 fuzzy-matches
the event name itself (confirmed 2026-10-08 against several real 2026
sessions). This resolves even for the one race this project has spent the
most time on this season (the 2026 Bahrain GP, whose official Location
field inexplicably reads "Kuala Lumpur" -- the same upstream oddity
documented at length in CLAUDE.md for OpenF1's own stint data) -- but that
race's circuit MAP lookup specifically fails (FastF1 keys the track map by
that same Location string, which matches no known circuit), confirmed by
hand. That failure is handled here like any other: caught, returns None.
"""
import os
import statistics

from data.live import HTTP_CACHE_DB_PATH

# Same directory HTTP_CACHE_DB_PATH already lives in -- production sets
# that to /data (the mounted Railway volume) via its own env var, so this
# inherits the same persistent location automatically, no new Railway
# configuration needed (same convention engine/undercut_calibration.py
# already established for its own live-recalibration cache).
_CACHE_DIR = os.path.join(os.path.dirname(HTTP_CACHE_DB_PATH) or ".", "fastf1_cache")

_cache_enabled = False

WET_COMPOUNDS = {"INTERMEDIATE", "WET"}
DRY_COMPOUNDS = {"SOFT", "MEDIUM", "HARD"}
APEX_RADIUS_M = 40        # metres, straight-line, from a corner's reference X/Y
MAX_LAPS_PER_BUCKET = 40  # bounds processing cost -- each lap is its own telemetry pull
MIN_SAMPLES_PER_CORNER = 3
CANARY_LIAR_COUNT = 3     # how many corners to name at each end of the ranking


def _ensure_cache() -> None:
    global _cache_enabled
    if _cache_enabled:
        return
    os.makedirs(_CACHE_DIR, exist_ok=True)
    import fastf1
    fastf1.Cache.enable_cache(_CACHE_DIR)
    fastf1.logger.set_log_level("ERROR")
    _cache_enabled = True


def _apex_speeds(lap_rows, corners: list[dict]) -> dict[int, list[float]]:
    """For each lap, find the minimum speed within APEX_RADIUS_M (straight-
    line X/Y distance, not along-lap Distance) of each corner's reference
    position. X/Y proximity, not a 1D distance window, is deliberate: a
    lap's own total `Distance` isn't perfectly consistent lap-to-lap
    (different racing lines cover slightly different ground), so a fixed
    window around a reference Distance marker drifts further from the true
    corner the later it falls in the lap -- confirmed 2026-10-08 on real
    data (Canada): windowing on Distance alone produced a physically
    impossible result (wet apex speed FASTER than dry) that grew in
    magnitude corner-by-corner through the lap, the exact signature of
    accumulating drift. X/Y proximity has no such drift; it's a real
    position regardless of how the lap's own distance accounting reads."""
    speeds_by_corner: dict[int, list[float]] = {c["Number"]: [] for c in corners}
    radius2 = APEX_RADIUS_M ** 2
    for _, lap in lap_rows.head(MAX_LAPS_PER_BUCKET).iterrows():
        try:
            tel = lap.get_telemetry()
        except Exception:
            continue
        if tel.empty:
            continue
        for c in corners:
            dist2 = (tel["X"] - c["X"]) ** 2 + (tel["Y"] - c["Y"]) ** 2
            window = tel[dist2 <= radius2]
            if len(window):
                speeds_by_corner[c["Number"]].append(float(window["Speed"].min()))
    return speeds_by_corner


def build_corner_sensitivity(year: int, country_name: str) -> dict | None:
    """Returns None for any of several real, expected cases: FastF1 has no
    session for this race yet, the race's circuit map doesn't resolve, or
    there simply isn't enough clean wet-compound running to compare against
    the dry baseline (most races, most of the time) -- never raises."""
    try:
        _ensure_cache()
        import fastf1
        session = fastf1.get_session(year, country_name, "R")
        session.load(telemetry=True, laps=True, weather=False)
    except Exception as e:
        print(f"[corner_sensitivity] session load failed for {year} {country_name}: {e}")
        return None

    try:
        circuit_info = session.get_circuit_info()
        corners = circuit_info.corners[["Number", "X", "Y"]].to_dict("records")
    except Exception as e:
        print(f"[corner_sensitivity] no circuit map for {year} {country_name}: {e}")
        return None
    if not corners:
        return None

    try:
        laps = session.laps
        clean = laps[(laps["TrackStatus"] == "1") & laps["LapTime"].notna()
                    & laps["PitInTime"].isna() & laps["PitOutTime"].isna()]
        wet_laps = clean[clean["Compound"].isin(WET_COMPOUNDS)]
        dry_laps = clean[clean["Compound"].isin(DRY_COMPOUNDS)]
        if len(wet_laps) < MIN_SAMPLES_PER_CORNER or len(dry_laps) < MIN_SAMPLES_PER_CORNER:
            return None   # a dry race, or not enough clean wet running to compare

        wet_speeds = _apex_speeds(wet_laps, corners)
        dry_speeds = _apex_speeds(dry_laps, corners)
    except Exception as e:
        print(f"[corner_sensitivity] telemetry processing failed for {year} {country_name}: {e}")
        return None

    results = []
    for c in corners:
        n = c["Number"]
        wet, dry = wet_speeds.get(n, []), dry_speeds.get(n, [])
        if len(wet) < MIN_SAMPLES_PER_CORNER or len(dry) < MIN_SAMPLES_PER_CORNER:
            continue
        dry_med, wet_med = statistics.median(dry), statistics.median(wet)
        if dry_med <= 0:
            continue
        results.append({
            "corner": n,
            "loss_pct": round((dry_med - wet_med) / dry_med * 100, 1),
            "dry_median_kmh": round(dry_med, 1),
            "wet_median_kmh": round(wet_med, 1),
            "n_dry": len(dry),
            "n_wet": len(wet),
        })
    if not results:
        return None
    results.sort(key=lambda r: -r["loss_pct"])
    return {
        "corners": results,
        "canary_corners": [r["corner"] for r in results[:CANARY_LIAR_COUNT]],
        "liar_corners": [r["corner"] for r in results[-CANARY_LIAR_COUNT:]],
    }
