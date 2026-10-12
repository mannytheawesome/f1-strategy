"""
Manual/local CLI entry point for the overtaking pass-rate calibration.

The actual logic lives in engine/overtake_calibration.py, which also
backs a live, automatic background job (see data/recalibrator.py) that
keeps engine/overtake_delta.py's numbers current in production without
anyone re-running this by hand. This script is kept for local
inspection/debugging -- e.g. the first real run, to sanity-check
magnitude before hardcoding a bootstrap snapshot into
engine/overtake_delta.py.

Run: python3 calibrate_overtake_delta.py
"""
import sys

sys.path.insert(0, ".")
from engine.overtake_calibration import (
    OVERTAKE_RACES_CACHE_PATH, OVERTAKE_DELTA_DATA_PATH, MIN_BUCKET_SAMPLES,
    run_incremental_calibration, _load_json,
)


def main():
    print(f"races cache: {OVERTAKE_RACES_CACHE_PATH}")
    print(f"output:      {OVERTAKE_DELTA_DATA_PATH}")
    agg = run_incremental_calibration()

    races_cache = _load_json(OVERTAKE_RACES_CACHE_PATH)
    by_circuit: dict[str, int] = {}
    for v in races_cache.values():
        if v:
            key = (v["circuit"] or "").lower()
            by_circuit[key] = by_circuit.get(key, 0) + len(v["samples"])

    print()
    print("=== per-circuit 50%-pass pace-delta threshold (s/lap) ===")
    for circuit, n in sorted(by_circuit.items(), key=lambda kv: -kv[1]):
        t = agg["by_circuit"].get(circuit)
        print(f"  {circuit:22s} n={n:5d}  "
             f"{f'threshold={t:.2f}s/lap' if t is not None else '(no clean crossing, falls back to default)'}")
    print()
    print(f"default: {agg['default']:.2f}s/lap")
    print(f"n_races={agg['n_races']}  n_samples={agg['n_samples']}")
    print(f"\nWritten to {OVERTAKE_DELTA_DATA_PATH}")


if __name__ == "__main__":
    main()
