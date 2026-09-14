"""
Unit tests for /api/next_meeting -- built while redesigning the front page
to show a real upcoming-race hero instead of an empty "select a race"
state. The endpoint previously only ever returned a meeting once one of
its sessions had already run (the "weekend in progress" case) -- a purely
future race with nothing run yet (the normal case for most of a gap
between race weekends) returned nothing at all, which the new hero needs
to render a countdown for. `in_progress` lets the frontend tell the two
cases apart: only load a briefing when it's True.
"""
import api.routers.briefings as briefings


def _session(meeting_key, country, circuit, session_type, session_name,
            date_start, date_end):
    return {"meeting_key": meeting_key, "country_name": country,
            "circuit_short_name": circuit, "session_type": session_type,
            "session_name": session_name, "date_start": date_start,
            "date_end": date_end}


class TestNextMeeting:
    def _patch(self, monkeypatch, sessions):
        monkeypatch.setattr(briefings, "_get", lambda *a, **k: sessions)
        monkeypatch.setattr(briefings, "_cache_get", lambda *a, **k: None)
        monkeypatch.setattr(briefings, "_cache_set", lambda *a, **k: None)

    def test_purely_future_race_returned_with_in_progress_false(self, monkeypatch):
        # No session has run yet -- the gap-between-races case, previously
        # returned nothing at all.
        sessions = [
            _session(1, "Azerbaijan", "Baku", "Race", "Race",
                    "2099-01-05T11:00:00+00:00", "2099-01-05T13:00:00+00:00"),
        ]
        self._patch(monkeypatch, sessions)
        result = briefings.next_meeting(2026)
        assert result["meeting"]["meeting_key"] == 1
        assert result["meeting"]["in_progress"] is False

    def test_in_progress_weekend_returned_with_in_progress_true(self, monkeypatch):
        sessions = [
            _session(1, "Spain", "Madring", "Practice", "Practice 1",
                    "2000-01-01T10:00:00+00:00", "2000-01-01T11:00:00+00:00"),
            _session(1, "Spain", "Madring", "Race", "Race",
                    "2099-01-05T13:00:00+00:00", "2099-01-05T15:00:00+00:00"),
        ]
        self._patch(monkeypatch, sessions)
        result = briefings.next_meeting(2026)
        assert result["meeting"]["meeting_key"] == 1
        assert result["meeting"]["in_progress"] is True
        assert result["meeting"]["completed_sessions"] == ["Practice 1"]

    def test_nearest_upcoming_meeting_wins_regardless_of_progress(self, monkeypatch):
        # An in-progress weekend is always the nearest one chronologically
        # in reality, but the endpoint should still pick strictly by date,
        # not by which one happens to have session data.
        sessions = [
            _session(1, "Azerbaijan", "Baku", "Practice", "Practice 1",
                    "2000-01-01T10:00:00+00:00", "2000-01-01T11:00:00+00:00"),
            _session(1, "Azerbaijan", "Baku", "Race", "Race",
                    "2099-01-05T13:00:00+00:00", "2099-01-05T15:00:00+00:00"),
            _session(2, "Singapore", "Marina Bay", "Race", "Race",
                    "2099-02-01T13:00:00+00:00", "2099-02-01T15:00:00+00:00"),
        ]
        self._patch(monkeypatch, sessions)
        result = briefings.next_meeting(2026)
        assert result["meeting"]["meeting_key"] == 1

    def test_round_number_and_total_rounds_computed(self, monkeypatch):
        sessions = [
            _session(1, "Bahrain", "Sakhir", "Race", "Race",
                    "2000-01-01T13:00:00+00:00", "2000-01-01T15:00:00+00:00"),
            _session(2, "Saudi Arabia", "Jeddah", "Race", "Race",
                    "2000-01-08T13:00:00+00:00", "2000-01-08T15:00:00+00:00"),
            _session(3, "Australia", "Melbourne", "Race", "Race",
                    "2099-01-15T13:00:00+00:00", "2099-01-15T15:00:00+00:00"),
            _session(4, "Japan", "Suzuka", "Race", "Race",
                    "2099-01-22T13:00:00+00:00", "2099-01-22T15:00:00+00:00"),
        ]
        self._patch(monkeypatch, sessions)
        result = briefings.next_meeting(2026)
        assert result["meeting"]["meeting_key"] == 3
        assert result["meeting"]["round_number"] == 3
        assert result["meeting"]["total_rounds"] == 4

    def test_no_upcoming_races_returns_none(self, monkeypatch):
        sessions = [
            _session(1, "Abu Dhabi", "Yas Marina", "Race", "Race",
                    "2000-01-01T13:00:00+00:00", "2000-01-01T15:00:00+00:00"),
        ]
        self._patch(monkeypatch, sessions)
        result = briefings.next_meeting(2026)
        assert result["meeting"] is None

    def test_is_sprint_weekend_flag(self, monkeypatch):
        sessions = [
            _session(1, "Miami", "Miami", "Qualifying", "Sprint Qualifying",
                    "2099-01-03T18:00:00+00:00", "2099-01-03T19:00:00+00:00"),
            _session(1, "Miami", "Miami", "Race", "Sprint",
                    "2099-01-04T18:00:00+00:00", "2099-01-04T19:00:00+00:00"),
            _session(1, "Miami", "Miami", "Race", "Race",
                    "2099-01-05T19:00:00+00:00", "2099-01-05T21:00:00+00:00"),
            _session(2, "Monaco", "Monte Carlo", "Race", "Race",
                    "2099-02-01T13:00:00+00:00", "2099-02-01T15:00:00+00:00"),
        ]
        self._patch(monkeypatch, sessions)
        result = briefings.next_meeting(2026)
        assert result["meeting"]["meeting_key"] == 1
        assert result["meeting"]["is_sprint_weekend"] is True

    def test_sprint_race_session_not_mistaken_for_the_grand_prix(self, monkeypatch):
        sessions = [
            _session(1, "Miami", "Miami", "Race", "Sprint",
                    "2099-01-04T18:00:00+00:00", "2099-01-04T19:00:00+00:00"),
            _session(1, "Miami", "Miami", "Race", "Race",
                    "2099-01-05T19:00:00+00:00", "2099-01-05T21:00:00+00:00"),
        ]
        self._patch(monkeypatch, sessions)
        result = briefings.next_meeting(2026)
        # race_date must come from the real GP, not the sprint
        assert result["meeting"]["race_date"] == "2099-01-05T19:00:00+00:00"
