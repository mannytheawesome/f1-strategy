"""
Per-circuit calibration for the overtaking pass-rate threshold (applied
in engine.prerace via _overtaking_cost).

_overtaking_cost previously derived "the pace edge needed to pass" purely
analytically, from the sim's track-position blend weight -- its own
docstring admitted this outright: "a model quantity, not an empirical DRS
measurement." User asked directly how much of an independent F1
strategist's published methodology we could adopt; her own pass-rate
tables (real counts: "225 instances within 1.2s, 28 passes by next lap,"
a measured 50%-pass threshold per circuit) were the sharpest, most
directly fixable gap -- we had the same underlying data already (lap
times + gap-to-car-ahead) and had simply never measured it.

Method (engine/overtake_calibration.py, offline/live): for every green-
flag lap across 2023-2026, for every pair of cars adjacent in the running
order with a gap under GAP_THRESHOLD_S, compute the pace delta (leading
car's lap time minus the following car's -- positive means the following
car was faster that lap) and whether their order flips by the start of
the next lap. Bucket by pace delta, find the 50%-pass crossover per
circuit. Verified directly against real cached data before trusting it:
the pooled curve is clean and monotonic in the 0-3s/lap range (sample
sizes in the thousands), and the crossover lands at ~1.1-1.2s/lap --
closely matching the strategist's own reported Budapest (1.09) and
Zandvoort (1.14) figures, an independent cross-check neither number was
fitted to produce.

OVERTAKE_PASS_THRESHOLD_S below is the real measured snapshot from the
first run of calibrate_overtake_delta.py (2026-10-12, 2023-2026 cache,
68 races, 28,118 close-pair samples) -- not a guess. Worth being honest
about what it does and doesn't show: most true street/desert circuits
(Baku, Singapore, Monte Carlo, Las Vegas, Jeddah) found NO clean 50%
crossing within the sampled pace-delta range, despite 800-1400+ samples
each -- not a data-scarcity gap, but a plausible real finding: those
circuits may genuinely never reliably convert a close gap into a pass
within a single lap, however large the pace advantage, since a real pass
there usually takes several laps of DRS-train following rather than one
clean move. They fall back to DEFAULT below rather than a fabricated
number, which is the correct behaviour given what the data actually
shows, not a failure of the calibration. Hungaroring's 2.50s/lap is the
one number worth treating with more caution than the rest -- notably
higher than every other circuit, plausible for a famously hard-to-pass
track but a single crossing off one bucket boundary, not corroborated by
multiple consistent buckets the way most of the others are. Re-check it
once more races accumulate rather than assuming it's precise.

Only then hardcode a bootstrap snapshot here -- same stance as
undercut_shift.py and restart_delta.py.
"""

# circuit_short_name (lowercased) -> measured pace-delta (s/lap) a
# trailing car needs over a leading car, at a gap under
# engine.overtake_calibration.GAP_THRESHOLD_S, for a 50% chance of
# completing the pass by the next lap. Trailing comment is the real
# sample size behind each figure, as of this snapshot (2026-10-12).
OVERTAKE_PASS_THRESHOLD_S: dict[str, float] = {
    "spielberg":          0.87,   # n=1168
    "monza":              0.89,   # n=1267
    "shanghai":           0.98,   # n=1233
    "miami":              1.01,   # n=1467
    "melbourne":          1.13,   # n=1326
    "spa-francorchamps":  1.12,   # n=1042
    "zandvoort":          1.18,   # n=1376
    "yas marina circuit": 1.19,   # n=1346
    "silverstone":        1.20,   # n=1123
    "catalunya":          1.27,   # n=1157
    "suzuka":             1.28,   # n=1639
    "hungaroring":        2.50,   # n=1149 -- see docstring caveat above
}

# Pooled field-wide median across every circuit's real samples -- a
# better blind guess than a hand-picked constant for a circuit with no
# track record yet (a brand new venue, or one not yet calibrated) *and*
# the circuits above that found no clean crossing of their own (see
# docstring: most true street/desert circuits land here, not from too
# little data, but because a close gap there may genuinely never
# reliably convert within one lap).
DEFAULT_OVERTAKE_PASS_THRESHOLD_S = 1.1


def pass_threshold_for(circuit: str) -> float:
    """Measured pace-delta (s/lap) needed for a 50% chance of completing
    a pass within one lap at `circuit`. Prefers the live, self-updating
    calibration (refreshed daily by data/recalibrator.py) if it exists;
    falls back to the hardcoded bootstrap snapshot otherwise (a fresh
    deploy, or the persisted file being missing/unreadable)."""
    # Deferred: engine.overtake_calibration imports from engine.prerace
    # (for _prerace_sources/CIRCUIT_LAPS via engine.undercut_calibration),
    # which imports pass_threshold_for from THIS module -- a top-level
    # import here would be circular. Same reasoning as undercut_shift_for.
    from engine.overtake_calibration import load_calibration
    key = (circuit or "").lower()
    live = load_calibration()
    if live is not None:
        return live["by_circuit"].get(key, live["default"])
    return OVERTAKE_PASS_THRESHOLD_S.get(key, DEFAULT_OVERTAKE_PASS_THRESHOLD_S)
