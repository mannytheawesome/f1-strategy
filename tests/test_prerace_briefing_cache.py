"""
Regression test for a real production incident: the Anthropic account ran
out of credit, narrative generation failed on every request, and because a
failed narrative was never cached, every single page load re-ran the full
build_prerace_data pipeline AND re-attempted the doomed LLM call --
turning what should be an instant cache hit into a ~50s wait, repeatedly,
for as long as the underlying billing issue lasted.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import engine.prerace as prerace

MEETING_KEY = 999999


def _cleanup():
    path = prerace._prerace_cache_path(MEETING_KEY)
    if os.path.exists(path):
        os.remove(path)


def test_failed_narrative_is_cached_and_not_retried_within_cooldown():
    _cleanup()
    calls = {"build": 0, "narrative": 0}

    def fake_build(meeting_key, total_laps=None):
        calls["build"] += 1
        return {"fake": "pack"}

    def fake_narrative(*args, **kwargs):
        calls["narrative"] += 1
        return None  # simulates the Anthropic call failing

    try:
        with patch.object(prerace, "build_prerace_data", side_effect=fake_build), \
             patch.object(prerace, "generate_structured_narrative", side_effect=fake_narrative), \
             patch.object(prerace, "_prerace_sources", return_value=[{"session_key": 999}]):
            first = prerace.get_prerace_briefing(MEETING_KEY)
            assert calls["build"] == 1
            assert calls["narrative"] == 1
            assert first.get("narrative_failed_at") is not None

            second = prerace.get_prerace_briefing(MEETING_KEY)
            # The real bug: this used to re-run the full pipeline every time.
            assert calls["build"] == 1
            assert calls["narrative"] == 1
            assert second["narrative_failed_at"] == first["narrative_failed_at"]
    finally:
        _cleanup()


def test_narrative_retried_after_cooldown_expires():
    _cleanup()
    calls = {"build": 0}

    def fake_build(meeting_key, total_laps=None):
        calls["build"] += 1
        return {"fake": "pack"}

    try:
        with patch.object(prerace, "build_prerace_data", side_effect=fake_build), \
             patch.object(prerace, "generate_structured_narrative", return_value=None), \
             patch.object(prerace, "_prerace_sources", return_value=[{"session_key": 999}]):
            prerace.get_prerace_briefing(MEETING_KEY)
            path = prerace._prerace_cache_path(MEETING_KEY)
            import json
            with open(path) as f:
                cached = json.load(f)
            stale = (datetime.now(timezone.utc)
                     - timedelta(seconds=prerace.NARRATIVE_RETRY_COOLDOWN_S + 60))
            cached["narrative_failed_at"] = stale.isoformat()
            with open(path, "w") as f:
                json.dump(cached, f)

            prerace.get_prerace_briefing(MEETING_KEY)
            assert calls["build"] == 2  # retried, not stuck forever
    finally:
        _cleanup()


def test_successful_narrative_still_cached_normally():
    _cleanup()
    calls = {"build": 0}

    def fake_build(meeting_key, total_laps=None):
        calls["build"] += 1
        return {"fake": "pack"}

    try:
        with patch.object(prerace, "build_prerace_data", side_effect=fake_build), \
             patch.object(prerace, "generate_structured_narrative", return_value={"ok": True}), \
             patch.object(prerace, "_prerace_sources", return_value=[{"session_key": 999}]):
            first = prerace.get_prerace_briefing(MEETING_KEY)
            assert "narrative_failed_at" not in first
            prerace.get_prerace_briefing(MEETING_KEY)
            assert calls["build"] == 1  # unchanged: still a normal cache hit
    finally:
        _cleanup()
