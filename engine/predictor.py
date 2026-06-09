"""
Race Outcome Predictor.

Combines:
  1. Tyre degradation curves (from FP2/FP3, weighted > FP1)
  2. Current race pace per driver
  3. Pit stop timing and compound choice
  4. Safety car probability (from lap time spike detection)
  5. Gap to driver ahead (undercut/overcut viability)

Produces per-driver predictions:
  - Predicted finishing position
  - Optimal remaining strategy
  - Undercut window (if gap < threshold)
  - SC probability remaining in race
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import statistics

# ── Constants ────────────────────────────────────────────────────────────────

PIT_LOSS = 22.0          # seconds lost in pit lane at Monaco
UNDERCUT_WINDOW = 2.5    # gap (seconds) within which undercut is viable
SC_LAP_MULTIPLIER = 1.35 # lap time > 35% above session median → SC suspected

# Weight FP sessions: FP1 least reliable (track evolution), FP2/3 most reliable
FP_SESSION_WEIGHTS = {
    "FP1": 0.3,
    "FP2": 1.0,
    "FP3": 0.9,
}

DRY_COMPOUNDS = ["SOFT", "MEDIUM", "HARD"]


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class WeightedDegRate:
    """Degradation rate computed from multiple FP sessions, weighted by reliability."""
    compound: str
    deg_rate: float          # s/lap of tyre age
    baseline: float          # fresh tyre lap time
    data_points: int
    sessions_used: list[str]
    confidence: str          # HIGH / MEDIUM / LOW


@dataclass
class RacePace:
    """Per-driver clean race pace estimate."""
    driver_number: int
    acronym: str
    pace_median: float       # median lap time on clean laps
    pace_std: float          # consistency (lower = more consistent)
    laps_counted: int


@dataclass
class SCEvent:
    """A detected Safety Car or VSC period."""
    start_lap: int
    end_lap: int
    event_type: str          # SC | VSC | UNKNOWN


@dataclass
class DriverForecast:
    """Predicted race outcome for a single driver."""
    driver_number: int
    acronym: str
    predicted_position: int
    position_confidence: str   # HIGH / MEDIUM / LOW
    optimal_strategy: list[dict]   # list of {compound, start_lap, end_lap}
    undercut_viable: bool
    undercut_target: Optional[str]   # acronym of driver to undercut
    sc_adjusted: bool              # True if SC windows factored in
    predicted_finish_gap: float    # seconds behind predicted winner


@dataclass
class SCProbability:
    lap: int
    probability: float   # 0-1, probability of SC before end of race


# ── SC Detection ─────────────────────────────────────────────────────────────

def detect_sc_periods(laps_raw: list[dict]) -> list[SCEvent]:
    """
    Detect Safety Car / VSC periods by finding laps where the median lap time
    across all drivers spikes above the session median by SC_LAP_MULTIPLIER.
    """
    # Group lap times by lap number
    by_lap: dict[int, list[float]] = {}
    for lap in laps_raw:
        dur = lap.get("lap_duration")
        if dur and 60 < dur < 600:
            ln = lap["lap_number"]
            by_lap.setdefault(ln, []).append(dur)

    if not by_lap:
        return []

    # Session median (from laps with many drivers reporting)
    all_times = [t for times in by_lap.values() for t in times]
    session_median = statistics.median(all_times)
    threshold = session_median * SC_LAP_MULTIPLIER

    # Find SC laps
    sc_laps = sorted(
        ln for ln, times in by_lap.items()
        if len(times) >= 5 and statistics.median(times) > threshold
    )

    if not sc_laps:
        return []

    # Group consecutive laps into events
    events: list[SCEvent] = []
    start = sc_laps[0]
    prev = sc_laps[0]
    for lap in sc_laps[1:]:
        if lap > prev + 2:
            events.append(SCEvent(start_lap=start, end_lap=prev, event_type="SC"))
            start = lap
        prev = lap
    events.append(SCEvent(start_lap=start, end_lap=prev, event_type="SC"))

    return events


def sc_probability_remaining(
    sc_events_historical: list[SCEvent],
    current_lap: int,
    total_laps: int,
    circuit_key: Optional[str] = None,
) -> float:
    """
    Estimate probability of another SC before race end.

    Base rate: ~40% of races have ≥1 SC period. Adjusted by:
    - Laps remaining (more laps = more exposure)
    - Whether SC has already occurred (slight reduction if already had one)
    - Circuit type (street circuits higher, e.g. Monaco ~60%)
    """
    laps_remaining = max(0, total_laps - current_lap)
    if laps_remaining <= 0:
        return 0.0

    # Base SC rate per lap (roughly 40% per race / 60 laps = 0.67% per lap)
    base_per_lap = 0.0067

    # Street circuits have higher SC rate
    street_circuits = {"monaco", "baku", "singapore", "jeddah", "las_vegas", "miami"}
    if circuit_key and any(c in (circuit_key or "").lower() for c in street_circuits):
        base_per_lap = 0.012

    # Compound probability across remaining laps
    prob_no_sc = (1 - base_per_lap) ** laps_remaining

    # If we already had an SC, slightly lower the remaining probability
    if sc_events_historical:
        prob_no_sc = min(prob_no_sc * 1.15, 0.95)

    return round(1 - prob_no_sc, 3)


# ── Weighted deg rates from multiple FP sessions ──────────────────────────────

def build_weighted_deg_rates(
    fp_data: list[tuple[str, list[dict], list[dict]]],  # [(session_name, laps, stints), ...]
) -> dict[str, WeightedDegRate]:
    """
    Build degradation rates weighted by FP session reliability.
    fp_data: list of (session_name, laps_raw, stints_raw) tuples.
    Returns dict compound → WeightedDegRate.
    """
    # Collect (deg_rate, weight, data_points) per compound
    compound_samples: dict[str, list[tuple[float, float, int]]] = {}

    for session_name, laps_raw, stints_raw in fp_data:
        weight = FP_SESSION_WEIGHTS.get(session_name, 0.5)

        # Build stint map
        stint_map: dict[tuple, dict] = {}
        for s in stints_raw:
            end = s.get("lap_end") or 9999
            for ln in range(s["lap_start"], end + 1):
                stint_map[(s["driver_number"], ln)] = s

        # Group by compound
        compound_laps: dict[str, list[tuple[float, float]]] = {}
        for lap in laps_raw:
            dur = lap.get("lap_duration")
            if not dur or dur > 200 or dur < 60 or lap.get("is_pit_out_lap"):
                continue
            s = stint_map.get((lap["driver_number"], lap["lap_number"]))
            if not s:
                continue
            compound = s.get("compound", "UNKNOWN")
            if compound not in DRY_COMPOUNDS:
                continue
            age_start = s.get("tyre_age_at_start", 0)
            true_age = float(age_start + (lap["lap_number"] - s["lap_start"]))
            compound_laps.setdefault(compound, []).append((true_age, dur))

        # Fit a deg rate per compound for this session
        for compound, data in compound_laps.items():
            if len(data) < 5:
                continue
            xs = [d[0] for d in data]
            ys = [d[1] for d in data]
            n = len(xs)
            mx, my = sum(xs) / n, sum(ys) / n
            denom = sum((x - mx) ** 2 for x in xs)
            if denom == 0:
                continue
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
            intercept = my - slope * mx
            compound_samples.setdefault(compound, []).append(
                (slope, intercept, weight, n, session_name)
            )

    # Weighted average across sessions
    result: dict[str, WeightedDegRate] = {}
    for compound, samples in compound_samples.items():
        total_weight = sum(s[2] for s in samples)
        if total_weight == 0:
            continue
        w_deg = sum(s[0] * s[2] for s in samples) / total_weight
        w_base = sum(s[1] * s[2] for s in samples) / total_weight
        total_pts = sum(s[3] for s in samples)
        sessions = [s[4] for s in samples]

        if total_pts >= 20:
            confidence = "HIGH"
        elif total_pts >= 8:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        result[compound] = WeightedDegRate(
            compound=compound,
            deg_rate=max(w_deg, 0.0),
            baseline=w_base,
            data_points=total_pts,
            sessions_used=sessions,
            confidence=confidence,
        )

    return result


# ── Race pace estimation ──────────────────────────────────────────────────────

def estimate_race_pace(
    laps_raw: list[dict],
    sc_events: list[SCEvent],
    drivers_raw: dict[int, dict],
) -> dict[int, RacePace]:
    """
    Compute per-driver clean race pace, excluding SC laps and outliers.
    """
    sc_lap_set: set[int] = set()
    for ev in sc_events:
        for ln in range(ev.start_lap, ev.end_lap + 2):  # +1 lap buffer on restart
            sc_lap_set.add(ln)

    by_driver: dict[int, list[float]] = {}
    for lap in laps_raw:
        dur = lap.get("lap_duration")
        if not dur or lap.get("is_pit_out_lap") or lap["lap_number"] in sc_lap_set:
            continue
        if dur > 200 or dur < 60:
            continue
        by_driver.setdefault(lap["driver_number"], []).append(dur)

    result: dict[int, RacePace] = {}
    for num, times in by_driver.items():
        if len(times) < 3:
            continue
        # Remove outliers (top/bottom 10%)
        times_sorted = sorted(times)
        trim = max(1, len(times_sorted) // 10)
        clean = times_sorted[trim:-trim] if len(times_sorted) > 2 * trim else times_sorted
        d = drivers_raw.get(num, {})
        result[num] = RacePace(
            driver_number=num,
            acronym=d.get("name_acronym", str(num)),
            pace_median=statistics.median(clean),
            pace_std=statistics.stdev(clean) if len(clean) > 1 else 0.0,
            laps_counted=len(clean),
        )

    return result


# ── Undercut/overcut detection ────────────────────────────────────────────────

def find_undercut_opportunities(
    state_drivers: list[dict],   # serialised driver list from /api/live, sorted by position
    deg_rates: dict[str, WeightedDegRate],
) -> list[dict]:
    """
    For each driver, check if the driver ahead is within undercut window
    and their tyre is degrading faster.
    Returns list of undercut opportunity dicts.
    """
    opportunities = []

    for i, driver in enumerate(state_drivers):
        if i == 0:
            continue  # leader has no driver ahead
        driver_ahead = state_drivers[i - 1]

        interval = driver.get("interval")
        if interval is None or not isinstance(interval, (int, float)):
            continue
        if abs(interval) > UNDERCUT_WINDOW:
            continue

        # Check if driver ahead's tyre is older / degrading faster
        compound = driver.get("compound", "SOFT")
        compound_ahead = driver_ahead.get("compound", "SOFT")
        age = driver.get("tyre_age", 0) or 0
        age_ahead = driver_ahead.get("tyre_age", 0) or 0

        deg = deg_rates.get(compound)
        deg_ahead = deg_rates.get(compound_ahead)

        deg_rate = deg.deg_rate if deg else 0
        deg_rate_ahead = deg_ahead.deg_rate if deg_ahead else 0

        # Undercut is viable if: gap < UNDERCUT_WINDOW and driver ahead degrading faster
        undercut_advantage = (age_ahead * deg_rate_ahead) - (age * deg_rate)
        if undercut_advantage > 0.5 or (abs(interval) < 1.0 and age_ahead > age + 5):
            opportunities.append({
                "driver": driver.get("acronym"),
                "driver_number": driver.get("driver_number"),
                "target": driver_ahead.get("acronym"),
                "interval": round(interval, 3),
                "tyre_advantage_s": round(undercut_advantage, 2),
                "recommendation": "PIT NOW — undercut window open",
            })

    return opportunities


# ── Position prediction ───────────────────────────────────────────────────────

def predict_finishing_positions(
    state_drivers: list[dict],
    deg_rates: dict[str, WeightedDegRate],
    race_paces: dict[int, RacePace],
    current_lap: int,
    total_laps: int,
    sc_events: list[SCEvent],
) -> list[DriverForecast]:
    """
    Predict finishing positions based on:
    - Current gap to leader
    - Remaining pace advantage/disadvantage
    - Tyre deg on current compound
    - Expected pit stop(s) remaining
    """
    remaining = total_laps - current_lap
    if remaining <= 0:
        return []

    forecasts = []

    # Compute expected time to finish for each driver
    scores: list[tuple[float, dict]] = []

    for driver in state_drivers:
        if driver.get("retired"):
            continue

        num = driver["driver_number"]
        gap = driver.get("gap_to_leader") or 0.0
        compound = driver.get("compound", "SOFT")
        age = driver.get("tyre_age", 0) or 0

        # Base: current gap
        time_cost = gap if isinstance(gap, (int, float)) else 0.0

        # Add pace delta vs median field
        pace = race_paces.get(num)
        field_median = statistics.median(
            [p.pace_median for p in race_paces.values()]
        ) if race_paces else 82.0
        pace_delta = (pace.pace_median - field_median) if pace else 0.0
        time_cost += pace_delta * remaining

        # Add remaining deg cost
        deg = deg_rates.get(compound)
        if deg and deg.deg_rate > 0:
            # Deg accumulated from now to expected pit / end
            deg_cost = deg.deg_rate * min(remaining, max(0, deg.deg_rate > 0 and
                                          int(1.5 / deg.deg_rate) - age or remaining))
            time_cost += deg_cost

        scores.append((time_cost, driver))

    scores.sort(key=lambda x: x[0])

    winner_cost = scores[0][0] if scores else 0.0

    for predicted_pos, (cost, driver) in enumerate(scores, 1):
        num = driver["driver_number"]
        pace = race_paces.get(num)

        if pace and pace.laps_counted >= 10:
            conf = "HIGH"
        elif pace and pace.laps_counted >= 5:
            conf = "MEDIUM"
        else:
            conf = "LOW"

        forecasts.append(DriverForecast(
            driver_number=num,
            acronym=driver.get("acronym", str(num)),
            predicted_position=predicted_pos,
            position_confidence=conf,
            optimal_strategy=[],   # populated by strategy engine
            undercut_viable=False,
            undercut_target=None,
            sc_adjusted=len(sc_events) > 0,
            predicted_finish_gap=round(cost - winner_cost, 2),
        ))

    return forecasts


def to_dict(forecast: DriverForecast) -> dict:
    return {
        "driver_number": forecast.driver_number,
        "acronym": forecast.acronym,
        "predicted_position": forecast.predicted_position,
        "position_confidence": forecast.position_confidence,
        "undercut_viable": forecast.undercut_viable,
        "undercut_target": forecast.undercut_target,
        "sc_adjusted": forecast.sc_adjusted,
        "predicted_finish_gap": forecast.predicted_finish_gap,
    }
