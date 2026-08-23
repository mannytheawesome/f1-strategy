"""
Tyre inventory tracker.

Counts new sets used per driver per compound across all sessions in a
meeting up to the current session, then works out what's actually left for
the race — against each compound's OWN effective allocation, not the full
weekend allocation and not a shared pool split across compounds.

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
specification that can't be used or returned before Q3 — and Article
B6.1.2b defines that spec as "always being the softest of the three". Any
driver who actually reaches Q3 must hand back a second set of it right
after, leaving Q3 qualifiers with 6 instead of 7.

The regulation doesn't literally pin down WHICH compounds the 6 (or 5)
in-weekend returns come from — that's a team's own choice, and isn't
observable from OpenF1 stint data (which shows what was used, never what
was returned unused). But two things push hard in one direction, not spread
evenly across compounds:
  1. Article B6.3.8a.ii separately guarantees 2 sets of the mandatory RACE
     specification(s) can never be returned early at all — Hard and/or
     Medium are typically nominated, never Soft.
  2. Real team practice programmes are soft-heavy (softs see far more FP/
     Quali running and are rarely needed intact for the race) — teams have
     every incentive to give up spare softs at the mandatory checkpoints and
     essentially none to give up hards or mediums they haven't touched.

A first version of this model applied the pool cut PROPORTIONALLY across
whichever compounds still showed unopened sets — mathematically tidy, but
wrong in practice: it favoured diluting SOFT's large 8-set allocation
correctly, but also shaved MEDIUM and HARD in proportion to their much
smaller allocations, so a driver who never touched their Hards in practice
still showed 0 new Hards remaining once the shared pool ran tight. Fixed by
modelling the mandatory returns as landing entirely on SOFT (matching both
regulatory signals above): each compound's EFFECTIVE allocation is fixed
per weekend format, HARD and MEDIUM keep their full raw allocation
unconditionally, and only SOFT's is reduced by the in-weekend return count
(plus the Q3 set, which the regulation itself ties to the softest spec).
"weekend allocation minus in-weekend returns" then sums to exactly the
race-day pool (7, or 6 for Q3) by construction, with no proportional
guesswork needed.
"""

from __future__ import annotations
from dataclasses import dataclass, field

# Full weekend allocation per driver (Article B6.2.4) — used for display
# ("N of M sets") and as the ceiling when flooring the OpenF1 double-count
# artifact (see reconciled() below), not for "remaining" math directly.
ALLOCATION = {
    "standard": {"HARD": 2, "MEDIUM": 3, "SOFT": 8},
    "sprint":   {"HARD": 2, "MEDIUM": 4, "SOFT": 6},
}

# Sets mandatorily returned to the tyre supplier during the weekend
# (Article B6.3.8a / B6.3.9a), before Q3's extra soft — modelled as landing
# entirely on SOFT (see module docstring for why). Standard: 2 after FP1 + 2
# after FP2 + 2 after FP3 = 6. Sprint: 1 after FP1 + 1 after the Sprint + 3
# after Qualifying = 5.
MANDATORY_RETURNS = {"standard": 6, "sprint": 5}

# The Q3 tyre specification is, by regulation, always the softest of the
# three (Article B6.1.2b) — so the extra set a Q3 qualifier must hand back
# (Article B6.3.8a.i) comes off SOFT specifically, not a generic pool unit.
Q3_SOFT_REDUCTION = 1

COMPOUNDS = ["SOFT", "MEDIUM", "HARD"]


def _effective_allocation(allocation: dict[str, int], is_sprint: bool,
                          reached_q3: bool) -> dict[str, int]:
    """Per-compound sets actually available for Qualifying + Race, after
    in-weekend mandatory returns (assumed to land on SOFT — see module
    docstring). HARD and MEDIUM keep their full raw allocation."""
    returns = MANDATORY_RETURNS["sprint"] if is_sprint else MANDATORY_RETURNS["standard"]
    if reached_q3:
        returns += Q3_SOFT_REDUCTION
    eff = dict(allocation)
    eff["SOFT"] = max(0, eff.get("SOFT", 0) - returns)
    return eff


@dataclass
class DriverInventory:
    driver_number: int
    acronym: str
    team_colour: str
    # sets used per compound (new sets opened, tyre_age_at_start == 0)
    used: dict[str, int] = field(default_factory=dict)
    # full weekend allocation (Article B6.2.4) — for display only
    allocation: dict[str, int] = field(default_factory=dict)
    # per-compound sets actually available for qualifying + race, after
    # in-weekend mandatory returns (see _effective_allocation)
    effective_allocation: dict[str, int] = field(default_factory=dict)

    def reconciled(self) -> dict[str, dict[str, int]]:
        """{compound: {"used": int, "new": int}} per compound, independent
        of the other compounds — no shared-pool arithmetic, so a compound
        the driver hasn't touched keeps its full effective allocation as
        "new" regardless of how heavily the others were used.

        used is floored at the compound's own full weekend allocation —
        OpenF1 occasionally double-counts a restart/red-flag-split stint as
        a second fresh set (e.g. observed: 9 "new" SOFT stints against an
        8-set allocation), which is noise, not a real 9th set. Beyond that,
        used is never reduced: once a set is opened it stays with the
        driver. "new" is whatever's left of the EFFECTIVE (post-return)
        allocation once used is subtracted.
        """
        used = {c: min(self.used.get(c, 0), self.allocation.get(c, 0))
                for c in COMPOUNDS}
        new = {c: max(0, self.effective_allocation.get(c, 0) - used[c])
              for c in COMPOUNDS}
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
    q3_drivers: driver_numbers that reached Q3 — each loses one more SOFT set
      (Article B6.3.8a.i). None/empty if unknown; every driver then gets the
      more generous (non-Q3) allocation rather than guessing wrong.
    """
    alloc = ALLOCATION["sprint"] if is_sprint else ALLOCATION["standard"]
    q3_drivers = q3_drivers or set()

    inventories: dict[int, DriverInventory] = {}

    for num, d in drivers_raw.items():
        eff = _effective_allocation(alloc, is_sprint, num in q3_drivers)
        inventories[num] = DriverInventory(
            driver_number=num,
            acronym=d.get("name_acronym", str(num)),
            team_colour=d.get("team_colour") or "ffffff",
            allocation=dict(alloc),
            effective_allocation=eff,
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
