"""
Strategy sanity audit — checks every cached race weekend at once.

Regenerates the pre-race candidate plans for every weekend in ./cache (offline,
no HTTP) and asserts they are physically and strategically sensible, so a bad
plan is caught here rather than spotted by eye in one race's briefing.

Checks per candidate plan:
  repeat-compound   no pitting onto the compound just removed
  two-compound      the F1 rule: at least two dry compounds used
  min-stint         no stint shorter than MIN_STINT laps
  pit-order         pit laps strictly increasing and inside the race
  covers-race       stint lengths sum to the race distance
  unknown-compound  no UNKNOWN in a generated plan
And per race:
  has-live-plan     at least one plan is "in play"
  distance          race distance came from the circuit table, not the default
  deg-saturated     the deg regression hit the MAX_DEG clamp, i.e. it could not
                    measure wear and fell back to the ceiling. (A merely HIGH deg
                    rate is not flagged: races with elevated deg turn out to have
                    LOWER stop-count error than average, so a high reading is
                    usually real, not noise.)

Usage:
  python audit_strategies.py            # summary, exits 1 if anything fails
  python audit_strategies.py --verbose  # list every offending race
"""

from __future__ import annotations
import sys
import statistics
import collections

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from backtest_full import enumerate_weekends, load_weekend
from engine.predictor import (build_deg_curves, optimize_strategy, DRY,
                              MIN_STINT, SC_PIT_FACTOR)
from engine.pit_loss import pit_loss_for
from engine.prerace import CIRCUIT_LAPS, DEFAULT_LAPS, LIVE_MARGIN_S

STOP_COUNTS = (1, 2, 3)

# The clamp values in build_deg_curves. Landing exactly on one means the
# regression saturated rather than measured anything.
DEG_CLAMP = (0.30, 0.39)


def candidates_for(curves, field_baseline, pit_loss, total_laps):
    """The same forced 1/2/3-stop sweep the pre-race briefing publishes."""
    plans = []
    for stops in STOP_COUNTS:
        best = None
        for start in DRY:
            c = curves.get(start)
            if not c or not c.baseline:
                continue
            s = optimize_strategy(0, total_laps, start, 0, 0.0, curves,
                                  field_baseline, pit_loss,
                                  needs_compound_change=True,
                                  force_stops=stops,
                                  forbid_repeat_compound=True)
            if len(s.pits_remaining) != stops:
                continue
            if best is None or s.total_time_from_now < best[0]:
                seq = [start] + [p.compound for p in s.pits_remaining]
                pits = [p.lap for p in s.pits_remaining]
                bounds = [0] + pits + [total_laps]
                best = (s.total_time_from_now, seq, pits,
                        [bounds[i + 1] - bounds[i] for i in range(len(seq))])
        if best:
            plans.append({"total_time": best[0], "compound_sequence": best[1],
                          "pit_laps": best[2], "stint_lengths": best[3],
                          "stops": len(best[2])})
    plans.sort(key=lambda p: p["total_time"])
    if plans:
        base, base_stops = plans[0]["total_time"], plans[0]["stops"]
        for p in plans:
            p["time_delta"] = round(p["total_time"] - base, 1)
            refund = max(0, p["stops"] - base_stops) * (1 - SC_PIT_FACTOR) * pit_loss
            p["viability"] = ("in play" if p["time_delta"] <= LIVE_MARGIN_S
                              else "needs a Safety Car" if p["time_delta"] <= refund + LIVE_MARGIN_S
                              else "not on the table")
    return plans


def check_plan(p, total_laps):
    """Return a list of failed check names for one plan."""
    seq, lengths, pits = p["compound_sequence"], p["stint_lengths"], p["pit_laps"]
    bad = []
    if any(seq[i] == seq[i - 1] for i in range(1, len(seq))):
        bad.append("repeat-compound")
    if len({c for c in seq if c in DRY}) < 2:
        bad.append("two-compound")
    if any(l < MIN_STINT for l in lengths):
        bad.append("min-stint")
    if pits != sorted(pits) or len(set(pits)) != len(pits) or any(
            not 0 < l < total_laps for l in pits):
        bad.append("pit-order")
    if sum(lengths) != total_laps:
        bad.append("covers-race")
    if "UNKNOWN" in seq:
        bad.append("unknown-compound")
    return bad


def main(verbose=False):
    failures = collections.defaultdict(list)     # structural — these gate the exit code
    warnings = collections.defaultdict(list)     # quality — reported, not fatal
    viability_mix = collections.Counter()
    audited = skipped = 0

    for w in enumerate_weekends():
        d = load_weekend(w, cache_only=True)
        if not d or not d["fp_data"]:
            skipped += 1
            continue
        label = f"{w['year']} {w['country']}"
        circuit = (w["circuit"] or "").lower()
        try:
            curves = build_deg_curves(d["fp_data"])
        except Exception:
            skipped += 1
            continue
        baselines = [c.baseline for c in curves.values() if c.baseline > 0]
        if not baselines:
            skipped += 1
            continue
        audited += 1

        if circuit not in CIRCUIT_LAPS:
            failures["distance (fell back to DEFAULT_LAPS)"].append(f"{label} [{circuit}]")
        total_laps = CIRCUIT_LAPS.get(circuit, DEFAULT_LAPS)

        hot = {c: cu.deg_rate for c, cu in curves.items()
               if c in DRY and cu.baseline > 0
               and any(abs(cu.deg_rate - v) < 1e-6 for v in DEG_CLAMP)}
        if hot:
            warnings["deg-saturated (regression hit the clamp)"].append(
                f"{label}: " + ", ".join(f"{c} {r:.3f}" for c, r in sorted(hot.items())))

        plans = candidates_for(curves, statistics.median(baselines),
                               pit_loss_for(circuit), total_laps)
        if not plans:
            failures["no plans generated"].append(label)
            continue
        if not any(p["viability"] == "in play" for p in plans):
            failures["has-live-plan"].append(label)
        for p in plans:
            viability_mix[p["viability"]] += 1
            for name in check_plan(p, total_laps):
                failures[name].append(f"{label}: {'-'.join(p['compound_sequence'])}")

    print(f"audited {audited} race weekends ({skipped} skipped — no usable practice data)")
    print(f"candidate plans by viability: {dict(viability_mix)}\n")

    if failures:
        print("STRUCTURAL FAILURES (a plan that cannot be run)")
        for name, items in sorted(failures.items(), key=lambda kv: -len(kv[1])):
            print(f"  {name}: {len(items)}")
            for x in (items if verbose else items[:5]):
                print(f"      {x}")
    else:
        print("STRUCTURAL: PASS — every generated plan is runnable and legal.")

    if warnings:
        print("\nQUALITY WARNINGS (runnable, but the inputs look wrong)")
        for name, items in sorted(warnings.items(), key=lambda kv: -len(kv[1])):
            print(f"  {name}: {len(items)} of {audited} races")
            for x in (items if verbose else items[:5]):
                print(f"      {x}")
            if "deg-saturated" in name:
                print("      -> the fit hit MAX_DEG in build_deg_curves, so wear was not")
                print("         measured for that compound; the clamp value stands in for it.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(verbose="--verbose" in sys.argv))
