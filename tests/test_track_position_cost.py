"""
Unit tests for _track_position_cost -- the fix for a user-reported Monaco
2026 strategy bug: after fixing two real deg-curve/pit-loss bugs (see
CLAUDE.md's "twelfth issue"), the pace-only optimizer's top pick became a
2-stop plan, when real strategists are famously conservative at Monaco.
Checked against real data before building this: median stop counts across
48 clean dry races (2023-2026) split cleanly by circuit type -- street
circuits averaged ~1.1 stops, every normal circuit averaged 1.5-2.5.
"""
from engine.prerace import _track_position_cost, POSITION_RISK_SCALE
from engine.circuits import STREET_TRACK_POSITION_WEIGHT, NORMAL_TRACK_POSITION_WEIGHT


class TestTrackPositionCost:
    def test_mandatory_first_stop_is_always_free(self):
        # 1 stop is the mandatory minimum for the 2-compound rule -- no
        # position risk beyond what optimize_strategy's pit_loss already
        # prices in for it.
        assert _track_position_cost(1, "monaco", 18.1) == 0.0
        assert _track_position_cost(1, "monza", 25.5) == 0.0

    def test_zero_stops_is_free_too(self):
        assert _track_position_cost(0, "monaco", 18.1) == 0.0

    def test_extra_stop_costs_more_at_a_street_circuit(self):
        # Same extra-stop count, same pit_loss -- only the circuit type
        # differs, so the whole gap must come from track_position_weight.
        street_cost = _track_position_cost(2, "monaco", 20.0)
        normal_cost = _track_position_cost(2, "monza", 20.0)
        assert street_cost > normal_cost

    def test_cost_scales_with_extra_stops_not_total_stops(self):
        # A 3-stop plan has 2 EXTRA stops beyond the mandatory first one,
        # so its cost should be exactly double a 2-stop plan's (1 extra).
        two_stop = _track_position_cost(2, "monaco", 20.0)
        three_stop = _track_position_cost(3, "monaco", 20.0)
        assert abs(three_stop - 2 * two_stop) < 1e-6

    def test_matches_the_documented_formula(self):
        # Pins the exact formula so a future refactor can't silently change
        # its behaviour without a test noticing.
        cost = _track_position_cost(2, "monaco", 20.0)
        expected = round(1 * STREET_TRACK_POSITION_WEIGHT * 20.0 * POSITION_RISK_SCALE, 1)
        assert cost == expected

    def test_unknown_circuit_falls_back_to_normal_weight(self):
        cost = _track_position_cost(2, "some-new-circuit-not-in-the-table", 20.0)
        expected = round(1 * NORMAL_TRACK_POSITION_WEIGHT * 20.0 * POSITION_RISK_SCALE, 1)
        assert cost == expected
