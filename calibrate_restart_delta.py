"""
Manual/local CLI entry point for the cold-tyre restart-penalty calibration.

The actual logic lives in engine/restart_calibration.py, which also backs a
live, automatic background job (see data/recalibrator.py) that keeps
engine/restart_delta.py's numbers current in production without anyone
re-running this by hand. This script is kept for local inspection/
debugging -- e.g. the first real run, to sanity-check sign/magnitude
before hardcoding a bootstrap snapshot into engine/restart_delta.py.

Run: python3 calibrate_restart_delta.py
"""
import sys

sys.path.insert(0, ".")
from engine.restart_calibration import (
    RESTART_RACES_CACHE_PATH, RESTART_DELTA_DATA_PATH, MIN_SAMPLES,
    run_incremental_calibration, _load_json,
)


def main():
    print(f"races cache: {RESTART_RACES_CACHE_PATH}")
    print(f"output:      {RESTART_DELTA_DATA_PATH}")
    agg = run_incremental_calibration()

    races_cache = _load_json(RESTART_RACES_CACHE_PATH)
    by_compound: dict[str, list[float]] = {}
    for v in races_cache.values():
        if v:
            for s in v["samples"]:
                by_compound.setdefault(s["compound"], []).append(s["residual_s"])

    print()
    print("=== per-compound restart-lap residual (seconds vs field median) ===")
    for compound, residuals in sorted(by_compound.items(), key=lambda kv: -len(kv[1])):
        n = len(residuals)
        trusted = n >= MIN_SAMPLES
        delta = agg["by_compound"].get(compound)
        print(f"  {compound:12s} n={n:4d}  "
              f"{f'delta={delta:+.2f}s' if trusted else '(too few, falls back to 0.0)'}")
    print()
    print(f"n_races={agg['n_races']}  n_samples={agg['n_samples']}")
    print(f"\nWritten to {RESTART_DELTA_DATA_PATH}")


if __name__ == "__main__":
    main()
