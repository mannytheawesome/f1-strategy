"""
Regression test for a real production incident: the Anthropic account ran
out of credit, narrative generation failed on every request, and because a
failed narrative was never cached, every single page load re-ran the full
build_prerace_data pipeline AND re-attempted the doomed LLM call --
turning what should be an instant cache hit into a ~50s wait, repeatedly,
for as long as the underlying billing issue lasted.

All the fixtures below mock `_prerace_sources` with a completed, non-sprint
Qualifying session -- i.e. the state where get_prerace_briefing actually
attempts a narrative at all (see TestNarrativeGatedOnQualifying below for
the practice-only, narrative-skipped state these tests are deliberately
past).
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
             patch.object(prerace, "_prerace_sources", return_value=[{"session_key": 999, "session_type": "Qualifying", "session_name": "Qualifying"}]):
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
             patch.object(prerace, "_prerace_sources", return_value=[{"session_key": 999, "session_type": "Qualifying", "session_name": "Qualifying"}]):
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
             patch.object(prerace, "_prerace_sources", return_value=[{"session_key": 999, "session_type": "Qualifying", "session_name": "Qualifying"}]):
            first = prerace.get_prerace_briefing(MEETING_KEY)
            assert "narrative_failed_at" not in first
            prerace.get_prerace_briefing(MEETING_KEY)
            assert calls["build"] == 1  # unchanged: still a normal cache hit
    finally:
        _cleanup()


class TestNarrativeGatedOnQualifying:
    """Before Qualifying completes, `grid` is only a provisional practice-lap
    order (build_prerace_data falls back to the latest session's own
    classification) -- a narrative written off it would be narrating a grid
    that's about to change. This used to still trigger a full LLM call after
    every one of FP1/FP2/FP3 completing (up to 4 calls/weekend before the
    race even ran); it shouldn't attempt one at all until the real grid
    exists. See CLAUDE.md 2026-11-22."""

    def test_no_narrative_attempted_while_only_practice_has_completed(self):
        _cleanup()
        calls = {"build": 0, "narrative": 0}

        def fake_build(meeting_key, total_laps=None):
            calls["build"] += 1
            return {"fake": "pack"}

        def fake_narrative(*args, **kwargs):
            calls["narrative"] += 1
            return {"should": "never run"}

        practice_only = [{"session_key": 1, "session_type": "Practice", "session_name": "Practice 1"},
                          {"session_key": 2, "session_type": "Practice", "session_name": "Practice 2"}]
        try:
            with patch.object(prerace, "build_prerace_data", side_effect=fake_build), \
                 patch.object(prerace, "generate_structured_narrative", side_effect=fake_narrative), \
                 patch.object(prerace, "_prerace_sources", return_value=practice_only):
                briefing = prerace.get_prerace_briefing(MEETING_KEY)
                assert calls["build"] == 1
                assert calls["narrative"] == 0
                assert briefing["narrative"] is None
                assert "narrative_failed_at" not in briefing
        finally:
            _cleanup()

    def test_repeat_request_with_same_practice_sessions_is_a_cache_hit(self):
        # Same sessions as last time, still no Qualifying -- nothing changed
        # that would make attempting a narrative worthwhile, so this should
        # serve the cached pack rather than rebuilding it again.
        _cleanup()
        calls = {"build": 0}

        def fake_build(meeting_key, total_laps=None):
            calls["build"] += 1
            return {"fake": "pack"}

        practice_only = [{"session_key": 1, "session_type": "Practice", "session_name": "Practice 1"}]
        try:
            with patch.object(prerace, "build_prerace_data", side_effect=fake_build), \
                 patch.object(prerace, "generate_structured_narrative") as fake_narrative, \
                 patch.object(prerace, "_prerace_sources", return_value=practice_only):
                prerace.get_prerace_briefing(MEETING_KEY)
                prerace.get_prerace_briefing(MEETING_KEY)
                assert calls["build"] == 1
                fake_narrative.assert_not_called()
        finally:
            _cleanup()

    def test_narrative_attempted_once_qualifying_completes(self):
        # Same meeting, but the next session to complete is the real
        # Qualifying -- source_keys changes, and now a narrative should
        # actually be attempted.
        _cleanup()
        calls = {"narrative": 0}

        def fake_narrative(*args, **kwargs):
            calls["narrative"] += 1
            return {"ok": True}

        practice_only = [{"session_key": 1, "session_type": "Practice", "session_name": "Practice 1"}]
        with_quali = practice_only + [
            {"session_key": 2, "session_type": "Qualifying", "session_name": "Qualifying"}]
        try:
            with patch.object(prerace, "build_prerace_data", return_value={"fake": "pack"}), \
                 patch.object(prerace, "generate_structured_narrative", side_effect=fake_narrative), \
                 patch.object(prerace, "_prerace_sources", return_value=practice_only):
                briefing = prerace.get_prerace_briefing(MEETING_KEY)
                assert calls["narrative"] == 0
                assert briefing["narrative"] is None

            with patch.object(prerace, "build_prerace_data", return_value={"fake": "pack"}), \
                 patch.object(prerace, "generate_structured_narrative", side_effect=fake_narrative), \
                 patch.object(prerace, "_prerace_sources", return_value=with_quali):
                briefing = prerace.get_prerace_briefing(MEETING_KEY)
                assert calls["narrative"] == 1
                assert briefing["narrative"] == {"ok": True}

            # A sprint-weekend's Sprint Qualifying must not count as the
            # real grid-setting session.
            sprint_quali_only = [
                {"session_key": 3, "session_type": "Qualifying", "session_name": "Sprint Qualifying"}]
            with patch.object(prerace, "build_prerace_data", return_value={"fake": "pack"}), \
                 patch.object(prerace, "generate_structured_narrative", side_effect=fake_narrative), \
                 patch.object(prerace, "_prerace_sources", return_value=sprint_quali_only):
                briefing = prerace.get_prerace_briefing(MEETING_KEY)
                assert calls["narrative"] == 1  # unchanged -- not attempted
                assert briefing["narrative"] is None
        finally:
            _cleanup()
