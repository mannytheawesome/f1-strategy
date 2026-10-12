"""
Live, self-updating calibration of the overtaking pass-rate threshold
(see engine/overtake_delta.py's module docstring for what this number is
and why it's measured per-circuit from real lap-time and gap data rather
than derived analytically).

Same shape as engine/undercut_calibration.py and
engine/restart_calibration.py -- importable (data/recalibrator.py's
background thread calls it), persisted next to the SQLite HTTP cache
(survives a Railway redeploy), and incremental (a periodic re-run only
ever evaluates a race that wasn't already in the persisted per-race
cache). A separate persisted file from the other two calibrations' --
one calibration's cache corruption shouldn't affect the others.

engine/overtake_delta.py's hardcoded OVERTAKE_PASS_THRESHOLD_S stays in
the codebase as the bootstrap default -- what a fresh deploy uses before
this module's background job has produced its own live file, and what
pass_threshold_for() falls back to if that file is ever missing or
unreadable.
"""
import json
import os
import statistics
import time

from data.live import get_laps, get_all_intervals, HIST_TTL, HTTP_CACHE_DB_PATH
from engine.undercut_calibration import _completed_races

_CACHE_DIR = os.path.dirname(HTTP_CACHE_DB_PATH) or "var"
OVERTAKE_RACES_CACHE_PATH = os.environ.get(
    "OVERTAKE_CALIBRATION_RACES_PATH",
    os.path.join(_CACHE_DIR, "overtake_calibration_races.json"))
OVERTAKE_DELTA_DATA_PATH = os.environ.get(
    "OVERTAKE_DELTA_DATA_PATH", os.path.join(_CACHE_DIR, "overtake_delta.json"))

MAX_RETRIES = 5
RETRY_DELAY_S = 8
API_PACE_S = 0.15

YEARS = (2023, 2024, 2025, 2026)

# Only a pair of cars running this close counts as a genuine passing
# opportunity to sample -- loosely mirrors the strategist's own reported
# "within 1.2 seconds" population, loosened slightly to widen the sample
# without admitting pairs so far apart they were never racing each other.
GAP_THRESHOLD_S = 2.0

# Lap-time bucket width (s/lap) for the pass-rate curve, and the minimum
# raw sample count a bucket needs before its pass rate is trusted enough
# to anchor part of the 50% crossover -- checked directly against real
# data before picking this number: buckets this wide in the 0-3s/lap
# range routinely clear several hundred samples per circuit from just
# 2-4 cached races each, so 20 is a conservative floor, not a stretch.
PACE_BUCKET_WIDTH = 0.25
MIN_BUCKET_SAMPLES = 20

# A circuit needs samples spanning a real crossing (see
# _threshold_from_samples) before its own number overrides the pooled
# default -- there is no meaningful "too few races" count to gate on
# directly here, unlike the undercut/restart calibrations, since this
# measures lap-pairs, not races; gating happens at the bucket level.


def _running_order_at(intervals_by_driver: dict, t: str) -> list[int]:
    """Driver numbers ordered by their gap-to-leader as of the latest
    interval record at or before timestamp t. OpenF1 occasionally reports
    gap_to_leader as a string sentinel ("+1 LAP") for a lapped car --
    those are excluded, not coerced, since a lapped car's "gap" doesn't
    mean the same thing as a genuine on-track gap."""
    order = []
    for drv, rows in intervals_by_driver.items():
        best = None
        for r in rows:
            if r["date"] <= t:
                best = r
            else:
                break
        if best is not None and isinstance(best.get("gap_to_leader"), (int, float)):
            order.append((drv, best["gap_to_leader"]))
    order.sort(key=lambda x: x[1])
    return [d for d, _ in order]


def _close_pair_samples(race_session_key: int) -> list[tuple[float, bool]]:
    """For every green-flag lap, every pair of cars adjacent in the
    running order with a gap under GAP_THRESHOLD_S: (pace_delta, passed).
    pace_delta is the leading car's lap time minus the following car's
    (positive = the following car was faster that lap). passed is
    whether their order flips by the start of the next lap. Excludes a
    pit-out lap for either car, and any lap where either car's time
    exceeds 110% of the field's own median that lap (a neutralisation or
    incident, not a genuine racing lap -- same style of field-relative
    check used for the restart-penalty calibration)."""
    laps = get_laps(race_session_key, HIST_TTL)
    intervals = get_all_intervals(race_session_key, HIST_TTL)

    laps_by_driver_lap: dict[tuple[int, int], dict] = {}
    lap_start: dict[int, list[str]] = {}
    for l in laps:
        if l.get("date_start") and l.get("lap_duration"):
            laps_by_driver_lap[(l["driver_number"], l["lap_number"])] = l
            lap_start.setdefault(l["lap_number"], []).append(l["date_start"])

    intervals_by_driver: dict[int, list[dict]] = {}
    for r in intervals:
        if r.get("date") and r.get("gap_to_leader") is not None:
            intervals_by_driver.setdefault(r["driver_number"], []).append(r)
    for rows in intervals_by_driver.values():
        rows.sort(key=lambda r: r["date"])

    out: list[tuple[float, bool]] = []
    all_laps = sorted(lap_start.keys())
    for lap_n in all_laps:
        if lap_n + 1 not in lap_start:
            continue
        t0 = min(lap_start[lap_n])
        t1 = min(lap_start[lap_n + 1])
        order_start = _running_order_at(intervals_by_driver, t0)
        order_next = _running_order_at(intervals_by_driver, t1)
        if len(order_start) < 2 or len(order_next) < 2:
            continue
        rank_next = {d: i for i, d in enumerate(order_next)}

        field_times = [laps_by_driver_lap[(d, lap_n)]["lap_duration"]
                       for d in order_start if (d, lap_n) in laps_by_driver_lap]
        if len(field_times) < 5:
            continue
        field_median = statistics.median(field_times)

        gaps_at_t0: dict[int, float] = {}
        for d in order_start:
            best = None
            for r in intervals_by_driver.get(d, []):
                if r["date"] <= t0:
                    best = r
                else:
                    break
            if best is not None and isinstance(best.get("gap_to_leader"), (int, float)):
                gaps_at_t0[d] = best["gap_to_leader"]

        for i in range(len(order_start) - 1):
            ahead, behind = order_start[i], order_start[i + 1]
            la = laps_by_driver_lap.get((ahead, lap_n))
            lb = laps_by_driver_lap.get((behind, lap_n))
            if not la or not lb:
                continue
            if la.get("is_pit_out_lap") or lb.get("is_pit_out_lap"):
                continue
            if la["lap_duration"] > field_median * 1.1 or lb["lap_duration"] > field_median * 1.1:
                continue
            if behind not in gaps_at_t0 or ahead not in gaps_at_t0:
                continue
            gap = gaps_at_t0[behind] - gaps_at_t0[ahead]
            if gap > GAP_THRESHOLD_S or gap < 0:
                continue
            pace_delta = la["lap_duration"] - lb["lap_duration"]
            passed = rank_next.get(behind, 999) < rank_next.get(ahead, 999)
            out.append((pace_delta, passed))
    return out


def _threshold_from_samples(samples: list[tuple[float, bool]]) -> float | None:
    """The pace delta (s/lap) at which the bucketed pass rate crosses
    50%, by linear interpolation between the first adjacent pair of
    buckets (ascending by pace delta) that straddle it -- both needing
    >= MIN_BUCKET_SAMPLES to be trusted. None if no such crossing exists
    (too little data, or the curve never actually crosses 50% in a
    trustworthy range)."""
    buckets: dict[float, list[bool]] = {}
    for pd, passed in samples:
        b = round(pd / PACE_BUCKET_WIDTH) * PACE_BUCKET_WIDTH
        buckets.setdefault(b, []).append(passed)

    trusted = sorted((b, sum(v) / len(v)) for b, v in buckets.items()
                     if len(v) >= MIN_BUCKET_SAMPLES)
    for (b0, r0), (b1, r1) in zip(trusted, trusted[1:]):
        if r0 < 0.5 <= r1 and r1 != r0:
            frac = (0.5 - r0) / (r1 - r0)
            return round(b0 + frac * (b1 - b0), 2)
    return None


def evaluate_one(r: dict) -> dict | None:
    samples = None
    for attempt in range(MAX_RETRIES):
        try:
            samples = _close_pair_samples(r["race_session_key"])
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
    """{circuit: pass_threshold_s_per_lap} for every circuit whose
    pooled real samples produce a trustworthy 50% crossing, plus a
    "default" field -- the crossing from every circuit's samples pooled
    together, for a circuit with no trustworthy crossing of its own yet
    (a brand new venue, or simply too little data so far)."""
    by_circuit: dict[str, list[tuple[float, bool]]] = {}
    all_samples: list[tuple[float, bool]] = []
    for v in races_cache.values():
        if v:
            key = (v["circuit"] or "").lower()
            by_circuit.setdefault(key, []).extend(v["samples"])
            all_samples.extend(v["samples"])

    out = {}
    for circuit, samples in by_circuit.items():
        t = _threshold_from_samples(samples)
        if t is not None:
            out[circuit] = t
    default = _threshold_from_samples(all_samples)
    return {"by_circuit": out,
           "default": default if default is not None else 1.1,
           "n_races": sum(1 for v in races_cache.values() if v and v["samples"]),
           "n_samples": len(all_samples)}


def run_incremental_calibration(years: tuple = YEARS) -> dict:
    """Fetch any completed race not already in the persisted per-race
    cache, evaluate it, and recompute + persist the per-circuit
    aggregate. Safe to call repeatedly -- races already cached are never
    re-fetched, so a periodic re-run only ever does the work of however
    many races have newly completed since the last run."""
    races_cache = _load_json(OVERTAKE_RACES_CACHE_PATH)
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
        _save_json(OVERTAKE_RACES_CACHE_PATH, races_cache)

    agg = aggregate(races_cache)
    _save_json(OVERTAKE_DELTA_DATA_PATH, agg)
    return agg


def load_calibration() -> dict | None:
    """The current self-updating calibration, or None if the background
    job hasn't produced one yet (a fresh deploy, or the volume being
    empty) -- callers fall back to the hardcoded bootstrap default."""
    if not os.path.exists(OVERTAKE_DELTA_DATA_PATH):
        return None
    try:
        with open(OVERTAKE_DELTA_DATA_PATH) as f:
            data = json.load(f)
        if "by_circuit" in data and "default" in data:
            return data
    except Exception:
        pass
    return None
