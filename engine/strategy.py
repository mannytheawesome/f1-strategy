"""
Strategy generator.

Produces 4–5 plausible race strategies for each driver given:
  - Current lap, tyre compound, tyre age
  - Remaining laps
  - Degradation curves from the session

Each strategy is a list of stints: [{compound, start_lap, end_lap}, ...]
Strategies cover 1-stop and 2-stop options across viable compound combos.
"""

from __future__ import annotations
from dataclasses import dataclass
from engine.degradation import TyreDegradation, MAX_LIFE, CLIFF_SECONDS

# Compounds available for dry racing (no inters/wets in strategy planning)
DRY_COMPOUNDS = ["SOFT", "MEDIUM", "HARD"]

# Minimum laps on the current tyre before we plan a strategy from it
# (filters out formation lap / safety car stints on intermediates etc.)
MIN_CURRENT_STINT = 3

# Minimum stint length (can't pit on lap 1 of a stint)
MIN_STINT = 12

# F1 rule: must use at least 2 different compounds during the race
REQUIRED_COMPOUNDS = 2


@dataclass
class Stint:
    compound: str
    start_lap: int
    end_lap: int

    @property
    def length(self) -> int:
        return self.end_lap - self.start_lap + 1

    def to_dict(self) -> dict:
        return {
            "compound": self.compound,
            "start_lap": self.start_lap,
            "end_lap": self.end_lap,
            "length": self.length,
        }


@dataclass
class Strategy:
    label: str
    stints: list[Stint]
    total_time_penalty: float   # estimated extra seconds vs optimal (lower = better)
    stop_count: int

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "stints": [s.to_dict() for s in self.stints],
            "total_time_penalty": round(self.total_time_penalty, 2),
            "stop_count": self.stop_count,
        }


def _cliff(compound: str, curves: dict[str, TyreDegradation]) -> int:
    """Optimal stint length for a compound (tyre cliff lap)."""
    c = curves.get(compound)
    if c and c.cliff_lap > 0:
        return c.cliff_lap
    return MAX_LIFE.get(compound, 40)


def _stint_penalty(compound: str, length: int, curves: dict[str, TyreDegradation]) -> float:
    """
    Estimate extra lap time accumulated by running past optimal length.
    = deg_rate * max(0, length - cliff)^2 * 0.5  (quadratic past cliff)
    """
    c = curves.get(compound)
    if c is None or c.deg_rate <= 0:
        return 0.0
    cliff = c.cliff_lap
    overrun = max(0, length - cliff)
    return c.deg_rate * overrun * overrun * 0.5


PIT_STOP_TIME = 22.0  # seconds lost per pit stop


def _evaluate(stints: list[tuple[str, int]], curves: dict) -> float:
    """Score a strategy (lower = faster). Accounts for deg penalty + pit time."""
    penalty = (len(stints) - 1) * PIT_STOP_TIME
    for compound, length in stints:
        penalty += _stint_penalty(compound, length, curves)
    return penalty


def generate_strategies(
    current_lap: int,
    total_laps: int,
    current_compound: str,
    current_tyre_age: int,
    curves: dict[str, TyreDegradation],
) -> list[Strategy]:
    """
    Generate 4–5 candidate strategies from the current race position.
    Remaining laps = total_laps - current_lap.
    Current stint has already run current_tyre_age laps.
    """
    remaining = total_laps - current_lap
    if remaining <= 0:
        return []

    # If currently on a non-dry compound or a very short stint (e.g. safety car inters),
    # treat the next dry compound as the starting point
    if current_compound not in DRY_COMPOUNDS or current_tyre_age < MIN_CURRENT_STINT:
        # Start fresh — pretend we're about to pit onto a soft
        current_compound = "SOFT"
        current_tyre_age = 0

    strategies: list[Strategy] = []
    seen: set[tuple] = set()

    def add(label: str, plan: list[tuple[str, int]]) -> None:
        """plan = [(compound, stint_length), ...]"""
        key = tuple(plan)
        if key in seen:
            return
        # Validate: all stints meet minimum length, total laps add up,
        # and at least 2 different compounds used in full race
        if any(length < MIN_STINT for _, length in plan):
            return
        if sum(l for _, l in plan) != remaining:
            return
        compounds_used = {c for c, _ in plan} | {current_compound}
        if len(compounds_used) < REQUIRED_COMPOUNDS:
            return
        seen.add(key)
        penalty = _evaluate(plan, curves)
        lap = current_lap
        stints = []
        # First partial current stint (already running) — clamp start to lap 1
        stint_start = max(1, current_lap - current_tyre_age)
        stints.append(Stint(current_compound, stint_start, current_lap + plan[0][1]))
        lap = current_lap + plan[0][1] + 1
        for compound, length in plan[1:]:
            stints.append(Stint(compound, lap, lap + length - 1))
            lap += length
        strategies.append(Strategy(label=label, stints=stints,
                                   total_time_penalty=penalty,
                                   stop_count=len(plan) - 1))

    # ── Remaining laps to distribute ──────────────────────────────────────

    # How many laps left on this stint before cliff
    cliff_current = _cliff(current_compound, curves)
    laps_left_on_current = max(MIN_STINT, cliff_current - current_tyre_age)
    laps_left_on_current = min(laps_left_on_current, remaining - MIN_STINT)

    # Compound "hardness" rank — can only switch to equal or harder compound
    # unless fewer than SOFT_SPLASH_LAPS remain (late splash is valid)
    HARDNESS = {"SOFT": 0, "MEDIUM": 1, "HARD": 2}
    SOFT_SPLASH_LAPS = 15   # allow downgrade to softer only in last 15 laps

    # ── 1-stop strategies ─────────────────────────────────────────────────
    for c2 in DRY_COMPOUNDS:
        if c2 == current_compound and current_tyre_age < 5:
            continue   # same compound again only if already some age
        # Don't suggest going to a softer compound mid-race unless it's a late splash
        if HARDNESS.get(c2, 0) < HARDNESS.get(current_compound, 0):
            continue
        for ext in range(max(MIN_STINT, laps_left_on_current - 5),
                         min(remaining - MIN_STINT, laps_left_on_current + 8) + 1, 3):
            r2 = remaining - ext
            if r2 < MIN_STINT:
                continue
            # Allow soft only if the soft stint is short (splash) or current is also soft
            if c2 == "SOFT" and r2 > SOFT_SPLASH_LAPS and current_compound != "SOFT":
                continue
            add(f"{current_compound[0]}–{c2[0]}", [(current_compound, ext), (c2, r2)])

    # ── 2-stop strategies ─────────────────────────────────────────────────
    for c2 in DRY_COMPOUNDS:
        for c3 in DRY_COMPOUNDS:
            compounds = {current_compound, c2, c3}
            if len(compounds) < REQUIRED_COMPOUNDS:
                continue
            cliff2 = _cliff(c2, curves)
            cliff3 = _cliff(c3, curves)
            # Distribute remaining laps roughly around cliff lengths
            for s1 in range(MIN_STINT, min(remaining - 2*MIN_STINT, laps_left_on_current + 5) + 1, 4):
                for s2 in range(MIN_STINT, remaining - s1 - MIN_STINT + 1, 4):
                    s3 = remaining - s1 - s2
                    if s3 < MIN_STINT:
                        continue
                    # No downgrade to a softer compound mid-race unless it's
                    # a genuine late splash on the final stint.
                    if HARDNESS.get(c2, 0) < HARDNESS.get(current_compound, 0):
                        continue
                    if HARDNESS.get(c3, 0) < HARDNESS.get(c2, 0) and s3 > SOFT_SPLASH_LAPS:
                        continue
                    add(f"{current_compound[0]}–{c2[0]}–{c3[0]}",
                        [(current_compound, s1), (c2, s2), (c3, s3)])

    # Sort by penalty and take the 5 best distinct strategies
    strategies.sort(key=lambda s: s.total_time_penalty)

    # Deduplicate by stop-count + compound sequence
    seen_labels: set[str] = set()
    result: list[Strategy] = []
    for s in strategies:
        sig = f"{s.stop_count}:" + ",".join(st.compound for st in s.stints)
        if sig not in seen_labels:
            seen_labels.add(sig)
            result.append(s)
        if len(result) >= 5:
            break

    # Re-label cleanly
    for i, s in enumerate(result):
        s.label = f"Strategy {i+1}"

    return result
