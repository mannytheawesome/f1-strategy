"""
Tyre degradation engine.

For each driver in a live/replay state, calculates:
  - deg_rate:       average seconds lost per lap on current compound (from this session's data)
  - laps_remaining: estimated laps before tyre is past its performance cliff
  - pit_window:     (earliest_lap, latest_lap) the driver should box
  - status:         "OK" | "SOON" | "OVERDUE"

Approach: purely data-driven heuristics from the current session.
  1. Collect all clean stint laps (no pit-in, no pit-out, no SC) grouped by compound.
  2. Fit a linear degradation rate: seconds per lap of tyre age.
  3. Define a "cliff" threshold: when lap time has risen by CLIFF_SECONDS above the
     fresh-tyre baseline, the tyre is considered spent.
  4. From current age + rate, project how many laps remain before the cliff.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import statistics

# How many seconds of lap time rise counts as "tyre cliff"
CLIFF_SECONDS = {
    "SOFT":         1.5,
    "MEDIUM":       2.0,
    "HARD":         2.5,
    "INTERMEDIATE": 2.0,
    "WET":          2.0,
}
DEFAULT_CLIFF = 2.0

# Hard cap on tyre life (safety net when data is sparse)
MAX_LIFE = {
    "SOFT":         28,
    "MEDIUM":       42,
    "HARD":         58,
    "INTERMEDIATE": 35,
    "WET":          45,
}
DEFAULT_MAX = 40

# Minimum laps in a stint to trust the degradation rate
MIN_STINT_LAPS = 5


@dataclass
class TyreDegradation:
    compound: str
    deg_rate: float           # seconds lost per lap of tyre age
    baseline: float           # lap time on fresh tyre (lap 1 of stint)
    cliff_lap: int            # tyre age at which cliff is hit
    data_points: int          # how many laps this was built from


@dataclass
class DriverPrediction:
    driver_number: int
    acronym: str
    compound: str
    tyre_age: int
    deg_rate: float
    laps_remaining: int       # estimated laps before cliff
    pit_earliest: int         # current race lap
    pit_latest: int           # current race lap
    status: str               # OK | SOON | OVERDUE
    confidence: str           # HIGH | LOW (based on data quality)


def _median(vals: list[float]) -> float:
    return statistics.median(vals) if vals else 0.0


def build_degradation_curves(laps_raw: list[dict], stints_raw: list[dict]) -> dict[str, TyreDegradation]:
    """
    Build a degradation curve per compound from all stints in the session.
    Returns dict compound → TyreDegradation.
    """
    # Map (driver, stint_number) → compound + lap_start
    stint_map: dict[tuple, dict] = {}
    for s in stints_raw:
        key = (s["driver_number"], s["stint_number"])
        stint_map[key] = s

    # Group lap times by compound and tyre age (lap within stint)
    # compound → {tyre_age: [lap_time, ...]}
    age_times: dict[str, dict[int, list[float]]] = {}

    for lap in laps_raw:
        dur = lap.get("lap_duration")
        if dur is None or dur > 200 or dur < 55:   # skip outliers / SC laps
            continue
        if lap.get("is_pit_out_lap"):
            continue

        num = lap["driver_number"]
        lap_num = lap["lap_number"]

        # find which stint this lap belongs to
        stint = None
        for s in stints_raw:
            if s["driver_number"] != num:
                continue
            end = s.get("lap_end") or 999
            if s["lap_start"] <= lap_num <= end:
                stint = s
                break
        if stint is None:
            continue

        compound = stint.get("compound", "UNKNOWN")
        if compound == "UNKNOWN":
            continue

        tyre_age = stint.get("tyre_age_at_start", 0) + (lap_num - stint["lap_start"])
        if tyre_age < 0:
            continue

        age_times.setdefault(compound, {}).setdefault(tyre_age, []).append(dur)

    curves: dict[str, TyreDegradation] = {}

    for compound, age_map in age_times.items():
        if not age_map:
            continue

        ages = sorted(age_map.keys())
        # Need at least MIN_STINT_LAPS age buckets to fit a line
        if len(ages) < MIN_STINT_LAPS:
            continue

        medians = {age: _median(times) for age, times in age_map.items()}

        # Linear regression: lap_time = baseline + deg_rate * tyre_age
        xs = list(medians.keys())
        ys = list(medians.values())
        n = len(xs)
        sx  = sum(xs);    sy  = sum(ys)
        sxx = sum(x*x for x in xs)
        sxy = sum(x*y for x, y in zip(xs, ys))
        denom = n * sxx - sx * sx
        if denom == 0:
            continue
        deg_rate = (n * sxy - sx * sy) / denom
        baseline = (sy - deg_rate * sx) / n

        # Cliff = age where deg_rate pushes lap time CLIFF_SECONDS above baseline
        cliff_delta = CLIFF_SECONDS.get(compound, DEFAULT_CLIFF)
        if deg_rate > 0:
            cliff_lap = int(cliff_delta / deg_rate)
        else:
            cliff_lap = MAX_LIFE.get(compound, DEFAULT_MAX)

        # Cap at hard maximum
        cliff_lap = min(cliff_lap, MAX_LIFE.get(compound, DEFAULT_MAX))
        cliff_lap = max(cliff_lap, 10)   # always at least 10 laps

        curves[compound] = TyreDegradation(
            compound=compound,
            deg_rate=max(deg_rate, 0.0),
            baseline=baseline,
            cliff_lap=cliff_lap,
            data_points=sum(len(v) for v in age_map.values()),
        )

    return curves


def predict_drivers(
    state: dict,                          # driver_number → DriverState
    curves: dict[str, TyreDegradation],
    current_race_lap: int,
    total_race_laps: int,
) -> dict[int, DriverPrediction]:
    """
    For every driver in state, produce a pit stop prediction.
    """
    predictions: dict[int, DriverPrediction] = {}

    for num, ds in state.items():
        if ds.retired:
            continue
        stint = ds.current_stint
        if stint is None:
            continue

        compound = stint.compound
        age = ds.tyre_age or 0
        curve = curves.get(compound)

        if curve and curve.deg_rate > 0:
            cliff = curve.cliff_lap
            confidence = "HIGH" if curve.data_points >= 10 else "LOW"
            deg_rate = curve.deg_rate
        else:
            # Fallback: use hard cap with LOW confidence
            cliff = MAX_LIFE.get(compound, DEFAULT_MAX)
            confidence = "LOW"
            deg_rate = 0.0

        laps_remaining = max(0, cliff - age)
        laps_to_end    = total_race_laps - current_race_lap

        # Pit window: box within 3 laps either side of cliff
        pit_earliest = current_race_lap + max(0, laps_remaining - 3)
        pit_latest   = current_race_lap + laps_remaining + 2

        # Status
        if age >= cliff:
            status = "OVERDUE"
        elif laps_remaining <= 4:
            status = "SOON"
        else:
            status = "OK"

        # If no more race laps needed, no pit required
        if laps_to_end <= laps_remaining:
            status = "OK"
            laps_remaining = laps_to_end

        pit_latest   = min(pit_latest, total_race_laps)
        pit_earliest = min(pit_earliest, total_race_laps)

        predictions[num] = DriverPrediction(
            driver_number=num,
            acronym=ds.acronym,
            compound=compound,
            tyre_age=age,
            deg_rate=deg_rate,
            laps_remaining=laps_remaining,
            pit_earliest=pit_earliest,
            pit_latest=pit_latest,
            status=status,
            confidence=confidence,
        )

    return predictions
