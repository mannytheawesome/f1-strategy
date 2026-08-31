"""Circuit classification shared across the strategy engine.

Street circuits are far harder to overtake on, so the predictor leans more on
current track position (and less on simulated pace) when ordering the finish,
and expects a higher safety-car rate. Both the membership set and the tuned
position weight lived, duplicated, in five different files — they live here now.
"""

# Substring-matched (case-insensitive) against circuit_short_name. OpenF1's
# actual circuit_short_name for Monaco is "Monte Carlo" and for Las Vegas is
# "Las Vegas" (space, not underscore) — "monaco" and "las_vegas" never matched
# either, silently classifying both as normal circuits everywhere (backtest
# and production) until 2026-08-11. Keeping the old aliases too in case
# circuit ever arrives from a different field upstream.
STREET_CIRCUITS = {"monaco", "monte carlo", "baku", "singapore", "jeddah",
                   "las_vegas", "las vegas", "miami"}

# Share of the finish-time estimate given to current track position vs pace sim.
# Tuned on the full-history backtest (81 weekends, 2023-2026): 0.85 street /
# 0.5 normal. Re-swept 2026-08-11 after fixing Monaco/Vegas street-circuit
# matching (see STREET_CIRCUITS above) — with Monaco correctly counted, the
# street optimum moved 0.75 -> 0.85 (winner-hit 84.4% -> 84.8% at ~flat MAE;
# checked up to 1.0, which is strictly worse, so 0.85 is a real peak not a
# grid-edge artifact). normal stays 0.5, unchanged by the fix.
STREET_TRACK_POSITION_WEIGHT = 0.85
NORMAL_TRACK_POSITION_WEIGHT = 0.5


def is_street_circuit(circuit: str) -> bool:
    cl = (circuit or "").lower()
    return any(c in cl for c in STREET_CIRCUITS)


def track_position_weight(circuit: str) -> float:
    return (STREET_TRACK_POSITION_WEIGHT if is_street_circuit(circuit)
            else NORMAL_TRACK_POSITION_WEIGHT)


# Known recent circuit resurfacing / long-absence-return events, from public
# reporting — not derivable from OpenF1, which has no such field at all.
# Manually curated and necessarily incomplete; only includes events actually
# verified against a real source (news coverage of the specific resurfacing),
# not general impression. Value is the season in which the NEW surface first
# saw an F1 weekend.
#
# Why this matters: a brand-new track surface behaves very differently in
# its very first F1 weekend (FP1 = the first F1 laps ever on that tarmac) vs
# by race day, once 2+ days of practice, qualifying, and dozens of cars have
# laid rubber down — and that gap shrinks as the surface "beds in" over
# subsequent seasons. Directly measured on Spa (resurfaced June 2024, before
# the July 2024 Belgian GP): the FP-only degradation fit's gap vs the real
# race-measured rate was ~4x the following year's gap, and effectively zero
# two years later (2026). A second check on Miami (resurfaced ahead of its
# 2023 race) showed the same DIRECTION but far more weakly and noisily — a
# real effect, but with only a handful of known events across the 4 cached
# seasons, nowhere near enough to fit a reliable numerical correction.
# RESURFACING_CAVEAT below is deliberately a CAVEAT, not a correction: it
# flags a briefing's degradation numbers as less reliable, it doesn't try to
# adjust them.
RESURFACING_EVENTS = {
    "spa-francorchamps": 2024,   # ~half the track resurfaced June 2024
    "miami":             2023,   # resurfaced ahead of its 2nd F1 race
    "shanghai":          2024,   # freshly resurfaced for its post-COVID return
    "lusail":            2023,   # "transformative renovation" ahead of Oct 2023 GP
    "suzuka":            2026,   # West Course (incl. Spoon Curve) resurfaced before March 2026
}


def resurfacing_caveat(circuit: str, year: int | None) -> str | None:
    """A caveat string if this race falls within 2 seasons of a known
    resurfacing/return event for its circuit, else None. Strength fades
    with time since the event, matching what was actually measured on
    Spa: the event year itself gets the strongest wording (~4x gap
    measured), the following year weaker (~1/4 that gap), nothing
    asserted from two years on (gap was near zero by then)."""
    if not year:
        return None
    cl = (circuit or "").lower()
    for key, event_year in RESURFACING_EVENTS.items():
        if key not in cl:
            continue
        years_since = year - event_year
        if years_since == 0:
            return ("This circuit's surface is new this season — pre-race "
                    "degradation estimates are less reliable than usual "
                    "until real race data confirms them.")
        if years_since == 1:
            return ("This circuit was resurfaced last season — degradation "
                    "estimates may still be settling as the new surface beds in.")
        return None
    return None
