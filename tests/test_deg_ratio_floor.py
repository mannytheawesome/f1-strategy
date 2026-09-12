"""
Regression tests for the DEG_RATIO-based relative sanity floor in
build_deg_curves, added after a user-reported Monaco 2026 strategy bug:
the "Expected Pit Stop Strategies" table's top picks were absurd single
60+ lap stints on Hard.

Root cause: Hard's ENTIRE long-run sample came from FP1 alone (no Hard
running in FP2/FP3 at all -- confirmed on the real Monaco 2026 data), the
session most prone to large positive track evolution. Clean laps in a
real 21-lap FP1 Hard stint actually got FASTER over the run (track
evolution outweighing genuine wear), so the raw fitted slope came back
at/below zero and the old flat MIN_DEG floor (0.010) let it stay there --
a 13x gap below Medium's independently (FP1+FP2) measured rate, versus
DEG_RATIO's genuinely cross-compound-measured ~0.6x-of-Medium norm. Not
Monaco-specific: 23 of 74 cached meetings (31%) have this same
FP1-only-Hard pattern.
"""
from engine.predictor import DEG_RATIO, build_deg_curves


def _stint(driver, compound, lap_start, lap_end, tyre_age_at_start=0, stint_number=1):
    return {"driver_number": driver, "compound": compound, "lap_start": lap_start,
            "lap_end": lap_end, "tyre_age_at_start": tyre_age_at_start,
            "stint_number": stint_number}


def _laps(driver, lap_times, start_lap=1):
    return [{"driver_number": driver, "lap_number": start_lap + i, "lap_duration": t,
             "is_pit_out_lap": False} for i, t in enumerate(lap_times)]


class TestDegRatioFloor:
    def test_fp1_only_flat_hard_gets_floored_relative_to_medium(self):
        # Medium: a genuine, clearly-degrading long run (like Monaco's real
        # FP1+FP2 sample). Hard: an FP1-only stint whose clean laps flatten
        # out / improve slightly -- track evolution masking real wear, same
        # shape as the real Monaco 2026 case.
        med_laps = _laps(1, [90.0 + 0.13 * i for i in range(12)])
        hard_laps = _laps(2, [88.0, 87.9, 87.85, 87.8, 87.75, 87.9,
                              87.7, 87.65, 87.8, 87.6, 87.55, 87.7])
        stints = [
            _stint(1, "MEDIUM", 1, 12),
            _stint(2, "HARD", 1, 12),
        ]
        fp_data = [("FP1", med_laps + hard_laps, stints)]
        curves = build_deg_curves(fp_data)

        assert "MEDIUM" in curves and "HARD" in curves
        med, hard = curves["MEDIUM"], curves["HARD"]
        # The old flat MIN_DEG floor (0.010) must no longer be where this
        # lands -- it should sit near the DEG_RATIO-implied value instead.
        assert hard.deg_rate > 0.010
        expected_floor = med.deg_rate * DEG_RATIO["HARD"] * 0.4
        assert abs(hard.deg_rate - expected_floor) < 1e-6

    def test_genuinely_well_measured_soft_is_not_touched(self):
        # Regression guard: Monaco's real SOFT (0.169, independently
        # measured, above its own ratio floor) must NOT be overridden --
        # this floor should only catch implausibly LOW fits, never nudge a
        # perfectly good measurement.
        med_laps = _laps(1, [90.0 + 0.13 * i for i in range(12)])
        soft_laps = _laps(2, [88.0 + 0.169 * i for i in range(12)])
        stints = [
            _stint(1, "MEDIUM", 1, 12),
            _stint(2, "SOFT", 1, 12),
        ]
        fp_data = [("FP1", med_laps + soft_laps, stints)]
        curves = build_deg_curves(fp_data)

        soft_floor = curves["MEDIUM"].deg_rate * DEG_RATIO["SOFT"] * 0.4
        assert curves["SOFT"].deg_rate > soft_floor
        # Genuinely fitted rate survives roughly untouched -- well clear of
        # the ratio floor, not pinned exactly to it.
        assert abs(curves["SOFT"].deg_rate - 0.169) < 0.05

    def test_no_medium_curve_means_no_ratio_floor_applied(self):
        # The floor is relative to Medium -- with no Medium curve at all,
        # there's nothing to float Hard relative to, so it must fall back
        # to the existing flat MIN_DEG behaviour rather than crashing.
        hard_laps = _laps(1, [88.0, 87.9, 87.85, 87.8, 87.75, 87.9,
                              87.7, 87.65, 87.8, 87.6, 87.55, 87.7])
        stints = [_stint(1, "HARD", 1, 12)]
        fp_data = [("FP1", hard_laps, stints)]
        curves = build_deg_curves(fp_data)   # must not raise
        assert "HARD" in curves
