"""
Per-circuit calibration for the MEDIUM->HARD one-stop undercut/track-
position early-pit shift (see engine.prerace._shift_medium_start_earlier).

backtest_pit_timing.py found a real, consistent bias -- real MEDIUM->HARD
one-stop finishers pit earlier than optimize_strategy's pure-pace answer,
median 7 laps across 2026's 4 clean races -- and a flat MEDIUM_START_
UNDERCUT_SHIFT_LAPS=6 was shipped as a stopgap. But the measured bias
varied a lot by circuit within just that 4-race sample (Australia ~12
laps, Spa ~4), and the existing _undercut_power signal didn't explain the
variance. This script asks the obvious follow-up: does a circuit's own
HISTORY predict its own future bias better than one global number does?

Method: for every circuit, gather every completed race there across
2023-2026, and for each one compute (a) our own model's predicted
MEDIUM->HARD one-stop pit lap from FP-only data (the exact same
degradation-curve + optimize_strategy path build_prerace_data uses, but
skipping everything else in that pipeline -- team pace tables, Monte
Carlo projection, narrative generation -- none of which this needs) and
(b) every REAL one-stop MEDIUM->HARD finisher's actual pit lap that race
(excluding lap < 8, a Lap-1-incident filter -- see backtest_pit_timing.py
for why). The per-circuit median of (real - predicted) across all years
becomes that circuit's calibrated shift; a circuit with too few real
samples (< 3) falls back to the global default.

Run: python3 calibrate_undercut_shift.py
Results cached to cache/undercut_shift_results.json (per-race, so an
interrupted run resumes) and cache/undercut_shift_by_circuit.json (final
aggregate -- what gets hand-copied into engine/undercut_shift.py).
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, ".")
from data.live import _get, get_laps, get_stints, HIST_TTL
from engine.predictor import build_deg_curves, optimize_strategy, DRY
from engine.pit_loss import pit_loss_for
from engine.prerace import _prerace_sources, CIRCUIT_LAPS, DEFAULT_LAPS

RESULTS_FILE = "cache/undercut_shift_results.json"
CIRCUIT_FILE = "cache/undercut_shift_by_circuit.json"
MAX_RETRIES = 5
RETRY_DELAY_S = 8
API_PACE_S = 0.15   # small delay between calls -- be a good citizen given
                     # how often 429s have shown up this session


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
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                print(f"  {r['name']} {r['year']}: gave up ({e})")
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
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                print(f"  {r['name']} {r['year']}: gave up on real stints ({e})")
                return None
            time.sleep(RETRY_DELAY_S)

    matches = [{"real_pit_lap": lap, "predicted_pit_lap": predicted_lap,
               "error_laps": lap - predicted_lap} for lap in (real_laps or [])]
    return {"circuit": r["circuit"], "name": r["name"], "year": r["year"], "matches": matches}


def _load(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save(path: str, data: dict):
    os.makedirs("cache", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=1)


def main():
    cache = _load(RESULTS_FILE)
    races = []
    for year in (2023, 2024, 2025, 2026):
        races.extend(_completed_races(year))
    print(f"{len(races)} completed races found across 2023-2026")

    for r in races:
        key = f"{r['meeting_key']}"
        if key in cache and cache[key] is not None:
            continue
        print(f"evaluating {r['name']} {r['year']} ({r['circuit']}, meeting {r['meeting_key']})...")
        result = evaluate_one(r)
        cache[key] = result
        _save(RESULTS_FILE, cache)
        if result and result["matches"]:
            for m in result["matches"]:
                print(f"    real={m['real_pit_lap']:2d}  predicted={m['predicted_pit_lap']:2d}  "
                      f"error={m['error_laps']:+d}")

    by_circuit: dict[str, list[int]] = {}
    for v in cache.values():
        if v:
            for m in v["matches"]:
                by_circuit.setdefault((v["circuit"] or "").lower(), []).append(m["error_laps"])

    print()
    print("=== per-circuit calibration ===")
    out = {}
    all_errs = []
    for circuit, errs in sorted(by_circuit.items(), key=lambda kv: -len(kv[1])):
        all_errs.extend(errs)
        med = statistics.median(errs)
        n = len(errs)
        trusted = n >= 3
        print(f"  {circuit:22s} n={n:3d}  median={med:+.1f}  "
              f"{'(used)' if trusted else '(too few, falls back to default)'}")
        if trusted:
            out[circuit] = round(-med, 1)   # shift is positive laps EARLIER
    global_default = round(-statistics.median(all_errs), 1) if all_errs else 6.0
    print()
    print(f"global default (fallback): {global_default}")
    _save(CIRCUIT_FILE, {"by_circuit": out, "default": global_default,
                         "n_races": sum(1 for v in cache.values() if v and v["matches"]),
                         "n_matches": len(all_errs)})
    print(f"\nWritten to {CIRCUIT_FILE}")


if __name__ == "__main__":
    main()
