"""
Unit tests for the self-hosted site analytics (data/usage.py + the
/api/track and /api/admin/stats endpoints in api/routers/usage.py) --
built for the admin dashboard showing visit counts and which races/features
get used most.
"""
import pytest

import data.usage as usage
import api.routers.usage as usage_router


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Every test gets its own throwaway SQLite file so events from one
    test can never leak into another."""
    monkeypatch.setattr(usage, "DB_PATH", str(tmp_path / "analytics.db"))
    yield


class TestRecordEvent:
    def test_records_a_pageview(self):
        usage.record_event("visitor-1", "pageview", "briefing", None)
        stats = usage.get_stats()
        assert stats["total_events"] == 1
        assert stats["total_visitors"] == 1
        assert stats["pageviews_by_page"] == [{"page": "briefing", "count": 1}]

    def test_missing_visitor_id_or_event_type_is_a_noop(self):
        usage.record_event(None, "pageview", "briefing")
        usage.record_event("visitor-1", None, "briefing")
        stats = usage.get_stats()
        assert stats["total_events"] == 0

    def test_oversized_fields_are_truncated_not_rejected(self):
        # A public, unauthenticated endpoint feeds this -- a hostile or
        # malformed payload must never grow a row (or the DB) unbounded,
        # but a legitimate event with a too-long label should still record.
        usage.record_event("v" * 200, "pageview", "briefing", "x" * 5000)
        stats = usage.get_stats()
        assert stats["total_events"] == 1

    def test_unique_visitors_counted_once_across_multiple_events(self):
        usage.record_event("visitor-1", "pageview", "briefing")
        usage.record_event("visitor-1", "race_view", "briefing", "China")
        usage.record_event("visitor-2", "pageview", "briefing")
        stats = usage.get_stats()
        assert stats["total_visitors"] == 2
        assert stats["total_events"] == 3


class TestGetStats:
    def test_top_races_ranked_by_count(self):
        for _ in range(3):
            usage.record_event("v1", "race_view", "briefing", "Monaco")
        usage.record_event("v2", "race_view", "briefing", "Spain")
        stats = usage.get_stats()
        assert stats["top_races"][0] == {"label": "Monaco", "count": 3}
        assert stats["top_races"][1] == {"label": "Spain", "count": 1}

    def test_top_features_ranked_by_count(self):
        usage.record_event("v1", "feature", "briefing", "whatif_open")
        usage.record_event("v2", "feature", "briefing", "whatif_open")
        usage.record_event("v1", "feature", "briefing", "standings")
        stats = usage.get_stats()
        assert stats["top_features"][0] == {"label": "whatif_open", "count": 2}

    def test_race_views_and_features_dont_leak_into_each_others_rankings(self):
        usage.record_event("v1", "race_view", "briefing", "Monaco")
        usage.record_event("v1", "feature", "briefing", "whatif_open")
        stats = usage.get_stats()
        assert stats["top_races"] == [{"label": "Monaco", "count": 1}]
        assert stats["top_features"] == [{"label": "whatif_open", "count": 1}]

    def test_recent_events_returned_newest_first(self):
        usage.record_event("v1", "pageview", "briefing", None)
        usage.record_event("v1", "race_view", "briefing", "Monaco")
        stats = usage.get_stats()
        assert stats["recent"][0]["event_type"] == "race_view"
        assert stats["recent"][1]["event_type"] == "pageview"


class TestTrackEndpoint:
    def test_track_endpoint_records_a_real_event(self):
        event = usage_router.TrackEvent(visitor_id="v1", event_type="pageview", page="live", label=None)
        usage_router.track(event)
        stats = usage.get_stats()
        assert stats["total_events"] == 1
        assert stats["pageviews_by_page"] == [{"page": "live", "count": 1}]

    def test_track_endpoint_never_raises_on_empty_body(self):
        event = usage_router.TrackEvent()
        usage_router.track(event)   # must not raise
        assert usage.get_stats()["total_events"] == 0


class TestAdminAuth:
    def test_denied_when_admin_token_not_configured(self, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        assert usage_router._admin_allowed("anything") is False
        assert usage_router._admin_allowed(None) is False

    def test_denied_with_wrong_token(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        assert usage_router._admin_allowed("wrong") is False
        assert usage_router._admin_allowed(None) is False

    def test_allowed_with_correct_token(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        assert usage_router._admin_allowed("secret") is True

    def test_admin_stats_endpoint_raises_403_without_valid_token(self, monkeypatch):
        from fastapi import HTTPException
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        usage.record_event("v1", "pageview", "briefing")
        with pytest.raises(HTTPException) as exc:
            usage_router.admin_stats(days=30, x_admin_token="wrong")
        assert exc.value.status_code == 403

    def test_admin_stats_endpoint_returns_data_with_valid_token(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        usage.record_event("v1", "pageview", "briefing")
        result = usage_router.admin_stats(days=30, x_admin_token="secret")
        assert result["total_events"] == 1
