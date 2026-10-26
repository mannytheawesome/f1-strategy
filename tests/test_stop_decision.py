"""
Tests for engine.prerace._stop_decision's close_call_caveat -- added after a
2026-10-26 offline sweep of all 81 cached races (see PACK_VERSION 42's
comment in engine/prerace.py) found the model's stop-count call matches the
real race's dominant outcome only 44% of the time when the crossover margin
between the best candidates at two different stop counts is under ~10s --
no better than the ~47/53 base rate of 1-stop vs 2-stop dominant races --
rising to 71-100% once the margin passes ~20s. Below CLOSE_CALL_MARGIN_S the
call is backtested noise, not signal, and should say so rather than present
false confidence.
"""
from engine.prerace import _stop_decision, CLOSE_CALL_MARGIN_S
from engine.predictor import DegCurve

CURVES = {
    "SOFT":   DegCurve("SOFT", 0.15, 100.0, 50, "HIGH", []),
    "MEDIUM": DegCurve("MEDIUM", 0.10, 100.5, 50, "HIGH", []),
    "HARD":   DegCurve("HARD", 0.06, 101.0, 50, "HIGH", []),
}


def _strategy(stops, start_c, seq, total_time, stint_lengths, time_delta=None):
    return {
        "start_compound": start_c, "stops": stops, "compound_sequence": seq,
        "pit_laps": [sum(stint_lengths[:i + 1]) for i in range(len(stint_lengths) - 1)],
        "stint_lengths": stint_lengths, "total_time": total_time,
        "time_delta": time_delta if time_delta is not None else 0.0,
    }


class TestCloseCallCaveat:
    def test_close_margin_gets_flagged(self):
        strategies = [
            _strategy(1, "MEDIUM", ["MEDIUM", "HARD"], 5000.0, [28, 28], time_delta=0.0),
            _strategy(2, "SOFT", ["SOFT", "MEDIUM", "HARD"], 5005.0, [18, 19, 19], time_delta=5.0),
        ]
        sd = _stop_decision(strategies, CURVES, 22.0, 56, "test circuit", 0.1)
        assert sd["close_call_caveat"] is not None
        assert "close" in sd["close_call_caveat"]
        assert "1-stop" in sd["close_call_caveat"]
        assert "2-stop" in sd["close_call_caveat"]

    def test_wide_margin_no_caveat(self):
        strategies = [
            _strategy(1, "MEDIUM", ["MEDIUM", "HARD"], 5000.0, [28, 28], time_delta=0.0),
            _strategy(2, "SOFT", ["SOFT", "MEDIUM", "HARD"], 5030.0, [18, 19, 19], time_delta=30.0),
        ]
        sd = _stop_decision(strategies, CURVES, 22.0, 56, "test circuit", 0.1)
        assert sd["close_call_caveat"] is None

    def test_no_runner_at_different_stop_count_no_caveat(self):
        # Only one stop count represented at all -- no crossover to be close.
        strategies = [
            _strategy(1, "MEDIUM", ["MEDIUM", "HARD"], 5000.0, [28, 28], time_delta=0.0),
            _strategy(1, "SOFT", ["SOFT", "HARD"], 5003.0, [20, 36], time_delta=3.0),
        ]
        sd = _stop_decision(strategies, CURVES, 22.0, 56, "test circuit", 0.1)
        assert sd["crossover"] is None
        assert sd["close_call_caveat"] is None

    def test_margin_exactly_at_threshold_is_not_flagged(self):
        strategies = [
            _strategy(1, "MEDIUM", ["MEDIUM", "HARD"], 5000.0, [28, 28], time_delta=0.0),
            _strategy(2, "SOFT", ["SOFT", "MEDIUM", "HARD"], 5000.0 + CLOSE_CALL_MARGIN_S,
                      [18, 19, 19], time_delta=CLOSE_CALL_MARGIN_S),
        ]
        sd = _stop_decision(strategies, CURVES, 22.0, 56, "test circuit", 0.1)
        assert sd["close_call_caveat"] is None
