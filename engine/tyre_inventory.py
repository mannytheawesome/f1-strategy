"""
Tyre inventory tracker.

Counts new sets used per driver per compound across all sessions in a
meeting up to the current session, then subtracts that directly from the
full weekend allocation (Article B6.2.4) to get what's left for the race.
No shared "race-day pool" ceiling is modelled — the mandatory in-weekend
electronic returns (Article B6.3.8a/B6.3.9a) exist, but which specific
compounds get handed back at each checkpoint is a team's own choice and not
observable from OpenF1 telemetry, so an earlier version of this model tried
to enforce the resulting 7/6-set totals as a hard constraint. That produced
internally-consistent numbers that didn't match reality: cross-checked
against F1's own race-morning strategy-guide numbers for the 2026 Hungarian
GP, real drivers were shown holding fresh Hard/Medium sets in reserve well
past what a 7-set ceiling would allow, because a team that barely touches a
compound in practice keeps most of its full allocation for race day, return
schedule notwithstanding — the regulation caps how many sets survive, not
how few. Straight subtraction from the full 13/12-set allocation matches
that better than an invented pool cap does.

Full weekend allocation per driver, FIA 2026 Sporting Regulations Article
B6.2.4:
  Standard Format (non-sprint):    Hard 2 / Medium 3 / Soft 8  (13 total)
  Alternative Format (sprint):     Hard 2 / Medium 4 / Soft 6  (12 total)
"""

from __future__ import annotations
from dataclasses import dataclass, field

# Full weekend allocation per driver (Article B6.2.4).
ALLOCATION = {
    "standard": {"HARD": 2, "MEDIUM": 3, "SOFT": 8},
    "sprint":   {"HARD": 2, "MEDIUM": 4, "SOFT": 6},
}

COMPOUNDS = ["SOFT", "MEDIUM", "HARD"]


@dataclass
class DriverInventory:
    driver_number: int
    acronym: str
    team_colour: str
    # sets used per compound (new sets opened, tyre_age_at_start == 0)
    used: dict[str, int] = field(default_factory=dict)
    # full weekend allocation (Article B6.2.4)
    allocation: dict[str, int] = field(default_factory=dict)

    def reconciled(self) -> dict[str, dict[str, int]]:
        """{compound: {"used": int, "new": int}}. `new` is simply the
        compound's full weekend allocation minus what's been genuinely
        opened so far (floored at 0) — see module docstring for why no
        shared pool ceiling is applied on top of that."""
        out = {}
        for c in COMPOUNDS:
            used = min(self.used.get(c, 0), self.allocation.get(c, 0))
            new = max(0, self.allocation.get(c, 0) - used)
            out[c] = {"used": used, "new": new}
        return out

    def remaining(self, compound: str) -> int:
        return self.reconciled().get(compound, {}).get("new", 0)

    def total_held(self, compound: str) -> int:
        """new + used — every set of this compound the driver can legally
        fit for the race (B6.3.3: sets of the same dry-weather specification
        may be mixed after Qualifying, so a used set is just as fittable as
        a new one, not merely a fallback)."""
        r = self.reconciled().get(compound, {})
        return r.get("new", 0) + r.get("used", 0)

    def to_dict(self) -> dict:
        r = self.reconciled()
        return {
            "driver_number": self.driver_number,
            "acronym": self.acronym,
            "team_colour": self.team_colour,
            "inventory": {
                c: {
                    "used": r[c]["used"],
                    "total": self.allocation.get(c, 0),
                    "remaining": r[c]["new"],
                }
                for c in COMPOUNDS
            },
        }


def compute_inventory(
    stints_by_session: list[list[dict]],   # list of stints lists, one per session
    drivers_raw: dict[int, dict],
    is_sprint: bool = False,
    q3_drivers: set[int] | None = None,   # unused; kept for call-site compat
) -> list[DriverInventory]:
    """
    Compute tyre inventory for all drivers.

    stints_by_session: stints from each session in the meeting (in chronological order)
    drivers_raw: driver metadata dict (from get_drivers)
    is_sprint: True if sprint weekend (fewer soft sets allocated)
    q3_drivers: no longer used to reduce the pool (see module docstring) —
      kept as a parameter only so existing call sites don't need to change.
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

    # Count new sets opened, at most once per (driver, compound) PER SESSION.
    # OpenF1 stints with tyre_age_at_start==0 don't reliably mean "genuinely
    # fresh physical tyre" — verified directly against real data (Silverstone
    # 2026 sprint weekend): a single Qualifying session alone showed 4-5
    # separate SOFT stints all marked fresh for most of the field, pushing
    # some drivers' SEASON-long new-SOFT count past the 6-set sprint
    # allocation entirely (a physical impossibility) — cross-checked against
    # pit-lane visit records, which confirmed genuine pit stops at each
    # boundary, so this isn't stint-fragmentation _merge_stint_fragments
    # already handles; it's teams returning to the garage and going back out
    # on the SAME set for another run, with OpenF1 resetting the reported
    # age anyway. Real F1 teams essentially never fit more than one genuinely
    # new set of one compound within a single session (Quali's tight ~45min
    # window make multiple fresh sets implausible; even a full FP session
    # rarely uses more than one, matching this project's own understanding
    # of typical practice programmes) — only the first tyre_age_at_start==0
    # stint of a compound within a session counts as a new set; later ones
    # in the same session are treated as re-fitting that same freshly-opened
    # set, not opening another.
    for session_stints in stints_by_session:
        opened_this_session: set[tuple[int, str]] = set()
        for stint in session_stints:
            if stint.get("tyre_age_at_start", 0) != 0:
                continue  # not a new set
            num = stint["driver_number"]
            if num not in inventories:
                continue
            compound = stint.get("compound", "UNKNOWN")
            if compound not in COMPOUNDS:
                continue
            key = (num, compound)
            if key in opened_this_session:
                continue
            opened_this_session.add(key)
            inv = inventories[num]
            inv.used[compound] = inv.used.get(compound, 0) + 1

    # Sort by acronym
    result = sorted(inventories.values(), key=lambda d: d.acronym)
    return result
