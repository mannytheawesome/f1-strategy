"""
Tests for data.live._merge_stint_fragments's stint_number pre-merge, added
after a user-reported tyre-availability mismatch against F1.com's own
race-morning chart for Austin 2026. Several drivers (ANT, HAM, RUS, PIA)
showed 2-3 more SOFT sets than F1.com's chart; traced directly to real
OpenF1 stint rows where ONE physical stint got re-emitted as 2-3 separate
rows sharing the same stint_number, each row re-flagging
tyre_age_at_start=0 (no real pit-lane visit between them). The existing
age-arithmetic merge key only ever caught this for short 1-2 lap slivers
(the restart case its docstring describes); these fragments ran 3-9 laps
each and slipped through, inflating the driver's used-set count by a full
extra set per fragment beyond the first.
"""
from data.live import _merge_stint_fragments


def _row(driver, stint_number, compound, lap_start, lap_end, tyre_age=0):
    return {"driver_number": driver, "stint_number": stint_number,
            "compound": compound, "lap_start": lap_start, "lap_end": lap_end,
            "tyre_age_at_start": tyre_age}


class TestStintNumberPreMerge:
    def test_same_stint_number_fragments_collapse_to_one_row(self):
        # Austin 2026 FP1, ANT's real SOFT stint_number 2: three rows, each
        # re-flagged tyre_age_at_start=0, no pit-lane visit between any of
        # them -- one continuous 15-lap stint, not three new sets.
        rows = [
            _row(12, 2, "SOFT", 11, 14),
            _row(12, 2, "SOFT", 15, 17),
            _row(12, 2, "SOFT", 18, 25),
        ]
        result = _merge_stint_fragments(rows)
        assert len(result) == 1
        assert result[0]["lap_start"] == 11
        assert result[0]["lap_end"] == 25
        assert result[0]["tyre_age_at_start"] == 0

    def test_different_stint_numbers_stay_separate(self):
        # A genuine pit stop (new stint_number) onto a second fresh SOFT
        # must still be counted as its own set.
        rows = [
            _row(12, 1, "SOFT", 1, 6),
            _row(12, 2, "SOFT", 7, 16),
        ]
        result = _merge_stint_fragments(rows)
        assert sorted((s["lap_start"], s["lap_end"]) for s in result) == [(1, 6), (7, 16)]

    def test_missing_stint_number_does_not_wrongly_merge(self):
        # Two genuinely different stints that both lack a real stint_number
        # (sanitised to the 0 fallback) must NOT be merged into one just
        # because they share that fallback value.
        rows = [
            {"driver_number": 12, "stint_number": 0, "compound": "SOFT",
             "lap_start": 1, "lap_end": 6, "tyre_age_at_start": 0},
            {"driver_number": 12, "stint_number": 0, "compound": "SOFT",
             "lap_start": 20, "lap_end": 25, "tyre_age_at_start": 0},
        ]
        result = _merge_stint_fragments(rows)
        assert len(result) == 2

    def test_restart_slivers_from_the_docstring_example_still_merge(self):
        # Pre-existing behaviour must survive: short slivers around a
        # restart, each its own stint_number (a real pit-lane visit during
        # a red flag), still collapse via the age-arithmetic/sliver path.
        rows = [
            _row(1, 5, "HARD", 37, 66, tyre_age=0),
            _row(1, 6, "HARD", 67, 67, tyre_age=0),
            _row(1, 7, "HARD", 68, 68, tyre_age=0),
            _row(1, 8, "HARD", 69, 70, tyre_age=32),
        ]
        result = _merge_stint_fragments(rows)
        assert len(result) == 1
        assert result[0]["lap_start"] == 37
        assert result[0]["lap_end"] == 70
