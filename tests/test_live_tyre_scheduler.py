"""
Unit tests for data.live_tyre_scheduler's pure session-window logic --
_live_session_now, which decides whether any session in a season's
calendar is "live" right now. No network, no threads, no asyncio: this is
the one piece of the scheduler that's deterministic given a fixed clock,
so it's tested directly rather than through the background loop.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from data.live_tyre_scheduler import _live_session_now, STARTUP_GRACE_S


def _session(key, start: datetime, end: datetime):
    return {"session_key": key, "date_start": start.isoformat(),
            "date_end": end.isoformat()}


class TestLiveSessionNow:
    def test_session_currently_between_start_and_end_is_live(self):
        now = datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)
        sessions = [_session(1, now - timedelta(minutes=30), now + timedelta(minutes=30))]
        with patch("data.live_tyre_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            result = _live_session_now(sessions)
        assert result is not None
        assert result["session_key"] == 1

    def test_session_in_the_past_is_not_live(self):
        now = datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)
        sessions = [_session(1, now - timedelta(hours=5), now - timedelta(hours=3))]
        with patch("data.live_tyre_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            assert _live_session_now(sessions) is None

    def test_session_in_the_future_beyond_grace_is_not_live(self):
        now = datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)
        sessions = [_session(1, now + timedelta(hours=2), now + timedelta(hours=3))]
        with patch("data.live_tyre_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            assert _live_session_now(sessions) is None

    def test_session_starting_within_the_startup_grace_window_is_live(self):
        now = datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)
        sessions = [_session(1, now + timedelta(seconds=STARTUP_GRACE_S - 10),
                             now + timedelta(hours=1))]
        with patch("data.live_tyre_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            assert _live_session_now(sessions) is not None

    def test_missing_date_fields_are_skipped_not_raised(self):
        sessions = [{"session_key": 1}, {"session_key": 2, "date_start": "bad"}]
        assert _live_session_now(sessions) is None

    def test_naive_datetimes_are_treated_as_utc(self):
        # OpenF1 sometimes returns timestamps with no explicit offset --
        # must still compare correctly against an aware "now".
        now = datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)
        sessions = [{
            "session_key": 1,
            "date_start": (now - timedelta(minutes=10)).replace(tzinfo=None).isoformat(),
            "date_end": (now + timedelta(minutes=10)).replace(tzinfo=None).isoformat(),
        }]
        with patch("data.live_tyre_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            assert _live_session_now(sessions) is not None

    def test_empty_calendar_is_not_live(self):
        assert _live_session_now([]) is None
