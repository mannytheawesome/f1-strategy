"""
Unit tests for engine.briefing._build_whatif_scenario -- the auto-generated
"what if they'd pitted differently" counterfactual added 2026-10-08,
reusing engine.whatif.run_whatif (the same engine behind the manual what-if
editor) so the debrief can show a real, quantified strategy alternative
instead of only prose, following the same chart the interactive editor
already uses.
"""
from unittest.mock import patch

from engine.briefing import _build_whatif_scenario, WHATIF_MAX_ATTEMPTS


def _stint(compound, lap_start, lap_end, tyre_age=0):
    return {"compound": compound, "lap_start": lap_start, "lap_end": lap_end,
            "tyre_age_at_start": tyre_age}


def _stop(acronym, num, lap, gain_s, grade="neutral"):
    return {"acronym": acronym, "driver_number": num, "lap": lap,
            "from": "SOFT", "to": "HARD", "old_tyre_age": lap,
            "neutralised": None, "under_sc": False,
            "gain_s": gain_s, "grade": grade}


def _fake_run_whatif(delta_position=0, delta_gap=0.0, raises=False):
    def _run(session_key, driver_number, edited_stints):
        if raises:
            raise ValueError("invalid plan")
        return {"delta": {"position": delta_position, "gap": delta_gap},
                "trace": {"anchor_lap": 1, "baseline": [], "modified": []}}
    return _run


class TestBuildWhatifScenario:
    def test_empty_stops_graded_returns_none(self):
        assert _build_whatif_scenario(1, {}, [], {}, 50) is None

    def test_no_room_either_side_of_the_stop_is_skipped(self):
        # Mirrors the real Bahrain case: a 1-lap stint either side of the
        # worst stop leaves no room to try an alternate lap.
        stints_by_driver = {3: [_stint("INTERMEDIATE", 1, 5), _stint("SOFT", 6, 6),
                                _stint("HARD", 7, 50)]}
        stops_graded = [_stop("VER", 3, 6, -50.0, "howler")]
        with patch("engine.whatif.run_whatif", _fake_run_whatif()):
            assert _build_whatif_scenario(1, stints_by_driver, stops_graded, {}, 50) is None

    def test_stop_earlier_than_whatif_min_stop_lap_is_skipped(self):
        stints_by_driver = {3: [_stint("SOFT", 1, 3), _stint("HARD", 4, 50)]}
        stops_graded = [_stop("VER", 3, 3, -50.0, "howler")]
        with patch("engine.whatif.run_whatif", _fake_run_whatif(delta_position=5)):
            assert _build_whatif_scenario(1, stints_by_driver, stops_graded, {}, 50) is None

    def test_retired_driver_is_skipped(self):
        stints_by_driver = {3: [_stint("SOFT", 1, 10), _stint("HARD", 11, 50)]}
        stops_graded = [_stop("VER", 3, 10, -5.0, "costly")]
        with patch("engine.whatif.run_whatif", _fake_run_whatif(delta_position=3)):
            result = _build_whatif_scenario(1, stints_by_driver, stops_graded,
                                            {3: True}, 50)
        assert result is None

    def test_an_improving_position_change_is_reported(self):
        stints_by_driver = {3: [_stint("SOFT", 1, 10), _stint("HARD", 11, 50)]}
        stops_graded = [_stop("VER", 3, 10, -5.0, "costly")]
        with patch("engine.whatif.run_whatif", _fake_run_whatif(delta_position=2, delta_gap=4.1)):
            result = _build_whatif_scenario(1, stints_by_driver, stops_graded, {}, 50)
        assert result["acronym"] == "VER"
        assert result["real_stop_lap"] == 10
        assert result["delta_position"] == 2
        assert result["delta_gap_s"] == 4.1

    def test_a_gap_only_win_above_threshold_is_reported_even_with_no_position_change(self):
        stints_by_driver = {3: [_stint("SOFT", 1, 10), _stint("HARD", 11, 50)]}
        stops_graded = [_stop("VER", 3, 10, -5.0, "costly")]
        with patch("engine.whatif.run_whatif", _fake_run_whatif(delta_position=0, delta_gap=4.0)):
            result = _build_whatif_scenario(1, stints_by_driver, stops_graded, {}, 50)
        assert result is not None
        assert result["delta_position"] == 0

    def test_a_small_gap_only_win_below_threshold_is_not_reported(self):
        stints_by_driver = {3: [_stint("SOFT", 1, 10), _stint("HARD", 11, 50)]}
        stops_graded = [_stop("VER", 3, 10, -5.0, "costly")]
        with patch("engine.whatif.run_whatif", _fake_run_whatif(delta_position=0, delta_gap=0.5)):
            result = _build_whatif_scenario(1, stints_by_driver, stops_graded, {}, 50)
        assert result is None

    def test_a_losing_alternative_is_not_reported(self):
        stints_by_driver = {3: [_stint("SOFT", 1, 10), _stint("HARD", 11, 50)]}
        stops_graded = [_stop("VER", 3, 10, -5.0, "costly")]
        with patch("engine.whatif.run_whatif", _fake_run_whatif(delta_position=-1, delta_gap=-2.0)):
            result = _build_whatif_scenario(1, stints_by_driver, stops_graded, {}, 50)
        assert result is None

    def test_every_candidate_raising_degrades_to_none(self):
        stints_by_driver = {3: [_stint("SOFT", 1, 10), _stint("HARD", 11, 50)]}
        stops_graded = [_stop("VER", 3, 10, -5.0, "costly")]
        with patch("engine.whatif.run_whatif", _fake_run_whatif(raises=True)):
            result = _build_whatif_scenario(1, stints_by_driver, stops_graded, {}, 50)
        assert result is None

    def test_a_small_lap_shortfall_is_padded_and_still_evaluated(self):
        # A classified-but-lapped finisher's own stints fall short of
        # total_laps by a couple of laps -- must still be eligible.
        stints_by_driver = {3: [_stint("SOFT", 1, 10), _stint("HARD", 11, 48)]}
        stops_graded = [_stop("VER", 3, 10, -5.0, "costly")]
        with patch("engine.whatif.run_whatif", _fake_run_whatif(delta_position=1)):
            result = _build_whatif_scenario(1, stints_by_driver, stops_graded, {}, 50)
        assert result is not None

    def test_a_large_lap_shortfall_is_not_padded_and_is_skipped(self):
        # A big gap means something else happened (retirement-adjacent,
        # mechanical) that padding would misrepresent.
        stints_by_driver = {3: [_stint("SOFT", 1, 10), _stint("HARD", 11, 30)]}
        stops_graded = [_stop("VER", 3, 10, -5.0, "costly")]
        with patch("engine.whatif.run_whatif", _fake_run_whatif(delta_position=5)):
            result = _build_whatif_scenario(1, stints_by_driver, stops_graded, {}, 50)
        assert result is None

    def test_walks_past_an_ineligible_worse_stop_to_an_eligible_one(self):
        # The single worst stop has no room to shift; the next one down the
        # list does and should still be found.
        stints_by_driver = {
            3:  [_stint("INTERMEDIATE", 1, 1), _stint("SOFT", 2, 50)],   # no room
            16: [_stint("SOFT", 1, 10), _stint("HARD", 11, 50)],         # has room
        }
        stops_graded = [
            _stop("LEC", 16, 10, -3.0, "costly"),
            _stop("VER", 3, 1, -60.0, "howler"),
        ]
        with patch("engine.whatif.run_whatif", _fake_run_whatif(delta_position=1)):
            result = _build_whatif_scenario(1, stints_by_driver, stops_graded, {}, 50)
        assert result is not None
        assert result["acronym"] == "LEC"

    def test_attempt_budget_is_a_real_module_constant(self):
        # Sanity check the budget this suite relies on being bounded hasn't
        # silently been removed or renamed.
        assert isinstance(WHATIF_MAX_ATTEMPTS, int) and WHATIF_MAX_ATTEMPTS > 0
