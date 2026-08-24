"""
Tyre inventory tracker.

Counts new sets used per driver per compound across all sessions in a
meeting up to the current session, then works out what's actually left for
the race, respecting two constraints simultaneously — get either wrong and
the total is wrong in an obviously-checkable way:
  1. `used` per compound is an observed floor — once a set is opened it
     stays with the driver, so it can only ever be a lower bound.
  2. The TOTAL held (used + new, summed across all three compounds) must
     equal the real race-day pool exactly — not "at most", exactly, since
     the regulation guarantees a fixed number of sets survive to race day
     (see below), no more, no less.

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
Article B6.3.8a.i additionally reserves one set of the mandatory Q3
specification that can't be used or returned before Q3, and any driver who
actually reaches Q3 must hand back a second set of it right after —
leaving Q3 qualifiers with 6 instead of 7.

The regulation doesn't say WHICH compounds the 6 (or 5) in-weekend returns
come from — a team's own choice, unobservable from OpenF1 stint data. Two
earlier versions of this model each got half of the problem right and broke
the other half:
  - v1 split the pool cut PROPORTIONALLY across compounds by allocation
    SIZE. Mathematically kept the total exactly at the pool, but unfairly
    diluted HARD (smallest allocation, 2 sets) even when its own `used` was
    0 — a driver who never touched Hards in practice still showed 0 new
    Hards remaining, because the math didn't know they were untouched, only
    that the shared budget was tight.
  - v2 (reacting to that) gave HARD and MEDIUM their full raw allocation
    UNCONDITIONALLY, with only SOFT absorbing the pool cut. This fixed the
    dilution but broke the total-pool guarantee outright: HARD+MEDIUM then
    ALWAYS sum to their full 2+3=5 regardless of the pool, so a driver with
    any real Soft usage on top routinely showed 8-9 sets total instead of
    6-7 — user-caught immediately, since it's checkable by hand (MEDIUM's
    own new+used exceeding its own 3-set allocation is a plain
    contradiction, not a judgement call).

v3 (current): distribute the pool's leftover "new" budget GREEDILY, LEAST-
USED COMPOUND FIRST, rather than proportionally or unconditionally. A
compound nobody's touched gets first claim on whatever budget remains (so
it isn't diluted just because another compound got heavily used); a
heavily-used compound (usually Soft) absorbs the shortfall once the
untouched ones are satisfied. This provably keeps total = pool exactly
(the whole budget gets allocated, compound by compound, until it's gone or
every compound's own naive remaining is satisfied) while still protecting
untouched compounds the way real teams do — you don't return sets of a
compound you haven't needed yet, you return spares of the one you have.
"""

from __future__ import annotations
from dataclasses import dataclass, field

# Full weekend allocation per driver (Article B6.2.4).
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
    # full weekend allocation (Article B6.2.4)
    allocation: dict[str, int] = field(default_factory=dict)
    # sets left for qualifying + race, total across all compounds
    race_day_pool: int = 7

    def reconciled(self) -> dict[str, dict[str, int]]:
        """{compound: {"used": int, "new": int}}, used+new summing to
        EXACTLY race_day_pool (only less if the driver's own set count,
        after artifact correction, is already under it — see module
        docstring for the two constraints this has to satisfy at once).

        Step 1: used is floored at the compound's own full weekend
        allocation — OpenF1 occasionally double-counts a restart/red-flag-
        split stint as a second fresh set (e.g. observed: 9 "new" SOFT
        stints against an 8-set allocation), which is noise. If the total of
        THAT (still real per-compound `used`, summed) already exceeds the
        pool, that's the same artifact at the aggregate level — reduce
        proportionally across whichever compounds show any usage (rare;
        this only fires when raw usage alone is already implausibly high).

        Step 2: whatever's left of the pool is the "new" budget, handed out
        least-used-compound-first (see module docstring) rather than
        proportionally, so a compound with used=0 is never diluted just
        because a different compound was used heavily.
        """
        naive_used = {c: min(self.used.get(c, 0), self.allocation.get(c, 0))
                      for c in COMPOUNDS}
        total_naive_used = sum(naive_used.values())
        if total_naive_used > self.race_day_pool:
            used = self._proportional_cap(naive_used, self.race_day_pool)
        else:
            used = naive_used
        total_used = sum(used.values())

        # Process compounds in ascending-used GROUPS, not a flat sort — two
        # compounds tied on used (most commonly used=0, both untouched)
        # split their shared slice of the budget proportionally, rather than
        # whichever happens to sort first (SOFT, being first in COMPOUNDS)
        # grabbing the entire remaining budget and leaving the other at 0.
        new_budget = max(0, self.race_day_pool - total_used)
        new = {c: 0 for c in COMPOUNDS}
        by_used: dict[int, list[str]] = {}
        for c in COMPOUNDS:
            by_used.setdefault(used[c], []).append(c)
        for u in sorted(by_used):
            group = by_used[u]
            naive_group_new = {c: max(0, self.allocation.get(c, 0) - used[c]) for c in group}
            group_budget = min(sum(naive_group_new.values()), new_budget)
            allocated = self._proportional_cap(naive_group_new, group_budget)
            for c in group:
                new[c] = allocated[c]
            new_budget -= sum(allocated.values())

        return {c: {"used": used[c], "new": new[c]} for c in COMPOUNDS}

    @staticmethod
    def _proportional_cap(naive: dict[str, int], budget: int) -> dict[str, int]:
        """Scale `naive` down to sum to exactly `budget` (largest remainder
        method). Only used to correct the rare case where raw `used` alone
        already exceeds the pool — see reconciled()'s step 1."""
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
    q3_drivers: driver_numbers that reached Q3 — each has one fewer set in
      the race-day pool (Article B6.3.8a.i). None/empty if unknown; every
      driver then gets the more generous (non-Q3) pool rather than guessing
      wrong.
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
