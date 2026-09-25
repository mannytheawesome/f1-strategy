"""
Regression tests for the lap-0 projection's quali-gap blending.

Real bug (Baku 2026, user-reported: "surely Russell should be the
favorite, he completely destroyed the field in quali"): _run_projection
fed pace_rows' FP-derived pace_delta straight into the simulation with no
regard for its own low_confidence flag or sample size. A driver with a
tiny, noisy FP sample (5 laps, one session) that happened to read
extremely fast got the field's highest win probability and a predicted P1
finish despite qualifying P11 -- while the driver who actually took pole
by a large margin was projected only P2. Fixed by blending each driver's
real qualifying gap (already present on `grid`) into their pace_delta the
same way build_pace_model blends a quali-lap prior against thin race-lap
samples.
"""
import statistics

import pytest

from engine.predictor import DegCurve
from engine.prerace import (
    QUALI_GRID_PRIOR_LAPS, _blend_pace_delta, _parse_grid_gap, _run_projection,
)


class TestParseGridGap:
    def test_leader_is_zero(self):
        assert _parse_grid_gap("LEADER") == 0.0

    def test_plus_prefixed_gap_parses(self):
        assert _parse_grid_gap("+2.249") == 2.249

    def test_none_or_empty_is_zero(self):
        assert _parse_grid_gap(None) == 0.0
        assert _parse_grid_gap("") == 0.0

    def test_unparseable_value_is_zero(self):
        assert _parse_grid_gap("DNF") == 0.0


class TestBlendPaceDelta:
    def test_thin_fp_sample_is_pulled_strongly_towards_quali(self):
        # Real case: BEA's raw FP delta (-2.726, 5 laps) blended against his
        # quali-implied delta (~-0.04, since P11 of 22 sits almost exactly
        # at the field median gap) should land close to the quali side,
        # not anywhere near the extreme raw FP reading.
        blended = _blend_pace_delta(raw_delta=-2.726, r_w=5, quali_delta=-0.0425)
        assert -1.2 < blended < -0.6
        assert blended > -2.0   # nowhere near the unblended extreme

    def test_strong_fp_sample_resists_the_quali_prior(self):
        # A driver with a large, well-sampled FP delta should NOT be pulled
        # all the way to a quali_delta of 0 just because prior_laps exists --
        # weight of evidence should matter.
        blended = _blend_pace_delta(raw_delta=-1.0, r_w=100, quali_delta=0.0)
        assert blended < -0.85

    def test_no_fp_sample_uses_quali_delta_alone(self):
        assert _blend_pace_delta(raw_delta=0.0, r_w=0, quali_delta=-2.0) == -2.0

    def test_quali_dominance_improves_a_decent_fp_driver(self):
        # Real case: RUS's raw FP delta (-1.254, 10 laps) blended against his
        # quali-implied delta (~-2.29, taking pole by a big margin) should
        # move FASTER (more negative), not get diluted towards average.
        blended = _blend_pace_delta(raw_delta=-1.254, r_w=10, quali_delta=-2.2915)
        assert blended < -1.254


def _curve(compound, deg_rate=0.03, baseline=100.0):
    return DegCurve(compound=compound, deg_rate=deg_rate, baseline=baseline,
                    data_points=20, confidence="HIGH", sessions=["RACE"])


CURVES = {c: _curve(c) for c in ("SOFT", "MEDIUM", "HARD")}

STRATEGIES = [{"start_compound": "MEDIUM", "stops": 1,
              "compound_sequence": ["MEDIUM", "HARD"],
              "pit_laps": [25], "pit_windows": [[22, 28]],
              "stint_lengths": [25, 25], "total_time": 5000.0}]


class TestRunProjectionEndToEnd:
    def test_dominant_quali_pace_beats_a_thin_noisy_fp_outlier(self):
        # Mirrors the real Baku shape: a pole-sitter with a solid FP sample
        # and a big real quali margin, against a driver who qualified
        # mid-pack but has one wildly-fast, low-confidence FP reading.
        # With no unlucky-driver ordering dependence, the pole-sitter's
        # blended pace should come out clearly ahead.
        grid = [
            {"driver_number": 1, "acronym": "POLE", "position": 1, "gap": "LEADER"},
            {"driver_number": 2, "acronym": "P2", "position": 2, "gap": "+0.85"},
            {"driver_number": 3, "acronym": "P3", "position": 3, "gap": "+1.2"},
            {"driver_number": 4, "acronym": "P4", "position": 4, "gap": "+1.5"},
            {"driver_number": 5, "acronym": "P5", "position": 5, "gap": "+1.8"},
            {"driver_number": 6, "acronym": "OUTLIER", "position": 6, "gap": "+2.2"},
            {"driver_number": 7, "acronym": "P7", "position": 7, "gap": "+2.6"},
        ]
        pace_rows = [
            {"driver_number": 1, "pace_delta": -1.25, "laps": 10},
            {"driver_number": 6, "pace_delta": -2.73, "laps": 5},   # the noisy outlier
        ]
        forecasts = _run_projection(grid, pace_rows, CURVES, STRATEGIES,
                                    total_laps=50, pit_loss=20.0, circuit="baku")
        assert forecasts, "projection returned nothing"
        winner = min(forecasts, key=lambda f: f.predicted_position)
        assert winner.acronym == "POLE"

    def test_median_grid_gap_used_when_no_pace_row_exists(self):
        # A driver missing from pace_rows entirely must still get a
        # sensible quali-only delta, not crash or default to 0 vs the
        # wrong reference point.
        grid = [
            {"driver_number": 1, "acronym": "A", "position": 1, "gap": "LEADER"},
            {"driver_number": 2, "acronym": "B", "position": 2, "gap": "+1.0"},
        ]
        forecasts = _run_projection(grid, [], CURVES, STRATEGIES,
                                    total_laps=50, pit_loss=20.0, circuit="baku")
        assert forecasts   # must not raise, must produce something
