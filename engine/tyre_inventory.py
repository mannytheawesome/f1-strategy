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

A session's own tracked groups reset per session (each session gets at
most one real group per compound outside Qualifying — see
`compute_inventory`'s comments), but OpenF1's own `stint_number` does NOT
reset per session: a session can open on stint_number 2+, with
`tyre_age_at_start` already nonzero, when the car kept the same physical
tyre across the session boundary. An early version of this model treated
that case — a non-fresh stint with no local group to fold into — as
"continuation of a set opened before this session started, nothing new to
count," and simply dropped its mileage. Confirmed directly against the
official Mexico City 2026 race-morning tyre chart that this undercounted
real consumption for several drivers (Medium read a full set too high).
Now seeded from `tyre_age_at_start` itself — real, independently-reported
cumulative wear, not a reset-to-zero guess — so that mileage isn't lost.
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
# in-lap) and stays available for the race. Longer than this, real wear
# sets in and the set is no longer counted — it's not returned to the
# "new" bucket either, it's just gone from availability, same as if the
# team had discarded it.
#
# Per-compound, not a single shared number: a Madrid 2026 case (HAM/LEC/
# VER each opening Qualifying on a Medium for a 6-lap Q1 stint) first got
# "fixed" by raising one shared constant from 5 to 6 -- which happened to
# be wrong, caught by then actually pulling the real distribution instead
# of tuning on the next anecdote. Qualifying stint data had never been
# cached anywhere in this codebase before (every other caller skips
# Qualifying), so this constant had only ever been checked against
# whichever 1-2 races someone happened to look at. Sampling 30 real
# Qualifying sessions across 2023-2026 (1976 Soft groups, 12 Medium, 3
# Hard) showed why a shared number is wrong: SOFT has a clean two-cluster
# shape -- 3-4 laps (800+543, banker attempts) then a real dip at 5 laps
# (126) before a second, genuinely-more-worn cluster at 6-7 (208+173,
# drivers taking two flying-lap attempts on one set) -- so 5 was already
# correctly calibrated for Soft, and raising it to 6 would have wrongly
# reclassified that whole second cluster as still-fresh. MEDIUM's sample
# is tiny (only 12 in 4 years -- it's rarely used in Qualifying at all)
# and 11 of those 12 were 3-4 laps; Madrid's 6-lap stint is the ONLY 6-lap
# Medium sample in the real data, a genuine outlier rather than the norm,
# but still a real banker-style stint that shouldn't be discarded. HARD
# has essentially no Qualifying sample (n=3, all 2 laps) -- grouped with
# MEDIUM rather than invented a separate number, since compound physics
# says Hard tolerates at least as much mileage as Medium before meaningful
# wear, not less.
SHORT_STINT_LAPS = {"SOFT": 5, "MEDIUM": 6, "HARD": 6}


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


def remap_fp1_substitutes(
    stints: list[dict],
    session_drivers: dict[int, dict],
    primary_drivers: dict[int, dict],
) -> list[dict]:
    """A team's FIA-mandated rookie/reserve outing (nearly always FP1) swaps
    its car's regular driver number for a substitute's for that one session
    -- but it's the same car, same tyre allocation, so sets the substitute
    opens must still count against the regular driver's weekend inventory,
    not vanish from tracking entirely (the substitute's number isn't in
    `primary_drivers` at all, so compute_inventory would otherwise silently
    drop every stint keyed to it).

    Confirmed against real Monza 2026 FP1 data: four teams ran a substitute
    that session (Cadillac/HER for PER, Red Bull/IWA for VER, Williams/BRO
    for ALB, Alpine/ARO for GAS). team_name is the correct pairing key --
    driver-number proximity is NOT reliable: HER (25) actually subs for PER
    (11), not VER (3), despite being numerically closer to VER. Folding
    IWA's FP1 stints into VER correctly dropped his shown HARD availability
    from 2 (our prior, substitute-blind count) to 1, matching F1.com's own
    race-morning tyre chart exactly.
    """
    missing = {num: d for num, d in primary_drivers.items() if num not in session_drivers}
    extra = {num: d for num, d in session_drivers.items() if num not in primary_drivers}
    if not missing or not extra:
        return stints
    remap: dict[int, int] = {}
    for ex_num, ex_d in extra.items():
        team = ex_d.get("team_name")
        candidates = [num for num, d in missing.items() if d.get("team_name") == team]
        if len(candidates) == 1:
            remap[ex_num] = candidates[0]
    if not remap:
        return stints
    out = []
    for s in stints:
        num = s.get("driver_number")
        if num in remap:
            s = dict(s)
            s["driver_number"] = remap[num]
        out.append(s)
    return out


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
    live_flags_by_session: list[dict[int, list[dict]] | None] | None = None,
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
    live_flags_by_session: parallel list to stints_by_session, from
      data.live_timing_feed.load_captured_flags — the GENUINE "New"/used
      flag F1's live timing feed declares per stint, for any session someone
      ran a capture against. None (the entry, or the whole list) means no
      live data for that session, which is the default for every session
      before this existed: falls back to the tyre_age_at_start==0 guess
      exactly as before. Where live data IS available, it replaces the guess
      stint-for-stint (matched positionally — both lists describe the same
      real pit-stop-delimited sequence) rather than approximating it, which
      is what actually fixes the deep-Q3-runner overcount this guess can't:
      a driver refitting an already-scrubbed set for an extra banker lap
      reports tyre_age_at_start==0 same as a genuinely fresh one, but F1's
      own timing system knows the difference even when OpenF1 doesn't.
      Per driver+session, a live list SHORTER than that driver's OpenF1
      stints for the session is trusted for the prefix it actually covers
      (the capture runs from session start and a drop is never retried, so
      a short list is a genuine prefix, not an arbitrary subset) and treats
      everything past that prefix as an unconfirmed continuation rather
      than guessing it's fresh — see the comment at the per-driver
      live_list lookup below for why guessing fresh there was the bug.
      An empty list (connected but never confirmed a single stint) has no
      positional reference at all, so it's treated as no live data.
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
        live_flags = (live_flags_by_session[idx]
                      if live_flags_by_session and idx < len(live_flags_by_session) else None)

        by_driver: dict[int, list[dict]] = {}
        for stint in session_stints:
            num = stint.get("driver_number")
            if num in inventories:
                by_driver.setdefault(num, []).append(stint)

        for num, driver_stints in by_driver.items():
            driver_stints.sort(key=lambda s: s.get("stint_number", 0))
            # Real declared flags for this driver, in the same chronological
            # order as driver_stints -- both describe the same real sequence
            # of pit-stop-delimited stints, so position i in one is position
            # i in the other FOR WHATEVER PREFIX live_list ACTUALLY COVERS.
            # That prefix assumption holds even when live_list is SHORTER
            # than driver_stints, because the capture starts at/before
            # session start (data/live_tyre_scheduler.py's STARTUP_GRACE_S)
            # and a mid-session drop is never retried -- so a short list is
            # a genuine prefix, not an arbitrary subset. Confirmed directly:
            # every driver whose capture covered the WHOLE session that
            # Mexico City 2026 Qualifying (PIA, BEA, SAI, HUL) had the real
            # flag agree with tyre_age_at_start==0 on literally every
            # stint -- OpenF1 isn't fragmenting Qualifying stints the way it
            # does Practice ones, so a prefix match is trustworthy.
            #
            # An empty list means the capture connected but never confirmed
            # even the first stint -- no positional reference at all, same
            # as no capture.
            live_list = (live_flags or {}).get(num) if live_flags else None
            if live_list is not None and len(live_list) == 0:
                live_list = None

            # groups[compound] is a list of accumulated-lap totals, one per
            # physical set opened this session for that compound. Every
            # fresh-flagged stint starts a new group EXCEPT in a non-
            # Qualifying session once one real group already exists for
            # that compound — there, it's folded in as a continuation, same
            # as a non-fresh stint would be (see comment above).
            groups: dict[str, list[int]] = {}
            for i, stint in enumerate(driver_stints):
                compound = stint.get("compound", "UNKNOWN")
                if compound not in COMPOUNDS:
                    continue
                laps = _stint_laps(stint)
                if live_list is not None:
                    if i < len(live_list):
                        is_fresh = bool(live_list[i].get("new"))
                    else:
                        # Past where the capture dropped -- genuinely
                        # unknown, and in Qualifying a wrong "fresh" guess
                        # here is exactly the overcounting bug this exists
                        # to avoid (nothing folds it back down). Treat it as
                        # a continuation of whatever's already open instead:
                        # undercounting a real new stint is far safer than
                        # the inflation it replaces, and by this point in
                        # the sequence a group is already open from the
                        # live-confirmed prefix for any compound actually in
                        # use, so there's no first-stint-of-session case to
                        # lose.
                        is_fresh = False
                else:
                    is_fresh = stint.get("tyre_age_at_start", 0) == 0
                lst = groups.setdefault(compound, [])
                starts_new_group = is_fresh and (is_quali or not lst)
                if starts_new_group:
                    lst.append(laps)
                elif lst:
                    lst[-1] += laps
                else:
                    # A non-fresh stint with no local group to fold into --
                    # OpenF1's stint_number doesn't reset per session (a
                    # session can genuinely open on stint_number 2+, the
                    # car having kept the same physical tyre from the
                    # previous session), so this is real, already-worn
                    # rubber, not nothing. Dropping its mileage entirely
                    # (the old behaviour) undercounted real consumption --
                    # confirmed directly against the official Mexico City
                    # 2026 race-morning tyre chart: several drivers' Medium
                    # count read a full set too HIGH specifically on
                    # sessions shaped like this. tyre_age_at_start is real,
                    # independently-reported cumulative wear (confirmed:
                    # it's often nonzero at a session's first recorded
                    # stint, not silently reset to 0 the way a "no history
                    # before this session" guess would read it) -- seeding
                    # the group with it recovers that history instead of
                    # starting from zero, at the cost of only knowing a
                    # floor on this set's true age if even more of its
                    # history predates what tyre_age_at_start itself
                    # captured.
                    lst.append((stint.get("tyre_age_at_start") or 0) + laps)

            inv = inventories[num]
            for compound, group_laps in groups.items():
                threshold = SHORT_STINT_LAPS.get(compound, 5)
                for total_laps in group_laps:
                    if total_laps <= threshold:
                        inv.used[compound] = inv.used.get(compound, 0) + 1
                    else:
                        inv.discarded[compound] = inv.discarded.get(compound, 0) + 1

    result = sorted(inventories.values(), key=lambda d: d.acronym)
    return result
