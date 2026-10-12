"""
Unit tests for _overtaking_cost (engine/prerace.py) and pass_threshold_for
(engine/overtake_delta.py) -- the overtaking pass-rate threshold, now a
real measurement (engine/overtake_calibration.py) instead of the old
purely-analytical derivation from track_position_weight.
"""
import pytest

import engine.overtake_delta as overtake_delta
from engine.prerace import _overtaking_cost
from engine.overtake_delta import pass_threshold_for, DEFAULT_OVERTAKE_PASS_THRESHOLD_S


@pytest.fixture(autouse=True)
def _no_live_calibration_by_default(monkeypatch):
    # Every test here is about the bootstrap dict / wiring in isolation --
    # never let a REAL on-disk calibration file (e.g. one left over from
    # actually running calibrate_overtake_delta.py) leak into these.
    monkeypatch.setattr("engine.overtake_calibration.load_calibration", lambda: None)
    yield


class TestPassThresholdFor:
    def test_falls_back_to_bootstrap_when_no_live_calibration(self, monkeypatch):
        monkeypatch.setattr(overtake_delta, "OVERTAKE_PASS_THRESHOLD_S", {"monza": 0.9})
        assert pass_threshold_for("monza") == 0.9

    def test_unknown_circuit_falls_back_to_default(self, monkeypatch):
        monkeypatch.setattr(overtake_delta, "OVERTAKE_PASS_THRESHOLD_S", {})
        assert pass_threshold_for("some-new-circuit") == DEFAULT_OVERTAKE_PASS_THRESHOLD_S

    def test_prefers_live_calibration_over_bootstrap(self, monkeypatch):
        monkeypatch.setattr(overtake_delta, "OVERTAKE_PASS_THRESHOLD_S", {"monza": 0.9})
        monkeypatch.setattr("engine.overtake_calibration.load_calibration",
                            lambda: {"by_circuit": {"monza": 1.3}, "default": 1.1})
        assert pass_threshold_for("monza") == 1.3

    def test_live_calibration_falls_back_to_its_own_default_for_a_missing_circuit(self, monkeypatch):
        monkeypatch.setattr("engine.overtake_calibration.load_calibration",
                            lambda: {"by_circuit": {"baku": 0.8}, "default": 1.05})
        assert pass_threshold_for("some-uncalibrated-circuit") == 1.05

    def test_circuit_name_is_lowercased(self, monkeypatch):
        monkeypatch.setattr(overtake_delta, "OVERTAKE_PASS_THRESHOLD_S", {"monza": 0.9})
        assert pass_threshold_for("Monza") == 0.9


class TestOvertakingCost:
    def test_pass_threshold_comes_from_the_calibrated_lookup(self, monkeypatch):
        monkeypatch.setattr(overtake_delta, "OVERTAKE_PASS_THRESHOLD_S", {"monaco": 2.4})
        result = _overtaking_cost(78, "monaco")
        assert result["pass_threshold_s_per_lap"] == 2.4

    def test_unknown_circuit_falls_back_to_the_pooled_default(self, monkeypatch):
        monkeypatch.setattr(overtake_delta, "OVERTAKE_PASS_THRESHOLD_S", {})
        result = _overtaking_cost(60, "some-new-circuit-not-in-the-table")
        assert result["pass_threshold_s_per_lap"] == DEFAULT_OVERTAKE_PASS_THRESHOLD_S

    def test_difficulty_label_still_reflects_street_vs_normal(self, monkeypatch):
        monkeypatch.setattr(overtake_delta, "OVERTAKE_PASS_THRESHOLD_S", {})
        assert _overtaking_cost(78, "monaco")["difficulty"] == "hard"
        assert _overtaking_cost(53, "monza")["difficulty"] == "moderate"

    def test_result_shape_is_unchanged_for_downstream_consumers(self, monkeypatch):
        monkeypatch.setattr(overtake_delta, "OVERTAKE_PASS_THRESHOLD_S", {})
        result = _overtaking_cost(60, "silverstone")
        assert set(result.keys()) == {
            "track_position_weight", "battle_window_laps", "gap_assumed_s",
            "pass_threshold_s_per_lap", "difficulty", "note",
        }
