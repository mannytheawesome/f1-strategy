"""
Tests for the pre-race briefing charts (pit-strategy Gantt, team pace) and
the grid-construction regression this session found (Cadillac silently
dropped from every chart keyed off `grid`).

Unit tests use synthetic data and run with no network. Integration tests
(marked `integration`, skipped by default -- see pytest.ini) hit real
cached meetings through the full build_prerace_data pipeline, matching how
this session actually validated the fixes.
"""
import pytest

from engine.predictor import DegCurve
from engine.prerace import (
    PIT_WINDOW_MARGIN_S, PIT_WINDOW_MAX_SHIFT, _pit_window, _team_pace,
)


def _curve(compound, deg_rate=0.05, baseline=90.0):
    return DegCurve(compound=compound, deg_rate=deg_rate, baseline=baseline,
                     data_points=20, confidence="HIGH", sessions=["RACE"])


CURVES = {c: _curve(c) for c in ("SOFT", "MEDIUM", "HARD")}


class TestPitWindow:
    def test_window_lo_le_hi(self):
        seq = ["MEDIUM", "HARD"]
        lens = [25, 25]
        w = _pit_window(seq, lens, 0, CURVES, 90.0, 22.0, total_laps=50)
        assert w[0] <= w[1]

    def test_window_capped_at_max_shift_either_side(self):
        # A near-zero deg rate makes the time-vs-shift curve very flat, so
        # the window should hit the hard cap rather than growing unbounded
        # (the exact bug this cap was added for). _pit_window returns
        # absolute lap numbers (boundary + shift), so check width relative
        # to the pit boundary (lens[0] == 25 here), not the raw values.
        flat_curves = {c: _curve(c, deg_rate=0.0001) for c in CURVES}
        seq = ["MEDIUM", "HARD"]
        lens = [25, 25]
        boundary = lens[0]
        w = _pit_window(seq, lens, 0, flat_curves, 90.0, 22.0, total_laps=50)
        assert w[0] - boundary >= -PIT_WINDOW_MAX_SHIFT
        assert w[1] - boundary <= PIT_WINDOW_MAX_SHIFT

    def test_window_never_negative_width(self):
        for total_laps in (30, 50, 70):
            seq = ["SOFT", "MEDIUM"]
            lens = [total_laps // 2, total_laps - total_laps // 2]
            w = _pit_window(seq, lens, 0, CURVES, 90.0, 22.0, total_laps=total_laps)
            assert w[1] - w[0] >= 0


class TestTeamPace:
    GRID = [
        {"acronym": "NOR", "team": "McLaren", "team_colour": "F47600"},
        {"acronym": "HAM", "team": "Ferrari", "team_colour": "ED1131"},
        {"acronym": "BOT", "team": "Cadillac", "team_colour": "909090"},
        {"acronym": "PER", "team": "Cadillac", "team_colour": "909090"},
    ]

    def test_team_with_no_driver_data_gets_no_data_flag_not_omitted(self):
        # The real bug this session found (twice): a team missing pace data
        # must still appear, flagged, not silently vanish from the chart.
        pace_rows = [
            {"acronym": "NOR", "pace_delta": 0.0},
            {"acronym": "HAM", "pace_delta": 0.5},
        ]
        rows = _team_pace(pace_rows, self.GRID, field_baseline=90.0)
        teams = {r["team"] for r in rows}
        assert "Cadillac" in teams
        cadillac_row = next(r for r in rows if r["team"] == "Cadillac")
        assert cadillac_row["no_data"] is True
        assert cadillac_row["gap_s"] is None

    def test_fastest_team_gets_zero_gap(self):
        pace_rows = [
            {"acronym": "NOR", "pace_delta": 0.0},
            {"acronym": "HAM", "pace_delta": 0.5},
        ]
        rows = _team_pace(pace_rows, self.GRID, field_baseline=90.0)
        mclaren = next(r for r in rows if r["team"] == "McLaren")
        assert mclaren["gap_s"] == 0.0

    def test_no_data_teams_sort_after_ranked_teams(self):
        pace_rows = [{"acronym": "NOR", "pace_delta": 0.0}]
        rows = _team_pace(pace_rows, self.GRID, field_baseline=90.0)
        no_data_flags = [r["no_data"] for r in rows]
        # once True starts, it never flips back to False
        assert no_data_flags == sorted(no_data_flags)


@pytest.mark.integration
class TestRealMeetingIntegration:
    """Hits the real OpenF1 API against cached 2026 meetings. Run with
    `pytest -m integration`."""

    HUNGARY_2026 = 1291

    def test_grid_includes_full_22_car_field_not_hardcoded_20(self):
        # Regression test for the Cadillac bug: grid was hardcoded to
        # [:20], a leftover from the pre-2026 20-car field. 2026 added an
        # 11th team (22 cars) -- if both of one team's cars finished
        # outside the old cutoff, the team vanished from every chart keyed
        # off `grid` (team_pace, tyre availability), not even shown as
        # "no data", just silently absent.
        from engine.prerace import build_prerace_data
        pack = build_prerace_data(self.HUNGARY_2026)
        assert len(pack["grid"]) == 22
        teams = {g["team"] for g in pack["grid"]}
        assert "Cadillac" in teams

    def test_cadillac_appears_in_team_pace(self):
        from engine.prerace import build_prerace_data
        pack = build_prerace_data(self.HUNGARY_2026)
        teams = {t["team"] for t in pack["team_pace"]}
        assert "Cadillac" in teams

    def test_strategies_structurally_valid(self):
        from engine.prerace import build_prerace_data
        pack = build_prerace_data(self.HUNGARY_2026)
        strategies = pack["strategies"]
        assert strategies
        deltas = [s["time_delta"] for s in strategies]
        assert deltas == sorted(deltas)
        assert deltas[0] == 0
        for s in strategies:
            assert len(s["compound_sequence"]) == s["stops"] + 1
            assert len(s["pit_windows"]) == s["stops"]
            for j, (lo, hi) in enumerate(s["pit_windows"]):
                assert lo <= hi
                assert lo <= s["pit_laps"][j] <= hi
            assert s["viability"] in ("in play", "needs a Safety Car", "not on the table")
