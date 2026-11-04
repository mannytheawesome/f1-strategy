"""
Offline sweep: is Mexico City 2026's FP-vs-race degradation gap (FP running
predicted Soft/Medium wear roughly 2x worse than the actual race showed)
a one-off, or does it generalise across circuits?

Uses backtest_full.py's existing disk cache (./cache/*.json, 2023-2026,
cache_only -- never touches the network) and engine.predictor.build_deg_curves'
own FP_WEIGHTS["RACE"]=3.0 support to compute, for every cached race that has
both FP and race data: the FP-only deg_rate vs the FP+race deg_rate for each
compound that got a genuine STRICT long-run sample in the FP-only pass (not
one of the function's own backfill/ratio-estimated values -- comparing an
estimate against a measurement would conflate two different things).

Run: python3 sweep_degradation_shrink.py
"""
import sys
import statistics
from collections import defaultdict

sys.path.insert(0, ".")

from backtest_full import enumerate_weekends, load_weekend
from engine.predictor import (
    build_deg_curves, _stint_deg_samples, DEG_LONGRUN, FP_WEIGHTS, DRY,
)


def _strictly_measured_compounds(fp_data: list[tuple]) -> set[str]:
    """Compounds with a genuine long-run sample in the FP-only pass --
    mirrors build_deg_curves' own `strict` dict exactly."""
    strict: dict[str, list] = {}
    for name, laps_raw, stints_raw in fp_data:
        w = FP_WEIGHTS.get(name, 0.5)
        for c, rows in _stint_deg_samples(laps_raw, stints_raw, w, name).items():
            strict.setdefault(c, []).extend(rows)
    return {c for c, rows in strict.items() if rows}


def main():
    weekends = enumerate_weekends()
    print(f"{len(weekends)} weekends enumerated (2023-2026)")

    by_compound: dict[str, list[float]] = defaultdict(list)
    by_circuit_compound: dict[tuple[str, str], list[float]] = defaultdict(list)
    races_used = 0
    races_skipped_no_cache = 0
    races_skipped_no_measured_compound = 0

    for w in weekends:
        data = load_weekend(w, cache_only=True)
        if data is None or not data["fp_data"]:
            races_skipped_no_cache += 1
            continue

        fp_data = data["fp_data"]
        race_laps, race_stints = data["race_laps"], data["race_stints"]
        if not race_laps or not race_stints:
            races_skipped_no_cache += 1
            continue

        measured = _strictly_measured_compounds(fp_data) & set(DRY)
        if not measured:
            races_skipped_no_measured_compound += 1
            continue

        curves_fp_only = build_deg_curves(fp_data)
        curves_with_race = build_deg_curves(fp_data + [("RACE", race_laps, race_stints)])

        got_one = False
        for c in measured:
            fp_cur = curves_fp_only.get(c)
            race_cur = curves_with_race.get(c)
            if not fp_cur or not race_cur or fp_cur.deg_rate <= 0:
                continue
            # The race curve must itself have gained real race-lap evidence
            # for this compound, not just inherited the FP-only number
            # untouched (e.g. nobody ran it in the race -- Hard at Mexico).
            if "RACE" not in race_cur.sessions:
                continue
            ratio = race_cur.deg_rate / fp_cur.deg_rate
            by_compound[c].append(ratio)
            by_circuit_compound[(w["circuit"], c)].append(ratio)
            got_one = True
        races_used += got_one
        if not got_one:
            races_skipped_no_measured_compound += 1

    print(f"races used: {races_used}")
    print(f"races skipped (no cached FP+race data): {races_skipped_no_cache}")
    print(f"races skipped (no compound both measured pre-race AND raced): "
          f"{races_skipped_no_measured_compound}")

    print("\n=== per-compound FP-vs-race deg_rate ratio (race/FP, <1 = FP overstated wear) ===")
    for c in DRY:
        ratios = by_compound.get(c, [])
        if not ratios:
            print(f"  {c:>6}: no samples")
            continue
        print(f"  {c:>6}: n={len(ratios):3d}  median={statistics.median(ratios):.3f}  "
              f"mean={statistics.mean(ratios):.3f}  "
              f"stdev={statistics.stdev(ratios) if len(ratios) > 1 else 0:.3f}  "
              f"min={min(ratios):.3f}  max={max(ratios):.3f}")

    print("\n=== per-circuit median ratio (n>=3 only, unpooled) ===")
    by_circuit: dict[str, list[tuple[str, float, int]]] = defaultdict(list)
    for (circuit, c), ratios in by_circuit_compound.items():
        if len(ratios) >= 3:
            by_circuit[circuit].append((c, statistics.median(ratios), len(ratios)))
    for circuit in sorted(by_circuit):
        entries = ", ".join(f"{c}={med:.2f}(n={n})" for c, med, n in sorted(by_circuit[circuit]))
        print(f"  {circuit:>20}: {entries}")

    # Partial pooling: blend each circuit's own median toward the global
    # default, weighted by how much real data that circuit actually has.
    # weight = min(1, n/8) reuses build_deg_curves' own MEDIUM-confidence
    # threshold (pts>=8) as the point a measurement starts being trusted
    # mostly on its own -- not a new invented constant. n=1-2 circuits
    # barely move off the global default; a circuit with 8+ real samples
    # would be trusted almost entirely on its own (none have that many
    # yet -- every circuit here caps out at n=3-4).
    global_median = {c: statistics.median(by_compound[c]) for c in by_compound}
    print("\n=== partial-pooled per-circuit-compound shrink (ready to paste) ===")
    pooled: dict[str, dict[str, float]] = defaultdict(dict)
    for (circuit, c), ratios in sorted(by_circuit_compound.items()):
        n = len(ratios)
        weight = min(1.0, n / 8)
        blended = weight * statistics.median(ratios) + (1 - weight) * global_median[c]
        pooled[circuit][c] = round(blended, 3)
    for circuit in sorted(pooled):
        entries = ", ".join(f'"{c}": {v}' for c, v in sorted(pooled[circuit].items()))
        n_by_c = {c: len(by_circuit_compound[(circuit, c)]) for c in pooled[circuit]}
        n_str = ", ".join(f"{c} n={n}" for c, n in sorted(n_by_c.items()))
        print(f'    "{circuit.lower()}": {{{entries}}},  # {n_str}')


if __name__ == "__main__":
    main()
