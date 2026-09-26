"""
Regression tests for build_deg_curves' baseline ordering guard.

Real bug (Baku 2026): the user asked "what about the tyre strategy" after
checking the actual race against our pre-race strategy chart -- not one
of the 22 real drivers ran HARD at all that race, yet the chart's top two
ranked one-stop candidates were both HARD-based. Root cause: HARD's raw
baseline (fit from a thin 15-point/3-stint sample) read 0.19s FASTER than
MEDIUM's -- physically backwards, since a harder compound never generates
more peak grip on a fresh lap -- but the existing EXPECTED_OFFSET/
OFFSET_TOLERANCE clamp only catches deviations bigger than 1.0s, so this
smaller, still-backwards reading slipped through untouched and made HARD
look falsely competitive to the optimizer.

This guard runs right after that clamp and enforces the ordering
directly: HARD's baseline may never sit below MEDIUM's, nor SOFT's above
MEDIUM's -- mirroring the deg_rate monotonicity check that already exists
a few lines below it in the same function. +0.4/-0.6 below match
build_deg_curves' own (function-local) EXPECTED_OFFSET constants.
"""
from engine.predictor import build_deg_curves


def _stint(driver, compound, lap_start, lap_end, tyre_age_at_start=0, stint_number=1):
    return {"driver_number": driver, "compound": compound, "lap_start": lap_start,
            "lap_end": lap_end, "tyre_age_at_start": tyre_age_at_start,
            "stint_number": stint_number}


def _laps(driver, lap_times, start_lap=1):
    return [{"driver_number": driver, "lap_number": start_lap + i, "lap_duration": t,
             "is_pit_out_lap": False} for i, t in enumerate(lap_times)]


def _flat_stint(driver, compound, base_time, n=12):
    """A clean, near-flat long run -- degradation isn't what's under test
    here, just the baseline fit, so keep the slope negligible."""
    return (_laps(driver, [base_time + 0.01 * i for i in range(n)]),
            [_stint(driver, compound, 1, n)])


class TestHardNeverFasterThanMedium:
    def test_hard_baseline_faster_than_medium_within_tolerance_is_corrected(self):
        # Real Baku 2026 shape: HARD reads 0.19s faster than MEDIUM -- well
        # inside the 1.0s OFFSET_TOLERANCE, so the existing clamp wouldn't
        # catch it, but it's still backwards and must be fixed here.
        med_laps, med_stints = _flat_stint(1, "MEDIUM", 107.249)
        hard_laps, hard_stints = _flat_stint(2, "HARD", 107.06)   # faster than Medium
        fp_data = [("FP1", med_laps + hard_laps, med_stints + hard_stints)]
        curves = build_deg_curves(fp_data)

        assert curves["HARD"].baseline >= curves["MEDIUM"].baseline
        assert curves["HARD"].baseline == round(curves["MEDIUM"].baseline + 0.4, 3) \
            or abs(curves["HARD"].baseline - (curves["MEDIUM"].baseline + 0.4)) < 1e-6

    def test_hard_genuinely_slower_than_medium_is_left_alone(self):
        # Regression guard: a normal, physically-correct reading (HARD
        # slower than Medium, inside tolerance) must not be forced onto
        # the exact med+0.4 clamp target -- it's already fine as-is.
        med_laps, med_stints = _flat_stint(1, "MEDIUM", 107.0)
        hard_laps, hard_stints = _flat_stint(2, "HARD", 107.35)   # already slower, plausible gap
        fp_data = [("FP1", med_laps + hard_laps, med_stints + hard_stints)]
        curves = build_deg_curves(fp_data)

        assert curves["HARD"].baseline > curves["MEDIUM"].baseline
        forced_target = curves["MEDIUM"].baseline + 0.4
        assert abs(curves["HARD"].baseline - forced_target) > 0.05


class TestSoftNeverSlowerThanMedium:
    def test_soft_baseline_slower_than_medium_within_tolerance_is_corrected(self):
        med_laps, med_stints = _flat_stint(1, "MEDIUM", 107.0)
        soft_laps, soft_stints = _flat_stint(2, "SOFT", 107.2)   # backwards: slower than Medium
        fp_data = [("FP1", med_laps + soft_laps, med_stints + soft_stints)]
        curves = build_deg_curves(fp_data)

        assert curves["SOFT"].baseline <= curves["MEDIUM"].baseline

    def test_soft_genuinely_faster_than_medium_is_left_alone(self):
        med_laps, med_stints = _flat_stint(1, "MEDIUM", 107.0)
        soft_laps, soft_stints = _flat_stint(2, "SOFT", 106.5)   # correctly faster
        fp_data = [("FP1", med_laps + soft_laps, med_stints + soft_stints)]
        curves = build_deg_curves(fp_data)

        assert curves["SOFT"].baseline < curves["MEDIUM"].baseline
        forced_target = curves["MEDIUM"].baseline - 0.6
        assert abs(curves["SOFT"].baseline - forced_target) > 0.05


class TestNoMediumMeansNoOrderingGuard:
    def test_no_medium_curve_is_a_no_op_for_the_guard(self):
        hard_laps, hard_stints = _flat_stint(1, "HARD", 107.0)
        fp_data = [("FP1", hard_laps, hard_stints)]
        curves = build_deg_curves(fp_data)   # must not raise
        assert "HARD" in curves
