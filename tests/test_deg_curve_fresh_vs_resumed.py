"""
Regression tests for the fresh-vs-resumed tyre baseline fix.

User asked directly: are degradation rates different for a used (already-
fitted, resumed) tyre vs a genuinely fresh one? Checked with real 2026 race
data (matched tyre age 3-8 laps, normalised within each race so circuit
pace cancels out): degradation RATE showed no meaningful difference for
SOFT (fresh median 0.040 s/lap vs resumed 0.037), but BASELINE pace did --
a resumed SOFT ran ~1.5s/lap FASTER than a fresh one at the same nominal
age, consistently in 5/5 races checked (likely the graining/bedding-in
phase a genuinely fresh tyre hasn't been through yet). build_deg_curves
previously pooled fresh and resumed stints into one baseline fit, which
this finding says is measurably biased faster than a genuinely fresh
tyre's real pace -- exactly what optimize_strategy always simulates
(every candidate stint starts at age 0).

Fixing this naively (fresh-only baseline, unconditionally) surfaced a
second, real bug on real Monza data: a compound can have as few as ONE
genuinely-fresh long-run stint in FP data (most FP long runs continue an
already-opened tyre), and that one stint can itself be a noisy outlier --
Monza's MEDIUM curve had exactly one fresh 8-lap sample whose baseline was
~4 seconds below every other sample, and fresh-only filtering made it the
ENTIRE baseline. Requiring at least 2 independent fresh stints before
trusting fresh-only (falling back to the full pool otherwise) fixes that
without giving up the real correction where enough fresh data exists.
"""
from engine.predictor import DegCurve, build_deg_curves, _stint_deg_samples


def _stint(driver, compound, lap_start, lap_end, tyre_age_at_start=0, stint_number=1):
    return {"driver_number": driver, "compound": compound, "lap_start": lap_start,
            "lap_end": lap_end, "tyre_age_at_start": tyre_age_at_start,
            "stint_number": stint_number}


def _laps(driver, lap_times, start_lap=1):
    return [{"driver_number": driver, "lap_number": start_lap + i, "lap_duration": t,
             "is_pit_out_lap": False} for i, t in enumerate(lap_times)]


class TestStintDegSamplesTagsFreshness:
    def test_fresh_stint_tagged_true(self):
        laps = _laps(1, [90.0, 90.1, 90.2, 90.3, 90.4, 90.5, 90.6, 90.7])
        stints = [_stint(1, "SOFT", 1, 9, tyre_age_at_start=0)]
        out = _stint_deg_samples(laps, stints, weight=1.0, session_name="RACE")
        assert out["SOFT"][0][5] is True

    def test_resumed_stint_tagged_false(self):
        laps = _laps(1, [90.0, 90.1, 90.2, 90.3, 90.4, 90.5, 90.6, 90.7])
        stints = [_stint(1, "SOFT", 1, 9, tyre_age_at_start=12)]
        out = _stint_deg_samples(laps, stints, weight=1.0, session_name="RACE")
        assert out["SOFT"][0][5] is False


class TestBaselineUsesFreshOnlyWhenEnoughExist:
    def test_baseline_drawn_from_fresh_stints_when_at_least_two(self):
        # Two fresh SOFT stints (base ~90.0) and one resumed stint whose
        # own extrapolated baseline reads much faster (~86.0, mimicking
        # the measured graining/bedding-in effect) -- with 2 fresh
        # samples available, the resumed one must not drag the baseline
        # down towards it.
        fp_data = [
            ("FP2", _laps(1, [90.0, 90.1, 90.2, 90.3, 90.4, 90.5, 90.6, 90.7]),
             [_stint(1, "SOFT", 1, 9, tyre_age_at_start=0)]),
            ("FP3", _laps(2, [89.9, 90.0, 90.1, 90.2, 90.3, 90.4, 90.5, 90.6]),
             [_stint(2, "SOFT", 1, 9, tyre_age_at_start=0)]),
            ("FP1", _laps(3, [86.0, 86.05, 86.1, 86.15, 86.2, 86.25, 86.3, 86.35]),
             [_stint(3, "SOFT", 1, 9, tyre_age_at_start=15)]),
        ]
        curves = build_deg_curves(fp_data)
        assert curves["SOFT"].baseline > 88.0   # anchored to the fresh pair, not pulled to ~86

    def test_baseline_falls_back_to_full_pool_with_fewer_than_two_fresh(self):
        # Real Monza regression: exactly ONE fresh stint, whose own
        # baseline is a noisy outlier far from every resumed sample.
        # Fresh-only would make that single noisy stint the WHOLE
        # baseline; must fall back to the full (fresh+resumed) pool
        # instead, same as before this fix existed.
        fp_data = [
            ("FP1", _laps(1, [87.0, 87.1, 87.2, 87.3, 87.4, 87.5, 87.6, 87.7]),
             [_stint(1, "MEDIUM", 1, 9, tyre_age_at_start=9)]),
            ("FP2", _laps(2, [87.2, 87.3, 87.4, 87.5, 87.6, 87.7, 87.8, 87.9]),
             [_stint(2, "MEDIUM", 1, 9, tyre_age_at_start=7)]),
            ("FP3", _laps(3, [83.0, 83.5, 84.0, 84.5, 85.0, 85.5, 86.0, 86.5]),
             [_stint(3, "MEDIUM", 1, 9, tyre_age_at_start=0)]),   # the one noisy fresh outlier
        ]
        curves = build_deg_curves(fp_data)
        # The lone fresh stint's own extrapolated baseline is nowhere near
        # 87 -- if it dominated, curves["MEDIUM"].baseline would land far
        # below the two resumed (~87) samples instead of near them.
        assert curves["MEDIUM"].baseline > 86.0

    def test_degradation_rate_still_pools_fresh_and_resumed(self):
        # Only the BASELINE fit is scoped to fresh-only -- the measured
        # evidence found no meaningful rate difference, so the rate should
        # keep using every sample regardless of this fix, for the extra
        # robustness of a bigger pooled sample.
        fp_data = [
            ("FP2", _laps(1, [90.0, 90.3, 90.6, 90.9, 91.2, 91.5, 91.8, 92.1]),
             [_stint(1, "HARD", 1, 9, tyre_age_at_start=0)]),
            ("FP3", _laps(2, [88.0, 88.3, 88.6, 88.9, 89.2, 89.5, 89.8, 90.1]),
             [_stint(2, "HARD", 1, 9, tyre_age_at_start=20)]),
        ]
        curves = build_deg_curves(fp_data)
        assert curves["HARD"].data_points == 16   # both stints' points counted
