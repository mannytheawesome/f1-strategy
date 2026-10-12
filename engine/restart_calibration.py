"""
Live, self-updating calibration of the cold-tyre Safety Car/VSC restart
penalty (see engine/restart_delta.py's module docstring for what this
number is, why it's measured in seconds against the field's own median
lap time rather than in track positions, and why it's pooled globally
rather than split by circuit).

Same shape as engine/undercut_calibration.py (the per-circuit undercut-
shift's live version) -- importable (data/recalibrator.py's background
thread calls it), persisted next to the SQLite HTTP cache (survives a
Railway redeploy), and incremental (a periodic re-run only ever evaluates
a race that wasn't already in the persisted per-race cache). Deliberately
a SEPARATE persisted file from the undercut calibration's, not reused --
one calibration's cache corruption shouldn't be able to affect the other.

engine/restart_delta.py's hardcoded RESTART_LAP_DELTA_S stays in the
codebase as the bootstrap default -- what a fresh deploy uses before this
module's background job has produced its own live file, and what
restart_delta_for() falls back to if that file is ever missing or
unreadable.
"""
import json
import os
import statistics
import time

from data.live import get_laps, get_race_control, get_stints, HIST_TTL, HTTP_CACHE_DB_PATH
from engine.predictor import DRY
from engine.undercut_calibration import _completed_races

_CACHE_DIR = os.path.dirname(HTTP_CACHE_DB_PATH) or "var"
RESTART_RACES_CACHE_PATH = os.environ.get(
    "RESTART_CALIBRATION_RACES_PATH",
    os.path.join(_CACHE_DIR, "restart_calibration_races.json"))
RESTART_DELTA_DATA_PATH = os.environ.get(
    "RESTART_DELTA_DATA_PATH", os.path.join(_CACHE_DIR, "restart_delta.json"))

# A compound needs at least this many real restart-lap samples, pooled
# globally, before its measured median overrides the "assume no effect"
# default -- same rail as engine/undercut_calibration.py's MIN_SAMPLES; a
# smaller sample proved genuinely wild there, no reason to expect
# otherwise for a rarer event (a race-ruining neutralisation) than a
# one-stop pit lap.
MIN_SAMPLES = 10

MAX_RETRIES = 5
RETRY_DELAY_S = 8
API_PACE_S = 0.15

YEARS = (2023, 2024, 2025, 2026)

# How far past a race-control event's end_lap to search for the real
# first green-flag lap (see _true_restart_lap) -- found necessary by
# checking real data: Singapore 2026's two VSCs in the SAME race disagreed
# on whether end_lap itself was already back to racing pace. First VSC
# (start_lap 8, end_lap 9): field median lap time was 108.2s on lap 9 vs
# a ~99.5s pre-VSC baseline -- still neutralised, the real restart was lap
# 10 (99.2s). Second VSC (start_lap 39, end_lap 40): lap 40 was ALREADY
# 98.6s, essentially the real restart lap itself. Trusting end_lap
# literally would have mixed a still-slow lap in with genuine restart
# laps -- noise that dilutes any real compound-level signal. Checked
# directly against race_control + laps for session_key 11388.
RESTART_LAP_SEARCH_OFFSETS = (0, 1, 2)

# How many laps immediately before an event's start_lap to use as the
# "normal racing pace" reference (median, robust to one noisy lap).
PRE_EVENT_BASELINE_LAPS = 3

# A candidate lap counts as "really back to racing pace" once the field's
# median lap time on it is within this ratio of the pre-event baseline --
# loose enough that a compound genuinely slower to warm up (the effect
# this whole calibration exists to measure) isn't itself misclassified as
# "not yet restarted," tight enough to reject a lap that's still clearly
# VSC/SC-delta-limited (Singapore's lap 9 above was +8.7% over baseline).
RESTART_PACE_TOLERANCE = 1.08


def _true_restart_lap(event: dict, laps_by_lap: dict[int, list[dict]]) -> int | None:
    """The real first green-flag lap for this event, found by checking
    actual field pace rather than trusting race_control's end_lap at face
    value (see RESTART_LAP_SEARCH_OFFSETS' comment -- confirmed
    necessary, not hypothetical, on real data). Returns None if no
    pre-event baseline exists (e.g. a lap-1 incident) or no candidate lap
    within the search window ever gets back to it (e.g. the race ends
    under caution)."""
    pre_laps = range(max(1, event["start_lap"] - PRE_EVENT_BASELINE_LAPS), event["start_lap"])
    baseline_times = [r["lap_duration"] for l in pre_laps for r in laps_by_lap.get(l, [])]
    if not baseline_times:
        return None
    baseline = statistics.median(baseline_times)

    for offset in RESTART_LAP_SEARCH_OFFSETS:
        candidate = event["end_lap"] + offset
        rows = laps_by_lap.get(candidate, [])
        if len(rows) < 2:
            continue
        field_median = statistics.median(r["lap_duration"] for r in rows)
        if field_median <= baseline * RESTART_PACE_TOLERANCE:
            return candidate
    return None


def _restart_events(race_session_key: int) -> list[dict]:
    """Real (non-fabricated) SC/VSC restarts for this race -- every event
    that got a genuine race-control "ENDING"/"IN THIS LAP" close.
    Re-parses get_race_control directly rather than reusing
    data.live.get_sc_laps_from_race_control, which synthesises
    end_lap = start_lap + 5 for an event that never closes (e.g. a red-
    flag finish) -- a fabricated lap, not a measured restart, that would
    corrupt this calibration if pooled in. Same DEPLOYED/ENDING/VIRTUAL
    text-matching as that function, deliberately without its
    still-active-event close-out step."""
    messages = get_race_control(race_session_key, HIST_TTL)
    events = []
    active: dict[str, int | None] = {"SC": None, "VSC": None}
    for msg in sorted(messages, key=lambda m: m.get("date", "")):
        lap = msg.get("lap_number")
        text = (msg.get("message") or "").upper()
        if msg.get("category") != "SafetyCar" or not text:
            continue
        kind = "VSC" if ("VIRTUAL" in text or text.startswith("VSC")) else "SC"
        if "DEPLOYED" in text:
            if active[kind] is None:
                active[kind] = lap
        elif "ENDING" in text or "IN THIS LAP" in text:
            if active[kind] is not None and lap:
                events.append({"type": kind, "start_lap": active[kind], "end_lap": lap})
                active[kind] = None
    return events


def _restart_lap_residuals(race_session_key: int, events: list[dict]) -> list[dict]:
    """For each real restart, each eligible driver's lap-time residual on
    the TRUE first green-flag lap (see _true_restart_lap -- not
    race_control's end_lap taken at face value) vs the field's own median
    lap time on that same lap (cross-sectional -- cancels out track
    evolution/fuel/circuit effects automatically, no dependency on each
    driver's own fitted deg curve), tagged with their compound at that
    lap. Excludes a pit-out lap (its time is dominated by the stop
    itself, not restart grip -- dropped before the field median is even
    computed, so one car's slow in-lap can't drag the baseline every
    other car is judged against), a lap that falls exactly on a stint's
    first lap (just pitted into a new compound on the green-flag lap
    itself -- a rare, genuinely ambiguous case, not the common
    pitted-under-caution-then-restarted pattern, which this does NOT
    exclude), and a non-DRY/UNKNOWN compound (no physical meaning to
    compare wet-compound restart grip against dry, and UNKNOWN is a known
    data gap, not a real sample)."""
    laps = get_laps(race_session_key, HIST_TTL)
    stints = get_stints(race_session_key, HIST_TTL)

    laps_by_lap: dict[int, list[dict]] = {}
    for l in laps:
        if l.get("lap_duration"):
            laps_by_lap.setdefault(l["lap_number"], []).append(l)
    stints_by_driver: dict[int, list[dict]] = {}
    for s in stints:
        stints_by_driver.setdefault(s["driver_number"], []).append(s)

    out = []
    for ev in events:
        target_lap = _true_restart_lap(ev, laps_by_lap)
        if target_lap is None:
            continue
        # Pit-out laps are dropped BEFORE computing the field median, not
        # just before sampling -- one car's artificially slow in-lap must
        # not drag the baseline every other car is compared against.
        rows = [r for r in laps_by_lap.get(target_lap, [])
               if not r.get("is_pit_out_lap")]
        if len(rows) < 2:
            continue   # can't form a meaningful field median off 0-1 cars
        field_median = statistics.median(r["lap_duration"] for r in rows)
        for r in rows:
            driver_stints = stints_by_driver.get(r["driver_number"], [])
            stint = next((s for s in driver_stints
                         if s["lap_start"] <= target_lap <= (s.get("lap_end") or target_lap)),
                        None)
            if stint is None or stint["lap_start"] == target_lap:
                continue
            compound = stint.get("compound")
            if compound not in DRY:
                continue
            out.append({"compound": compound,
                       "residual_s": round(r["lap_duration"] - field_median, 3)})
    return out


def evaluate_one(r: dict) -> dict | None:
    events = None
    for attempt in range(MAX_RETRIES):
        try:
            events = _restart_events(r["race_session_key"])
            break
        except Exception:
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(RETRY_DELAY_S)
    if not events:
        return {"circuit": r["circuit"], "name": r["name"], "year": r["year"], "samples": []}

    samples = None
    for attempt in range(MAX_RETRIES):
        try:
            samples = _restart_lap_residuals(r["race_session_key"], events)
            break
        except Exception:
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(RETRY_DELAY_S)
    return {"circuit": r["circuit"], "name": r["name"], "year": r["year"],
           "samples": samples or []}


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


def aggregate(races_cache: dict) -> dict:
    """{compound: seconds} for every compound with >= MIN_SAMPLES real
    restart-lap residuals, pooled globally across every circuit/year --
    no per-circuit split and no cross-compound default (see
    engine/restart_delta.py's docstring for why neither applies here)."""
    by_compound: dict[str, list[float]] = {}
    for v in races_cache.values():
        if v:
            for s in v["samples"]:
                by_compound.setdefault(s["compound"], []).append(s["residual_s"])

    out = {}
    for compound, residuals in by_compound.items():
        if len(residuals) >= MIN_SAMPLES:
            out[compound] = round(statistics.median(residuals), 2)
    return {"by_compound": out,
           "n_races": sum(1 for v in races_cache.values() if v and v["samples"]),
           "n_samples": sum(len(v["samples"]) for v in races_cache.values() if v)}


def run_incremental_calibration(years: tuple = YEARS) -> dict:
    """Fetch any completed race not already in the persisted per-race
    cache, evaluate it, and recompute + persist the global per-compound
    aggregate. Safe to call repeatedly -- races already cached are never
    re-fetched, so a periodic re-run only ever does the work of however
    many races have newly completed since the last run."""
    races_cache = _load_json(RESTART_RACES_CACHE_PATH)
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
        _save_json(RESTART_RACES_CACHE_PATH, races_cache)

    agg = aggregate(races_cache)
    _save_json(RESTART_DELTA_DATA_PATH, agg)
    return agg


def load_calibration() -> dict | None:
    """The current self-updating calibration, or None if the background
    job hasn't produced one yet (a fresh deploy, or the volume being
    empty) -- callers fall back to the hardcoded bootstrap default."""
    if not os.path.exists(RESTART_DELTA_DATA_PATH):
        return None
    try:
        with open(RESTART_DELTA_DATA_PATH) as f:
            data = json.load(f)
        if "by_compound" in data:
            return data
    except Exception:
        pass
    return None
