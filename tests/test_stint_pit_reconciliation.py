"""
Unit tests for data.live._split_stints_on_missing_pit_stops / get_pit_stops --
a real, confirmed data gap found 2026-10-05 comparing this project's own
debrief page against Pirelli's official pit-stop graphic for the 2026
Bahrain GP (meeting 1308, a race with heavy Safety-Car-clustered pit
activity).

OpenF1's `stints` endpoint simply has no row boundary at all for some real,
same-compound pit stops on this race -- confirmed independently against
OpenF1's own separate `pit` endpoint (the real pit-lane timing log) AND
Pirelli's published graphic, both agreeing on stops `stints` was missing
entirely for 4 different drivers checked by hand (the race winner's real
laps-33 and laps-43 stops, among others). Before this fix, `stints` showed
one unbroken 46-lap stint for the winner from lap 10 to the flag; the real
stop count was undercounted by 2.

This is a MISSING-boundary fix only -- it does not second-guess a compound
`stints` already reports for an existing row, only adds a boundary where a
confirmed real pit-lane visit has no stint-row counterpart at all.
"""
from data.live import _split_stints_on_missing_pit_stops


def _stint(driver, compound, lap_start, lap_end, tyre_age=0):
    return {"driver_number": driver, "compound": compound,
            "lap_start": lap_start, "lap_end": lap_end,
            "tyre_age_at_start": tyre_age}


def _pit(driver, lap):
    return {"driver_number": driver, "lap_number": lap}


class TestMissingPitSplit:
    def test_real_winner_shape_two_missing_stops_get_split(self):
        # The actual bug: VER's real race had stops at laps 9, 33, 43, but
        # `stints` only had a boundary for lap 9 -- one 46-lap mega-stint
        # covered laps 10-55 with no row for the other two real stops.
        stints = [
            _stint(3, "INTERMEDIATE", 1, 1),
            _stint(3, "SOFT", 2, 9),
            _stint(3, "SOFT", 10, 55),
        ]
        pits = [_pit(3, 9), _pit(3, 33), _pit(3, 43)]
        result = _split_stints_on_missing_pit_stops(stints, pits)
        shape = sorted((s["compound"], s["lap_start"], s["lap_end"]) for s in result)
        assert shape == [
            ("INTERMEDIATE", 1, 1),
            ("SOFT", 2, 9),
            ("SOFT", 10, 33),
            ("SOFT", 34, 43),
            ("SOFT", 44, 55),
        ]

    def test_split_pieces_get_fresh_tyre_age(self):
        # A real pit visit is strong evidence of a new physical set even
        # when stints never recorded the change -- the second half of a
        # split must not inherit the original stint's growing tyre age.
        stints = [_stint(3, "SOFT", 10, 55, tyre_age=0)]
        pits = [_pit(3, 33)]
        result = _split_stints_on_missing_pit_stops(stints, pits)
        second_half = next(s for s in result if s["lap_start"] == 34)
        assert second_half["tyre_age_at_start"] == 0

    def test_pit_lap_already_matching_a_real_boundary_is_not_re_split(self):
        # A pit that `stints` already correctly reflects (a new stint
        # genuinely starts right after it) must be left completely alone.
        stints = [
            _stint(3, "INTERMEDIATE", 1, 1),
            _stint(3, "SOFT", 2, 55),
        ]
        pits = [_pit(3, 1)]   # already matches stint boundary at lap 2
        result = _split_stints_on_missing_pit_stops(stints, pits)
        assert result == stints

    def test_no_pit_data_is_a_no_op(self):
        stints = [_stint(3, "SOFT", 1, 55)]
        assert _split_stints_on_missing_pit_stops(stints, []) == stints

    def test_unaffected_driver_is_untouched(self):
        # Only the driver(s) with a real, unreflected pit visit should see
        # any change -- a clean driver's stints must pass through exactly.
        stints = [
            _stint(3, "SOFT", 1, 55),      # has a real missing stop
            _stint(12, "SOFT", 1, 20),     # clean, no missing stops
            _stint(12, "MEDIUM", 21, 55),
        ]
        pits = [_pit(3, 30), _pit(12, 20)]   # 12's pit already matches its boundary
        result = _split_stints_on_missing_pit_stops(stints, pits)
        driver_12 = [s for s in result if s["driver_number"] == 12]
        assert driver_12 == [stints[1], stints[2]]

    def test_multiple_drivers_each_reconciled_independently(self):
        stints = [
            _stint(16, "SOFT", 10, 43),
            _stint(6, "SOFT", 10, 44),
        ]
        pits = [_pit(16, 28), _pit(6, 31)]
        result = _split_stints_on_missing_pit_stops(stints, pits)
        lec = sorted((s["lap_start"], s["lap_end"]) for s in result if s["driver_number"] == 16)
        had = sorted((s["lap_start"], s["lap_end"]) for s in result if s["driver_number"] == 6)
        assert lec == [(10, 28), (29, 43)]
        assert had == [(10, 31), (32, 44)]

    def test_pit_near_an_existing_boundary_is_not_re_split(self):
        # Real bug found checking this fix against the full field: a
        # genuine, Pirelli-confirmed lap-33 pit stop was already correctly
        # reflected by an existing stint boundary at lap 35 (one lap later
        # than the naive pit_lap+1=34 check expected -- some of this race's
        # own stint rows land a real stop's boundary a lap or two late). An
        # exact-match check treated lap 33 as still "missing" and inserted
        # a redundant split, fragmenting one real stint into a genuine
        # piece plus a nonsensical 1-lap sliver ending right where the
        # already-correct next stint begins.
        stints = [
            _stint(81, "MEDIUM", 10, 34),
            _stint(81, "HARD", 35, 55),
        ]
        pits = [_pit(81, 33)]
        result = _split_stints_on_missing_pit_stops(stints, pits)
        assert result == stints

    def test_pit_outside_tolerance_within_a_long_stint_still_splits(self):
        # The tolerance guard must not swallow a genuinely-missing split
        # just because it shares a file with a near-boundary one -- a pit
        # lap comfortably inside a stint (nowhere near either edge) still
        # needs its own split.
        stints = [_stint(81, "MEDIUM", 10, 34)]
        pits = [_pit(81, 20)]   # 10 laps from either edge
        result = _split_stints_on_missing_pit_stops(stints, pits)
        shape = sorted((s["lap_start"], s["lap_end"]) for s in result)
        assert shape == [(10, 20), (21, 34)]

    def test_pit_lap_outside_any_stint_span_is_ignored(self):
        # A pit lap that doesn't fall strictly inside any known stint (e.g.
        # pit data slightly misaligned, or a formation-lap artifact) must
        # not raise or fabricate a nonsensical split.
        stints = [_stint(3, "SOFT", 10, 20)]
        pits = [_pit(3, 50)]
        result = _split_stints_on_missing_pit_stops(stints, pits)
        assert result == stints
