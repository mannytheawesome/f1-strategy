"""
Unit tests for run_monte_carlo's rain_probability parameter -- added
2026-10-05 after a real race (Bahrain, meeting 1308) started genuinely wet
with the model carrying zero forward-looking rain signal.

WET_SC_RATE_MULTIPLIER (1.66x) is a real measurement (measure_wet_weather_
rates.py, 67 dry + 19 wet races, 2023-2026 cache) -- these tests check the
MECHANISM (does rain_probability actually move the SC lottery, does 0.0
reduce to today's unchanged behaviour), not the specific constant, which
would need re-deriving from the same script if the underlying cache grows.
"""
import random

from engine.predictor import (
    DriverForecast, DriverStrategy, PitPlan, run_monte_carlo, WET_SC_RATE_MULTIPLIER,
)


def _forecast(driver_number, acronym, pits_remaining=()):
    strategy = DriverStrategy(
        driver_number=driver_number, acronym=acronym, current_lap=0,
        current_compound="MEDIUM", current_age=0, pits_remaining=list(pits_remaining),
        total_time_from_now=0.0, laps_until_must_pit=None, confidence="HIGH")
    return DriverForecast(
        driver_number=driver_number, acronym=acronym, current_position=1,
        predicted_position=0, predicted_gap=0.0, confidence="HIGH",
        strategy=strategy, undercut=None, pace_bias_std_s_per_lap=0.0)


def _run(rain_probability, seed=42):
    random.seed(seed)
    fc = _forecast(1, "VER")
    forecasts = [fc]
    scored = [(90.0, fc)]
    run_monte_carlo(forecasts, scored, current_lap=0, total_laps=50,
                    sc_events=[], field_baseline=90.0, pit_loss=22.0,
                    n_runs=4000, circuit="sakhir", rain_probability=rain_probability)
    return fc


class TestRainProbabilityDefault:
    def test_default_is_dry_zero_rain(self):
        # Every existing call site that doesn't pass rain_probability must
        # see unchanged behaviour -- the parameter defaults to 0.0.
        import inspect
        sig = inspect.signature(run_monte_carlo)
        assert sig.parameters["rain_probability"].default == 0.0


class TestWetScRateMultiplier:
    def test_constant_is_a_real_measured_elevation_not_a_guess(self):
        # Sanity guard on the constant itself: must be a genuine increase
        # (measured wet > dry), and not something absurdly large that would
        # indicate a unit/percentage mixup when it was derived.
        assert 1.0 < WET_SC_RATE_MULTIPLIER < 5.0

    def test_rain_probability_is_clamped_to_0_1(self):
        # Out-of-range inputs (a caller bug upstream) must not invert the
        # blend or produce a negative/absurd effective SC rate -- clamped
        # silently rather than raising, matching this module's existing
        # defensive style elsewhere (e.g. max(0, remaining)).
        fc_over = _run(rain_probability=5.0, seed=1)
        fc_at_one = _run(rain_probability=1.0, seed=1)
        # Same clamp result -> same seeded outcome.
        assert fc_over.win_probability == fc_at_one.win_probability

        fc_under = _run(rain_probability=-3.0, seed=1)
        fc_at_zero = _run(rain_probability=0.0, seed=1)
        assert fc_under.win_probability == fc_at_zero.win_probability


class TestRainProbabilityShiftsScLottery:
    def test_higher_rain_probability_favours_a_driver_with_a_stop_planned(self):
        # The SC lottery (run_monte_carlo's docstring, point 3) refunds part
        # of the pit loss ONLY to drivers with a stop still to take. If
        # rain_probability is really reaching the SC rate, a driver who still
        # has a stop planned should average BETTER (lower mean finish) as
        # rain_probability rises, relative to an identical driver who has
        # already made all their stops and gains nothing from an SC.
        has_stop = _forecast(1, "HAS_STOP", pits_remaining=[PitPlan(lap=20, compound="HARD")])
        no_stop = _forecast(2, "NO_STOP", pits_remaining=[])
        forecasts = [has_stop, no_stop]
        scored = [(90.0, has_stop), (90.0, no_stop)]  # identical base pace

        random.seed(7)
        run_monte_carlo(forecasts, scored, current_lap=0, total_laps=50,
                        sc_events=[], field_baseline=90.0, pit_loss=22.0,
                        n_runs=4000, circuit="sakhir", rain_probability=0.0)
        dry_gap = has_stop.win_probability - no_stop.win_probability

        has_stop2 = _forecast(1, "HAS_STOP", pits_remaining=[PitPlan(lap=20, compound="HARD")])
        no_stop2 = _forecast(2, "NO_STOP", pits_remaining=[])
        forecasts2 = [has_stop2, no_stop2]
        scored2 = [(90.0, has_stop2), (90.0, no_stop2)]

        random.seed(7)
        run_monte_carlo(forecasts2, scored2, current_lap=0, total_laps=50,
                        sc_events=[], field_baseline=90.0, pit_loss=22.0,
                        n_runs=4000, circuit="sakhir", rain_probability=1.0)
        wet_gap = has_stop2.win_probability - no_stop2.win_probability

        assert wet_gap > dry_gap
