"""
Unit tests for engine.corner_sensitivity.build_corner_sensitivity -- the
FastF1-backed corner grip-sensitivity analysis added 2026-10-08, extended
2026-10-08 with a fresh-vs-worn-tyre degradation fallback for races with no
wet-compound running (most races, most of the time -- the original
wet-vs-dry comparison alone only ever produced content for one race all
season).

Unit tests mock at the fastf1 API boundary (fastf1.get_session and
_apex_speeds) so they exercise only this module's own orchestration logic
(session/circuit-info failure handling, which comparison mode is chosen,
the sample-count gating for each, and the ranking/canary-liar selection),
with no network and no real telemetry processing. _apex_speeds' own
X/Y-proximity apex-finding logic gets a direct, lighter-weight test using
small real pandas fixtures (the one place real telemetry shape matters)
rather than mocking pandas itself.
"""
from unittest.mock import MagicMock, patch

import pandas as pd

from engine.corner_sensitivity import (
    build_corner_sensitivity, _apex_speeds, MIN_SAMPLES_PER_CORNER,
    FRESH_MAX_AGE, WORN_MIN_AGE,
)


def _lap_row(compound, tyre_life=0):
    return {"TrackStatus": "1", "LapTime": pd.Timedelta(seconds=100),
            "PitInTime": pd.NaT, "PitOutTime": pd.NaT,
            "Compound": compound, "TyreLife": tyre_life}


def _wet_dry_laps_df(n_wet, n_dry):
    # TyreLife is set well above FRESH_MAX_AGE on the dry side so these rows
    # can't be ambiguously picked up by the shared fake _apex_speeds factory
    # as a "fresh" degradation sample instead of a wet/dry one.
    rows = [_lap_row("INTERMEDIATE", tyre_life=WORN_MIN_AGE + 2) for _ in range(n_wet)]
    rows += [_lap_row("SOFT", tyre_life=WORN_MIN_AGE + 2) for _ in range(n_dry)]
    return pd.DataFrame(rows)


def _degradation_laps_df(n_fresh, n_worn, compound="SOFT"):
    rows = [_lap_row(compound, tyre_life=1) for _ in range(n_fresh)]
    rows += [_lap_row(compound, tyre_life=WORN_MIN_AGE + 5) for _ in range(n_worn)]
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


def _fake_apex_speeds_factory(by_compound_or_life):
    """Returns a stand-in for _apex_speeds keyed on whichever column value
    distinguishes the two buckets being compared (Compound for wet/dry,
    TyreLife for degradation)."""
    def fake(lap_rows, corners):
        if lap_rows.empty:
            return {c["Number"]: [] for c in corners}
        compound = lap_rows["Compound"].iloc[0]
        life = lap_rows["TyreLife"].iloc[0]
        key = ("wet" if compound in ("INTERMEDIATE", "WET")
               else "fresh" if life <= FRESH_MAX_AGE else "dry_or_worn")
        return by_compound_or_life[key]
    return fake


class TestBuildCornerSensitivityWetDry:
    def test_session_load_failure_returns_none(self):
        session = _fake_session(_wet_dry_laps_df(5, 5), load_raises=True)
        with patch("fastf1.get_session", return_value=session):
            assert build_corner_sensitivity(2026, "Bahrain") is None

    def test_missing_circuit_info_returns_none(self):
        # Confirmed real case: the 2026 Bahrain GP's official Location field
        # reads "Kuala Lumpur", which matches no known FastF1 circuit map.
        session = _fake_session(_wet_dry_laps_df(5, 5), circuit_info_raises=True)
        with patch("fastf1.get_session", return_value=session):
            assert build_corner_sensitivity(2026, "Bahrain") is None

    def test_enough_wet_and_dry_laps_uses_wet_dry_mode(self):
        corners = [{"Number": n, "X": float(n * 100), "Y": 0.0} for n in range(1, 4)]
        session = _fake_session(_wet_dry_laps_df(10, 10), corners=corners)
        fake = _fake_apex_speeds_factory({
            "dry_or_worn": {1: [200.0]*5, 2: [190.0]*5, 3: [180.0]*5},
            "wet": {1: [100.0]*5, 2: [185.0]*5, 3: [179.0]*5},
        })
        with patch("fastf1.get_session", return_value=session), \
             patch("engine.corner_sensitivity._apex_speeds", side_effect=fake):
            result = build_corner_sensitivity(2026, "Australia")

        assert result is not None
        assert result["mode"] == "wet_dry"
        assert result["a_label"] == "dry"
        assert result["b_label"] == "wet"
        by_corner = {c["corner"]: c for c in result["corners"]}
        assert by_corner[1]["loss_pct"] == 50.0
        assert result["canary_corners"][0] == 1


class TestBuildCornerSensitivityDegradationFallback:
    def test_zero_wet_laps_falls_back_to_degradation(self):
        corners = [{"Number": n, "X": float(n * 100), "Y": 0.0} for n in range(1, 4)]
        session = _fake_session(_degradation_laps_df(10, 10), corners=corners)
        fake = _fake_apex_speeds_factory({
            "fresh": {1: [200.0]*5, 2: [190.0]*5, 3: [180.0]*5},
            "dry_or_worn": {1: [150.0]*5, 2: [185.0]*5, 3: [179.0]*5},
        })
        with patch("fastf1.get_session", return_value=session), \
             patch("engine.corner_sensitivity._apex_speeds", side_effect=fake):
            result = build_corner_sensitivity(2026, "Australia")

        assert result is not None
        assert result["mode"] == "degradation"
        assert result["a_label"] == "fresh tyres"
        assert result["b_label"] == "worn tyres"
        assert result["compound"] == "SOFT"
        by_corner = {c["corner"]: c for c in result["corners"]}
        assert by_corner[1]["loss_pct"] == 25.0

    def test_holds_compound_constant_using_the_most_run_dry_compound(self):
        corners = [{"Number": 1, "X": 0.0, "Y": 0.0}]
        rows = ([_lap_row("SOFT", tyre_life=1) for _ in range(3)]
               + [_lap_row("SOFT", tyre_life=WORN_MIN_AGE + 2) for _ in range(3)]
               + [_lap_row("HARD", tyre_life=1) for _ in range(20)]
               + [_lap_row("HARD", tyre_life=WORN_MIN_AGE + 2) for _ in range(20)])
        session = _fake_session(pd.DataFrame(rows), corners=corners)
        fake = _fake_apex_speeds_factory({
            "fresh": {1: [200.0]*5},
            "dry_or_worn": {1: [150.0]*5},
        })
        with patch("fastf1.get_session", return_value=session), \
             patch("engine.corner_sensitivity._apex_speeds", side_effect=fake):
            result = build_corner_sensitivity(2026, "Australia")

        # HARD has more total laps (40) than SOFT (6) -- must be the one picked
        assert result is not None
        assert result["compound"] == "HARD"

    def test_not_enough_worn_laps_in_any_mode_returns_none(self):
        # Short stints only (e.g. a red-flag-shortened race) -- never reaches
        # WORN_MIN_AGE, and there's no wet running either.
        rows = [_lap_row("SOFT", tyre_life=i) for i in range(1, 8)] * 5
        session = _fake_session(pd.DataFrame(rows))
        with patch("fastf1.get_session", return_value=session):
            assert build_corner_sensitivity(2026, "Australia") is None

    def test_no_dry_compound_laps_at_all_returns_none(self):
        session = _fake_session(pd.DataFrame([_lap_row("WET", tyre_life=1)] * 10))
        with patch("fastf1.get_session", return_value=session):
            assert build_corner_sensitivity(2026, "Australia") is None

    def test_an_unexpected_exception_during_processing_is_caught(self):
        session = _fake_session(_degradation_laps_df(10, 10))
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
