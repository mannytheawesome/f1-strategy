"""
Unit tests for data/live.py's disk-backed cache layer (L2 under the existing
in-memory dict) -- added so cached OpenF1 data survives a Railway redeploy
instead of being wiped and re-fetched from scratch every time, and so
provably-completed race data (post-race debriefs, the season schedule,
standings) can be cached effectively forever via HIST_TTL_FINAL.
"""
import pytest

import data.live as live


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "_cache", {})
    monkeypatch.setattr(live, "_stale", {})
    monkeypatch.setattr(live, "HTTP_CACHE_DB_PATH", str(tmp_path / "http_cache.db"))
    yield


class TestConstants:
    def test_hist_ttl_final_is_dramatically_longer_than_hist_ttl(self):
        # The whole point of HIST_TTL_FINAL is to be "forever" relative to
        # HIST_TTL's 1-hour default -- a regression that quietly shrinks it
        # back down would silently undo the redeploy/re-fetch savings.
        assert live.HIST_TTL_FINAL > live.HIST_TTL * 1000


class TestDiskPersistence:
    def test_historical_entry_survives_a_simulated_restart(self):
        live._cache_set("k1", {"hello": "world"}, live.HIST_TTL)
        # A restart wipes the in-memory dict but not the disk file.
        live._cache.clear()

        assert live._cache_get("k1") == {"hello": "world"}

    def test_forever_ttl_entry_survives_a_simulated_restart(self):
        live._cache_set("k1", [1, 2, 3], live.HIST_TTL_FINAL)
        live._cache.clear()

        assert live._cache_get("k1") == [1, 2, 3]

    def test_short_lived_live_entries_are_not_persisted_to_disk(self):
        # LIVE_TTL (10s) entries gain nothing from surviving a restart (a
        # redeploy takes far longer than 10s anyway) -- persisting them
        # would just add disk I/O to the hottest, most frequent write path
        # for no benefit.
        live._cache_set("k1", {"live": True}, live.LIVE_TTL)
        live._cache.clear()

        assert live._cache_get("k1") is None

    def test_expired_disk_entry_is_not_served_as_fresh(self):
        # Backdate the fetch time so it's already past its own ttl.
        past = live.time.time() - live.HIST_TTL - 10
        live._disk_set("k1", {"old": True}, past, live.HIST_TTL)
        live._cache.clear()

        assert live._cache_get("k1") is None

    def test_max_age_still_overrides_a_disk_hit(self):
        # _cache_get's freshness contract (reader's max_age wins if
        # stricter) must still hold for entries loaded from disk, not just
        # ones already sitting in memory -- this is the same bug class that
        # once froze the live board mid-race (see _cache_get's docstring).
        # Backdated deliberately (rather than a tiny max_age + real elapsed
        # wall-clock time) so the assertion can't flake on a fast machine.
        ten_seconds_ago = live.time.time() - 10
        live._disk_set("k1", {"v": 1}, ten_seconds_ago, live.HIST_TTL_FINAL)
        live._cache.clear()

        assert live._cache_get("k1", max_age=1) is None

    def test_disk_write_failure_on_non_serialisable_data_does_not_raise(self):
        # _cache_set must never break its caller just because an in-memory
        # object (e.g. containing a custom class instance) can't be
        # JSON-encoded for the disk layer -- the in-memory cache still works.
        class Unserialisable:
            pass

        live._cache_set("k1", Unserialisable(), live.HIST_TTL)   # must not raise
        assert live._cache_get("k1") is not None   # still served from memory


class TestCachedGet:
    def test_cached_get_persists_across_a_restart_for_historical_ttl(self, monkeypatch):
        calls = []

        def fake_get(endpoint, **params):
            calls.append(endpoint)
            return [{"ok": True}]

        monkeypatch.setattr(live, "_get", fake_get)

        first = live._cached_get("laps:999", "laps", live.HIST_TTL_FINAL, session_key=999)
        live._cache.clear()   # simulate a redeploy
        second = live._cached_get("laps:999", "laps", live.HIST_TTL_FINAL, session_key=999)

        assert first == second == [{"ok": True}]
        assert calls == ["laps"]   # only fetched once, not once per "restart"
