"""
Unit tests for engine.pit_loss -- the per-circuit measured pit-loss table
that existed in the codebase (used by backtest_full.py and
audit_strategies.py) but was never wired into the live pre-race pipeline
for non-sprint weekends. build_prerace_data used a flat 22.0s constant
instead, regardless of circuit -- wrong by ~4s at Monaco specifically
(real measured value: 18.1s, n=102 clean stops), which overstates every
extra pit stop's cost and biases the strategy search toward under-
stopping. Fixed by wiring pit_loss_for(circuit) into the non-sprint
fallback branch in engine/prerace.py.
"""
import engine.prerace as prerace
from engine.pit_loss import CIRCUIT_PIT_LOSS, DEFAULT_PIT_LOSS, pit_loss_for


class TestPitLossFor:
    def test_known_circuit_returns_measured_value(self):
        assert pit_loss_for("monaco") == 18.1

    def test_case_insensitive(self):
        assert pit_loss_for("MONACO") == pit_loss_for("monaco")

    def test_alias_matches_canonical_name(self):
        assert pit_loss_for("monaco") == pit_loss_for("monte carlo")

    def test_unknown_circuit_falls_back_to_field_median(self):
        assert pit_loss_for("some-future-circuit-not-in-table") == DEFAULT_PIT_LOSS

    def test_empty_or_none_circuit_falls_back_safely(self):
        assert pit_loss_for("") == DEFAULT_PIT_LOSS
        assert pit_loss_for(None) == DEFAULT_PIT_LOSS

    def test_measured_range_matches_documented_spread(self):
        # Sanity guard on the table itself, not just the lookup function --
        # the module docstring claims a 16.8s-28.3s spread.
        values = CIRCUIT_PIT_LOSS.values()
        assert min(values) == 16.8
        assert max(values) == 28.3


class TestPitLossWiredIntoPrerace:
    """Regression guard for the actual bug: engine/prerace.py must reach
    for the real per-circuit table on a non-sprint weekend, not silently
    fall back to a flat constant that happened to work by coincidence for
    some circuits and be meaningfully wrong for others (Monaco: 22.0 vs
    the real 18.1)."""

    def test_prerace_imports_the_real_per_circuit_lookup(self):
        assert prerace.pit_loss_for is pit_loss_for

    def test_prerace_no_longer_imports_the_flat_constant(self):
        # The bug was reaching for a flat PIT_LOSS constant as the non-
        # sprint fallback instead of the per-circuit table -- assert the
        # import is gone entirely so a future revert can't silently
        # reintroduce the flat fallback without a test noticing.
        assert not hasattr(prerace, "PIT_LOSS")
