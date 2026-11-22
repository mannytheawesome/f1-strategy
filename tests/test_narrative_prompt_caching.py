"""
generate_structured_narrative (engine/briefing.py) is called repeatedly with
the exact same ~900-token system prompt (NARRATIVE_SYSTEM/PRERACE_SYSTEM
never vary per-request, only the user message's data pack does) -- up to
4x/weekend on the pre-race side before a separate fix in this same commit
cut that to 1, plus generate_narrative's own automatic tyre-claim-violation
retry re-sending it a second time within one request. Confirms the system
prompt is sent with an Anthropic prompt-caching marker so repeat calls are
billed at the cached (~90% cheaper) rate for that block instead of full
price every time. See CLAUDE.md 2026-11-22.
"""
from unittest.mock import MagicMock, patch

from engine.briefing import generate_structured_narrative


def _fake_response(text='{"ok": true}'):
    response = MagicMock()
    response.stop_reason = "end_turn"
    block = MagicMock()
    block.type = "text"
    block.text = text
    response.content = [block]
    return response


def test_system_prompt_is_sent_with_an_ephemeral_cache_control_marker():
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_response()

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = fake_create

    with patch("anthropic.Anthropic", return_value=fake_client):
        result = generate_structured_narrative(
            {"fake": "pack"}, "system instructions", {"type": "object"}, "task")

    assert result == {"ok": True}
    assert captured["system"] == [{
        "type": "text",
        "text": "system instructions",
        "cache_control": {"type": "ephemeral"},
    }]
