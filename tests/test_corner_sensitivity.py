"""
Unit tests for engine.corner_sensitivity.build_corner_sensitivity -- the
FastF1-backed wet/dry corner grip-sensitivity analysis added 2026-10-08.

Unit tests mock at the fastf1 API boundary (fastf1.get_session and
_apex_speeds) so they exercise only this module's own orchestration logic
(session/circuit-info failure handling, the wet/dry sample-count gating,
and the ranking/canary-liar selection), with no network and no real
telemetry processing. _apex_speeds' own X/Y-proximity apex-finding logic
gets a direct, lighter-weight test using small real pandas fixtures (the
one place real telemetry shape matters) rather than mocking pandas itself.
"""
from unittest.mock import MagicMock, patch

import pandas as pd

from engine.corner_sensitivity import (
    build_corner_sensitivity, _apex_speeds, MIN_SAMPLES_PER_CORNER,
)


def _clean_laps_df(n_wet, n_dry):
    rows = []
    for i in range(n_wet):
        rows.append({"TrackStatus": "1", "LapTime": pd.Timedelta(seconds=100),
                     "PitInTime": pd.NaT, "PitOutTime": pd.NaT, "Compound": "INTERMEDIATE"})
    for i in range(n_dry):
        rows.append({"TrackStatus": "1", "LapTime": pd.Timedelta(seconds=90),
                     "PitInTime": pd.NaT, "PitOutTime": pd.NaT, "Compound": "SOFT"})
    return pd.DataFrame(rows)


def _fake_session(laps_df, corners=None, circuit_info_raises=False, load_raises=False):
    session = MagicMock()
    if load_raises:
        session.load.side_effect = RuntimeError("no session archived yet")
    session.laps = laps_df
    if circuit_info_raises:
        session.get_circuit_info.side_effect = RuntimeError("no circuit map")
    else:
        ci = MagicMock()
        ci.corners = pd.DataFrame(corners or [{"Number": 1, "X": 0.0, "Y": 0.0}])
        session.get_circuit_info.return_value = ci
    return session


class TestBuildCornerSensitivity:
    def test_session_load_failure_returns_none(self):
        session = _fake_session(_clean_laps_df(5, 5), load_raises=True)
        with patch("fastf1.get_session", return_value=session):
            assert build_corner_sensitivity(2026, "Bahrain") is None

    def test_missing_circuit_info_returns_none(self):
        # Confirmed real case: the 2026 Bahrain GP's official Location field
        # reads "Kuala Lumpur", which matches no known FastF1 circuit map.
        session = _fake_session(_clean_laps_df(5, 5), circuit_info_raises=True)
        with patch("fastf1.get_session", return_value=session):
            assert build_corner_sensitivity(2026, "Bahrain") is None

    def test_not_enough_wet_laps_returns_none(self):
        session = _fake_session(_clean_laps_df(1, 10))
        with patch("fastf1.get_session", return_value=session):
            assert build_corner_sensitivity(2026, "Australia") is None

    def test_not_enough_dry_laps_returns_none(self):
        session = _fake_session(_clean_laps_df(10, 1))
        with patch("fastf1.get_session", return_value=session):
            assert build_corner_sensitivity(2026, "Australia") is None

    def test_a_bone_dry_race_with_zero_wet_laps_returns_none(self):
        session = _fake_session(_clean_laps_df(0, 30))
        with patch("fastf1.get_session", return_value=session):
            assert build_corner_sensitivity(2026, "Australia") is None

    def test_successful_ranking_and_canary_liar_selection(self):
        corners = [{"Number": n, "X": float(n * 100), "Y": 0.0} for n in range(1, 6)]
        session = _fake_session(_clean_laps_df(10, 10), corners=corners)

        def fake_apex_speeds(lap_rows, corners):
            compound = lap_rows["Compound"].iloc[0]
            if compound == "SOFT":
                return {1: [200.0]*5, 2: [190.0]*5, 3: [180.0]*5, 4: [170.0]*5, 5: [160.0]*5}
            return {1: [100.0]*5, 2: [185.0]*5, 3: [179.0]*5, 4: [100.0]*5, 5: [159.0]*5}

        with patch("fastf1.get_session", return_value=session), \
             patch("engine.corner_sensitivity._apex_speeds", side_effect=fake_apex_speeds):
            result = build_corner_sensitivity(2026, "Australia")

        assert result is not None
        # Corners 1 and 4 lose the most (50%), 3 and 5 lose almost nothing
        assert result["canary_corners"][0] in (1, 4)
        assert 3 in result["liar_corners"] or 5 in result["liar_corners"]
        by_corner = {c["corner"]: c for c in result["corners"]}
        assert by_corner[1]["loss_pct"] == 50.0
        assert by_corner[3]["loss_pct"] < 1.0

    def test_a_corner_with_too_few_samples_in_one_bucket_is_excluded(self):
        corners = [{"Number": 1, "X": 100.0, "Y": 0.0}, {"Number": 2, "X": 200.0, "Y": 0.0}]
        session = _fake_session(_clean_laps_df(10, 10), corners=corners)

        def fake_apex_speeds(lap_rows, corners):
            compound = lap_rows["Compound"].iloc[0]
            if compound == "SOFT":
                return {1: [200.0]*5, 2: [190.0]*5}
            # corner 2's wet bucket has too few samples -- below MIN_SAMPLES_PER_CORNER
            return {1: [150.0]*5, 2: [180.0]*(MIN_SAMPLES_PER_CORNER - 1)}

        with patch("fastf1.get_session", return_value=session), \
             patch("engine.corner_sensitivity._apex_speeds", side_effect=fake_apex_speeds):
            result = build_corner_sensitivity(2026, "Australia")

        assert result is not None
        corners_in_result = {c["corner"] for c in result["corners"]}
        assert corners_in_result == {1}

    def test_an_unexpected_exception_during_processing_is_caught(self):
        session = _fake_session(_clean_laps_df(10, 10))
        with patch("fastf1.get_session", return_value=session), \
             patch("engine.corner_sensitivity._apex_speeds", side_effect=ValueError("boom")):
            assert build_corner_sensitivity(2026, "Australia") is None


class TestApexSpeeds:
    def _telemetry(self, points):
        # points: (X, Y, Speed) triples
        return pd.DataFrame(points, columns=["X", "Y", "Speed"])

    def test_finds_the_minimum_speed_within_the_radius(self):
        corners = [{"Number": 1, "X": 100.0, "Y": 0.0}]
        # distances from (100,0): 60, 10, 0, 10, 60 metres along X
        tel = self._telemetry([(40, 0, 250), (90, 0, 180), (100, 0, 150),
                               (110, 0, 160), (160, 0, 260)])
        fake_lap = MagicMock()
        fake_lap.get_telemetry.return_value = tel
        lap_rows = MagicMock()
        lap_rows.head.return_value = lap_rows
        lap_rows.iterrows.return_value = [(0, fake_lap)]

        result = _apex_speeds(lap_rows, corners)
        assert result[1] == [150.0]

    def test_a_lap_whose_telemetry_raises_is_skipped_not_fatal(self):
        corners = [{"Number": 1, "X": 100.0, "Y": 0.0}]
        fake_lap_bad = MagicMock()
        fake_lap_bad.get_telemetry.side_effect = RuntimeError("no telemetry")
        fake_lap_good = MagicMock()
        fake_lap_good.get_telemetry.return_value = self._telemetry([(100, 0, 155.0)])
        lap_rows = MagicMock()
        lap_rows.head.return_value = lap_rows
        lap_rows.iterrows.return_value = [(0, fake_lap_bad), (1, fake_lap_good)]

        result = _apex_speeds(lap_rows, corners)
        assert result[1] == [155.0]

    def test_a_corner_with_no_telemetry_in_its_radius_gets_an_empty_list(self):
        corners = [{"Number": 1, "X": 100.0, "Y": 0.0}, {"Number": 2, "X": 5000.0, "Y": 0.0}]
        fake_lap = MagicMock()
        fake_lap.get_telemetry.return_value = self._telemetry([(100, 0, 150.0)])
        lap_rows = MagicMock()
        lap_rows.head.return_value = lap_rows
        lap_rows.iterrows.return_value = [(0, fake_lap)]

        result = _apex_speeds(lap_rows, corners)
        assert result[1] == [150.0]
        assert result[2] == []

    def test_distance_drift_along_the_lap_does_not_corrupt_a_later_corner(self):
        # The real bug found 2026-10-08 (Canada): a point far along the lap
        # but geometrically nowhere near corner 2 must not be picked up just
        # because an (abandoned) 1D along-lap window would have drifted onto
        # it. X/Y proximity must still correctly separate the two corners.
        corners = [{"Number": 1, "X": 0.0, "Y": 0.0}, {"Number": 2, "X": 10000.0, "Y": 0.0}]
        tel = self._telemetry([(0, 0, 120.0), (10000, 0, 90.0)])
        fake_lap = MagicMock()
        fake_lap.get_telemetry.return_value = tel
        lap_rows = MagicMock()
        lap_rows.head.return_value = lap_rows
        lap_rows.iterrows.return_value = [(0, fake_lap)]

        result = _apex_speeds(lap_rows, corners)
        assert result[1] == [120.0]
        assert result[2] == [90.0]
