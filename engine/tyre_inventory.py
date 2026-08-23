"""
Tyre inventory tracker.

Counts new sets used per driver per compound across all sessions in a
meeting up to the current session, then works out what's actually left for
the race — both per-compound (against the full weekend allocation) and
against the smaller pool the FIA Sporting Regulations leave available by
race day once mandatory in-weekend returns are accounted for.

Full weekend allocation, FIA 2026 Sporting Regulations Article B6.2.4:
  Standard Format (non-sprint):    Hard 2 / Medium 3 / Soft 8  (13 total)
  Alternative Format (sprint):     Hard 2 / Medium 4 / Soft 6  (12 total)

That 13/12-set figure is NOT what's available by race day, though — Article
B6.3.8a (Standard) and B6.3.9a (Alternative) require teams to electronically
return sets at fixed checkpoints during the weekend, regardless of whether
those sets were ever used:
  Standard:    2 sets back after FP1, 2 more after FP2, 2 more after FP3
               -> 6 of 13 gone before Quali even starts -> 7 remain.
  Alternative: 1 set back after FP1, 1 after the Sprint, 3 after Quali
               -> 5 of 12 gone -> 7 remain (same number, different schedule).
On top of that, Article B6.3.8a.i reserves one set of the mandatory Q3
(softest) specification that can't be used or returned before Q3 — and any
driver who actually reaches Q3 must hand back a second set of that spec
right after, leaving Q3 qualifiers with 6 instead of 7.

The regulation doesn't fix WHICH compounds get returned during the weekend —
that's a team's own choice, and isn't observable from OpenF1 stint data
(which shows what was used, never what was returned unused). What IS
observable — and can't be walked back — is what's already been opened
(`used`): once a set is fitted it stays with the driver, so `used` is a
floor, never reduced. The pool constraint has to land on the "new" (never-
fitted) side instead: new-remaining is capped so `new + used` together never
exceed the real race-day pool, distributing that smaller "new" budget
proportionally across compounds that still show any naive remaining. This is
an approximation of *which* compound absorbs the cut, not a claim
of exact set identity — the total it sums to is the one thing the
regulation actually guarantees.
"""

from __future__ import annotations
from dataclasses import dataclass, field

# Standard allocation per driver per weekend type (Article B6.2.4)
ALLOCATION = {
    "standard": {"HARD": 2, "MEDIUM": 3, "SOFT": 8},
    "sprint":   {"HARD": 2, "MEDIUM": 4, "SOFT": 6},
}

# Sets left for Qualifying + Race after mandatory in-weekend returns
# (Article B6.3.8a / B6.3.9a — see module docstring). One fewer for a driver
# who actually reached Q3 (Article B6.3.8a.i).
RACE_DAY_POOL = {"standard": 7, "sprint": 7}
Q3_POOL_REDUCTION = 1

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
    # sets left for qualifying + race, total across all compounds
    race_day_pool: int = 7

    @staticmethod
    def _proportional_cap(naive: dict[str, int], budget: int) -> dict[str, int]:
        """Scale `naive` down to sum to exactly `budget` if it's currently
        over, split proportionally (largest remainder method so the
        integers land exactly on budget). Returns `naive` unchanged if
        already within budget."""
        total = sum(naive.values())
        if total <= budget or total == 0:
            return dict(naive)
        scale = budget / total
        scaled = {c: v * scale for c, v in naive.items()}
        floors = {c: int(v) for c, v in scaled.items()}
        remainder = budget - sum(floors.values())
        by_frac = sorted(naive, key=lambda c: scaled[c] - floors[c], reverse=True)
        for c in by_frac[:remainder]:
            floors[c] += 1
        return floors

    def reconciled(self) -> dict[str, dict[str, int]]:
        """{compound: {"used": int, "new": int}}, used+new summing to
        race_day_pool (or less only if the driver's own set count, after
        artifact correction, is already under it — see module docstring).

        Two artifacts get corrected here, both already-observed counts that
        can't legitimately exceed a regulation-fixed ceiling:
          1. Per-compound used > that compound's own full allocation (e.g. 9
             "new" SOFT stints against an 8-set allocation) — OpenF1
             occasionally double-counts a restart/red-flag-split stint as a
             second fresh set.
          2. Total used (after #1) > the race-day pool itself — same
             artifact class, just past the smaller, tighter bound.
        used is otherwise a floor, never reduced for any other reason: once
        a set is opened it stays with the driver. Whatever's left of the
        pool after used is the "new" (never-fitted) budget, split across
        compounds proportional to how much of their own allocation is still
        unopened.
        """
        naive_used = {c: min(self.used.get(c, 0), self.allocation.get(c, 0))
                      for c in COMPOUNDS}
        used = self._proportional_cap(naive_used, self.race_day_pool)
        total_used = sum(used.values())

        naive_new = {c: max(0, self.allocation.get(c, 0) - used[c]) for c in COMPOUNDS}
        new_budget = max(0, self.race_day_pool - total_used)
        new = self._proportional_cap(naive_new, new_budget)

        return {c: {"used": used[c], "new": new[c]} for c in COMPOUNDS}

    def remaining(self, compound: str) -> int:
        return self.reconciled().get(compound, {}).get("new", 0)

    def total_held(self, compound: str) -> int:
        """new + used — every set of this compound the driver can legally
        fit for the race (B6.3.3: sets of the same dry-weather specification
        may be mixed after Qualifying, so a used set is just as fittable as
        a new one, not merely a fallback). This is the right figure for
        "can this driver start a strategy on this compound at all" — using
        remaining() (new-only) there undercounts real stock and can make an
        otherwise-legal strategy search find nothing at all."""
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
    q3_drivers: set[int] | None = None,   # driver_numbers known to have reached Q3
) -> list[DriverInventory]:
    """
    Compute tyre inventory for all drivers.

    stints_by_session: stints from each session in the meeting (in chronological order)
    drivers_raw: driver metadata dict (from get_drivers)
    is_sprint: True if sprint weekend (fewer soft sets allocated, different return schedule)
    q3_drivers: driver_numbers that reached Q3 — each has one fewer set in the
      race-day pool (Article B6.3.8a.i). None/empty if unknown; every driver
      then gets the more generous (non-Q3) pool rather than guessing wrong.
    """
    alloc = ALLOCATION["sprint"] if is_sprint else ALLOCATION["standard"]
    base_pool = RACE_DAY_POOL["sprint"] if is_sprint else RACE_DAY_POOL["standard"]
    q3_drivers = q3_drivers or set()

    inventories: dict[int, DriverInventory] = {}

    for num, d in drivers_raw.items():
        pool = base_pool - Q3_POOL_REDUCTION if num in q3_drivers else base_pool
        inventories[num] = DriverInventory(
            driver_number=num,
            acronym=d.get("name_acronym", str(num)),
            team_colour=d.get("team_colour") or "ffffff",
            allocation=dict(alloc),
            race_day_pool=pool,
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
