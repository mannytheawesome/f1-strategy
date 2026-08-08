"""
Per-circuit pit loss — the time a stop actually costs against staying out.

The engine used a single flat 22.0s everywhere. Measured across 2,083 clean
stops in the 2023-2026 cache, the real figure ranges from 16.8s (Montreal) to
28.3s (Imola) — an 11.5s spread that decides stop counts and undercut windows.

Method (offline, from lap timing): for each stop, take the driver's in-lap and
out-lap against a LOCAL baseline (median of laps L-4..L-2 and L+2..L+4, so fuel
and tyre state are matched), then

    loss = (in_lap - baseline) + (out_lap - baseline)

Contexts whose baseline is itself abnormal (safety car, incident) are dropped,
and the per-circuit figure is the median over all remaining stops. This is the
strategically relevant quantity — it is NOT the same as OpenF1's `pit_duration`,
which measures time in the pit lane and ignores what staying out would have cost.
"""

# circuit_short_name (lowercased) -> measured median pit loss in seconds.
# The trailing comment is the sample size behind each figure.
CIRCUIT_PIT_LOSS = {
    "montreal":            16.8,   # n=112
    "monte carlo":         18.1,   # n=102
    "monaco":              18.1,   # alias
    "melbourne":           19.3,   # n=78
    "spa-francorchamps":   19.5,   # n=110
    "spa":                 19.5,   # alias
    "miami":               20.3,   # n=69
    "jeddah":              20.8,   # n=28
    "austin":              21.3,   # n=78
    "hungaroring":         21.3,   # n=146
    "baku":                21.3,   # n=44
    "spielberg":           21.6,   # n=141
    "interlagos":          22.5,   # n=81
    "las vegas":           22.5,   # n=71
    "yas marina circuit":  22.6,   # n=88
    "yas marina":          22.6,   # alias
    "mexico city":         22.6,   # n=63
    "suzuka":              22.6,   # n=97
    "shanghai":            23.2,   # n=58
    "catalunya":           23.3,   # n=166
    "zandvoort":           23.9,   # n=93
    "sakhir":              24.1,   # n=112
    "silverstone":         25.2,   # n=112
    "monza":               25.5,   # n=73
    "singapore":           27.3,   # n=47
    "lusail":              27.5,   # n=78
    "imola":               28.3,   # n=36
}

# Field median across all measured stops — a better blind guess than the old
# flat 22.0 for a circuit we have never raced on.
DEFAULT_PIT_LOSS = 22.6


def pit_loss_for(circuit: str) -> float:
    """Measured pit loss for a circuit, falling back to the field median."""
    return CIRCUIT_PIT_LOSS.get((circuit or "").lower(), DEFAULT_PIT_LOSS)
