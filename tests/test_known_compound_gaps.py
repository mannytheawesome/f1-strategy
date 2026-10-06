"""
Unit tests for the KNOWN_COMPOUND_GAPS fill-in in data.live.get_stints.

Found 2026-10-06 cross-referencing the 2026 Australian GP (meeting 1279,
session 11234) against Pirelli's official pit-stop graphic: 6 drivers'
opening stint has `compound: null` in OpenF1's raw `stints` response (with
tyre_age_at_start=2 -- a used/scrubbed set, not a live-session field still
being backfilled), which the existing sanitiser falls back to "UNKNOWN" for.
Pirelli's graphic confirms MEDIUM for every one of them. KNOWN_COMPOUND_GAPS
fills exactly that gap, keyed by (session_key, driver_number, stint_number)
so it can never override a compound OpenF1 actually reported.
"""
from unittest.mock import patch

from data.live import get_stints, KNOWN_COMPOUND_GAPS


def _raw_stint(driver, stint_number, lap_start, lap_end, compound, tyre_age=0):
    return {"meeting_key": 1279, "session_key": 11234, "driver_number": driver,
            "stint_number": stint_number, "lap_start": lap_start, "lap_end": lap_end,
            "compound": compound, "tyre_age_at_start": tyre_age}


class TestKnownCompoundGaps:
    def test_null_compound_with_a_verified_gap_entry_is_filled(self):
        rows = [
            _raw_stint(10, 1, 1, 10, None, tyre_age=2),
            _raw_stint(10, 2, 11, 57, "HARD", tyre_age=0),
        ]
        with patch("data.live._cached_get", return_value=rows), \
             patch("data.live.get_pit_stops", return_value=[]):
            stints = get_stints(11234)
        first = next(s for s in stints if s["driver_number"] == 10 and s["lap_start"] == 1)
        assert first["compound"] == "MEDIUM"

    def test_null_compound_with_no_gap_entry_still_falls_back_to_unknown(self):
        # A different session/driver/stint combination has no verified entry
        # -- must NOT guess, same as before this fix existed.
        rows = [_raw_stint(999, 1, 1, 10, None, tyre_age=2)]
        with patch("data.live._cached_get", return_value=rows), \
             patch("data.live.get_pit_stops", return_value=[]):
            stints = get_stints(11234)
        assert stints[0]["compound"] == "UNKNOWN"

    def test_a_reported_compound_is_never_overridden_by_the_gap_table(self):
        # Defensive: even if a (session, driver, stint_number) key happened to
        # collide with a gap entry, a real reported compound must win --
        # KNOWN_COMPOUND_GAPS only ever fills a null, never overrides one.
        rows = [_raw_stint(10, 1, 1, 10, "SOFT", tyre_age=0)]
        with patch("data.live._cached_get", return_value=rows), \
             patch("data.live.get_pit_stops", return_value=[]):
            stints = get_stints(11234)
        assert stints[0]["compound"] == "SOFT"

    def test_all_six_verified_australia_entries_are_present_and_medium(self):
        australia_entries = {k: v for k, v in KNOWN_COMPOUND_GAPS.items() if k[0] == 11234}
        assert len(australia_entries) == 6
        assert set(australia_entries.values()) == {"MEDIUM"}
