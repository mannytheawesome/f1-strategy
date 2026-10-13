"""
Unit tests for engine/standings.py -- season_race_progress (the Grand Prix
round-count logic, sprints excluded) and the shared get_season_sessions
caching (data/live.py). compute_standings itself is already covered by
tests/test_races_and_standings.py's TestStandings (same real computation,
now shared from here).
"""
import pytest

import engine.standings as standings_mod
import data.live as live


@pytest.fixture(autouse=True)
def _isolated_live_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "_cache", {})
    monkeypatch.setattr(live, "_stale", {})
    monkeypatch.setattr(live, "HTTP_CACHE_DB_PATH", str(tmp_path / "http_cache.db"))


def _race(meeting_key, date_end, sprint=False):
    return {"meeting_key": meeting_key, "session_type": "Race",
            "session_name": "Sprint" if sprint else "Race",
            "date_start": date_end, "date_end": date_end,
            "session_key": meeting_key * 10}


class TestSeasonRaceProgress:
    def test_counts_completed_vs_remaining_excluding_sprints(self, monkeypatch):
        sessions = [
            _race(1, "2000-01-01T15:00:00+00:00"),            # completed
            _race(2, "2000-01-08T15:00:00+00:00", sprint=True),  # excluded
            _race(2, "2000-01-08T16:00:00+00:00"),            # completed GP
            _race(3, "2999-01-01T15:00:00+00:00"),            # not yet run
        ]
        monkeypatch.setattr(standings_mod, "_cache_get", lambda *a, **k: None)
        monkeypatch.setattr(standings_mod, "_cache_set", lambda *a, **k: None)
        monkeypatch.setattr(live, "_cache_get", lambda *a, **k: None)
        monkeypatch.setattr(live, "_cache_set", lambda *a, **k: None)
        monkeypatch.setattr(live, "_get", lambda endpoint, **p: sessions)

        progress = standings_mod.season_race_progress(2026)
        assert progress == {"completed": 2, "total": 3, "remaining": 1}

    def test_no_sessions_is_a_safe_zero(self, monkeypatch):
        monkeypatch.setattr(standings_mod, "_cache_get", lambda *a, **k: None)
        monkeypatch.setattr(standings_mod, "_cache_set", lambda *a, **k: None)
        monkeypatch.setattr(live, "_cache_get", lambda *a, **k: None)
        monkeypatch.setattr(live, "_cache_set", lambda *a, **k: None)
        monkeypatch.setattr(live, "_get", lambda endpoint, **p: [])

        assert standings_mod.season_race_progress(2026) == {
            "completed": 0, "total": 0, "remaining": 0}
