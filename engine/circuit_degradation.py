"""
Per-circuit correction for FP-only degradation estimates.

engine.predictor.build_deg_curves fits deg_rate straight from a weekend's own
Practice data. Confirmed directly against real Mexico City 2026 race laps:
the FP-only estimate overstated how fast Soft and Medium actually wore in the
race by almost exactly the same amount (Soft 0.194->0.093 s/lap, Medium
0.149->0.072 s/lap once real race laps were folded in via build_deg_curves'
own FP_WEIGHTS["RACE"] support) -- FP running (short stints, aggressive push
laps, no fuel/tyre management) doesn't represent how a managed race stint
actually wears, and that gap was the same size for both compounds, pointing
to something generic about Practice running at this circuit rather than a
compound-specific effect. Hard had no real race laps to compare against
(nobody ran it there), so it isn't included here.

This is intentionally a single circuit-wide multiplier, not per-compound: one
race's evidence can't responsibly support three independent per-compound
numbers, and the one circuit measured so far showed the same shrink for both
compounds anyway. Each entry should grow more compound-specific (or get
corrected) only once more races at that circuit are actually measured --
not extrapolated from a single weekend.
"""

# circuit_short_name (lowercased) -> real-race-measured deg_rate / FP-only
# deg_rate, i.e. how much more gently the real race wears than FP running
# predicts. The trailing comment is the sample size behind each figure.
CIRCUIT_RACE_DEG_SHRINK = {
    "mexico city": 0.48,   # n=1 race (2026): SOFT 0.48x, MEDIUM 0.48x
}

# 1.0 (no adjustment) for any circuit not yet measured against a real race.
DEFAULT_SHRINK = 1.0


def race_deg_shrink_for(circuit: str) -> float:
    """Multiplier for an FP-only deg_rate estimate, learned by comparing a
    past prediction at this circuit against its actual race laps. Only
    meaningful when the curve being corrected has NO real race data of its
    own already folded in -- see build_deg_curves' `circuit` parameter."""
    return CIRCUIT_RACE_DEG_SHRINK.get((circuit or "").lower(), DEFAULT_SHRINK)
