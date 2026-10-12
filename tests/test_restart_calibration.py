"""
Unit tests for engine/restart_calibration.py -- the live, self-updating
cold-tyre Safety Car/VSC restart-penalty calibration. User-reported
(Singapore 2026): a MEDIUM->HARD 1-stop ranked as a viable candidate
despite HARD never being raced there historically, traced to the model
having no concept of a restart's cold-tyre position swing at all.

No real network calls here -- _completed_races/get_race_control/get_laps/
get_stints (the parts that would hit OpenF1) are monkeypatched throughout;
these tests exercise the event-parsing, residual, and aggregation logic
in isolation.
"""
import json

import pytest

import engine.restart_calibration as calib


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(calib, "RESTART_RACES_CACHE_PATH", str(tmp_path / "races.json"))
    monkeypatch.setattr(calib, "RESTART_DELTA_DATA_PATH", str(tmp_path / "output.json"))
    yield


def _rc_msg(category, message, lap_number, date):
    return {"category": category, "message": message, "lap_number": lap_number,
           "date": date, "flag": None, "scope": None}


class TestRestartEvents:
    def test_a_real_closed_event_is_kept(self, monkeypatch):
        messages = [
            _rc_msg("SafetyCar", "SAFETY CAR DEPLOYED", 10, "t1"),
            _rc_msg("SafetyCar", "SAFETY CAR ENDING", 13, "t2"),
        ]
        monkeypatch.setattr(calib, "get_race_control", lambda *a, **k: messages)
        events = calib._restart_events(1)
        assert events == [{"type": "SC", "start_lap": 10, "end_lap": 13}]

    def test_an_event_with_no_ending_message_is_dropped_not_fabricated(self, monkeypatch):
        # e.g. a red-flag finish -- real case this guards against: the
        # shared get_sc_laps_from_race_control synthesises
        # end_lap = start_lap + 5 here, a fabricated lap that must never
        # be pooled into a "measured restart" sample.
        messages = [_rc_msg("SafetyCar", "SAFETY CAR DEPLOYED", 40, "t1")]
        monkeypatch.setattr(calib, "get_race_control", lambda *a, **k: messages)
        assert calib._restart_events(1) == []

    def test_vsc_is_distinguished_from_full_sc(self, monkeypatch):
        messages = [
            _rc_msg("SafetyCar", "VIRTUAL SAFETY CAR DEPLOYED", 5, "t1"),
            _rc_msg("SafetyCar", "VSC ENDING", 7, "t2"),
        ]
        monkeypatch.setattr(calib, "get_race_control", lambda *a, **k: messages)
        events = calib._restart_events(1)
        assert events == [{"type": "VSC", "start_lap": 5, "end_lap": 7}]

    def test_non_safety_car_messages_are_ignored(self, monkeypatch):
        messages = [_rc_msg("Flag", "YELLOW FLAG", 10, "t1")]
        monkeypatch.setattr(calib, "get_race_control", lambda *a, **k: messages)
        assert calib._restart_events(1) == []


class TestTrueRestartLap:
    """Regression guard for a real finding: Singapore 2026's two VSCs in
    the SAME race disagreed on whether race_control's end_lap was
    already back to racing pace (confirmed directly against session_key
    11388's real race_control + laps) -- trusting end_lap at face value
    mixes a still-neutralised lap in with genuine restart laps."""

    def _laps_dict(self, rows):
        # rows: list of (lap_number, lap_duration) -- one synthetic driver
        out: dict[int, list[dict]] = {}
        for l, t in rows:
            out.setdefault(l, []).append({"lap_duration": t, "is_pit_out_lap": False})
        return out

    def test_end_lap_itself_when_already_back_to_pace(self):
        # Mirrors Singapore's second VSC: end_lap already at baseline pace.
        laps_by_lap = self._laps_dict(
            [(l, 99.0) for l in (36, 37, 38)] + [(40, 98.6), (40, 98.6)])
        event = {"start_lap": 39, "end_lap": 40}
        assert calib._true_restart_lap(event, laps_by_lap) == 40

    def test_falls_through_to_end_lap_plus_one_when_end_lap_still_slow(self):
        # Mirrors Singapore's first VSC: end_lap (9) still neutralised
        # (108.2s vs a ~99.5s baseline), real restart is end_lap+1 (10).
        laps_by_lap = self._laps_dict(
            [(l, 99.5) for l in (5, 6, 7)]
            + [(9, 108.2), (9, 108.2)] + [(10, 99.2), (10, 99.2)])
        event = {"start_lap": 8, "end_lap": 9}
        assert calib._true_restart_lap(event, laps_by_lap) == 10

    def test_no_pre_event_baseline_returns_none(self):
        # e.g. a lap-1 incident -- nothing to compare against.
        laps_by_lap = self._laps_dict([(2, 99.0), (2, 99.0)])
        event = {"start_lap": 1, "end_lap": 2}
        assert calib._true_restart_lap(event, laps_by_lap) is None

    def test_no_candidate_ever_gets_back_to_pace_returns_none(self):
        # e.g. the race ends under caution shortly after.
        laps_by_lap = self._laps_dict(
            [(l, 99.0) for l in (17, 18, 19)] + [(21, 140.0), (22, 141.0), (23, 142.0)])
        event = {"start_lap": 20, "end_lap": 21}
        assert calib._true_restart_lap(event, laps_by_lap) is None


class TestRestartLapResiduals:
    def _laps(self, rows):
        # rows: list of (driver_number, lap_number, lap_duration, is_pit_out_lap)
        return [{"driver_number": d, "lap_number": l, "lap_duration": t,
                "is_pit_out_lap": p} for d, l, t, p in rows]

    def _stints(self, rows):
        # rows: list of (driver_number, lap_start, lap_end, compound)
        return [{"driver_number": d, "lap_start": s, "lap_end": e, "compound": c}
               for d, s, e, c in rows]

    def _baseline(self, start_lap, time=100.0):
        # Normal-pace laps right before start_lap, so _true_restart_lap
        # has something to compare the candidate restart lap against --
        # a fixed driver_number (99) that never appears in any test's
        # stints, so it's never itself sampled as a restart-lap residual.
        return self._laps([(99, l, time, False)
                           for l in range(start_lap - 3, start_lap)])

    def test_slower_compound_shows_a_positive_residual_vs_field_median(self, monkeypatch):
        events = [{"type": "SC", "start_lap": 10, "end_lap": 13}]
        laps = self._baseline(10) + self._laps([
            (1, 13, 100.0, False), (2, 13, 100.0, False), (3, 13, 110.0, False),
        ])
        stints = self._stints([
            (1, 1, 20, "SOFT"), (2, 1, 20, "MEDIUM"), (3, 1, 20, "HARD"),
        ])
        monkeypatch.setattr(calib, "get_laps", lambda *a, **k: laps)
        monkeypatch.setattr(calib, "get_stints", lambda *a, **k: stints)

        out = calib._restart_lap_residuals(1, events)
        by_compound = {s["compound"]: s["residual_s"] for s in out}
        # field median of [100, 100, 110] = 100
        assert by_compound["HARD"] == 10.0
        assert by_compound["SOFT"] == 0.0

    def test_pit_out_lap_is_excluded(self, monkeypatch):
        events = [{"type": "SC", "start_lap": 10, "end_lap": 13}]
        laps = self._baseline(10) + self._laps([
            (1, 13, 100.0, False), (2, 13, 200.0, True), (3, 13, 101.0, False),
        ])
        stints = self._stints([
            (1, 1, 20, "SOFT"), (2, 1, 20, "SOFT"), (3, 1, 20, "SOFT"),
        ])
        monkeypatch.setattr(calib, "get_laps", lambda *a, **k: laps)
        monkeypatch.setattr(calib, "get_stints", lambda *a, **k: stints)

        out = calib._restart_lap_residuals(1, events)
        assert len(out) == 2   # driver 2's pit-out lap never sampled

    def test_a_lap_that_is_the_stints_first_lap_is_excluded(self, monkeypatch):
        # Just pitted into a new compound on this exact lap -- ambiguous
        # which tyre was really on track for most of it.
        events = [{"type": "SC", "start_lap": 10, "end_lap": 13}]
        laps = self._baseline(10) + self._laps([(1, 13, 100.0, False), (2, 13, 101.0, False)])
        stints = self._stints([(1, 1, 20, "SOFT"), (2, 13, 20, "MEDIUM")])
        monkeypatch.setattr(calib, "get_laps", lambda *a, **k: laps)
        monkeypatch.setattr(calib, "get_stints", lambda *a, **k: stints)

        out = calib._restart_lap_residuals(1, events)
        assert [s["compound"] for s in out] == ["SOFT"]

    def test_unknown_compound_is_excluded(self, monkeypatch):
        events = [{"type": "SC", "start_lap": 10, "end_lap": 13}]
        laps = self._baseline(10) + self._laps([(1, 13, 100.0, False), (2, 13, 101.0, False)])
        stints = self._stints([(1, 1, 20, "SOFT"), (2, 1, 20, "UNKNOWN")])
        monkeypatch.setattr(calib, "get_laps", lambda *a, **k: laps)
        monkeypatch.setattr(calib, "get_stints", lambda *a, **k: stints)

        out = calib._restart_lap_residuals(1, events)
        assert [s["compound"] for s in out] == ["SOFT"]

    def test_a_retired_driver_has_no_lap_row_and_is_simply_absent(self, monkeypatch):
        events = [{"type": "SC", "start_lap": 10, "end_lap": 13}]
        laps = self._baseline(10) + self._laps([(1, 13, 100.0, False), (2, 13, 101.0, False)])
        # driver 3 retired before lap 13 -- no lap row at all, no stint
        # bound to lap 13 either.
        stints = self._stints([(1, 1, 20, "SOFT"), (2, 1, 20, "SOFT"),
                               (3, 1, 7, "HARD")])
        monkeypatch.setattr(calib, "get_laps", lambda *a, **k: laps)
        monkeypatch.setattr(calib, "get_stints", lambda *a, **k: stints)

        out = calib._restart_lap_residuals(1, events)
        assert len(out) == 2

    def test_fewer_than_two_cars_on_the_lap_yields_no_samples(self, monkeypatch):
        events = [{"type": "SC", "start_lap": 10, "end_lap": 13}]
        laps = self._baseline(10) + self._laps([(1, 13, 100.0, False)])
        stints = self._stints([(1, 1, 20, "SOFT")])
        monkeypatch.setattr(calib, "get_laps", lambda *a, **k: laps)
        monkeypatch.setattr(calib, "get_stints", lambda *a, **k: stints)

        assert calib._restart_lap_residuals(1, events) == []


class TestAggregate:
    def test_compound_with_enough_samples_gets_its_own_delta(self):
        races_cache = {
            "1": {"samples": [{"compound": "HARD", "residual_s": 1.0}] * calib.MIN_SAMPLES},
        }
        agg = calib.aggregate(races_cache)
        assert agg["by_compound"]["HARD"] == 1.0

    def test_compound_below_min_samples_is_left_out(self):
        races_cache = {
            "1": {"samples": [{"compound": "SOFT", "residual_s": -1.0}]
                            * (calib.MIN_SAMPLES - 1)},
        }
        agg = calib.aggregate(races_cache)
        assert "SOFT" not in agg["by_compound"]

    def test_positive_and_negative_deltas_both_representable(self):
        races_cache = {
            "1": {"samples": [{"compound": "HARD", "residual_s": 2.0}] * calib.MIN_SAMPLES
                           + [{"compound": "SOFT", "residual_s": -1.0}] * calib.MIN_SAMPLES},
        }
        agg = calib.aggregate(races_cache)
        assert agg["by_compound"]["HARD"] > 0
        assert agg["by_compound"]["SOFT"] < 0

    def test_no_samples_anywhere_is_a_safe_no_op(self):
        races_cache = {"1": {"samples": []}, "2": None}
        agg = calib.aggregate(races_cache)
        assert agg["by_compound"] == {}
        assert agg["n_races"] == 0


class TestRunIncrementalCalibration:
    def test_only_newly_completed_races_are_evaluated(self, monkeypatch):
        with open(calib.RESTART_RACES_CACHE_PATH, "w") as f:
            json.dump({"1": {"samples": []}}, f)

        monkeypatch.setattr(calib, "_completed_races",
                            lambda year: [{"meeting_key": 1}, {"meeting_key": 2}]
                            if year == 2026 else [])
        evaluated = []
        def fake_evaluate(r):
            evaluated.append(r["meeting_key"])
            return {"samples": []}
        monkeypatch.setattr(calib, "evaluate_one", fake_evaluate)

        calib.run_incremental_calibration(years=(2026,))
        assert evaluated == [2]

    def test_result_is_persisted_to_output_path(self, monkeypatch):
        monkeypatch.setattr(calib, "_completed_races",
                            lambda year: [{"meeting_key": 1}] if year == 2026 else [])
        monkeypatch.setattr(calib, "evaluate_one",
                            lambda r: {"samples": [{"compound": "HARD", "residual_s": 1.0}]
                                                  * calib.MIN_SAMPLES})

        calib.run_incremental_calibration(years=(2026,))
        with open(calib.RESTART_DELTA_DATA_PATH) as f:
            written = json.load(f)
        assert written["by_compound"]["HARD"] == 1.0


class TestLoadCalibration:
    def test_missing_file_returns_none(self):
        assert calib.load_calibration() is None

    def test_valid_file_is_loaded(self):
        calib._save_json(calib.RESTART_DELTA_DATA_PATH, {"by_compound": {"HARD": 1.0}})
        loaded = calib.load_calibration()
        assert loaded["by_compound"]["HARD"] == 1.0

    def test_corrupt_file_returns_none_not_a_crash(self):
        with open(calib.RESTART_DELTA_DATA_PATH, "w") as f:
            f.write("{not valid json")
        assert calib.load_calibration() is None

    def test_file_missing_expected_keys_returns_none(self):
        calib._save_json(calib.RESTART_DELTA_DATA_PATH, {"unexpected": "shape"})
        assert calib.load_calibration() is None
