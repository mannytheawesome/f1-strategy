"""
Tests for the pre-race briefing charts (pit-strategy Gantt, team pace) and
the grid-construction regression this session found (Cadillac silently
dropped from every chart keyed off `grid`).

Unit tests use synthetic data and run with no network. Integration tests
(marked `integration`, skipped by default -- see pytest.ini) hit real
cached meetings through the full build_prerace_data pipeline, matching how
this session actually validated the fixes.
"""
import pytest

import engine.prerace as prerace
from engine.predictor import DegCurve
from engine.prerace import (
    PIT_WINDOW_MARGIN_S, PIT_WINDOW_MAX_SHIFT, _pit_window, _team_pace,
    _long_run_pace, _shift_medium_start_earlier,
)
from engine.predictor import MIN_STINT, optimize_strategy
from engine.undercut_shift import CIRCUIT_UNDERCUT_SHIFT, DEFAULT_UNDERCUT_SHIFT, undercut_shift_for


def _curve(compound, deg_rate=0.05, baseline=90.0):
    return DegCurve(compound=compound, deg_rate=deg_rate, baseline=baseline,
                     data_points=20, confidence="HIGH", sessions=["RACE"])


CURVES = {c: _curve(c) for c in ("SOFT", "MEDIUM", "HARD")}


class TestPitWindow:
    def test_window_lo_le_hi(self):
        seq = ["MEDIUM", "HARD"]
        lens = [25, 25]
        w = _pit_window(seq, lens, 0, CURVES, 90.0, 22.0, total_laps=50)
        assert w[0] <= w[1]

    def test_window_capped_at_max_shift_either_side(self):
        # A near-zero deg rate makes the time-vs-shift curve very flat, so
        # the window should hit the hard cap rather than growing unbounded
        # (the exact bug this cap was added for). _pit_window returns
        # absolute lap numbers (boundary + shift), so check width relative
        # to the pit boundary (lens[0] == 25 here), not the raw values.
        flat_curves = {c: _curve(c, deg_rate=0.0001) for c in CURVES}
        seq = ["MEDIUM", "HARD"]
        lens = [25, 25]
        boundary = lens[0]
        w = _pit_window(seq, lens, 0, flat_curves, 90.0, 22.0, total_laps=50)
        assert w[0] - boundary >= -PIT_WINDOW_MAX_SHIFT
        assert w[1] - boundary <= PIT_WINDOW_MAX_SHIFT

    def test_window_never_negative_width(self):
        for total_laps in (30, 50, 70):
            seq = ["SOFT", "MEDIUM"]
            lens = [total_laps // 2, total_laps - total_laps // 2]
            w = _pit_window(seq, lens, 0, CURVES, 90.0, 22.0, total_laps=total_laps)
            assert w[1] - w[0] >= 0


class TestMediumStartUndercutShift:
    """Real case (Monza 2026, user-reported): our MEDIUM->HARD one-stop
    candidate recommended pitting at lap 31, well past F1.com's published
    window. backtest_pit_timing.py found a real, consistent early-pit bias
    across 4 clean 2026 races the pure lap-time DP has no way to see (no
    undercut/track-position concept at all) -- but calibrate_undercut_shift
    .py then found, across each circuit's full 2023-2026 history, that the
    bias is genuinely circuit-specific and not always early (see
    engine.undercut_shift's module docstring). _shift_medium_start_earlier
    applies whatever shift (positive = earlier, negative = later) that
    calibration supplies for a given circuit."""

    def test_positive_shift_moves_the_pit_lap_earlier(self):
        # Pure-pace optimum at lap 25 of 53 -- plenty of room either side
        # of MIN_STINT for the full shift to apply unclamped.
        pit_laps, lens, _ = _shift_medium_start_earlier(
            "MEDIUM", "HARD", [25, 28], 53, CURVES, 90.0, 22.0, shift_laps=6)
        assert pit_laps == [19]
        assert lens == [19, 34]

    def test_negative_shift_moves_the_pit_lap_later(self):
        # Real case: Mexico City's calibrated shift is negative (-10) --
        # real one-stoppers there pit LATER than the pure-pace answer.
        pit_laps, lens, _ = _shift_medium_start_earlier(
            "MEDIUM", "HARD", [20, 33], 53, CURVES, 90.0, 22.0, shift_laps=-10)
        assert pit_laps == [30]
        assert lens == [30, 23]

    def test_shift_floored_at_min_stint_not_below(self):
        # Pure-pace optimum already close to MIN_STINT -- a 6-lap earlier
        # shift would go below it; must floor there instead.
        pit_laps, lens, _ = _shift_medium_start_earlier(
            "MEDIUM", "HARD", [10, 40], 50, CURVES, 90.0, 22.0, shift_laps=6)
        assert pit_laps == [MIN_STINT]
        assert lens[0] == MIN_STINT

    def test_shift_capped_at_total_laps_minus_min_stint_not_above(self):
        # A large negative (later) shift must not push the final stint
        # below MIN_STINT either.
        pit_laps, lens, _ = _shift_medium_start_earlier(
            "MEDIUM", "HARD", [40, 13], 53, CURVES, 90.0, 22.0, shift_laps=-20)
        assert pit_laps == [53 - MIN_STINT]
        assert lens[1] == MIN_STINT

    def test_lengths_still_sum_to_total_laps(self):
        pit_laps, lens, _ = _shift_medium_start_earlier(
            "MEDIUM", "HARD", [30, 23], 53, CURVES, 90.0, 22.0, shift_laps=6)
        assert sum(lens) == 53

    def test_total_time_recomputed_for_the_shifted_split_not_the_optimum(self):
        # Ask optimize_strategy for its own genuine pure-pace optimum under
        # these curves, then confirm the shifted split -- built starting
        # from that same optimum -- scores a strictly WORSE (higher) time.
        # If this instead returned the original optimum's total_time
        # unchanged, a UI relying on it (viability/time_delta) would show a
        # pit lap inconsistent with its own quoted time cost.
        skewed_curves = {"MEDIUM": _curve("MEDIUM", deg_rate=0.02, baseline=90.0),
                         "HARD": _curve("HARD", deg_rate=0.01, baseline=90.6),
                         "SOFT": _curve("SOFT", deg_rate=0.06, baseline=89.4)}
        strat = optimize_strategy(0, 53, "MEDIUM", 0, 0.0, skewed_curves, 90.0, 22.0,
                                  needs_compound_change=True, force_stops=1,
                                  forbid_repeat_compound=True, force_end_compound="HARD")
        optimal_pit = strat.pits_remaining[0].lap
        optimum_time = strat.total_time_from_now
        _, _, shifted_time = _shift_medium_start_earlier(
            "MEDIUM", "HARD", [optimal_pit, 53 - optimal_pit], 53, skewed_curves, 90.0, 22.0,
            shift_laps=6)
        assert shifted_time > optimum_time


class TestUndercutShiftLookup:
    def test_known_circuit_returns_its_calibrated_value(self):
        assert undercut_shift_for("Monza") == CIRCUIT_UNDERCUT_SHIFT["monza"]

    def test_lookup_is_case_insensitive(self):
        assert undercut_shift_for("MONZA") == undercut_shift_for("monza")

    def test_unknown_circuit_falls_back_to_default(self):
        assert undercut_shift_for("Nonexistent Circuit") == DEFAULT_UNDERCUT_SHIFT

    def test_none_circuit_falls_back_to_default(self):
        assert undercut_shift_for(None) == DEFAULT_UNDERCUT_SHIFT

    def test_calibration_includes_both_signs(self):
        # The real, evidence-based finding this session: roughly half of
        # the well-sampled circuits need a LATER correction, not earlier
        # -- not a uniformly-early "undercut defense everywhere" rule.
        values = CIRCUIT_UNDERCUT_SHIFT.values()
        assert any(v > 0 for v in values)
        assert any(v < 0 for v in values)


class TestTeamPace:
    GRID = [
        {"acronym": "NOR", "team": "McLaren", "team_colour": "F47600"},
        {"acronym": "HAM", "team": "Ferrari", "team_colour": "ED1131"},
        {"acronym": "BOT", "team": "Cadillac", "team_colour": "909090"},
        {"acronym": "PER", "team": "Cadillac", "team_colour": "909090"},
    ]

    def test_team_with_no_driver_data_gets_no_data_flag_not_omitted(self):
        # The real bug this session found (twice): a team missing pace data
        # must still appear, flagged, not silently vanish from the chart.
        pace_rows = [
            {"acronym": "NOR", "pace_delta": 0.0},
            {"acronym": "HAM", "pace_delta": 0.5},
        ]
        rows = _team_pace(pace_rows, self.GRID, field_baseline=90.0)
        teams = {r["team"] for r in rows}
        assert "Cadillac" in teams
        cadillac_row = next(r for r in rows if r["team"] == "Cadillac")
        assert cadillac_row["no_data"] is True
        assert cadillac_row["gap_s"] is None

    def test_fastest_team_gets_zero_gap(self):
        pace_rows = [
            {"acronym": "NOR", "pace_delta": 0.0},
            {"acronym": "HAM", "pace_delta": 0.5},
        ]
        rows = _team_pace(pace_rows, self.GRID, field_baseline=90.0)
        mclaren = next(r for r in rows if r["team"] == "McLaren")
        assert mclaren["gap_s"] == 0.0

    def test_no_data_teams_sort_after_ranked_teams(self):
        pace_rows = [{"acronym": "NOR", "pace_delta": 0.0}]
        rows = _team_pace(pace_rows, self.GRID, field_baseline=90.0)
        no_data_flags = [r["no_data"] for r in rows]
        # once True starts, it never flips back to False
        assert no_data_flags == sorted(no_data_flags)

    def test_confidence_flags_propagate_from_the_teams_fastest_driver(self):
        # Real bug found on Shanghai 2026: a team's rank can be built
        # entirely off a low-lap or Sprint-Race-only sample and look just as
        # authoritative as a team with a genuine long run. _team_pace must
        # carry that signal through, not drop it at the driver->team step.
        pace_rows = [
            {"acronym": "NOR", "pace_delta": 0.0,
             "low_confidence": True, "race_pace_only": False},
            {"acronym": "HAM", "pace_delta": 0.5,
             "low_confidence": False, "race_pace_only": True},
        ]
        rows = _team_pace(pace_rows, self.GRID, field_baseline=90.0)
        mclaren = next(r for r in rows if r["team"] == "McLaren")
        ferrari = next(r for r in rows if r["team"] == "Ferrari")
        assert mclaren["low_confidence"] is True
        assert mclaren["race_pace_only"] is False
        assert ferrari["low_confidence"] is False
        assert ferrari["race_pace_only"] is True

    def test_no_data_team_gets_flags_false_not_missing(self):
        pace_rows = [{"acronym": "NOR", "pace_delta": 0.0,
                      "low_confidence": False, "race_pace_only": False}]
        rows = _team_pace(pace_rows, self.GRID, field_baseline=90.0)
        cadillac = next(r for r in rows if r["team"] == "Cadillac")
        assert cadillac["low_confidence"] is False
        assert cadillac["race_pace_only"] is False

    def test_missing_flags_on_pace_rows_default_to_false(self):
        # Old-shape pace_rows (no low_confidence/race_pace_only keys, as
        # used by the other tests in this class) must not KeyError.
        pace_rows = [{"acronym": "NOR", "pace_delta": 0.0}]
        rows = _team_pace(pace_rows, self.GRID, field_baseline=90.0)
        mclaren = next(r for r in rows if r["team"] == "McLaren")
        assert mclaren["low_confidence"] is False
        assert mclaren["race_pace_only"] is False


class TestLongRunPaceConfidenceFlags:
    """The Shanghai 2026 investigation: McLaren showed no_data while Audi
    and Racing Bulls out-ranked Red Bull, driven by a 5-lap outlier sample
    (HAM) and several teams' rankings being built entirely from Sprint Race
    laps (real racing, not a controlled pace read) rather than genuine FP
    long runs. These flags surface that instead of presenting every sample
    with equal confidence."""

    def _laps(self, driver, lap_times, start_lap=1):
        return [{"driver_number": driver, "lap_number": start_lap + i,
                 "lap_duration": t, "is_pit_out_lap": False}
                for i, t in enumerate(lap_times)]

    def _patch(self, monkeypatch, laps, stints, acronym="NOR", driver=1):
        monkeypatch.setattr(prerace, "get_laps", lambda *a, **k: laps)
        monkeypatch.setattr(prerace, "get_stints", lambda *a, **k: stints)
        monkeypatch.setattr(prerace, "get_drivers",
                            lambda *a, **k: {driver: {"name_acronym": acronym}})
        monkeypatch.setattr("data.live.get_yellow_laps", lambda *a, **k: set())

    def test_thin_sample_flagged_low_confidence(self, monkeypatch):
        # 7-lap stint -> in/out-lap dropped by the ls<ln<le bound -> exactly
        # 5 usable laps, below PACE_MIN_CONFIDENT_LAPS (8).
        laps = self._laps(1, [90.0] * 7)
        stints = [{"driver_number": 1, "compound": "MEDIUM",
                   "lap_start": 1, "lap_end": 7, "tyre_age_at_start": 0}]
        self._patch(monkeypatch, laps, stints)
        sources = [{"session_key": 1, "session_type": "Practice",
                    "session_name": "Practice 1"}]
        rows = _long_run_pace(sources, {})
        assert rows[0]["low_confidence"] is True

    def test_genuine_long_run_not_flagged(self, monkeypatch):
        # 12-lap Practice-1 stint -> 10 usable laps, comfortably clear of
        # both thresholds.
        laps = self._laps(1, [90.0] * 12)
        stints = [{"driver_number": 1, "compound": "MEDIUM",
                   "lap_start": 1, "lap_end": 12, "tyre_age_at_start": 0}]
        self._patch(monkeypatch, laps, stints)
        sources = [{"session_key": 1, "session_type": "Practice",
                    "session_name": "Practice 1"}]
        rows = _long_run_pace(sources, {})
        assert rows[0]["low_confidence"] is False
        assert rows[0]["race_pace_only"] is False

    def test_sprint_race_only_sample_flagged(self, monkeypatch):
        # Same shape as the genuine-long-run case, but sourced entirely from
        # the Sprint Race session rather than any Practice session.
        laps = self._laps(1, [90.0] * 12)
        stints = [{"driver_number": 1, "compound": "MEDIUM",
                   "lap_start": 1, "lap_end": 12, "tyre_age_at_start": 0}]
        self._patch(monkeypatch, laps, stints)
        sources = [{"session_key": 1, "session_type": "Race",
                    "session_name": "Sprint"}]
        rows = _long_run_pace(sources, {})
        assert rows[0]["race_pace_only"] is True
        assert rows[0]["low_confidence"] is False

    def test_any_practice_contribution_clears_race_pace_only(self, monkeypatch):
        # A driver with laps from BOTH Practice 1 and the Sprint should not
        # be flagged race_pace_only -- they do have a genuine FP sample.
        fp_laps = self._laps(1, [90.0] * 12)
        sprint_laps = self._laps(1, [90.0] * 12)
        fp_stint = [{"driver_number": 1, "compound": "MEDIUM",
                     "lap_start": 1, "lap_end": 12, "tyre_age_at_start": 0}]
        sprint_stint = [{"driver_number": 1, "compound": "MEDIUM",
                         "lap_start": 1, "lap_end": 12, "tyre_age_at_start": 0}]

        def fake_get_laps(session_key, *a, **k):
            return fp_laps if session_key == 1 else sprint_laps

        def fake_get_stints(session_key, *a, **k):
            return fp_stint if session_key == 1 else sprint_stint

        monkeypatch.setattr(prerace, "get_laps", fake_get_laps)
        monkeypatch.setattr(prerace, "get_stints", fake_get_stints)
        monkeypatch.setattr(prerace, "get_drivers",
                            lambda *a, **k: {1: {"name_acronym": "NOR"}})
        monkeypatch.setattr("data.live.get_yellow_laps", lambda *a, **k: set())
        sources = [
            {"session_key": 1, "session_type": "Practice", "session_name": "Practice 1"},
            {"session_key": 2, "session_type": "Race", "session_name": "Sprint"},
        ]
        rows = _long_run_pace(sources, {})
        assert rows[0]["race_pace_only"] is False

    def test_reserve_driver_dropped_from_pace_table(self, monkeypatch):
        # Real case found on Hungary 2026: McLaren's reserve (Fornaroli) ran
        # a mandatory rookie FP1 session and out-paced NOR/PIA in the table,
        # despite never qualifying or starting the race. grid_acronyms
        # restricts the result to actual grid entrants.
        reserve_laps = self._laps(1, [80.0] * 12)   # unrealistically fast
        race_driver_laps = self._laps(2, [90.0] * 12)
        stints = [
            {"driver_number": 1, "compound": "MEDIUM", "lap_start": 1, "lap_end": 12, "tyre_age_at_start": 0},
            {"driver_number": 2, "compound": "MEDIUM", "lap_start": 1, "lap_end": 12, "tyre_age_at_start": 0},
        ]
        monkeypatch.setattr(prerace, "get_laps",
                            lambda *a, **k: reserve_laps + race_driver_laps)
        monkeypatch.setattr(prerace, "get_stints", lambda *a, **k: stints)
        monkeypatch.setattr(prerace, "get_drivers",
                            lambda *a, **k: {1: {"name_acronym": "RES"},
                                             2: {"name_acronym": "NOR"}})
        monkeypatch.setattr("data.live.get_yellow_laps", lambda *a, **k: set())
        sources = [{"session_key": 1, "session_type": "Practice", "session_name": "Practice 1"}]

        unfiltered = _long_run_pace(sources, {})
        assert {r["acronym"] for r in unfiltered} == {"RES", "NOR"}

        filtered = _long_run_pace(sources, {}, grid_acronyms={"NOR"})
        assert {r["acronym"] for r in filtered} == {"NOR"}
        # NOR's pace_delta should also no longer be measured against a field
        # median pulled toward the reserve's unrealistic pace.
        assert filtered[0]["pace_delta"] == 0.0


class TestLongRunPaceFetchFailures:
    """A rate-limited session fetch inside _long_run_pace was already
    tolerated (skip that session, keep going) but left no record that it
    happened -- an identical query could silently return a worse-informed
    result depending on whether OpenF1 429'd that call, with nothing
    telling the reader it happened. fetch_failures makes that visible."""

    def _laps(self, driver, lap_times, start_lap=1):
        return [{"driver_number": driver, "lap_number": start_lap + i,
                 "lap_duration": t, "is_pit_out_lap": False}
                for i, t in enumerate(lap_times)]

    def test_failed_session_recorded_when_list_given(self, monkeypatch):
        def raise_error(*a, **k):
            raise RuntimeError("429 Too Many Requests")

        monkeypatch.setattr(prerace, "get_laps", raise_error)
        sources = [{"session_key": 1, "session_type": "Practice",
                    "session_name": "Practice 1"}]
        failures = []
        rows = _long_run_pace(sources, {}, fetch_failures=failures)
        assert rows == []
        assert failures == ["Practice 1"]

    def test_successful_session_records_nothing(self, monkeypatch):
        laps = self._laps(1, [90.0] * 12)
        stints = [{"driver_number": 1, "compound": "MEDIUM",
                   "lap_start": 1, "lap_end": 12, "tyre_age_at_start": 0}]
        monkeypatch.setattr(prerace, "get_laps", lambda *a, **k: laps)
        monkeypatch.setattr(prerace, "get_stints", lambda *a, **k: stints)
        monkeypatch.setattr(prerace, "get_drivers",
                            lambda *a, **k: {1: {"name_acronym": "NOR"}})
        monkeypatch.setattr("data.live.get_yellow_laps", lambda *a, **k: set())
        sources = [{"session_key": 1, "session_type": "Practice",
                    "session_name": "Practice 1"}]
        failures = []
        rows = _long_run_pace(sources, {}, fetch_failures=failures)
        assert len(rows) == 1
        assert failures == []

    def test_omitting_the_list_does_not_raise(self, monkeypatch):
        # Backward compatibility: every existing call site (and the many
        # tests above) doesn't pass fetch_failures at all.
        monkeypatch.setattr(prerace, "get_laps",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429")))
        sources = [{"session_key": 1, "session_type": "Practice",
                    "session_name": "Practice 1"}]
        rows = _long_run_pace(sources, {})   # must not raise
        assert rows == []


class TestLongRunPaceSessionWeighting:
    """User-reported gap: unlike degradation-RATE fitting (predictor.
    FP_WEIGHTS), the pace-LEVEL calculation pooled every session's clean
    laps unweighted -- a driver's FP1 laps (green, barely-rubbered track,
    genuinely slower) counted exactly as much as their FP2 laps (much more
    representative of race/quali conditions)."""

    def _patch(self, monkeypatch, laps_by_session, stints_by_session,
              drivers=None, acronym="NOR", driver=1):
        def fake_get_laps(session_key, *a, **k):
            return laps_by_session[session_key]

        def fake_get_stints(session_key, *a, **k):
            return stints_by_session[session_key]

        monkeypatch.setattr(prerace, "get_laps", fake_get_laps)
        monkeypatch.setattr(prerace, "get_stints", fake_get_stints)
        monkeypatch.setattr(prerace, "get_drivers",
                            lambda *a, **k: drivers or {driver: {"name_acronym": acronym}})
        monkeypatch.setattr("data.live.get_yellow_laps", lambda *a, **k: set())

    def test_fp1_laps_are_downweighted_against_fp2(self, monkeypatch):
        # MIX: equal-sized clean samples from FP1 (95.0, contaminated/slow)
        # and FP2 (85.0, their true representative pace). ANCHOR: a clean
        # FP2-only reference at 90.0. Unweighted, MIX's raw median would be
        # the midpoint of 85/95 = 90.0 -- an exact tie with ANCHOR, hiding
        # that MIX is genuinely faster. Weighted (FP1=0.3, FP2=1.0), MIX's
        # median should sit much closer to their true 85.0 FP2 pace,
        # correctly ranking them ahead of ANCHOR instead of tied.
        mix_fp1 = self._laps_helper(1, [95.0] * 11)
        mix_fp2 = self._laps_helper(1, [85.0] * 11)
        anchor_fp2 = self._laps_helper(2, [90.0] * 11)
        stint_mix = {"driver_number": 1, "compound": "MEDIUM",
                     "lap_start": 1, "lap_end": 11, "tyre_age_at_start": 0}
        stint_anchor = {"driver_number": 2, "compound": "MEDIUM",
                        "lap_start": 1, "lap_end": 11, "tyre_age_at_start": 0}
        self._patch(monkeypatch,
                    laps_by_session={1: mix_fp1, 2: mix_fp2 + anchor_fp2},
                    stints_by_session={1: [stint_mix], 2: [stint_mix, stint_anchor]},
                    drivers={1: {"name_acronym": "MIX"}, 2: {"name_acronym": "ANCHOR"}})
        sources = [
            {"session_key": 1, "session_type": "Practice", "session_name": "Practice 1"},
            {"session_key": 2, "session_type": "Practice", "session_name": "Practice 2"},
        ]
        rows = _long_run_pace(sources, {})
        by_acr = {r["acronym"]: r for r in rows}
        assert by_acr["MIX"]["pace_delta"] < by_acr["ANCHOR"]["pace_delta"]
        assert by_acr["MIX"]["pace_rank"] == 1

    @staticmethod
    def _laps_helper(driver, lap_times, start_lap=1):
        return [{"driver_number": driver, "lap_number": start_lap + i,
                 "lap_duration": t, "is_pit_out_lap": False}
                for i, t in enumerate(lap_times)]

    def test_weighted_median_helper_confirms_fp1_pulled_toward_fp2(self):
        # Direct check of the actual mechanism, bypassing the pace_delta
        # indirection above (which cancels out for a single driver): the
        # weighted median of (95.0, weight=0.3)x11 + (90.0, weight=1.0)x11
        # must land at 90.0, not the unweighted midpoint 92.5.
        from engine.predictor import _weighted_median, FP_WEIGHTS
        pairs = [(95.0, FP_WEIGHTS["FP1"])] * 11 + [(90.0, FP_WEIGHTS["FP2"])] * 11
        assert _weighted_median(pairs) == 90.0
        # Confirms the old unweighted behaviour really was the midpoint,
        # i.e. this is a genuine change, not a no-op.
        import statistics
        unweighted = statistics.median([95.0] * 11 + [90.0] * 11)
        assert unweighted == 92.5


@pytest.mark.integration
class TestRealMeetingIntegration:
    """Hits the real OpenF1 API against cached 2026 meetings. Run with
    `pytest -m integration`."""

    HUNGARY_2026 = 1291

    def test_grid_includes_full_22_car_field_not_hardcoded_20(self):
        # Regression test for the Cadillac bug: grid was hardcoded to
        # [:20], a leftover from the pre-2026 20-car field. 2026 added an
        # 11th team (22 cars) -- if both of one team's cars finished
        # outside the old cutoff, the team vanished from every chart keyed
        # off `grid` (team_pace, tyre availability), not even shown as
        # "no data", just silently absent.
        from engine.prerace import build_prerace_data
        pack = build_prerace_data(self.HUNGARY_2026)
        assert len(pack["grid"]) == 22
        teams = {g["team"] for g in pack["grid"]}
        assert "Cadillac" in teams

    def test_cadillac_appears_in_team_pace(self):
        from engine.prerace import build_prerace_data
        pack = build_prerace_data(self.HUNGARY_2026)
        teams = {t["team"] for t in pack["team_pace"]}
        assert "Cadillac" in teams

    def test_strategies_structurally_valid(self):
        from engine.prerace import build_prerace_data
        pack = build_prerace_data(self.HUNGARY_2026)
        strategies = pack["strategies"]
        assert strategies
        deltas = [s["time_delta"] for s in strategies]
        assert deltas == sorted(deltas)
        assert deltas[0] == 0
        for s in strategies:
            assert len(s["compound_sequence"]) == s["stops"] + 1
            assert len(s["pit_windows"]) == s["stops"]
            for j, (lo, hi) in enumerate(s["pit_windows"]):
                assert lo <= hi
                assert lo <= s["pit_laps"][j] <= hi
            assert s["viability"] in ("in play", "needs a Safety Car", "not on the table")

    MONZA_2026 = 1293

    def test_monza_medium_hard_uses_monzas_own_calibrated_shift(self):
        # User-reported: F1.com's own Monza 2026 strategy guide showed
        # MEDIUM->HARD's pit window as 22-28. A flat, 4-race-derived 6-lap
        # shift happened to reproduce that exactly (lap 25) -- but Monza's
        # OWN full 2023-2026 history (n=20 real matched drivers,
        # calibrate_undercut_shift.py) says the genuine circuit-specific
        # bias is only +1 lap, not +6. That's the more rigorous number
        # (20 real historical samples beats matching one external
        # screenshot), even though it moves away from the exact F1.com
        # figure -- pure-pace optimum was lap 31, so lap 30 here.
        from engine.prerace import build_prerace_data
        from engine.undercut_shift import CIRCUIT_UNDERCUT_SHIFT
        pack = build_prerace_data(self.MONZA_2026)
        mh = next(s for s in pack["strategies"]
                  if s["compound_sequence"] == ["MEDIUM", "HARD"])
        assert mh["pit_laps"] == [31 - round(CIRCUIT_UNDERCUT_SHIFT["monza"])]

    def test_monza_medium_soft_splash_stint_is_not_shifted(self):
        # MEDIUM->SOFT also starts on MEDIUM, but the shift is scoped off
        # of it (end_c softer than start_c) -- shifting it would otherwise
        # risk pushing the final SOFT splash stint's length past
        # SOFT_SPLASH_MAX, making the DP's own chosen sequence illegal.
        from engine.prerace import build_prerace_data
        from engine.predictor import SOFT_SPLASH_MAX
        pack = build_prerace_data(self.MONZA_2026)
        ms = next(s for s in pack["strategies"]
                  if s["compound_sequence"] == ["MEDIUM", "SOFT"])
        assert ms["stint_lengths"][1] <= SOFT_SPLASH_MAX
