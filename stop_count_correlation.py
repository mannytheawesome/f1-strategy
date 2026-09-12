"""
Real-data check behind engine.prerace._track_position_cost's POSITION_RISK_SCALE:
median real stop counts per circuit, dry races only, compared against
track_position_weight.

Built 2026-09-12 investigating a user-reported Monaco strategy bug (the
"Expected Pit Stop Strategies" table's pace-only top pick was a 2-stop,
when real Monaco strategists are famously conservative). Answers: does a
circuit's existing track_position_weight (0.85 street / 0.50 normal,
already backtest-calibrated for the race-outcome projection) actually
predict how many stops real teams choose?

Uses only the cached session lists (cache/sessions_year-*.json) for the
race-session lookup to avoid re-fetching /sessions per meeting (that was
the first version of this script -- rate-limited immediately). Per-race
weather and stint data still hits the live API (or its in-memory cache),
so a full run costs ~96 requests; expect a handful of 429s on a cold
cache, which are just skipped.

Run: python3 stop_count_correlation.py
"""
import json
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, ".")
from data.live import get_stints, get_weather_summary
from engine.circuits import is_street_circuit, track_position_weight

MIN_LAPS_TO_COUNT = 30   # exclude early retirements from a driver's stop count
MIN_DRIVERS_FOR_MEDIAN = 5   # skip a race if too few clean (non-wet, non-DNF) drivers remain


def _load_cached_race_sessions() -> list[dict]:
    sessions = []
    for yr in (2023, 2024, 2025, 2026):
        path = f"cache/sessions_year-{yr}.json"
        if os.path.exists(path):
            with open(path) as f:
                sessions.extend(json.load(f))
    return [s for s in sessions if s.get("session_type") == "Race"
            and "sprint" not in s.get("session_name", "").lower()]


def real_stop_counts_by_circuit() -> dict[str, list[float]]:
    """{circuit_short_name.lower(): [median_stop_count_per_race, ...]}"""
    results: dict[str, list[float]] = defaultdict(list)
    for race in _load_cached_race_sessions():
        circuit = (race.get("circuit_short_name") or "").lower()
        if not circuit:
            continue
        try:
            weather = get_weather_summary(race["session_key"], 999999)
        except Exception:
            continue
        if weather.get("rainfall"):
            continue
        try:
            stints = get_stints(race["session_key"], 999999)
        except Exception:
            continue
        by_driver = defaultdict(list)
        for st in stints:
            by_driver[st["driver_number"]].append(st)
        stop_counts = []
        for num, sts in by_driver.items():
            compounds = {s.get("compound") for s in sts}
            if "INTERMEDIATE" in compounds or "WET" in compounds:
                continue
            laps_run = sum((s.get("lap_end") or 0) - (s.get("lap_start") or 0) + 1 for s in sts)
            if laps_run < MIN_LAPS_TO_COUNT:
                continue
            stop_counts.append(len(sts) - 1)
        if len(stop_counts) < MIN_DRIVERS_FOR_MEDIAN:
            continue
        results[circuit].append(statistics.median(stop_counts))
    return dict(results)


def main():
    results = real_stop_counts_by_circuit()
    rows = []
    for circuit, medians in results.items():
        rows.append((track_position_weight(circuit), is_street_circuit(circuit),
                     circuit, statistics.mean(medians), len(medians)))
    rows.sort(key=lambda r: -r[0])

    print(f"{'circuit':<22} {'tpw':>5} {'street':>7} {'avg_real_stops':>15} {'n_races':>8}")
    for tpw, street, circuit, avg_stops, n in rows:
        print(f"{circuit:<22} {tpw:>5.2f} {str(street):>7} {avg_stops:>15.2f} {n:>8}")

    street_avgs = [r[3] for r in rows if r[1]]
    normal_avgs = [r[3] for r in rows if not r[1]]
    if street_avgs and normal_avgs:
        print()
        print(f"street mean of per-circuit averages: {statistics.mean(street_avgs):.2f}")
        print(f"normal mean of per-circuit averages: {statistics.mean(normal_avgs):.2f}")


if __name__ == "__main__":
    main()
