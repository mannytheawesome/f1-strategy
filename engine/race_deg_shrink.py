"""
Partially-pooled, per-circuit-and-compound correction for FP-only
degradation estimates.

engine.predictor.build_deg_curves fits deg_rate straight from a weekend's
own Practice data. First confirmed against Mexico City 2026 alone (see
CLAUDE.md): the FP-only estimate overstated real race wear there by about
2x for both Soft and Medium. That immediately raised the obvious next
question -- is this circuit-specific, or does it generalise? -- before a
single-race number went any further than that one weekend.

Swept every cached 2023-2026 race with both FP and race data
(sweep_degradation_shrink.py, offline, backtest_full.py's own cache, 68
races) comparing each compound's FP-only deg_rate against its FP+race
deg_rate wherever the compound got a genuine long-run sample pre-race AND
was actually raced. Two things came out of it:

1. The DIRECTION is universal: every compound's GLOBAL median ratio is
   well below 1.0 (SOFT 0.82, MEDIUM 0.59, HARD 0.57, n=17/54/48) -- FP
   running overstates real race wear almost everywhere, not just at
   Mexico City. Physically unsurprising: pre-race running never runs
   genuine fuel-correct, tyre-managed long stints the way a real race
   does.

2. The MAGNITUDE varies a lot per circuit (0.33 to 1.42 on only 3-4
   races each -- the same thin-sample shape already rejected for a
   per-circuit DNF table elsewhere in this project), but isn't PURE
   noise either: a flat global default, tried first, flipped Mexico
   City 2026's own recommendation back to Hard-heavy -- contradicting
   the one real race this can be checked against (0/22 drivers used
   Hard that weekend) -- which the single-race number it replaced had
   gotten right.

Uses partial pooling rather than picking one extreme: each circuit's own
median is blended toward the global default, weighted by
weight = min(1, n/8) -- reusing build_deg_curves' own MEDIUM-confidence
threshold (pts>=8) as the point a measurement starts being trusted mostly
on its own, not a new invented constant.

Worth being honest about what this does and doesn't fix: Mexico City's
pooled values (n=2-3, weight~0.25-0.375) still aren't pulled far enough
toward its own raw single-race number to flip the recommendation back to
Medium->Soft->Soft -- checked directly, it still lands on Hard->Medium
with these pooled figures. That's not a bug, it's partial pooling doing
exactly what it's for: refusing to fully trust a thin sample, which by
construction means it won't always match any ONE race either, including
the one real race available to check it against. Shipped anyway --
deliberately, not by default -- because trusting a single race's number
completely is the worse failure mode across the whole calendar, even
though it's the better fit for this one circuit. Revisit once Mexico
City has enough real samples (n approaching 8) for its own pooled weight
to actually dominate -- this will shift there on its own as more races
accumulate, without needing to revisit
the formula.
"""

# Median FP+race / FP-only deg_rate across 68 cached 2023-2026 races, for
# whichever compound had a genuine long-run FP sample AND was actually
# raced that weekend (sweep_degradation_shrink.py). Median, not mean --
# same reason build_deg_curves uses a weighted median elsewhere: one wild
# race shouldn't drag the whole compound's number. Used directly for any
# circuit not in CIRCUIT_RACE_DEG_SHRINK, and as the pooling target for
# circuits that are.
GLOBAL_RACE_DEG_SHRINK = {
    "SOFT":   0.82,   # n=17
    "MEDIUM": 0.59,   # n=54
    "HARD":   0.57,   # n=48
}

# circuit_short_name (lowercased) -> {compound: partially-pooled shrink}.
# Each value is weight*circuit_median + (1-weight)*GLOBAL_RACE_DEG_SHRINK,
# weight = min(1, n/8); the trailing comment per circuit is each
# compound's own sample size. A compound/circuit combination with no
# cached sample at all is simply absent -- falls through to the global
# default, same as weight=0 would compute anyway.
CIRCUIT_RACE_DEG_SHRINK = {
    "austin":              {"HARD": 0.511},                                    # HARD n=1
    "baku":                {"HARD": 0.530, "MEDIUM": 0.542},                   # HARD n=1, MEDIUM n=2
    "catalunya":           {"HARD": 0.550, "MEDIUM": 0.556, "SOFT": 0.696},     # HARD n=2, MEDIUM n=3, SOFT n=4
    "hungaroring":         {"HARD": 0.471, "MEDIUM": 0.458, "SOFT": 0.765},     # HARD n=4, MEDIUM n=4, SOFT n=1
    "imola":               {"HARD": 0.677, "MEDIUM": 0.677},                   # HARD n=1, MEDIUM n=2
    "interlagos":          {"HARD": 0.564},                                    # HARD n=1
    "jeddah":              {"HARD": 0.553, "MEDIUM": 0.558, "SOFT": 0.881},     # HARD n=2, MEDIUM n=3, SOFT n=2
    "las vegas":           {"HARD": 0.564, "MEDIUM": 0.558},                   # HARD n=1, MEDIUM n=3
    "lusail":              {"HARD": 0.467, "MEDIUM": 0.636},                   # HARD n=2, MEDIUM n=1
    "melbourne":           {"HARD": 0.649, "MEDIUM": 0.610},                   # HARD n=1, MEDIUM n=2
    "mexico city":         {"HARD": 0.601, "MEDIUM": 0.582},                   # HARD n=3, MEDIUM n=2
    "miami":               {"HARD": 0.524, "MEDIUM": 0.671},                   # HARD n=2, MEDIUM n=2
    "monte carlo":         {"HARD": 0.734, "MEDIUM": 0.740, "SOFT": 0.789},     # HARD n=3, MEDIUM n=3, SOFT n=2
    "monaco":              {"HARD": 0.734, "MEDIUM": 0.740, "SOFT": 0.789},     # alias
    "montreal":            {"HARD": 0.613, "MEDIUM": 0.720, "SOFT": 0.841},     # HARD n=2, MEDIUM n=4, SOFT n=1
    "monza":               {"HARD": 0.571, "MEDIUM": 0.740},                   # HARD n=1, MEDIUM n=3
    "sakhir":              {"HARD": 0.575, "MEDIUM": 0.564, "SOFT": 0.866},     # HARD n=1, MEDIUM n=1, SOFT n=3
    "shanghai":            {"HARD": 0.628, "MEDIUM": 0.536},                   # HARD n=1, MEDIUM n=1
    "silverstone":         {"HARD": 0.585, "MEDIUM": 0.636, "SOFT": 0.841},     # HARD n=3, MEDIUM n=2, SOFT n=1
    "singapore":           {"HARD": 0.539, "MEDIUM": 0.507, "SOFT": 0.792},     # HARD n=2, MEDIUM n=2, SOFT n=1
    "spa-francorchamps":   {"HARD": 0.480, "MEDIUM": 0.616},                   # HARD n=3, MEDIUM n=2
    "spa":                 {"HARD": 0.480, "MEDIUM": 0.616},                   # alias
    "spielberg":           {"HARD": 0.732, "MEDIUM": 0.620, "SOFT": 0.818},     # HARD n=3, MEDIUM n=2, SOFT n=1
    "suzuka":              {"HARD": 0.571, "MEDIUM": 0.533},                   # HARD n=3, MEDIUM n=3
    "yas marina circuit":  {"HARD": 0.555, "MEDIUM": 0.788},                   # HARD n=1, MEDIUM n=3
    "yas marina":          {"HARD": 0.555, "MEDIUM": 0.788},                   # alias
    "zandvoort":           {"HARD": 0.838, "MEDIUM": 0.574, "SOFT": 0.806},     # HARD n=4, MEDIUM n=4, SOFT n=1
}

DEFAULT_SHRINK = 1.0


def race_deg_shrink_for(compound: str, circuit: str = "") -> float:
    """Multiplier for an FP-only deg_rate estimate for this compound at
    this circuit, learned from comparing real races' FP-only predictions
    against what actually happened. Only meaningful when the curve being
    corrected has NO real race data of its own already folded in -- see
    build_deg_curves' `apply_race_shrink` parameter."""
    c = (compound or "").upper()
    circuit_table = CIRCUIT_RACE_DEG_SHRINK.get((circuit or "").lower())
    if circuit_table and c in circuit_table:
        return circuit_table[c]
    return GLOBAL_RACE_DEG_SHRINK.get(c, DEFAULT_SHRINK)
