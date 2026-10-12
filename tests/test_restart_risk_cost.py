"""
Unit tests for _restart_risk_cost (engine/prerace.py) and restart_delta_for
(engine/restart_delta.py) -- the cold-tyre Safety Car/VSC restart-penalty
EV cost. User-reported (Singapore 2026): a MEDIUM->HARD 1-stop ranked as
a viable strategy candidate despite HARD never being raced there
historically, traced to nothing in this codebase representing a
compound's cold-tyre restart penalty at all.
"""
import pytest

import engine.restart_delta as restart_delta
from engine.prerace import _restart_risk_cost
from engine.restart_delta import restart_delta_for, DEFAULT_RESTART_DELTA_S


@pytest.fixture(autouse=True)
def _no_live_calibration_by_default(monkeypatch):
    # Every test here is about the bootstrap dict / formula in isolation --
    # never let a REAL on-disk calibration file (e.g. one left over from
    # actually running calibrate_restart_delta.py) leak into these.
    # Individual tests that want to exercise the live-calibration path
    # override this with their own monkeypatch.setattr call below.
    monkeypatch.setattr("engine.restart_calibration.load_calibration", lambda: None)
    yield


class TestRestartRiskCost:
    def test_matches_the_documented_formula(self, monkeypatch):
        monkeypatch.setattr(restart_delta, "RESTART_LAP_DELTA_S",
                            {"HARD": 2.0, "MEDIUM": 0.0})

        cost = _restart_risk_cost(["MEDIUM", "HARD"], [30, 32], 62, sc_prob=0.5)
        expected = round(0.5 * ((30 / 62) * 0.0 + (32 / 62) * 2.0), 1)
        assert cost == expected

    def test_zero_sc_probability_means_zero_cost_regardless_of_compound(self, monkeypatch):
        monkeypatch.setattr(restart_delta, "RESTART_LAP_DELTA_S", {"HARD": 5.0})
        cost = _restart_risk_cost(["HARD"], [62], 62, sc_prob=0.0)
        assert cost == 0.0

    def test_uncalibrated_compound_costs_nothing(self, monkeypatch):
        monkeypatch.setattr(restart_delta, "RESTART_LAP_DELTA_S", {})
        cost = _restart_risk_cost(["SOFT", "MEDIUM"], [20, 42], 62, sc_prob=0.8)
        assert cost == 0.0

    def test_a_compound_that_gains_time_produces_a_negative_cost(self, monkeypatch):
        # A negative restart_delta (gains track position/time) should be
        # able to make the whole term a bonus, not just floor at zero --
        # the formula is a straight EV sum, not a one-sided penalty.
        monkeypatch.setattr(restart_delta, "RESTART_LAP_DELTA_S", {"SOFT": -3.0})
        cost = _restart_risk_cost(["SOFT"], [62], 62, sc_prob=1.0)
        assert cost < 0

    def test_empty_plan_or_zero_total_laps_does_not_crash(self):
        assert _restart_risk_cost([], [], 62, sc_prob=0.5) == 0.0
        assert _restart_risk_cost(["SOFT"], [10], 0, sc_prob=0.5) == 0.0


class TestRestartDeltaFor:
    def test_falls_back_to_bootstrap_when_no_live_calibration(self, monkeypatch):
        monkeypatch.setattr(restart_delta, "RESTART_LAP_DELTA_S", {"HARD": 1.5})
        assert restart_delta_for("HARD") == 1.5

    def test_unknown_compound_falls_back_to_default(self, monkeypatch):
        monkeypatch.setattr(restart_delta, "RESTART_LAP_DELTA_S", {})
        assert restart_delta_for("HARD") == DEFAULT_RESTART_DELTA_S

    def test_prefers_live_calibration_over_bootstrap(self, monkeypatch):
        monkeypatch.setattr(restart_delta, "RESTART_LAP_DELTA_S", {"HARD": 1.5})
        monkeypatch.setattr("engine.restart_calibration.load_calibration",
                            lambda: {"by_compound": {"HARD": 9.9}})
        assert restart_delta_for("HARD") == 9.9

    def test_live_calibration_falls_back_to_default_for_a_missing_compound(self, monkeypatch):
        monkeypatch.setattr("engine.restart_calibration.load_calibration",
                            lambda: {"by_compound": {"SOFT": -1.0}})
        assert restart_delta_for("HARD") == DEFAULT_RESTART_DELTA_S
