"""
Regression tests for a real, three-part bug found while investigating a
persistent wet-race winner-hit gap (77% vs 86% for dry, at every checkpoint,
not closing as more race data arrived): engine/predictor.py's core
simulation, degradation fitting, and strategy search worked exclusively
with DRY = ["SOFT", "MEDIUM", "HARD"] -- zero references to INTERMEDIATE
or WET anywhere.

Confirmed mechanism:
  1. build_deg_curves/_stint_deg_samples silently dropped every
     INTERMEDIATE stint -- no wet degradation curve was ever fitted from
     real data, no matter how much genuine wet running a race had.
  2. build_pace_model DID include intermediate laps in the raw pace
     signal, but applied ZERO tyre-age correction to them (curves.get(c)
     returned None for a compound with no curve) -- tyre-wear noise
     leaked straight into the driver pace-delta.
  3. _stint_lap_times silently defaulted an intermediate's baseline pace
     to the SAME as a dry Medium (COMPOUND_DELTA.get(compound, 0) -> 0)
     whenever no curve existed -- flatly wrong whenever the model has to
     simulate a driver actually on wet-weather rubber.

Fitted from 57 genuine long-run intermediate stints (836 laps) across
every rain-affected race in the 2023-2026 cache. IMPORTANT, and reported
honestly to the user: after fixing an unrelated baseline-comparison
mistake (an earlier before/after check was contaminated by a stale
backtest_results.json left over from a different sweep), this fix shows
NO measurable change in backtest winner-hit/MAE. Kept anyway because it's
a genuine correctness fix (real code paths no longer silently drop real
data or assume nonsensical defaults) with zero measured downside -- these
tests verify the mechanism directly, not a backtest score.
"""
from engine.predictor import (
    DRY, INTERMEDIATE_MIN_DEG, COMPOUND_DELTA, DegCurve,
    build_deg_curves, _stint_deg_samples, _stint_time,
)


def _stint(driver, compound, lap_start, lap_end, tyre_age_at_start=0, stint_number=1):
    return {"driver_number": driver, "compound": compound, "lap_start": lap_start,
            "lap_end": lap_end, "tyre_age_at_start": tyre_age_at_start,
            "stint_number": stint_number}


def _laps(driver, lap_times, start_lap=1):
    return [{"driver_number": driver, "lap_number": start_lap + i, "lap_duration": t,
             "is_pit_out_lap": False} for i, t in enumerate(lap_times)]


class TestStintDegSamplesIncludesIntermediate:
    def test_intermediate_stint_is_no_longer_silently_dropped(self):
        # A genuine 10-lap intermediate long run -- would previously
        # produce {} entirely (compound filtered out before lap_start
        # check), so INTERMEDIATE never appeared in the output at all.
        laps = _laps(1, [95.0, 94.5, 94.8, 95.1, 95.3, 95.6, 95.9, 96.1, 96.4, 96.7])
        stints = [_stint(1, "INTERMEDIATE", 1, 10)]
        out = _stint_deg_samples(laps, stints, weight=1.0, session_name="RACE")
        assert "INTERMEDIATE" in out
        assert len(out["INTERMEDIATE"]) == 1

    def test_wet_full_wet_compound_still_not_tracked(self):
        # Full WET has only 5 genuine long-run stints across the whole
        # cache -- deliberately not given its own curve-fitting path.
        laps = _laps(1, [95.0, 94.5, 94.8, 95.1, 95.3, 95.6, 95.9, 96.1, 96.4, 96.7])
        stints = [_stint(1, "WET", 1, 10)]
        out = _stint_deg_samples(laps, stints, weight=1.0, session_name="RACE")
        assert "WET" not in out

    def test_dry_compounds_unaffected_by_intermediate_stints_present(self):
        # The exact regression this session worried about: does adding
        # INTERMEDIATE support change ANY dry compound's own sample.
        # min_laps=8 for the strict pass, and the in-lap is dropped
        # (range(lo, hi) is exclusive of hi), so a stint needs 9+ laps.
        dry_times = [90.0, 90.2, 90.4, 90.6, 90.8, 91.0, 91.2, 91.4, 91.6]
        inter_times = [95.0, 94.8, 95.1, 95.3, 95.6, 95.9, 96.1, 96.4, 96.6]
        dry_laps = _laps(1, dry_times)
        inter_laps = _laps(2, inter_times)
        stints_with_inter = [_stint(1, "MEDIUM", 1, len(dry_times)),
                             _stint(2, "INTERMEDIATE", 1, len(inter_times))]
        stints_without_inter = [_stint(1, "MEDIUM", 1, len(dry_times))]

        out_with = _stint_deg_samples(dry_laps + inter_laps, stints_with_inter, 1.0, "RACE")
        out_without = _stint_deg_samples(dry_laps, stints_without_inter, 1.0, "RACE")
        assert out_with["MEDIUM"] == out_without["MEDIUM"]


class TestBuildDegCurvesIntermediateHandling:
    def _wet_fp_data(self, slope_laps):
        laps = _laps(1, slope_laps)
        stints = [_stint(1, "INTERMEDIATE", 1, len(slope_laps))]
        return [("RACE", laps, stints)]

    def test_real_intermediate_data_produces_a_curve(self):
        fp_data = self._wet_fp_data([95.0, 94.8, 95.1, 95.3, 95.6, 95.9, 96.1, 96.4, 96.6, 96.9])
        curves = build_deg_curves(fp_data)
        assert "INTERMEDIATE" in curves

    def test_intermediate_deg_rate_floored_at_min(self):
        # Real fitted intermediate slopes across the cache came back
        # negative (track drying out faster than tyre wear within one
        # stint) -- build_deg_curves' existing max(deg, 0.0) already
        # floors that; INTERMEDIATE_MIN_DEG adds a further floor so the
        # optimiser never treats an intermediate as literally zero-wear.
        fp_data = self._wet_fp_data([95.0, 94.0, 93.0, 92.0, 91.0, 90.0, 89.0, 88.0, 87.0, 86.0])
        curves = build_deg_curves(fp_data)
        assert curves["INTERMEDIATE"].deg_rate >= INTERMEDIATE_MIN_DEG

    def test_no_intermediate_data_means_no_intermediate_curve(self):
        # Matches the OLD behaviour exactly for a genuinely dry race.
        laps = _laps(1, [90.0, 90.2, 90.4, 90.6, 90.8, 91.0, 91.2, 91.4])
        stints = [_stint(1, "MEDIUM", 1, 8)]
        curves = build_deg_curves([("RACE", laps, stints)])
        assert "INTERMEDIATE" not in curves

    def test_dry_curves_bit_for_bit_identical_with_or_without_intermediate(self):
        dry_laps = _laps(1, [90.0, 90.2, 90.4, 90.6, 90.8, 91.0, 91.2, 91.4, 91.6, 91.8,
                             92.0, 92.2, 92.4, 92.6, 92.8, 93.0, 93.2, 93.4, 93.6, 93.8])
        inter_laps = _laps(2, [95.0, 94.8, 95.1, 95.3, 95.6, 95.9, 96.1, 96.4, 96.6, 96.9])
        stints_with = [_stint(1, "MEDIUM", 1, 20), _stint(2, "INTERMEDIATE", 1, 10)]
        stints_without = [_stint(1, "MEDIUM", 1, 20)]

        curves_with = build_deg_curves([("RACE", dry_laps + inter_laps, stints_with)])
        curves_without = build_deg_curves([("RACE", dry_laps, stints_without)])
        assert curves_with["MEDIUM"].deg_rate == curves_without["MEDIUM"].deg_rate
        assert curves_with["MEDIUM"].baseline == curves_without["MEDIUM"].baseline

    def test_no_dry_compound_measured_does_not_crash_ratio_backfill(self):
        # Edge case the cross-compound-ratio backfill guard exists for:
        # if INTERMEDIATE is the ONLY thing ever measured, `ref` must
        # never become "INTERMEDIATE" (DEG_RATIO has no such key -- would
        # KeyError before the measured_dry fix).
        laps = _laps(1, [95.0, 94.8, 95.1, 95.3, 95.6, 95.9, 96.1, 96.4, 96.6, 96.9])
        stints = [_stint(1, "INTERMEDIATE", 1, 10)]
        curves = build_deg_curves([("RACE", laps, stints)])  # must not raise
        assert "INTERMEDIATE" in curves
        assert "SOFT" not in curves
        assert "HARD" not in curves


class TestCompoundDeltaAndStintTime:
    def test_intermediate_has_a_real_fallback_delta_not_same_as_medium(self):
        # The old bug: COMPOUND_DELTA.get("INTERMEDIATE", 0) silently
        # defaulted to 0 -- identical to dry Medium. Now has a real,
        # clearly-flagged-as-a-judgment-call positive offset instead.
        assert COMPOUND_DELTA["INTERMEDIATE"] > 0

    def test_stint_time_uses_real_curve_baseline_when_available_not_the_fallback(self):
        real_curve = DegCurve("INTERMEDIATE", 0.05, 100.0, 50, "HIGH", ["RACE"])
        curves = {"INTERMEDIATE": real_curve, "MEDIUM": DegCurve("MEDIUM", 0.025, 90.0, 50, "HIGH", ["RACE"])}
        t = _stint_time("INTERMEDIATE", 0, 1, 0, 50, 0.0, curves, field_baseline=90.0)
        # Should reflect the real curve's baseline (~100), not
        # field_baseline + COMPOUND_DELTA fallback (90 + 8 = 98).
        assert abs(t - 100.0) < 1.0
