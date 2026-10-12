"""
Unit tests for engine/overtake_calibration.py -- the live, self-updating
overtaking pass-rate calibration. User asked how much of an independent
F1 strategist's published methodology (real pass-rate tables measured
from close-pair lap-time/gap data) we could adopt -- this replaces
_overtaking_cost's old purely-analytical threshold.

No real network calls here -- _completed_races/get_laps/get_all_intervals
(the parts that would hit OpenF1) are monkeypatched throughout; these
tests exercise the running-order reconstruction, sampling, threshold-
fitting, and aggregation logic in isolation.
"""
import json

import pytest

import engine.overtake_calibration as calib


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(calib, "OVERTAKE_RACES_CACHE_PATH", str(tmp_path / "races.json"))
    monkeypatch.setattr(calib, "OVERTAKE_DELTA_DATA_PATH", str(tmp_path / "output.json"))
    yield


def _interval(driver, date, gap):
    return {"driver_number": driver, "date": date, "gap_to_leader": gap}


class TestRunningOrderAt:
    def test_orders_by_gap_to_leader_ascending(self):
        intervals_by_driver = {
            1: [_interval(1, "t0", 0.0)],
            2: [_interval(2, "t0", 1.5)],
            3: [_interval(3, "t0", 0.8)],
        }
        assert calib._running_order_at(intervals_by_driver, "t1") == [1, 3, 2]

    def test_uses_latest_record_at_or_before_the_timestamp(self):
        intervals_by_driver = {
            1: [_interval(1, "t0", 0.0), _interval(1, "t2", 5.0)],
        }
        assert calib._running_order_at(intervals_by_driver, "t1") == [1]

    def test_a_lapped_car_string_sentinel_is_excluded_not_coerced(self):
        intervals_by_driver = {
            1: [_interval(1, "t0", 0.0)],
            2: [{"driver_number": 2, "date": "t0", "gap_to_leader": "+1 LAP"}],
        }
        assert calib._running_order_at(intervals_by_driver, "t1") == [1]


class TestThresholdFromSamples:
    def test_finds_the_interpolated_50_percent_crossing(self):
        # bucket 0.0 -> 0% pass rate, bucket 0.5 -> 100% -- crossing at 0.25
        samples = ([(0.0, False)] * calib.MIN_BUCKET_SAMPLES
                  + [(0.5, True)] * calib.MIN_BUCKET_SAMPLES)
        assert calib._threshold_from_samples(samples) == 0.25

    def test_below_min_bucket_samples_is_not_trusted(self):
        samples = ([(0.0, False)] * (calib.MIN_BUCKET_SAMPLES - 1)
                  + [(0.5, True)] * (calib.MIN_BUCKET_SAMPLES - 1))
        assert calib._threshold_from_samples(samples) is None

    def test_no_crossing_returns_none(self):
        # every trusted bucket is already above 50% -- no crossing to find
        samples = [(1.0, True)] * calib.MIN_BUCKET_SAMPLES
        assert calib._threshold_from_samples(samples) is None

    def test_picks_the_first_crossing_ascending(self):
        samples = ([(0.0, False)] * calib.MIN_BUCKET_SAMPLES
                  + [(0.5, True)] * calib.MIN_BUCKET_SAMPLES
                  + [(1.0, False)] * calib.MIN_BUCKET_SAMPLES
                  + [(1.5, True)] * calib.MIN_BUCKET_SAMPLES)
        assert calib._threshold_from_samples(samples) == 0.25


class TestClosePairSamples:
    def _laps(self, rows):
        # rows: (driver_number, lap_number, date_start, lap_duration, is_pit_out_lap)
        return [{"driver_number": d, "lap_number": l, "date_start": t,
                "lap_duration": dur, "is_pit_out_lap": p}
               for d, l, t, dur, p in rows]

    def test_a_faster_trailing_car_that_passes_is_sampled_as_a_pass(self, monkeypatch):
        # Driver 2 is 1s/lap faster than driver 1 on lap 5 (99.0 vs 100.0)
        # and overtakes it by lap 6 (gap_to_leader order flips). Drivers
        # 3-5 are unremarkable padding, just to clear the field_median
        # gate (needs >= 5 timed drivers).
        laps = self._laps([
            (1, 5, "t5", 100.0, False), (2, 5, "t5", 99.0, False),
            (3, 5, "t5", 100.0, False), (4, 5, "t5", 100.0, False),
            (5, 5, "t5", 100.0, False),
            # lap 6 rows only need to exist so the lap_n+1 lookahead has
            # something to find -- their own values aren't under test.
            (1, 6, "t6", 100.0, False), (2, 6, "t6", 99.0, False),
            (3, 6, "t6", 100.0, False), (4, 6, "t6", 100.0, False),
            (5, 6, "t6", 100.0, False),
        ])
        intervals = [
            _interval(1, "t5", 0.0), _interval(2, "t5", 1.0), _interval(3, "t5", 2.0),
            _interval(4, "t5", 3.0), _interval(5, "t5", 4.0),
            _interval(2, "t6", 0.0), _interval(1, "t6", 1.0), _interval(3, "t6", 2.0),
            _interval(4, "t6", 3.0), _interval(5, "t6", 4.0),
        ]
        monkeypatch.setattr(calib, "get_laps", lambda *a, **k: laps)
        monkeypatch.setattr(calib, "get_all_intervals", lambda *a, **k: intervals)

        out = calib._close_pair_samples(1)
        assert (1.0, True) in out

    def test_pit_out_lap_is_excluded(self, monkeypatch):
        laps = self._laps([
            (1, 5, "t5", 100.0, False), (2, 5, "t5", 200.0, True),
            (3, 5, "t5", 100.0, False), (4, 5, "t5", 100.0, False),
            (5, 5, "t5", 100.0, False),
            (1, 6, "t6", 100.0, False), (2, 6, "t6", 100.0, False),
            (3, 6, "t6", 100.0, False), (4, 6, "t6", 100.0, False),
            (5, 6, "t6", 100.0, False),
        ])
        intervals = [
            _interval(1, "t5", 0.0), _interval(2, "t5", 1.0), _interval(3, "t5", 1.5),
            _interval(4, "t5", 1.8), _interval(5, "t5", 1.9),
            _interval(1, "t6", 0.0), _interval(2, "t6", 1.0), _interval(3, "t6", 1.5),
            _interval(4, "t6", 1.8), _interval(5, "t6", 1.9),
        ]
        monkeypatch.setattr(calib, "get_laps", lambda *a, **k: laps)
        monkeypatch.setattr(calib, "get_all_intervals", lambda *a, **k: intervals)

        out = calib._close_pair_samples(1)
        # 4 adjacent pairs normally [(1,2),(2,3),(3,4),(4,5)] -- driver 2's
        # pit-out lap excludes BOTH pairs it appears in ((1,2) as the
        # trailing car, (2,3) as the leading car), leaving exactly 2.
        assert len(out) == 2


class TestAggregate:
    def test_circuit_with_a_clean_crossing_gets_its_own_threshold(self):
        races_cache = {
            "1": {"circuit": "Monza",
                 "samples": [(0.0, False)] * calib.MIN_BUCKET_SAMPLES
                          + [(0.5, True)] * calib.MIN_BUCKET_SAMPLES},
        }
        agg = calib.aggregate(races_cache)
        assert agg["by_circuit"]["monza"] == 0.25

    def test_circuit_with_no_crossing_is_left_out(self):
        races_cache = {
            "1": {"circuit": "Imola", "samples": [(1.0, True)] * calib.MIN_BUCKET_SAMPLES},
        }
        agg = calib.aggregate(races_cache)
        assert "imola" not in agg["by_circuit"]

    def test_default_comes_from_every_circuits_samples_pooled(self):
        races_cache = {
            "1": {"circuit": "A", "samples": [(0.0, False)] * calib.MIN_BUCKET_SAMPLES},
            "2": {"circuit": "B", "samples": [(0.5, True)] * calib.MIN_BUCKET_SAMPLES},
        }
        agg = calib.aggregate(races_cache)
        assert agg["default"] == 0.25

    def test_no_samples_anywhere_is_a_safe_no_op(self):
        races_cache = {"1": {"circuit": "A", "samples": []}, "2": None}
        agg = calib.aggregate(races_cache)
        assert agg["by_circuit"] == {}
        assert agg["default"] == 1.1   # hardcoded final fallback, no crash


class TestRunIncrementalCalibration:
    def test_only_newly_completed_races_are_evaluated(self, monkeypatch):
        with open(calib.OVERTAKE_RACES_CACHE_PATH, "w") as f:
            json.dump({"1": {"circuit": "Monza", "samples": []}}, f)

        monkeypatch.setattr(calib, "_completed_races",
                            lambda year: [{"meeting_key": 1, "circuit": "Monza"},
                                         {"meeting_key": 2, "circuit": "Baku"}]
                            if year == 2026 else [])
        evaluated = []
        def fake_evaluate(r):
            evaluated.append(r["meeting_key"])
            return {"circuit": r["circuit"], "samples": []}
        monkeypatch.setattr(calib, "evaluate_one", fake_evaluate)

        calib.run_incremental_calibration(years=(2026,))
        assert evaluated == [2]

    def test_result_is_persisted_to_output_path(self, monkeypatch):
        monkeypatch.setattr(calib, "_completed_races",
                            lambda year: [{"meeting_key": 1, "circuit": "Monza"}]
                            if year == 2026 else [])
        monkeypatch.setattr(calib, "evaluate_one",
                            lambda r: {"circuit": r["circuit"],
                                       "samples": [(0.0, False)] * calib.MIN_BUCKET_SAMPLES
                                                 + [(0.5, True)] * calib.MIN_BUCKET_SAMPLES})

        calib.run_incremental_calibration(years=(2026,))
        with open(calib.OVERTAKE_DELTA_DATA_PATH) as f:
            written = json.load(f)
        assert written["by_circuit"]["monza"] == 0.25


class TestLoadCalibration:
    def test_missing_file_returns_none(self):
        assert calib.load_calibration() is None

    def test_valid_file_is_loaded(self):
        calib._save_json(calib.OVERTAKE_DELTA_DATA_PATH,
                         {"by_circuit": {"monza": 0.25}, "default": 1.1})
        loaded = calib.load_calibration()
        assert loaded["by_circuit"]["monza"] == 0.25

    def test_corrupt_file_returns_none_not_a_crash(self):
        with open(calib.OVERTAKE_DELTA_DATA_PATH, "w") as f:
            f.write("{not valid json")
        assert calib.load_calibration() is None

    def test_file_missing_expected_keys_returns_none(self):
        calib._save_json(calib.OVERTAKE_DELTA_DATA_PATH, {"unexpected": "shape"})
        assert calib.load_calibration() is None
