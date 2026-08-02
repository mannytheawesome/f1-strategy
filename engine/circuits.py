"""Circuit classification shared across the strategy engine.

Street circuits are far harder to overtake on, so the predictor leans more on
current track position (and less on simulated pace) when ordering the finish,
and expects a higher safety-car rate. Both the membership set and the tuned
position weight lived, duplicated, in five different files — they live here now.
"""

# Substring-matched (case-insensitive) against circuit_short_name.
STREET_CIRCUITS = {"monaco", "baku", "singapore", "jeddah", "las_vegas", "miami"}

# Share of the finish-time estimate given to current track position vs pace sim.
# Tuned on the full-history backtest: 0.75 street / 0.6 normal.
STREET_TRACK_POSITION_WEIGHT = 0.75
NORMAL_TRACK_POSITION_WEIGHT = 0.6


def is_street_circuit(circuit: str) -> bool:
    cl = (circuit or "").lower()
    return any(c in cl for c in STREET_CIRCUITS)


def track_position_weight(circuit: str) -> float:
    return (STREET_TRACK_POSITION_WEIGHT if is_street_circuit(circuit)
            else NORMAL_TRACK_POSITION_WEIGHT)
