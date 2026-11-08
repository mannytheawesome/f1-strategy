"""
Unit tests for data/live.py's get_starting_grid -- added so the pre-race
grid reflects real grid penalties (engine/gearbox changes etc.) instead of
qualifying's own pure lap-time classification, which knows nothing about
them. See CLAUDE.md 2026-11-08 for the real São Paulo 2026 case (VER, HAM,
RUS, LEC all dropped; pole changed from RUS to NOR) this fixed.
"""
import pytest

import data.live as live


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "_cache", {})
    monkeypatch.setattr(live, "_stale", {})
    monkeypatch.setattr(live, "HTTP_CACHE_DB_PATH", str(tmp_path / "http_cache.db"))
    yield


class TestGetStartingGrid:
    def test_maps_driver_number_to_real_post_penalty_position(self, monkeypatch):
        rows = [
            {"position": 1, "driver_number": 1, "meeting_key": 1299, "session_key": 11408},
            {"position": 2, "driver_number": 12, "meeting_key": 1299, "session_key": 11408},
            {"position": 21, "driver_number": 3, "meeting_key": 1299, "session_key": 11408},
        ]
        monkeypatch.setattr(live, "_get", lambda endpoint, **p: rows)
        grid = live.get_starting_grid(11408)
        assert grid == {1: 1, 12: 2, 3: 21}

    def test_rows_missing_position_or_driver_number_are_skipped(self, monkeypatch):
        rows = [
            {"position": 1, "driver_number": 1},
            {"position": None, "driver_number": 5},
            {"driver_number": 7},
        ]
        monkeypatch.setattr(live, "_get", lambda endpoint, **p: rows)
        grid = live.get_starting_grid(11408)
        assert grid == {1: 1}

    def test_returns_empty_dict_on_fetch_failure(self, monkeypatch):
        def boom(endpoint, **p):
            raise RuntimeError("OpenF1 down")
        monkeypatch.setattr(live, "_get", boom)
        assert live.get_starting_grid(11408) == {}

    def test_returns_empty_dict_when_endpoint_has_no_data_yet(self, monkeypatch):
        # Pre-2024 meetings, or a weekend OpenF1 hasn't published this for yet.
        monkeypatch.setattr(live, "_get", lambda endpoint, **p: [])
        assert live.get_starting_grid(11408) == {}
