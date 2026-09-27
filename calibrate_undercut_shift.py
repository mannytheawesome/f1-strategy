"""
Manual/local CLI entry point for the undercut-shift calibration.

The actual logic now lives in engine/undercut_calibration.py, which also
backs a live, automatic background job (see data/recalibrator.py) that
keeps engine/undercut_shift.py's numbers current in production without
anyone re-running this by hand. This script is kept for local
inspection/debugging -- e.g. checking the calibration against a
non-default cache location, or re-running it standalone against
production's persisted cache after copying it down.

Run: python3 calibrate_undercut_shift.py
"""
import sys

sys.path.insert(0, ".")
from engine.undercut_calibration import (
    RACES_CACHE_PATH, OUTPUT_PATH, MIN_SAMPLES, run_incremental_calibration,
    _load_json,
)


def main():
    print(f"races cache: {RACES_CACHE_PATH}")
    print(f"output:      {OUTPUT_PATH}")
    aggregate = run_incremental_calibration()

    races_cache = _load_json(RACES_CACHE_PATH)
    by_circuit: dict[str, list[int]] = {}
    for v in races_cache.values():
        if v:
            for m in v["matches"]:
                by_circuit.setdefault((v["circuit"] or "").lower(), []).append(m["error_laps"])

    print()
    print("=== per-circuit calibration ===")
    for circuit, errs in sorted(by_circuit.items(), key=lambda kv: -len(kv[1])):
        n = len(errs)
        trusted = n >= MIN_SAMPLES
        shift = aggregate["by_circuit"].get(circuit)
        print(f"  {circuit:22s} n={n:3d}  "
              f"{f'shift={shift:+.1f}' if trusted else '(too few, falls back to default)'}")
    print()
    print(f"default: {aggregate['default']}")
    print(f"\nWritten to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
