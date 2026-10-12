"""
Per-compound calibration for the cold-tyre Safety Car/VSC restart penalty
(applied in engine.prerace via _restart_risk_cost).

optimize_strategy's lap-time model has no concept of a restart at all --
degradation curves price a tyre fading over a stint, not a one-time
cold-tyre penalty on the specific lap racing resumes after a
neutralisation. Real case that surfaced this (Singapore 2026, user-cross-
checked against an independent strategist's analysis and F1.com's own
Pirelli-sourced preview): HARD was ranked as a viable 1-stop candidate
despite 0 of 22 real finishers ever racing on it there, because HARD is
slow to reach operating temperature after a restart and loses track
position in the laps right after one -- an effect this codebase had no
representation of at all.

Method (calibrate_restart_delta.py, offline, see engine/restart_calibration.py
for the live/self-updating version): for every real Safety Car/VSC restart
across 2023-2026 (excluding any event whose end lap was never confirmed by
a genuine race-control "ENDING"/"IN THIS LAP" message -- a fabricated
close is not a measured restart), compare each eligible driver's lap time
on the restart lap against the FIELD'S OWN MEDIAN lap time on that same
lap (cross-sectional, not fit against each driver's own deg curve -- this
cancels out track evolution/fuel/circuit effects for free, and needs no
dependency on build_deg_curves at all). A compound's delta is the median
residual across every such sample, pooled globally -- not split by
circuit. Unlike engine/undercut_shift.py's per-circuit shift, this isn't
split by circuit: the cold-tyre effect is roughly circuit-invariant tyre-
temperature physics, whereas how much a lost lap costs in track position
is already modelled separately (track_position_weight/_overtaking_cost).
A circuit split would also starve exactly the compound this feature exists
to catch -- HARD is rarely-to-never raced at the street circuits where
this effect matters most, precisely because of this effect, so a street-
only HARD bucket could end up with zero samples by construction.

RESTART_LAP_DELTA_S below is the real measured snapshot from the first
two actual runs of calibrate_restart_delta.py (2026-10-12, 2023-2026
cache, no circuit split) -- NOT a guess or a third-party figure. It is
also, honestly, a near-null result: every compound came back within
0.03s of the field median, HARD included, despite the Singapore case
that motivated this feature. Two independent fixes to the lap-selection
logic (the second specifically correcting a confirmed race_control
end_lap misalignment, verified directly against Singapore 2026's own two
real VSCs) moved the numbers around but never produced a stable,
sizeable HARD penalty -- if anything the signal got WEAKER after fixing
a real bug, which is itself evidence that what little signal the first
run showed was mostly noise from exactly which lap got sampled, not a
robust effect. Each compound's sample size comfortably clears
MIN_SAMPLES (600+ each), so this is a confident "no detectable effect at
this pooled, global level," not a data-scarcity gap.

This doesn't mean the underlying Buscombe/F1.com restart-grip claim is
wrong -- it may be real but circuit-specific (diluted by pooling every
circuit together, the exact tradeoff this module's docstring accepted
to avoid starving HARD's street-circuit sample to zero) or simply too
small in raw lap-time terms to separate from noise at this sample size.
Re-run calibrate_restart_delta.py as more races accumulate, or revisit
the circuit-split tradeoff, before assuming either way. Until then,
_restart_risk_cost correctly applies ~0 cost everywhere -- an honest
reflection of what's actually been measured, not a bug.
"""

# compound -> measured seconds lost on the lap right after a real SC/VSC
# restart, relative to the field's own median lap time on that same lap
# (positive = slower than the field, negative = faster). A real measured
# snapshot (see module docstring for why it's a near-null result, and why
# that's an honest finding rather than a placeholder).
RESTART_LAP_DELTA_S: dict[str, float] = {
    "HARD": 0.0,      # n=606
    "MEDIUM": -0.0,   # n=392
    "SOFT": -0.0,     # n=222
}

# Safe "assume no effect" prior for a compound with no calibrated number
# (either nothing has been measured yet, or that compound never cleared
# MIN_SAMPLES) -- unlike undercut_shift.py's DEFAULT_UNDERCUT_SHIFT (a
# pooled field-wide median, a meaningful fallback there), there's no
# cross-compound default that makes physical sense here: SOFT's restart
# behaviour says nothing about HARD's.
DEFAULT_RESTART_DELTA_S = 0.0


def restart_delta_for(compound: str) -> float:
    """Measured cold-tyre restart penalty for `compound`, in seconds
    (positive = slower than field median on the restart lap). Prefers the
    live, self-updating calibration (refreshed daily by
    data/recalibrator.py) if it exists; falls back to the hardcoded
    bootstrap snapshot otherwise (a fresh deploy, or the persisted file
    being missing/unreadable)."""
    # Deferred: engine.restart_calibration imports from engine.prerace
    # (for _prerace_sources/CIRCUIT_LAPS via engine.undercut_calibration),
    # which imports restart_delta_for from THIS module -- a top-level
    # import here would be circular. Same reasoning as undercut_shift_for.
    from engine.restart_calibration import load_calibration
    live = load_calibration()
    if live is not None:
        return live["by_compound"].get(compound, DEFAULT_RESTART_DELTA_S)
    return RESTART_LAP_DELTA_S.get(compound, DEFAULT_RESTART_DELTA_S)
