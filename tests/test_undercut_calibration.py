"""
Unit tests for engine/undercut_calibration.py -- the live, self-updating
version of the per-circuit undercut-shift calibration. User asked
directly: "automatic recalibration," since the original calibration was a
one-off script whose output got hand-copied into a hardcoded dict and
then never touched again.

No real network calls here -- _completed_races/evaluate_one (the parts
that hit OpenF1) are monkeypatched throughout; these tests exercise the
incremental-caching and aggregation logic in isolation.
"""
import json

import pytest

import engine.undercut_calibration as calib


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(calib, "RACES_CACHE_PATH", str(tmp_path / "races.json"))
    monkeypatch.setattr(calib, "OUTPUT_PATH", str(tmp_path / "output.json"))
    yield


class TestAggregateByCircuit:
    def test_circuit_with_enough_samples_gets_its_own_shift(self):
        races_cache = {
            "1": {"circuit": "Monza",
                 "matches": [{"error_laps": e} for e in [-1] * calib.MIN_SAMPLES]},
        }
        agg = calib.aggregate_by_circuit(races_cache)
        assert "monza" in agg["by_circuit"]
        assert agg["by_circuit"]["monza"] == 1.0   # shift = -median(error)

    def test_circuit_below_min_samples_falls_back_to_default(self):
        races_cache = {
            "1": {"circuit": "Imola",
                 "matches": [{"error_laps": -5} for _ in range(calib.MIN_SAMPLES - 1)]},
        }
        agg = calib.aggregate_by_circuit(races_cache)
        assert "imola" not in agg["by_circuit"]

    def test_default_is_field_median_across_all_matches(self):
        races_cache = {
            "1": {"circuit": "A", "matches": [{"error_laps": -2}] * 3},
            "2": {"circuit": "B", "matches": [{"error_laps": -6}] * 3},
        }
        agg = calib.aggregate_by_circuit(races_cache)
        assert agg["default"] == 4.0   # -median([-2,-2,-2,-6,-6,-6]) = 4.0

    def test_no_matches_anywhere_is_a_safe_no_op(self):
        races_cache = {"1": {"circuit": "A", "matches": []}, "2": None}
        agg = calib.aggregate_by_circuit(races_cache)
        assert agg["by_circuit"] == {}
        assert agg["default"] == 4.0   # hardcoded final fallback, no crash

    def test_positive_and_negative_shifts_both_representable(self):
        # Real finding this session: some circuits need pitting LATER
        # (negative shift), not just earlier -- the aggregation itself
        # must not clip or assume one sign.
        races_cache = {
            "1": {"circuit": "Early", "matches": [{"error_laps": -5}] * calib.MIN_SAMPLES},
            "2": {"circuit": "Late", "matches": [{"error_laps": 5}] * calib.MIN_SAMPLES},
        }
        agg = calib.aggregate_by_circuit(races_cache)
        assert agg["by_circuit"]["early"] > 0
        assert agg["by_circuit"]["late"] < 0


class TestRunIncrementalCalibration:
    def test_only_newly_completed_races_are_evaluated(self, monkeypatch, tmp_path):
        # Pre-seed the races cache as if meeting 1 was already evaluated
        # in a previous run.
        with open(calib.RACES_CACHE_PATH, "w") as f:
            json.dump({"1": {"circuit": "Monza", "matches": []}}, f)

        monkeypatch.setattr(calib, "_completed_races",
                            lambda year: [{"meeting_key": 1, "circuit": "Monza"},
                                         {"meeting_key": 2, "circuit": "Baku"}]
                            if year == 2026 else [])
        evaluated = []
        def fake_evaluate(r):
            evaluated.append(r["meeting_key"])
            return {"circuit": r["circuit"], "matches": []}
        monkeypatch.setattr(calib, "evaluate_one", fake_evaluate)

        calib.run_incremental_calibration(years=(2026,))
        assert evaluated == [2]   # meeting 1 already cached, only 2 is new

    def test_result_is_persisted_to_output_path(self, monkeypatch):
        monkeypatch.setattr(calib, "_completed_races",
                            lambda year: [{"meeting_key": 1, "circuit": "Monza"}]
                            if year == 2026 else [])
        monkeypatch.setattr(calib, "evaluate_one",
                            lambda r: {"circuit": r["circuit"],
                                       "matches": [{"error_laps": -1}] * calib.MIN_SAMPLES})

        calib.run_incremental_calibration(years=(2026,))
        with open(calib.OUTPUT_PATH) as f:
            written = json.load(f)
        assert written["by_circuit"]["monza"] == 1.0

    def test_second_run_with_no_new_races_still_refreshes_output(self, monkeypatch):
        # A day where nothing new completed must still be safe to call --
        # not just a no-op that leaves output.json stale/missing.
        with open(calib.RACES_CACHE_PATH, "w") as f:
            json.dump({"1": {"circuit": "Monza",
                             "matches": [{"error_laps": -1}] * calib.MIN_SAMPLES}}, f)
        monkeypatch.setattr(calib, "_completed_races", lambda year: [])
        monkeypatch.setattr(calib, "evaluate_one", lambda r: (_ for _ in ()).throw(
            AssertionError("should not be called -- nothing new")))

        agg = calib.run_incremental_calibration(years=(2026,))
        assert agg["by_circuit"]["monza"] == 1.0


class TestLoadCalibration:
    def test_missing_file_returns_none(self):
        assert calib.load_calibration() is None

    def test_valid_file_is_loaded(self):
        calib._save_json(calib.OUTPUT_PATH, {"by_circuit": {"monza": 1.0}, "default": 4.0})
        loaded = calib.load_calibration()
        assert loaded["by_circuit"]["monza"] == 1.0

    def test_corrupt_file_returns_none_not_a_crash(self):
        with open(calib.OUTPUT_PATH, "w") as f:
            f.write("{not valid json")
        assert calib.load_calibration() is None

    def test_file_missing_expected_keys_returns_none(self):
        calib._save_json(calib.OUTPUT_PATH, {"unexpected": "shape"})
        assert calib.load_calibration() is None
