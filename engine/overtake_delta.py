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

OVERTAKE_PASS_THRESHOLD_S below is the real measured snapshot, refreshed
2026-10-22 (2023-2026 cache, 85 races, 36,117 close-pair samples -- up
from the first run's 68 races/28,118 samples on 2026-10-12) -- not a
guess. Worth being honest about what it does and doesn't show: Singapore,
Monte Carlo, Las Vegas, Jeddah, and Lusail still found NO clean 50%
crossing within the sampled pace-delta range, despite 800-1800+ samples
each -- not a data-scarcity gap, but a plausible real finding: those
circuits may genuinely never reliably convert a close gap into a pass
within a single lap, however large the pace advantage, since a real pass
there usually takes several laps of DRS-train following rather than one
clean move. They fall back to DEFAULT below rather than a fabricated
number, which is the correct behaviour given what the data actually
shows, not a failure of the calibration.

Two things changed on this refresh, not just the numbers moving within
noise: Baku now has a clean crossing (1.28, n=1853) where the first run
found none -- more samples resolved it, rather than it being a stable
"never converts" circuit like the ones above. And Hungaroring's 2.50s/lap,
flagged in the first run as "a single crossing off one bucket boundary,
not corroborated the way the others are -- re-check once more races
accumulate" -- has now fully collapsed to NO clean crossing at all
(n=1696, up from 1149) and is removed from the table below. The caution
was correct; the number it was cautioning about no longer exists. Treat
any single-run crossing with the same scepticism until it's survived a
refresh like this one.

Only then hardcode a bootstrap snapshot here -- same stance as
undercut_shift.py and restart_delta.py.
"""

# circuit_short_name (lowercased) -> measured pace-delta (s/lap) a
# trailing car needs over a leading car, at a gap under
# engine.overtake_calibration.GAP_THRESHOLD_S, for a 50% chance of
# completing the pass by the next lap. Trailing comment is the real
# sample size behind each figure, as of this snapshot (2026-10-22).
OVERTAKE_PASS_THRESHOLD_S: dict[str, float] = {
    "monza":              0.90,   # n=1701
    "shanghai":           0.98,   # n=1233
    "miami":              1.01,   # n=1467
    "spielberg":          1.02,   # n=1508
    "catalunya":          1.09,   # n=1543
    "melbourne":          1.13,   # n=1326
    "interlagos":         1.13,   # n=1372
    "spa-francorchamps":  1.19,   # n=1443
    "yas marina circuit": 1.19,   # n=1346
    "zandvoort":          1.20,   # n=2156
    "austin":             1.25,   # n=1054
    "baku":               1.28,   # n=1853 -- new this refresh, see docstring
    "suzuka":             1.28,   # n=1639
    "silverstone":        1.44,   # n=1520
    "mexico city":        1.46,   # n=1454
}

# Pooled field-wide median across every circuit's real samples -- a
# better blind guess than a hand-picked constant for a circuit with no
# track record yet (a brand new venue, or one not yet calibrated) *and*
# the circuits above that found no clean crossing of their own (see
# docstring: Singapore/Monte Carlo/Las Vegas/Jeddah/Lusail land here, not
# from too little data, but because a close gap there may genuinely never
# reliably convert within one lap).
DEFAULT_OVERTAKE_PASS_THRESHOLD_S = 1.14


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
