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
