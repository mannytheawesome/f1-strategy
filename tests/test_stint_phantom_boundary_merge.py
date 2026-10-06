"""
Unit tests for data.live._merge_stints_without_matching_pit_stop -- the
inverse of _split_stints_on_missing_pit_stops, found 2026-10-06 while
investigating a user report that Hamilton's real 31-lap opening SOFT stint
in the 2026 Bahrain GP (meeting 1308) showed as SOFT(1)+MEDIUM(2-31) in
`stints`.

Root cause: that race's formation lap was red-flagged, and teams freely
swapped tyres on the grid during the ~48 minute stoppage -- no pit lane
involved, so `stints` records each grid-side swap as its own row with no
matching entry in `pit` (the real pit-lane timing log). Cross-checked the
whole field against Pirelli's own published pit-stop graphic: 20 of 22
drivers had at least one such phantom boundary, and merging every boundary
with no real pit-lane visit within tolerance brought the field's total stop
count to exactly 73 -- an exact match for `pit`'s own independent total.
"""
from data.live import _merge_stints_without_matching_pit_stop


def _stint(driver, compound, lap_start, lap_end, tyre_age=0):
    return {"driver_number": driver, "compound": compound,
            "lap_start": lap_start, "lap_end": lap_end,
            "tyre_age_at_start": tyre_age}


def _pit(driver, lap):
    return {"driver_number": driver, "lap_number": lap}


class TestPhantomBoundaryMerge:
    def test_single_phantom_boundary_merges_into_earlier_compound(self):
        # Hamilton's real case: SOFT(1)+MEDIUM(2-31) in `stints`, but no real
        # pit-lane visit anywhere near lap 1-2 (his real stops were 31, 43) --
        # Pirelli and the real pit log both show one continuous 31-lap SOFT
        # stint. The merge must keep SOFT (the earlier compound), not MEDIUM.
        stints = [
            _stint(44, "SOFT", 1, 1),
            _stint(44, "MEDIUM", 2, 31),
            _stint(44, "MEDIUM", 32, 43),
            _stint(44, "SOFT", 44, 55),
        ]
        pits = [_pit(44, 31), _pit(44, 43)]
        result = _merge_stints_without_matching_pit_stop(stints, pits)
        shape = sorted((s["compound"], s["lap_start"], s["lap_end"]) for s in result)
        assert shape == [
            ("MEDIUM", 32, 43),
            ("SOFT", 1, 31),
            ("SOFT", 44, 55),
        ]

    def test_multiple_phantom_boundaries_all_collapse_to_the_earliest_compound(self):
        # Colapinto's real case: three slivers (SOFT/MEDIUM/HARD) in the
        # first 9 laps with no matching pit-lane visit anywhere near them --
        # Pirelli shows one continuous 9-lap SOFT stint.
        stints = [
            _stint(43, "SOFT", 1, 1),
            _stint(43, "MEDIUM", 2, 2),
            _stint(43, "HARD", 3, 9),
            _stint(43, "MEDIUM", 10, 31),
        ]
        pits = [_pit(43, 9), _pit(43, 31)]
        result = _merge_stints_without_matching_pit_stop(stints, pits)
        shape = sorted((s["compound"], s["lap_start"], s["lap_end"]) for s in result)
        assert shape == [("MEDIUM", 10, 31), ("SOFT", 1, 9)]

    def test_merged_stint_keeps_the_earlier_tyre_age(self):
        stints = [
            _stint(44, "SOFT", 1, 1, tyre_age=0),
            _stint(44, "MEDIUM", 2, 31, tyre_age=0),
        ]
        pits = [_pit(44, 31)]
        result = _merge_stints_without_matching_pit_stop(stints, pits)
        merged = next(s for s in result if s["lap_start"] == 1)
        assert merged["compound"] == "SOFT"
        assert merged["lap_end"] == 31
        assert merged["tyre_age_at_start"] == 0

    def test_nearest_match_does_not_let_one_pit_lap_confirm_two_boundaries(self):
        # Leclerc's real case: SOFT(1)-INTERMEDIATE(2,3) has an unconfirmed
        # boundary at lap 1, and a GENUINELY confirmed real stop at lap 3
        # (matching the INTERMEDIATE(2,3)->SOFT(4,9) boundary). Lap 3 is
        # within tolerance of BOTH boundaries (1 and 3) -- a naive
        # "any boundary within tolerance" check would confirm both and leave
        # the real lap-1 phantom split standing. Only the lap-1 boundary
        # should merge; the genuine lap-3 stop, and LEC's real second
        # compound, must survive untouched.
        stints = [
            _stint(16, "SOFT", 1, 1),
            _stint(16, "INTERMEDIATE", 2, 3),
            _stint(16, "SOFT", 4, 9),
            _stint(16, "SOFT", 10, 28),
        ]
        pits = [_pit(16, 3), _pit(16, 9), _pit(16, 28)]
        result = _merge_stints_without_matching_pit_stop(stints, pits)
        shape = sorted((s["compound"], s["lap_start"], s["lap_end"]) for s in result)
        assert shape == [
            ("SOFT", 1, 3),
            ("SOFT", 4, 9),
            ("SOFT", 10, 28),
        ]

    def test_nearest_match_prefers_the_closer_boundary_when_laps_are_tight(self):
        # Bortoleto's real case: SOFT(1)-INTERMEDIATE(2,2) has an unconfirmed
        # boundary at lap 1, and a genuine real stop at lap 2 (matching the
        # INTERMEDIATE(2,2)->SOFT(3,9) boundary exactly). Both boundaries (1
        # and 2) sit within tolerance of the lap-2 pit, but lap 2 is an exact
        # match for the second boundary and must not be spent on the first.
        stints = [
            _stint(5, "SOFT", 1, 1),
            _stint(5, "INTERMEDIATE", 2, 2),
            _stint(5, "SOFT", 3, 9),
        ]
        pits = [_pit(5, 2), _pit(5, 9)]
        result = _merge_stints_without_matching_pit_stop(stints, pits)
        shape = sorted((s["compound"], s["lap_start"], s["lap_end"]) for s in result)
        assert shape == [("SOFT", 1, 2), ("SOFT", 3, 9)]

    def test_boundary_confirmed_by_a_real_pit_stop_is_left_alone(self):
        # A genuine, pit-log-confirmed compound change must never be merged
        # away, even if it's short -- this is what keeps this fix distinct
        # from the earlier, rejected "trust the first entry" rule.
        stints = [
            _stint(16, "SOFT", 1, 3),
            _stint(16, "INTERMEDIATE", 4, 9),
        ]
        pits = [_pit(16, 3)]
        result = _merge_stints_without_matching_pit_stop(stints, pits)
        assert result == stints

    def test_no_pit_data_is_a_no_op(self):
        stints = [_stint(44, "SOFT", 1, 1), _stint(44, "MEDIUM", 2, 31)]
        assert _merge_stints_without_matching_pit_stop(stints, []) == stints

    def test_single_stint_driver_is_a_no_op(self):
        stints = [_stint(77, "SOFT", 1, 7)]
        result = _merge_stints_without_matching_pit_stop(stints, [_pit(77, 5)])
        assert result == stints

    def test_unaffected_driver_is_untouched(self):
        stints = [
            _stint(44, "SOFT", 1, 1),
            _stint(44, "MEDIUM", 2, 31),
            _stint(12, "INTERMEDIATE", 1, 9),
            _stint(12, "MEDIUM", 10, 33),
        ]
        pits = [_pit(44, 31), _pit(12, 9), _pit(12, 33)]
        result = _merge_stints_without_matching_pit_stop(stints, pits)
        driver_12 = sorted(
            (s["compound"], s["lap_start"], s["lap_end"])
            for s in result if s["driver_number"] == 12
        )
        assert driver_12 == [("INTERMEDIATE", 1, 9), ("MEDIUM", 10, 33)]

    def test_multiple_drivers_each_reconciled_independently(self):
        stints = [
            _stint(44, "SOFT", 1, 1),
            _stint(44, "MEDIUM", 2, 31),
            _stint(43, "SOFT", 1, 1),
            _stint(43, "MEDIUM", 2, 2),
            _stint(43, "HARD", 3, 9),
        ]
        pits = [_pit(44, 31), _pit(43, 9)]
        result = _merge_stints_without_matching_pit_stop(stints, pits)
        ham = sorted((s["compound"], s["lap_start"], s["lap_end"])
                     for s in result if s["driver_number"] == 44)
        col = sorted((s["compound"], s["lap_start"], s["lap_end"])
                     for s in result if s["driver_number"] == 43)
        assert ham == [("SOFT", 1, 31)]
        assert col == [("SOFT", 1, 9)]
