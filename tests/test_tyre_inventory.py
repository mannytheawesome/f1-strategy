"""
Unit tests for engine.tyre_inventory — synthetic data only, no network.
Each test reconstructs a real scenario debugged against actual OpenF1 data
this session, so a regression here means one of those bugs came back.
"""
import pytest

from conftest import make_driver, make_stint
from engine.tyre_inventory import (
    ALLOCATION, COMPOUNDS, SHORT_STINT_LAPS, compute_inventory,
)

DRIVERS = {1: make_driver(1, "NOR")}


def _inv(stints_by_session, session_is_qualifying=None, is_sprint=False):
    result = compute_inventory(stints_by_session, DRIVERS, is_sprint=is_sprint,
                                session_is_qualifying=session_is_qualifying)
    assert len(result) == 1
    return result[0]


class TestAllocation:
    def test_standard_allocation_values(self):
        assert ALLOCATION["standard"] == {"HARD": 2, "MEDIUM": 3, "SOFT": 8}

    def test_sprint_allocation_values(self):
        # MEDIUM was wrongly 3 in an earlier version — Article B6.2.4's
        # Alternative Format table gives sprint weekends an extra Medium,
        # not an extra Soft.
        assert ALLOCATION["sprint"] == {"HARD": 2, "MEDIUM": 4, "SOFT": 6}

    def test_untouched_driver_gets_full_allocation(self):
        inv = _inv([[]])
        r = inv.reconciled()
        for c in COMPOUNDS:
            assert r[c] == {"used": 0, "new": ALLOCATION["standard"][c]}

    @pytest.mark.parametrize("is_sprint", [False, True])
    def test_used_discarded_new_always_sums_to_allocation(self, is_sprint):
        session = [
            make_stint(1, "SOFT", 1, 3, tyre_age_at_start=0),   # short -> used
            make_stint(1, "SOFT", 4, 20, tyre_age_at_start=3),  # continuation, long
            make_stint(1, "MEDIUM", 21, 22, tyre_age_at_start=0),
        ]
        inv = _inv([session], is_sprint=is_sprint)
        r = inv.reconciled()
        alloc = ALLOCATION["sprint" if is_sprint else "standard"]
        for c in COMPOUNDS:
            total = r[c]["used"] + inv.discarded.get(c, 0) + r[c]["new"]
            assert total == alloc[c]
            assert r[c]["used"] <= alloc[c]
            assert r[c]["new"] >= 0


class TestLengthClassification:
    """The core fix from this session: a set's fate is decided by how many
    laps it actually ran, not by which session it was opened in."""

    def test_short_stint_stays_used_and_available(self):
        session = [make_stint(1, "SOFT", 1, SHORT_STINT_LAPS, tyre_age_at_start=0)]
        inv = _inv([session])
        r = inv.reconciled()
        assert r["SOFT"]["used"] == 1
        assert inv.discarded.get("SOFT", 0) == 0

    def test_long_stint_is_discarded_not_used(self):
        session = [make_stint(1, "SOFT", 1, SHORT_STINT_LAPS + 1, tyre_age_at_start=0)]
        inv = _inv([session])
        r = inv.reconciled()
        assert r["SOFT"]["used"] == 0
        assert inv.discarded.get("SOFT", 0) == 1

    def test_boundary_at_exactly_short_stint_laps_counts_as_short(self):
        session = [make_stint(1, "HARD", 1, SHORT_STINT_LAPS, tyre_age_at_start=0)]
        inv = _inv([session])
        assert inv.reconciled()["HARD"]["used"] == 1


class TestNonQualifyingSessionCap:
    """Real bug (NOR's Hungary 2026 FP1): OpenF1 fragments ONE physical
    tyre into multiple tyre_age_at_start==0 stints across pit-lane in/out
    cycles within a single Practice run. Each fresh flag after the first
    must fold into the same group, not start a new one, or a genuinely
    13-lap worn tyre gets misclassified as three short "fresh" fragments."""

    def test_multiple_fresh_flags_in_one_practice_session_are_one_set(self):
        # Mirrors NOR's real FP1: stints of 2, 3, and 8 laps, all flagged
        # fresh, all really the same physical tyre (13 laps total -> worn).
        session = [
            make_stint(1, "SOFT", 10, 11, tyre_age_at_start=0, stint_number=2),
            make_stint(1, "SOFT", 12, 14, tyre_age_at_start=0, stint_number=3),
            make_stint(1, "SOFT", 19, 26, tyre_age_at_start=0, stint_number=5),
        ]
        inv = _inv([session], session_is_qualifying=[False])
        r = inv.reconciled()
        # One real set, and it's long (13 laps) -> discarded, not used.
        assert r["SOFT"]["used"] == 0
        assert inv.discarded.get("SOFT", 0) == 1

    def test_genuine_continuation_stint_folds_into_same_group(self):
        session = [
            make_stint(1, "SOFT", 1, 4, tyre_age_at_start=0, stint_number=1),
            make_stint(1, "SOFT", 5, 7, tyre_age_at_start=4, stint_number=2),
        ]
        inv = _inv([session], session_is_qualifying=[False])
        r = inv.reconciled()
        assert r["SOFT"]["used"] == 0  # 7 laps total, over the threshold
        assert inv.discarded.get("SOFT", 0) == 1


class TestQualifyingNoCap:
    """Real case (NOR's Hungary 2026 Quali): Q1/Q2/Q3 run under one
    session_key, and a driver can genuinely open a distinct fresh set for
    each segment (plus an extra Q3 attempt). Length alone must separate a
    worn set from several genuinely fresh ones — no per-session cap."""

    def test_three_independent_short_groups_all_count_as_used(self):
        session = [
            make_stint(1, "SOFT", 1, 4, tyre_age_at_start=0, stint_number=1),
            make_stint(1, "SOFT", 5, 7, tyre_age_at_start=4, stint_number=2),  # Q1, worn (7 laps)
            make_stint(1, "SOFT", 8, 10, tyre_age_at_start=0, stint_number=3),   # Q2, short
            make_stint(1, "SOFT", 11, 13, tyre_age_at_start=0, stint_number=4),  # Q3 attempt 1
            make_stint(1, "SOFT", 14, 16, tyre_age_at_start=0, stint_number=5),  # Q3 attempt 2
        ]
        inv = _inv([session], session_is_qualifying=[True])
        r = inv.reconciled()
        assert r["SOFT"]["used"] == 3
        assert inv.discarded.get("SOFT", 0) == 1

    def test_qualifying_group_count_not_capped_at_three(self):
        # Four independent short groups should all count -- there is no
        # inherent ceiling, unlike the old session-count-based model. Uses
        # SOFT (allocation 8) so the allocation floor itself (tested
        # separately below) doesn't mask what's being checked here.
        session = [
            make_stint(1, "SOFT", 1, 3, tyre_age_at_start=0, stint_number=1),
            make_stint(1, "SOFT", 4, 6, tyre_age_at_start=0, stint_number=2),
            make_stint(1, "SOFT", 7, 9, tyre_age_at_start=0, stint_number=3),
            make_stint(1, "SOFT", 10, 12, tyre_age_at_start=0, stint_number=4),
        ]
        inv = _inv([session], session_is_qualifying=[True])
        assert inv.reconciled()["SOFT"]["used"] == 4


class TestAllocationNeverExceeded:
    """Real bug (NOR/VER/LAW on a real cached race): MEDIUM new+used
    summed to more than the compound's own 3-set allocation -- a plain
    arithmetic contradiction. Must be impossible by construction now."""

    def test_used_floored_at_allocation_even_with_excess_raw_opens(self):
        # Five independent short "opens" of a compound with only a 3-set
        # allocation -- reconciled() must still floor used at 3, not 5.
        session = [
            make_stint(1, "MEDIUM", 1, 2, tyre_age_at_start=0, stint_number=1),
            make_stint(1, "MEDIUM", 3, 4, tyre_age_at_start=0, stint_number=2),
            make_stint(1, "MEDIUM", 5, 6, tyre_age_at_start=0, stint_number=3),
            make_stint(1, "MEDIUM", 7, 8, tyre_age_at_start=0, stint_number=4),
            make_stint(1, "MEDIUM", 9, 10, tyre_age_at_start=0, stint_number=5),
        ]
        inv = _inv([session], session_is_qualifying=[True])
        r = inv.reconciled()
        assert r["MEDIUM"]["used"] <= ALLOCATION["standard"]["MEDIUM"]
        assert r["MEDIUM"]["new"] >= 0
