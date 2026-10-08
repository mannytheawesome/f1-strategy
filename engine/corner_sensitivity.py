"""
Corner-by-corner grip-sensitivity analysis via FastF1 telemetry.

OpenF1 (this project's primary data source everywhere else) has no
telemetry or corner-level data at all -- only lap times and stint
boundaries. FastF1 (github.com/theOehrly/Fast-F1) reads the same official
F1 live-timing feed but exposes full car telemetry (speed/throttle/brake/
position) plus an official per-circuit corner map with an exact reference
position for every corner.

Two comparisons, tried in order, sharing one FastF1 session load:

1. wet_dry: median apex (minimum) speed across the race's own clean dry-
   compound laps vs its clean wet-compound laps -- Buscombe's "canary vs
   liar corner" (which corners show a grip change earliest/most clearly vs
   which stay deceptively quick). Only possible for a race that actually
   had wet-compound running, which is most races, most of the time.
2. degradation: falls back to this when there's no wet running (or not
   enough of it) to compare -- median apex speed on fresh tyres (early in
   a stint) vs worn tyres (well into one), holding compound constant (the
   race's single most-run dry compound, so a compound CHANGE never gets
   mistaken for wear). Works on essentially every race, since every race
   has fresh and worn tyres regardless of weather.

Both are IN-RACE comparisons, not cross-race, so track evolution and
temperature can't confound either one. Within whichever comparison ran,
the corners with the biggest relative speed loss are the "canaries"; the
smallest (or negative -- usually too few/noisy samples) are "liars".

Deliberately post-race only: FastF1's telemetry isn't populated until a
session is archived (unlike OpenF1, which this project also uses live).
Every failure mode -- no FastF1 session yet, no circuit map, not enough
clean running for EITHER comparison -- degrades to None rather than
guessing, same as every other optional pack field in engine/briefing.py.

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

# Degradation fallback: a lap this early on a set is "fresh" (tyre up to
# temperature, not yet degraded); this late is "worn". Chosen to comfortably
# fit inside a typical one-stop stint (20-35 laps) without demanding an
# unusually long run to get enough worn-lap samples.
FRESH_MAX_AGE = 3
WORN_MIN_AGE = 15


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


def _rank_corners(corners: list[dict], a_speeds: dict, b_speeds: dict) -> list[dict] | None:
    """a is the baseline (higher speed expected -- dry, or fresh tyres); b
    is the compromised condition (wet, or worn tyres). loss_pct > 0 means b
    was slower at that corner, as physically expected."""
    results = []
    for c in corners:
        n = c["Number"]
        a, b = a_speeds.get(n, []), b_speeds.get(n, [])
        if len(a) < MIN_SAMPLES_PER_CORNER or len(b) < MIN_SAMPLES_PER_CORNER:
            continue
        a_med, b_med = statistics.median(a), statistics.median(b)
        if a_med <= 0:
            continue
        results.append({
            "corner": n,
            "loss_pct": round((a_med - b_med) / a_med * 100, 1),
            "a_median_kmh": round(a_med, 1),
            "b_median_kmh": round(b_med, 1),
            "n_a": len(a),
            "n_b": len(b),
        })
    if not results:
        return None
    results.sort(key=lambda r: -r["loss_pct"])
    return results


def _wet_dry_comparison(laps, corners: list[dict]) -> dict | None:
    wet_laps = laps[laps["Compound"].isin(WET_COMPOUNDS)]
    dry_laps = laps[laps["Compound"].isin(DRY_COMPOUNDS)]
    if len(wet_laps) < MIN_SAMPLES_PER_CORNER or len(dry_laps) < MIN_SAMPLES_PER_CORNER:
        return None   # no wet running (most races), or not enough of it to compare
    results = _rank_corners(corners, _apex_speeds(dry_laps, corners), _apex_speeds(wet_laps, corners))
    if not results:
        return None
    return {
        "mode": "wet_dry",
        "a_label": "dry",
        "b_label": "wet",
        "corners": results,
        "canary_corners": [r["corner"] for r in results[:CANARY_LIAR_COUNT]],
        "liar_corners": [r["corner"] for r in results[-CANARY_LIAR_COUNT:]],
    }


def _degradation_comparison(laps, corners: list[dict]) -> dict | None:
    dry_laps = laps[laps["Compound"].isin(DRY_COMPOUNDS)]
    if dry_laps.empty:
        return None
    # Hold compound constant (the race's single most-run dry compound) so a
    # compound CHANGE is never mistaken for tyre wear.
    main_compound = dry_laps["Compound"].value_counts().idxmax()
    compound_laps = dry_laps[dry_laps["Compound"] == main_compound]
    fresh_laps = compound_laps[compound_laps["TyreLife"] <= FRESH_MAX_AGE]
    worn_laps = compound_laps[compound_laps["TyreLife"] >= WORN_MIN_AGE]
    if len(fresh_laps) < MIN_SAMPLES_PER_CORNER or len(worn_laps) < MIN_SAMPLES_PER_CORNER:
        return None   # no stints ran long enough to get enough worn-lap samples
    results = _rank_corners(corners, _apex_speeds(fresh_laps, corners), _apex_speeds(worn_laps, corners))
    if not results:
        return None
    return {
        "mode": "degradation",
        "a_label": "fresh tyres",
        "b_label": "worn tyres",
        "compound": main_compound,
        "corners": results,
        "canary_corners": [r["corner"] for r in results[:CANARY_LIAR_COUNT]],
        "liar_corners": [r["corner"] for r in results[-CANARY_LIAR_COUNT:]],
    }


def build_corner_sensitivity(year: int, country_name: str) -> dict | None:
    """Returns None for any of several real, expected cases: FastF1 has no
    session for this race yet, the race's circuit map doesn't resolve, or
    there simply isn't enough clean running for EITHER comparison -- never
    raises. Tries the wet/dry comparison first (the more interesting read
    when it's available); falls back to fresh-vs-worn degradation, which
    works on essentially any race regardless of weather."""
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
        return _wet_dry_comparison(clean, corners) or _degradation_comparison(clean, corners)
    except Exception as e:
        print(f"[corner_sensitivity] telemetry processing failed for {year} {country_name}: {e}")
        return None
