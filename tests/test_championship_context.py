"""
Unit tests for _championship_context (engine/prerace.py) -- the real
championship standing feeding the pre-race pack's `championship` field.
Narrative-only (feeds the_doors' risk/reward framing), same pattern as
_overtaking_cost/recovery_prior -- does not touch the strategy ranking.
"""
import pytest

from engine.prerace import _championship_context


def _grid_row(num, acronym):
    return {"position": 1, "acronym": acronym, "team": "Team",
            "driver_number": num, "team_colour": "#fff", "gap": None}


class TestChampionshipContext:
    def test_builds_per_grid_driver_standing_and_gap_to_leader(self, monkeypatch):
        monkeypatch.setattr(
            "engine.standings.compute_standings",
            lambda year: {"year": year, "drivers": [
                {"driver_number": 1, "acronym": "VER", "points": 300, "position": 1},
                {"driver_number": 4, "acronym": "NOR", "points": 288, "position": 2},
            ], "constructors": []})
        monkeypatch.setattr("engine.standings.season_race_progress",
                            lambda year: {"completed": 20, "total": 24, "remaining": 4})

        grid = [_grid_row(1, "VER"), _grid_row(4, "NOR")]
        out = _championship_context(grid, 2026)

        assert out["races_remaining"] == 4
        assert out["races_completed"] == 20
        by_num = {d["driver_number"]: d for d in out["drivers"]}
        assert by_num[1]["championship_position"] == 1
        assert by_num[1]["points_behind_leader"] == 0.0
        assert by_num[4]["points_behind_leader"] == 12.0

    def test_grid_driver_not_in_standings_is_skipped_not_crashed(self, monkeypatch):
        monkeypatch.setattr(
            "engine.standings.compute_standings",
            lambda year: {"year": year, "drivers": [
                {"driver_number": 1, "acronym": "VER", "points": 300, "position": 1},
            ], "constructors": []})
        monkeypatch.setattr("engine.standings.season_race_progress",
                            lambda year: {"completed": 1, "total": 24, "remaining": 23})

        grid = [_grid_row(1, "VER"), _grid_row(99, "NEW")]
        out = _championship_context(grid, 2026)
        assert [d["driver_number"] for d in out["drivers"]] == [1]

    def test_no_year_returns_none(self):
        assert _championship_context([_grid_row(1, "VER")], None) is None

    def test_empty_standings_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "engine.standings.compute_standings",
            lambda year: {"year": year, "drivers": [], "constructors": []})
        monkeypatch.setattr("engine.standings.season_race_progress",
                            lambda year: {"completed": 0, "total": 24, "remaining": 24})
        assert _championship_context([_grid_row(1, "VER")], 2026) is None

    def test_underlying_failure_returns_none_not_a_crash(self, monkeypatch):
        def boom(year):
            raise RuntimeError("openf1 down")
        monkeypatch.setattr("engine.standings.compute_standings", boom)
        assert _championship_context([_grid_row(1, "VER")], 2026) is None
