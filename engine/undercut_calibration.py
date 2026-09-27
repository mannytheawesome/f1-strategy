"""
Live, self-updating version of the per-circuit undercut-shift calibration
(see engine/undercut_shift.py's module docstring for what this number is
and why it's circuit-specific, not a flat constant).

The original calibration (calibrate_undercut_shift.py) was a one-off,
manually-run script -- accurate the day it ran, but frozen after that:
Baku's own result the very next weekend wouldn't feed back into its own
circuit's number without someone re-running the script by hand and
hand-editing engine/undercut_shift.py's CIRCUIT_UNDERCUT_SHIFT dict.
User asked directly: "automatic recalibration."

This module is that script's logic, refactored to be:
  - importable (data/recalibrator.py's background thread calls it)
  - persisted to whatever directory HTTP_CACHE_DB_PATH already lives in
    (production sets that to /data, the mounted Railway volume, via its
    own env var -- this inherits the same location automatically, no new
    Railway configuration needed) instead of the gitignored cache/
    directory the standalone script used -- so it survives a redeploy
    instead of re-fetching every race from scratch each time
  - incremental: the per-race cache means a periodic re-run only ever
    evaluates races that weren't already in it (a brand new completed
    race), never redoes the whole 2023-2026 sweep

engine/undercut_shift.py's hardcoded CIRCUIT_UNDERCUT_SHIFT stays in the
codebase as the bootstrap default -- what a fresh deploy uses before this
module's background job has produced its own live file, and what
undercut_shift_for() falls back to if that file is ever missing or
unreadable.
"""
import json
import os
import statistics
import time

from data.live import _get, get_laps, get_stints, HIST_TTL, HTTP_CACHE_DB_PATH
from engine.predictor import build_deg_curves, optimize_strategy
from engine.pit_loss import pit_loss_for
from engine.prerace import _prerace_sources, CIRCUIT_LAPS, DEFAULT_LAPS

# Default to whatever directory HTTP_CACHE_DB_PATH already lives in --
# production sets that to /data (the mounted Railway volume) via its own
# env var, so this inherits the same persistent location automatically,
# with no new Railway configuration needed. The explicit env vars below
# still exist for anyone who wants a different location.
_CACHE_DIR = os.path.dirname(HTTP_CACHE_DB_PATH) or "var"
RACES_CACHE_PATH = os.environ.get(
    "UNDERCUT_CALIBRATION_RACES_PATH",
    os.path.join(_CACHE_DIR, "undercut_calibration_races.json"))
OUTPUT_PATH = os.environ.get(
    "UNDERCUT_SHIFT_DATA_PATH", os.path.join(_CACHE_DIR, "undercut_shift.json"))

# A circuit needs at least this many real matched one-stop drivers before
# its own history overrides the field-wide default -- a smaller sample was
# checked and found genuinely wild, not just noisy-but-close (a real n=3
# case implied a 32-lap shift). Matches what was manually applied when
# this calibration first shipped (engine/undercut_shift.py's history).
MIN_SAMPLES = 10

MAX_RETRIES = 5
RETRY_DELAY_S = 8
API_PACE_S = 0.15   # small delay between calls -- be a good citizen given
                     # how often 429s have shown up on OpenF1 this season

YEARS = (2023, 2024, 2025, 2026)


def _completed_races(year: int) -> list[dict]:
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    meetings = _get("meetings", year=year)
    races = [m for m in meetings if "grand prix" in (m.get("meeting_name") or "").lower()]
    races.sort(key=lambda m: m["date_start"])
    out = []
    for m in races:
        try:
            sessions = _get("sessions", meeting_key=m["meeting_key"])
        except Exception:
            continue
        time.sleep(API_PACE_S)
        race = next((s for s in sessions if s.get("session_type") == "Race"
                    and "sprint" not in s.get("session_name", "").lower()), None)
        if not race or not race.get("date_end"):
            continue
        end = datetime.datetime.fromisoformat(race["date_end"].replace("Z", "+00:00"))
        if end < now:
            out.append({"meeting_key": m["meeting_key"], "name": m["meeting_name"],
                        "year": year, "circuit": m.get("circuit_short_name"),
                        "race_session_key": race["session_key"]})
    return out


def _predicted_medium_hard_pit_lap(meeting_key: int) -> tuple[int, int] | None:
    """(predicted_pit_lap, total_laps), or None if not computable -- the
    lean equivalent of build_prerace_data's deg-curve + strategy-search
    path, skipping everything else that pipeline also computes."""
    sources = _prerace_sources(meeting_key)
    circuit = next((s.get("circuit_short_name") for s in sources
                    if s.get("circuit_short_name")), "")
    total_laps = CIRCUIT_LAPS.get(circuit.lower(), DEFAULT_LAPS)

    fp_names = ["FP1", "FP2", "FP3"]
    fp_i = 0
    fp_data = []
    for s in sources:
        stype = s.get("session_type", "").lower()
        if stype == "practice" and fp_i < 3:
            fp_data.append((fp_names[fp_i], get_laps(s["session_key"], HIST_TTL),
                            get_stints(s["session_key"], HIST_TTL)))
            fp_i += 1
            time.sleep(API_PACE_S)
    if not fp_data:
        return None
    curves = build_deg_curves(fp_data)
    if "MEDIUM" not in curves or "HARD" not in curves:
        return None

    baselines = [c.baseline for c in curves.values() if c.baseline > 0]
    field_baseline = statistics.median(baselines) if baselines else 90.0
    pit_loss = pit_loss_for(circuit)

    strat = optimize_strategy(0, total_laps, "MEDIUM", 0, 0.0, curves,
                              field_baseline, pit_loss,
                              needs_compound_change=True, force_stops=1,
                              forbid_repeat_compound=True, force_end_compound="HARD")
    if len(strat.pits_remaining) != 1:
        return None
    return strat.pits_remaining[0].lap, total_laps


def _real_medium_hard_one_stops(race_session_key: int, total_laps: int) -> list[int]:
    stints = get_stints(race_session_key, HIST_TTL)
    by_driver: dict[int, list[dict]] = {}
    for s in stints:
        by_driver.setdefault(s["driver_number"], []).append(s)
    out = []
    for driver_stints in by_driver.values():
        driver_stints.sort(key=lambda s: s.get("stint_number", 0))
        if len(driver_stints) != 2:
            continue
        s1, s2 = driver_stints
        if s1.get("compound") != "MEDIUM" or s2.get("compound") != "HARD":
            continue
        if s1.get("lap_start") != 1:
            continue
        last_lap = s2.get("lap_end")
        if not last_lap or last_lap < total_laps - 2:
            continue
        pit_lap = s1.get("lap_end")
        if not pit_lap or pit_lap < 8:
            continue
        out.append(pit_lap)
    return out


def evaluate_one(r: dict) -> dict | None:
    pred = None
    for attempt in range(MAX_RETRIES):
        try:
            pred = _predicted_medium_hard_pit_lap(r["meeting_key"])
            break
        except Exception:
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(RETRY_DELAY_S)
    if pred is None:
        return {"circuit": r["circuit"], "name": r["name"], "year": r["year"], "matches": []}
    predicted_lap, total_laps = pred

    real_laps = None
    for attempt in range(MAX_RETRIES):
        try:
            real_laps = _real_medium_hard_one_stops(r["race_session_key"], total_laps)
            break
        except Exception:
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(RETRY_DELAY_S)

    matches = [{"real_pit_lap": lap, "predicted_pit_lap": predicted_lap,
               "error_laps": lap - predicted_lap} for lap in (real_laps or [])]
    return {"circuit": r["circuit"], "name": r["name"], "year": r["year"], "matches": matches}


def _load_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save_json(path: str, data: dict):
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=1)


def aggregate_by_circuit(races_cache: dict) -> dict:
    """{circuit: shift} for every circuit with >= MIN_SAMPLES real matched
    drivers, plus a "default" field -- the field-wide median for
    everything else. Positive shift = pit earlier than the pure-pace
    answer; negative = later."""
    by_circuit: dict[str, list[int]] = {}
    for v in races_cache.values():
        if v:
            for m in v["matches"]:
                by_circuit.setdefault((v["circuit"] or "").lower(), []).append(m["error_laps"])

    out = {}
    all_errs: list[int] = []
    for circuit, errs in by_circuit.items():
        all_errs.extend(errs)
        if len(errs) >= MIN_SAMPLES:
            out[circuit] = round(-statistics.median(errs), 1)
    default = round(-statistics.median(all_errs), 1) if all_errs else 4.0
    return {"by_circuit": out, "default": default,
            "n_races": sum(1 for v in races_cache.values() if v and v["matches"]),
            "n_matches": len(all_errs)}


def run_incremental_calibration(years: tuple = YEARS) -> dict:
    """Fetch any completed race not already in the persisted per-race
    cache, evaluate it, and recompute + persist the per-circuit aggregate.
    Safe to call repeatedly -- races already cached are never re-fetched,
    so a periodic re-run only ever does the work of however many races
    have newly completed since the last run."""
    races_cache = _load_json(RACES_CACHE_PATH)
    races = []
    for year in years:
        races.extend(_completed_races(year))

    changed = False
    for r in races:
        key = str(r["meeting_key"])
        if key in races_cache and races_cache[key] is not None:
            continue
        result = evaluate_one(r)
        races_cache[key] = result
        changed = True

    if changed:
        _save_json(RACES_CACHE_PATH, races_cache)

    aggregate = aggregate_by_circuit(races_cache)
    _save_json(OUTPUT_PATH, aggregate)
    return aggregate


def load_calibration() -> dict | None:
    """The current self-updating calibration, or None if the background
    job hasn't produced one yet (a fresh deploy, or the volume being
    empty) -- callers fall back to the hardcoded bootstrap default."""
    if not os.path.exists(OUTPUT_PATH):
        return None
    try:
        with open(OUTPUT_PATH) as f:
            data = json.load(f)
        if "by_circuit" in data and "default" in data:
            return data
    except Exception:
        pass
    return None
