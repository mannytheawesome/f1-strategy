"""
Per-circuit calibration for the MEDIUM->HARD one-stop undercut/track-
position pit-lap correction (applied in engine.prerace via
_shift_medium_start_earlier).

optimize_strategy's pure lap-time DP has no concept of undercut or
track-position risk -- every car is optimized as if racing alone.
Backtested (backtest_pit_timing.py) against 2026's completed races, real
MEDIUM->HARD one-stop finishers pitted earlier than the pure-pace answer,
median 7 laps across 4 clean races -- but that 4-race sample (Australia,
Suzuka, Spa, Spain) all happened to be early-biased circuits, and a flat
correction from it badly misrepresented circuits with the opposite or a
much smaller real bias.

Method (calibrate_undercut_shift.py, offline): for every circuit, every
completed race there across 2023-2026, compare optimize_strategy's own
predicted MEDIUM->HARD one-stop pit lap (from FP-only data, the same path
build_prerace_data uses) against every REAL clean one-stop MEDIUM->HARD
finisher's actual pit lap (excluding pit lap < 8 -- a Lap-1-incident
filter, not a strategy decision). A circuit's shift is the median of
(real - predicted) across every year, sign-flipped so positive means
"pit earlier than the pure-pace answer" and negative means "pit later."

Roughly half of the well-sampled circuits need a LATER correction, not
earlier -- e.g. Mexico City's real one-stoppers pit 10 laps later than
the pure-pace optimum, Miami's pit 2 laps later -- contradicting the
original "MEDIUM starters always defend the undercut" assumption drawn
from the 4-race sample alone. This is real, circuit-specific behaviour
(pit loss, overtaking difficulty, and Safety Car frequency all differ),
not noise -- a circuit needs n>=10 real matched samples to appear below;
smaller samples were genuinely wild (Monte Carlo's n=3 implied a 32-lap
shift) and fall back to the field-median default instead.
"""

# circuit_short_name (lowercased) -> measured shift in laps (positive =
# pit earlier than optimize_strategy's pure-pace answer; negative = later).
# Trailing comment is the real matched-driver sample size behind each figure.
CIRCUIT_UNDERCUT_SHIFT = {
    "baku":                 9.0,    # n=33
    "suzuka":               8.0,    # n=33
    "jeddah":               6.0,    # n=23
    "zandvoort":            5.5,    # n=14
    "spa-francorchamps":    4.0,    # n=13
    "spa":                  4.0,    # alias
    "las vegas":            1.5,    # n=16
    "monza":                1.0,    # n=20
    "singapore":           -1.0,    # n=25
    "miami":               -2.0,    # n=43
    "austin":              -3.5,    # n=12
    "hungaroring":         -5.0,    # n=10
    "imola":               -7.0,    # n=13
    "mexico city":        -10.0,    # n=16
}

# Field median across every circuit's real matched samples pooled -- a
# better blind guess than 0 for a circuit with no track record yet.
DEFAULT_UNDERCUT_SHIFT = 4.0


def undercut_shift_for(circuit: str) -> float:
    """Measured MEDIUM->HARD one-stop early-pit shift for a circuit
    (laps), falling back to the field median."""
    return CIRCUIT_UNDERCUT_SHIFT.get((circuit or "").lower(), DEFAULT_UNDERCUT_SHIFT)
