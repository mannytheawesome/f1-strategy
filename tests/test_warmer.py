"""
Unit tests for data/warmer.py's background cache pre-warming.

User-reported: Baku 2026 FP1 "not showing up" on the live board while FP2
was live -- root cause was a cold cache (nobody had loaded FP1's board
yet that session), and build_state's several sequential OpenF1 calls took
10+ seconds with no loading feedback on the frontend, reading as broken
rather than slow. These tests exercise the warming decision logic in
isolation (no real network, no real threads, no real sleep) -- the
threading itself is a one-line stdlib call, not worth testing.
"""
from datetime import datetime, timedelta, timezone

import pytest

import data.warmer as warmer


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@pytest.fixture(autouse=True)
def _isolated_warmed_set(monkeypatch):
    monkeypatch.setattr(warmer, "_warmed", set())
    yield


def _session(session_key, ended_seconds_ago):
    end = datetime.now(timezone.utc) - timedelta(seconds=ended_seconds_ago)
    return {"session_key": session_key, "date_end": _iso(end)}


class TestWarmsRecentlyCompletedSessions:
    def test_session_ended_within_window_gets_warmed(self, monkeypatch):
        calls = []
        monkeypatch.setattr(warmer, "get_latest_session", lambda: {"meeting_key": 1})
        monkeypatch.setattr(warmer, "_cached_get",
                            lambda *a, **k: [_session(101, ended_seconds_ago=600)])
        monkeypatch.setattr(warmer, "build_state", lambda sk, session=None: calls.append(sk))

        warmer._warm_recent_sessions()
        assert calls == [101]

    def test_session_still_in_the_future_is_skipped(self, monkeypatch):
        calls = []
        future_session = {"session_key": 202,
                          "date_end": _iso(datetime.now(timezone.utc) + timedelta(hours=1))}
        monkeypatch.setattr(warmer, "get_latest_session", lambda: {"meeting_key": 1})
        monkeypatch.setattr(warmer, "_cached_get", lambda *a, **k: [future_session])
        monkeypatch.setattr(warmer, "build_state", lambda sk, session=None: calls.append(sk))

        warmer._warm_recent_sessions()
        assert calls == []

    def test_session_ended_long_ago_outside_window_is_skipped(self, monkeypatch):
        calls = []
        stale = _session(303, ended_seconds_ago=warmer.WARM_WINDOW_S + 3600)
        monkeypatch.setattr(warmer, "get_latest_session", lambda: {"meeting_key": 1})
        monkeypatch.setattr(warmer, "_cached_get", lambda *a, **k: [stale])
        monkeypatch.setattr(warmer, "build_state", lambda sk, session=None: calls.append(sk))

        warmer._warm_recent_sessions()
        assert calls == []

    def test_session_missing_date_end_is_skipped(self, monkeypatch):
        calls = []
        monkeypatch.setattr(warmer, "get_latest_session", lambda: {"meeting_key": 1})
        monkeypatch.setattr(warmer, "_cached_get", lambda *a, **k: [{"session_key": 404}])
        monkeypatch.setattr(warmer, "build_state", lambda sk, session=None: calls.append(sk))

        warmer._warm_recent_sessions()
        assert calls == []


class TestSettledSessionsAreNotRepeatedlyWarmed:
    def test_session_past_settle_threshold_is_marked_warmed(self, monkeypatch):
        monkeypatch.setattr(warmer, "get_latest_session", lambda: {"meeting_key": 1})
        monkeypatch.setattr(warmer, "_cached_get",
                            lambda *a, **k: [_session(101, ended_seconds_ago=warmer.SETTLE_S + 60)])
        monkeypatch.setattr(warmer, "build_state", lambda sk, session=None: None)

        warmer._warm_recent_sessions()
        assert 101 in warmer._warmed

    def test_already_warmed_session_is_not_refetched(self, monkeypatch):
        calls = []
        warmer._warmed.add(101)
        monkeypatch.setattr(warmer, "get_latest_session", lambda: {"meeting_key": 1})
        monkeypatch.setattr(warmer, "_cached_get",
                            lambda *a, **k: [_session(101, ended_seconds_ago=600)])
        monkeypatch.setattr(warmer, "build_state", lambda sk, session=None: calls.append(sk))

        warmer._warm_recent_sessions()
        assert calls == []

    def test_session_still_settling_is_warmed_but_not_yet_marked(self, monkeypatch):
        # Mirrors data.live._ttl_for_session's own short-TTL window -- a
        # session younger than SETTLE_S keeps getting refreshed each tick
        # rather than being considered permanently warm.
        monkeypatch.setattr(warmer, "get_latest_session", lambda: {"meeting_key": 1})
        monkeypatch.setattr(warmer, "_cached_get",
                            lambda *a, **k: [_session(101, ended_seconds_ago=warmer.SETTLE_S - 30)])
        monkeypatch.setattr(warmer, "build_state", lambda sk, session=None: None)

        warmer._warm_recent_sessions()
        assert 101 not in warmer._warmed


class TestFailuresDontCrashTheLoop:
    def test_session_list_fetch_failure_is_swallowed(self, monkeypatch):
        monkeypatch.setattr(warmer, "get_latest_session", lambda: {"meeting_key": 1})

        def boom(*a, **k):
            raise ConnectionError("openf1 down")
        monkeypatch.setattr(warmer, "_cached_get", boom)

        warmer._warm_recent_sessions()   # must not raise

    def test_build_state_failure_for_one_session_is_swallowed_and_not_marked_warmed(self, monkeypatch):
        monkeypatch.setattr(warmer, "get_latest_session", lambda: {"meeting_key": 1})
        monkeypatch.setattr(warmer, "_cached_get",
                            lambda *a, **k: [_session(101, ended_seconds_ago=600)])

        def boom(sk, session=None):
            raise ConnectionError("openf1 down")
        monkeypatch.setattr(warmer, "build_state", boom)

        warmer._warm_recent_sessions()   # must not raise
        assert 101 not in warmer._warmed

    def test_no_meeting_key_is_a_no_op(self, monkeypatch):
        monkeypatch.setattr(warmer, "get_latest_session", lambda: {})
        warmer._warm_recent_sessions()   # must not raise
