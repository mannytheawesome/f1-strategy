"""
Tests for engine.prerace._strategy_win_rates -- the Monte Carlo,
probability-weighted companion to _stop_decision's deterministic time-delta
comparison, added 2026-10-08. Forces the pole sitter onto each candidate
strategy in turn (via _run_projection's override_start/prescribed_strategies)
and reads off the win/podium probabilities the SAME Monte Carlo pass
simulate_race always runs internally.

Unit tests mock _run_projection (a real race simulation otherwise) so they
exercise only _strategy_win_rates' own candidate-selection and extraction
logic, with no network and no real simulation cost.
"""
from unittest.mock import patch

from engine.prerace import _strategy_win_rates, STRATEGY_WIN_RATE_CANDIDATES
from engine.predictor import DriverForecast, DriverStrategy, PitPlan


def _strategy(stops, start_c, pit_laps, seq):
    return {"stops": stops, "start_compound": start_c, "pit_laps": pit_laps,
            "compound_sequence": seq, "total_time": 0.0, "time_delta": 0.0}


def _forecast(driver_number, win=0.0, podium=0.0, mean_finish=10.0):
    return DriverForecast(
        driver_number=driver_number, acronym=f"D{driver_number}",
        current_position=1, predicted_position=1, predicted_gap=0.0,
        confidence="HIGH",
        strategy=DriverStrategy(
            driver_number=driver_number, acronym=f"D{driver_number}", current_lap=0,
            current_compound="SOFT", current_age=0, pits_remaining=[],
            total_time_from_now=0.0, laps_until_must_pit=None, confidence="HIGH"),
        undercut=None, win_probability=win, podium_probability=podium,
        mean_finish=mean_finish)


GRID = [{"position": 1, "acronym": "VER", "driver_number": 1},
        {"position": 2, "acronym": "LEC", "driver_number": 16}]
PACE_ROWS = [{"driver_number": 1, "acronym": "VER", "pace_delta": 0.0, "laps_counted": 10}]


class TestStrategyWinRates:
    def test_no_grid_or_no_strategies_returns_none(self):
        assert _strategy_win_rates([], PACE_ROWS, {}, [], 50, 22.0, "test") is None
        assert _strategy_win_rates(GRID, PACE_ROWS, {}, [], 50, 22.0, "test") is None

    def test_picks_the_pole_sitter_as_the_reference_driver(self):
        strategies = [_strategy(1, "MEDIUM", [25], ["MEDIUM", "HARD"])]
        captured = {}

        def fake_run_projection(grid, pace_rows, curves, strats, total_laps, pit_loss,
                                circuit, inventory=None, rain_probability=0.0,
                                override_start=None, prescribed_strategies=None):
            captured["override_start"] = override_start
            captured["prescribed_strategies"] = prescribed_strategies
            return [_forecast(1, win=0.4, podium=0.7, mean_finish=3.2)]

        with patch("engine.prerace._run_projection", side_effect=fake_run_projection):
            result = _strategy_win_rates(GRID, PACE_ROWS, {}, strategies, 50, 22.0, "test")

        assert result["acronym"] == "VER"
        assert captured["override_start"] == {1: "MEDIUM"}
        assert 1 in captured["prescribed_strategies"]

    def test_candidate_results_are_extracted_correctly(self):
        strategies = [_strategy(1, "MEDIUM", [25], ["MEDIUM", "HARD"])]

        def fake_run_projection(*a, **kw):
            return [_forecast(1, win=0.512345, podium=0.834, mean_finish=3.456)]

        with patch("engine.prerace._run_projection", side_effect=fake_run_projection):
            result = _strategy_win_rates(GRID, PACE_ROWS, {}, strategies, 50, 22.0, "test")

        c = result["candidates"][0]
        assert c["stops"] == 1
        assert c["compound_sequence"] == ["MEDIUM", "HARD"]
        assert c["win_probability"] == 0.512
        assert c["podium_probability"] == 0.834
        assert c["mean_finish"] == 3.46

    def test_only_up_to_the_candidate_cap_is_simulated(self):
        strategies = [_strategy(s, "MEDIUM", [25], ["MEDIUM", "HARD"]) for s in range(1, 10)]
        calls = []

        def fake_run_projection(*a, **kw):
            calls.append(1)
            return [_forecast(1, win=0.3)]

        with patch("engine.prerace._run_projection", side_effect=fake_run_projection):
            _strategy_win_rates(GRID, PACE_ROWS, {}, strategies, 50, 22.0, "test")

        assert len(calls) == STRATEGY_WIN_RATE_CANDIDATES

    def test_a_candidate_whose_simulation_raises_is_skipped_not_fatal(self):
        strategies = [
            _strategy(1, "MEDIUM", [25], ["MEDIUM", "HARD"]),
            _strategy(2, "SOFT", [15, 35], ["SOFT", "MEDIUM", "HARD"]),
        ]
        call_count = {"n": 0}

        def fake_run_projection(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ValueError("simulation failed")
            return [_forecast(1, win=0.6, podium=0.9, mean_finish=2.1)]

        with patch("engine.prerace._run_projection", side_effect=fake_run_projection):
            result = _strategy_win_rates(GRID, PACE_ROWS, {}, strategies, 50, 22.0, "test")

        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["stops"] == 2

    def test_reference_driver_missing_from_forecasts_is_skipped(self):
        strategies = [_strategy(1, "MEDIUM", [25], ["MEDIUM", "HARD"])]

        def fake_run_projection(*a, **kw):
            return [_forecast(999, win=0.5)]   # not the pole sitter's number

        with patch("engine.prerace._run_projection", side_effect=fake_run_projection):
            result = _strategy_win_rates(GRID, PACE_ROWS, {}, strategies, 50, 22.0, "test")

        assert result is None

    def test_all_candidates_failing_returns_none(self):
        strategies = [_strategy(1, "MEDIUM", [25], ["MEDIUM", "HARD"])]

        def fake_run_projection(*a, **kw):
            raise ValueError("boom")

        with patch("engine.prerace._run_projection", side_effect=fake_run_projection):
            result = _strategy_win_rates(GRID, PACE_ROWS, {}, strategies, 50, 22.0, "test")

        assert result is None

    def test_pit_plans_are_built_from_pit_laps_and_sequence(self):
        strategies = [_strategy(2, "SOFT", [15, 35], ["SOFT", "MEDIUM", "HARD"])]
        captured = {}

        def fake_run_projection(grid, pace_rows, curves, strats, total_laps, pit_loss,
                                circuit, inventory=None, rain_probability=0.0,
                                override_start=None, prescribed_strategies=None):
            captured["plans"] = prescribed_strategies[1]
            return [_forecast(1, win=0.4)]

        with patch("engine.prerace._run_projection", side_effect=fake_run_projection):
            _strategy_win_rates(GRID, PACE_ROWS, {}, strategies, 50, 22.0, "test")

        plans = captured["plans"]
        assert [p.lap for p in plans] == [15, 35]
        assert [p.compound for p in plans] == ["MEDIUM", "HARD"]
