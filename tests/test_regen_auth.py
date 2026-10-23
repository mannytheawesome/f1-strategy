"""_regen_allowed must fail closed: regeneration (a paid LLM call) is denied
whenever ADMIN_TOKEN isn't configured, not left open to any visitor. Mirrors
TestAdminAuth in test_usage_analytics.py, which guards the same posture for
api/routers/usage.py's _admin_allowed."""
import api.routers.briefings as briefings_router


class TestRegenAuth:
    def test_denied_when_regenerate_false_regardless_of_token(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        assert briefings_router._regen_allowed(False, "secret") is False
        assert briefings_router._regen_allowed(False, None) is False

    def test_denied_when_admin_token_not_configured(self, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        assert briefings_router._regen_allowed(True, "anything") is False
        assert briefings_router._regen_allowed(True, None) is False

    def test_denied_with_wrong_token(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        assert briefings_router._regen_allowed(True, "wrong") is False
        assert briefings_router._regen_allowed(True, None) is False

    def test_allowed_with_correct_token(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        assert briefings_router._regen_allowed(True, "secret") is True
