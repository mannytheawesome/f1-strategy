"""
Tyre inventory tracker.

Counts new sets used per driver per compound across all sessions in a
meeting, classifies each opened set as still race-viable or worn past that
point, then subtracts the worn ones from the full weekend allocation
(Article B6.2.4) to get what's genuinely available for the race.

Full weekend allocation per driver, FIA 2026 Sporting Regulations Article
B6.2.4:
  Standard Format (non-sprint):    Hard 2 / Medium 3 / Soft 8  (13 total)
  Alternative Format (sprint):     Hard 2 / Medium 4 / Soft 6  (12 total)

No shared "race-day pool" ceiling is modelled on top of that — the
mandatory in-weekend electronic returns (Article B6.3.8a/B6.3.9a) exist,
but which specific compounds get handed back at each checkpoint is a
team's own choice and not observable from OpenF1 telemetry, so an earlier
version of this model tried to enforce the resulting 7/6-set totals as a
hard constraint. That produced internally-consistent numbers that didn't
match reality: cross-checked against F1's own race-morning strategy-guide
numbers for the 2026 Hungarian GP, real drivers were shown holding fresh
Hard/Medium sets in reserve well past what a 7-set ceiling would allow.

What DOES matter, also confirmed against that same F1.com reference and
the user's own domain knowledge: a set that's been opened isn't
automatically still race-viable. A Soft fitted for a Qualifying segment
runs maybe 3-4 laps (out-lap, one or two flying laps, in-lap) and is still
essentially fresh; a Soft opened in a Practice session for a longer run
gets meaningfully worn and is no longer something a strategist would count
as available for the race, even though the regulation doesn't force it to
be physically handed back. So each opened set is classified by how many
laps it actually ran (`SHORT_STINT_LAPS`), not just counted as "used."
"""

from __future__ import annotations
from dataclasses import dataclass, field

# Full weekend allocation per driver (Article B6.2.4).
ALLOCATION = {
    "standard": {"HARD": 2, "MEDIUM": 3, "SOFT": 8},
    "sprint":   {"HARD": 2, "MEDIUM": 4, "SOFT": 6},
}

COMPOUNDS = ["SOFT", "MEDIUM", "HARD"]

# A set run for this many laps or fewer in one outing is still essentially
# fresh (a qualifying-style banker-lap stint: out-lap + 1-2 flying laps +
# in-lap, real-world example ~3-4 laps) and stays available for the race.
# Longer than this, real wear sets in and the set is no longer counted —
# it's not returned to the "new" bucket either, it's just gone from
# availability, same as if the team had discarded it. Verified against
# real Hungary 2026 data: NOR's Qualifying soft stints were all 3-4 laps
# (stayed available); his Practice soft stints ran 8-13 laps each (fell
# outside this threshold, correctly dropped from the "used" count that
# would otherwise overstate what he can still fit in the race).
SHORT_STINT_LAPS = 5


@dataclass
class DriverInventory:
    driver_number: int
    acronym: str
    team_colour: str
    # sets opened but still race-viable (short stint so far — see
    # SHORT_STINT_LAPS), per compound
    used: dict[str, int] = field(default_factory=dict)
    # sets opened and run long enough to no longer be race-viable, per
    # compound — consumes allocation but isn't shown as available
    discarded: dict[str, int] = field(default_factory=dict)
    # full weekend allocation (Article B6.2.4)
    allocation: dict[str, int] = field(default_factory=dict)

    def reconciled(self) -> dict[str, dict[str, int]]:
        """{compound: {"used": int, "new": int}}. `used` is opened-but-
        still-viable sets; `new` is the full weekend allocation minus both
        those and the ones worn past SHORT_STINT_LAPS (floored at 0)."""
        out = {}
        for c in COMPOUNDS:
            total = self.allocation.get(c, 0)
            used = min(self.used.get(c, 0), total)
            discarded = min(self.discarded.get(c, 0), total - used)
            new = max(0, total - used - discarded)
            out[c] = {"used": used, "new": new}
        return out

    def remaining(self, compound: str) -> int:
        return self.reconciled().get(compound, {}).get("new", 0)

    def total_held(self, compound: str) -> int:
        """new + used — every set of this compound the driver can legally
        fit for the race (B6.3.3: sets of the same dry-weather specification
        may be mixed after Qualifying, so a used-but-viable set is just as
        fittable as a new one, not merely a fallback). Worn-past-threshold
        (`discarded`) sets are correctly excluded — they're gone, not
        holdable."""
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


def _stint_laps(stint: dict) -> int:
    start = stint.get("lap_start") or 0
    end = stint.get("lap_end") or start
    return max(0, end - start + 1)


# A Practice/Sprint/Race session genuinely gets one new set per compound in
# normal running (confirmed directly: NOR's Hungary 2026 FP1 showed THREE
# separate tyre_age_at_start==0 SOFT stints, but they're pit-lane in/out
# fragments of ONE physical tyre being repeatedly sent back out — treating
# each as its own group would classify a genuinely 13-lap-worn tyre as three
# short "still fresh" fragments instead, the opposite of correct). So a
# session outside Qualifying caps at 1 real group per compound; every
# fresh flag after the first is folded in as a continuation, same as any
# non-fresh stint would be.
#
# Qualifying (main or Sprint Quali) gets no cap at all: it's genuinely three
# elimination segments (Q1/Q2/Q3, or SQ1/SQ2/SQ3) run under one session_key,
# each normally on its own fresh set (confirmed: NOR's Hungary 2026
# Qualifying showed a 7-lap Q1 group followed by three independent 3-lap
# groups — Q2 plus two short Q3 attempts — and SHORT_STINT_LAPS alone
# correctly separates the one worn set from the three still-fresh ones
# without needing to guess how many segments a driver reached).
def compute_inventory(
    stints_by_session: list[list[dict]],   # list of stints lists, one per session
    drivers_raw: dict[int, dict],
    is_sprint: bool = False,
    q3_drivers: set[int] | None = None,   # unused; kept for call-site compat
    session_is_qualifying: list[bool] | None = None,
) -> list[DriverInventory]:
    """
    Compute tyre inventory for all drivers.

    stints_by_session: stints from each session in the meeting (in chronological order)
    drivers_raw: driver metadata dict (from get_drivers)
    is_sprint: True if sprint weekend (fewer soft sets allocated)
    q3_drivers: no longer used to reduce a shared pool (see module
      docstring) — kept as a parameter only so existing call sites don't
      need to change.
    session_is_qualifying: parallel list to stints_by_session — True for a
      session that's Qualifying or Sprint Qualifying, which gets no
      per-session cap on real-tyre groups (see the comment above). None/
      omitted treats every session as non-qualifying (cap of 1), matching
      the old behaviour for callers that don't pass it.
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

    for idx, session_stints in enumerate(stints_by_session):
        is_quali = bool(session_is_qualifying[idx]) if (
            session_is_qualifying and idx < len(session_is_qualifying)) else False

        by_driver: dict[int, list[dict]] = {}
        for stint in session_stints:
            num = stint.get("driver_number")
            if num in inventories:
                by_driver.setdefault(num, []).append(stint)

        for num, driver_stints in by_driver.items():
            driver_stints.sort(key=lambda s: s.get("stint_number", 0))
            # groups[compound] is a list of accumulated-lap totals, one per
            # physical set opened this session for that compound. Every
            # fresh-flagged stint starts a new group EXCEPT in a non-
            # Qualifying session once one real group already exists for
            # that compound — there, it's folded in as a continuation, same
            # as a non-fresh stint would be (see comment above).
            groups: dict[str, list[int]] = {}
            for stint in driver_stints:
                compound = stint.get("compound", "UNKNOWN")
                if compound not in COMPOUNDS:
                    continue
                laps = _stint_laps(stint)
                is_fresh = stint.get("tyre_age_at_start", 0) == 0
                lst = groups.setdefault(compound, [])
                starts_new_group = is_fresh and (is_quali or not lst)
                if starts_new_group:
                    lst.append(laps)
                elif lst:
                    lst[-1] += laps
                # else: continuation of a set opened before this session
                # started (no tracked group) — not one of THIS session's new
                # sets, so it doesn't add mileage to anything we're counting.

            inv = inventories[num]
            for compound, group_laps in groups.items():
                for total_laps in group_laps:
                    if total_laps <= SHORT_STINT_LAPS:
                        inv.used[compound] = inv.used.get(compound, 0) + 1
                    else:
                        inv.discarded[compound] = inv.discarded.get(compound, 0) + 1

    result = sorted(inventories.values(), key=lambda d: d.acronym)
    return result
