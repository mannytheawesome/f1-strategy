"""
Tyre inventory tracker.

Counts new sets used per driver per compound across all sessions
in a meeting up to the current session, then subtracts from the
standard allocation to show remaining new sets.

Standard allocation (non-sprint weekend):
  Hard:   2 sets
  Medium: 3 sets
  Soft:   8 sets

Sprint weekend:
  Hard:   2 sets
  Medium: 3 sets
  Soft:   6 sets
"""

from __future__ import annotations
from dataclasses import dataclass, field

# Standard allocation per driver per weekend type
ALLOCATION = {
    "standard": {"HARD": 2, "MEDIUM": 3, "SOFT": 8},
    "sprint":   {"HARD": 2, "MEDIUM": 3, "SOFT": 6},
}

COMPOUNDS = ["SOFT", "MEDIUM", "HARD"]


@dataclass
class DriverInventory:
    driver_number: int
    acronym: str
    team_colour: str
    # sets used per compound (new sets opened, tyre_age_at_start == 0)
    used: dict[str, int] = field(default_factory=dict)
    # allocation for this weekend type
    allocation: dict[str, int] = field(default_factory=dict)

    def remaining(self, compound: str) -> int:
        total = self.allocation.get(compound, 0)
        return max(0, total - self.used.get(compound, 0))

    def to_dict(self) -> dict:
        return {
            "driver_number": self.driver_number,
            "acronym": self.acronym,
            "team_colour": self.team_colour,
            "inventory": {
                c: {
                    "used": self.used.get(c, 0),
                    "total": self.allocation.get(c, 0),
                    "remaining": self.remaining(c),
                }
                for c in COMPOUNDS
            },
        }


def compute_inventory(
    stints_by_session: list[list[dict]],   # list of stints lists, one per session
    drivers_raw: dict[int, dict],
    is_sprint: bool = False,
) -> list[DriverInventory]:
    """
    Compute tyre inventory for all drivers.

    stints_by_session: stints from each session in the meeting (in chronological order)
    drivers_raw: driver metadata dict (from get_drivers)
    is_sprint: True if sprint weekend (fewer soft sets allocated)
    """
    alloc = ALLOCATION["sprint"] if is_sprint else ALLOCATION["standard"]

    inventories: dict[int, DriverInventory] = {}

    for num, d in drivers_raw.items():
        inventories[num] = DriverInventory(
            driver_number=num,
            acronym=d.get("name_acronym", str(num)),
            team_colour=d.get("team_colour") or "ffffff",
            allocation=dict(alloc),
        )

    # Count new sets opened across all sessions
    for session_stints in stints_by_session:
        for stint in session_stints:
            if stint.get("tyre_age_at_start", 0) != 0:
                continue  # not a new set
            num = stint["driver_number"]
            if num not in inventories:
                continue
            compound = stint.get("compound", "UNKNOWN")
            if compound not in COMPOUNDS:
                continue
            inv = inventories[num]
            inv.used[compound] = inv.used.get(compound, 0) + 1

    # Sort by acronym
    result = sorted(inventories.values(), key=lambda d: d.acronym)
    return result
