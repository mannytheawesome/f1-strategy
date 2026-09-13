"""
Regression tests for pace_bias_std / run_monte_carlo's pace-uncertainty fix.

Built 2026-09-13 after backtest_prerace_projection.py measured the pre-race
lap-0 projection at a 14% winner-hit rate across 14 real 2026 races, with
the model's top pick given 70-90% win probability almost every time and the
actual winner given ~0% in most misses (Madrid GP: HUL given a #2 win-
probability slot off an 11-lap Practice-1-only sample; the actual winner
ANT, on a 6-lap sample, given ~0%).

Root cause: every driver's pace_delta was fed into the simulation with the
SAME fixed uncertainty regardless of real sample size -- `pace_std` and
`confidence` were both computed from genuine data (laps_counted) but never
consumed anywhere. These tests exercise the fix directly: a thin-sample
driver's apparent pace edge should no longer dominate win probability the
way a flat-uncertainty model let it.
"""
import statistics

from engine.predictor import (
    DriverForecast, DriverStrategy, PitPlan, run_monte_carlo,
    PACE_BIAS_BASE, PACE_BIAS_THIN_K, simulate_race, DriverPace,
)


def _strategy(driver_number, acronym):
    return DriverStrategy(
        driver_number=driver_number, acronym=acronym, current_lap=0,
        current_compound="MEDIUM", current_age=0, pits_remaining=[],
        total_time_from_now=0.0, laps_until_must_pit=None, confidence="HIGH")


def _forecast(driver_number, acronym, pos, pace_bias_std):
    return DriverForecast(
        driver_number=driver_number, acronym=acronym, current_position=pos,
        predicted_position=0, predicted_gap=0.0, confidence="HIGH",
        strategy=_strategy(driver_number, acronym), undercut=None,
        pace_bias_std_s_per_lap=pace_bias_std)


class TestPaceBiasFormula:
    def test_bias_std_shrinks_with_more_laps(self):
        std_thin = PACE_BIAS_BASE + PACE_BIAS_THIN_K / (5 ** 0.5)
        std_solid = PACE_BIAS_BASE + PACE_BIAS_THIN_K / (20 ** 0.5)
        assert std_thin > std_solid

    def test_simulate_race_computes_a_real_pace_bias_not_a_flat_constant(self):
        curves = {}
        pace_model = {
            1: DriverPace(driver_number=1, acronym="THIN", pace_median=0.0,
                          pace_std=0.0, pace_delta=-1.0, laps_counted=5),
            2: DriverPace(driver_number=2, acronym="SOLID", pace_median=0.0,
                          pace_std=0.0, pace_delta=-1.0, laps_counted=20),
        }
        drivers = [
            {"driver_number": 1, "acronym": "THIN", "position": 1,
             "compound": "MEDIUM", "tyre_age": 0, "compounds_used": ["MEDIUM", "HARD"]},
            {"driver_number": 2, "acronym": "SOLID", "position": 2,
             "compound": "MEDIUM", "tyre_age": 0, "compounds_used": ["MEDIUM", "HARD"]},
        ]
        forecasts = simulate_race(drivers, 0, 50, curves, pace_model, [],
                                  pit_loss=20.0, track_position_weight=0.5)
        by_num = {f.driver_number: f for f in forecasts}
        assert by_num[1].pace_bias_std_s_per_lap > by_num[2].pace_bias_std_s_per_lap


class TestMonteCarloUsesPaceBias:
    def test_thin_sample_driver_gets_a_wider_position_range(self):
        # Identical deterministic finish time and identical lap-to-lap race
        # noise -- the ONLY difference is pace_bias_std_s_per_lap. The thin
        # driver's simulated outcomes must spread wider.
        fc_thin = _forecast(1, "THIN", 1, pace_bias_std=0.4)
        fc_solid = _forecast(2, "SOLID", 2, pace_bias_std=0.05)
        scored = [(100.0, fc_thin), (100.5, fc_solid)]
        forecasts = [fc_thin, fc_solid]
        run_monte_carlo(forecasts, scored, 0, 50, [], field_baseline=90.0,
                        pit_loss=20.0, n_runs=2000)
        thin_spread = fc_thin.position_range[1] - fc_thin.position_range[0]
        solid_spread = fc_solid.position_range[1] - fc_solid.position_range[0]
        assert thin_spread >= solid_spread

    def test_apparently_fast_thin_sample_no_longer_locks_up_win_probability(self):
        # The actual regression shape: one driver looks fastest on paper but
        # from a thin sample (Madrid's HUL); two others are close together
        # and well-sampled (Madrid's ANT/VER). Compare against what a FLAT,
        # equally-confident model of the same field would produce.
        def build(pace_bias_fast_thin, pace_bias_others):
            f1 = _forecast(1, "FAST_THIN", 1, pace_bias_std=pace_bias_fast_thin)
            f2 = _forecast(2, "CLOSE_A", 2, pace_bias_std=pace_bias_others)
            f3 = _forecast(3, "CLOSE_B", 3, pace_bias_std=pace_bias_others)
            # FAST_THIN is 3s clear on paper; CLOSE_A/B are separated by 0.2s.
            scored = [(97.0, f1), (100.0, f2), (100.2, f3)]
            forecasts = [f1, f2, f3]
            run_monte_carlo(forecasts, scored, 0, 55, [], field_baseline=90.0,
                            pit_loss=20.0, n_runs=3000)
            return f1.win_probability

        flat_win = build(0.05, 0.05)         # old behaviour: everyone equally trusted
        realistic_win = build(0.5, 0.05)     # fixed behaviour: FAST_THIN is uncertain
        assert realistic_win < flat_win
