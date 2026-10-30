"""
Unit tests for data.live_timing_feed's pure logic -- the deep-merge and
extraction functions that turn F1's raw live-timing message shapes into
the {driver_number: [{"compound","new","total_laps"}, ...]} structure
engine.tyre_inventory consumes. No network: these exercise the parsing
exactly as it will run against real messages, with synthetic ones shaped
like real F1 TimingAppData payloads (confirmed against the darshjoshi/
pitwall project's own field reads).
"""
import json
import os

from data.live_timing_feed import (
    _deep_merge, _session_finished, extract_tyre_flags, load_captured_flags,
)


class TestDeepMerge:
    def test_leaf_value_overwrites(self):
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_nested_dicts_recurse(self):
        base = {"Lines": {"44": {"Position": "1"}}}
        update = {"Lines": {"44": {"Position": "2"}}}
        assert _deep_merge(base, update) == {"Lines": {"44": {"Position": "2"}}}

    def test_keys_only_in_base_are_preserved(self):
        base = {"Lines": {"44": {"Position": "1", "GapToLeader": "0"}}}
        update = {"Lines": {"44": {"Position": "2"}}}
        merged = _deep_merge(base, update)
        assert merged["Lines"]["44"] == {"Position": "2", "GapToLeader": "0"}

    def test_new_driver_added_by_delta(self):
        base = {"Lines": {"44": {"Position": "1"}}}
        update = {"Lines": {"63": {"Position": "2"}}}
        merged = _deep_merge(base, update)
        assert set(merged["Lines"]) == {"44", "63"}

    def test_non_dict_update_replaces_base_entirely(self):
        assert _deep_merge({"a": 1}, "not a dict") == "not a dict"

    def test_none_base_takes_the_update_wholesale(self):
        assert _deep_merge(None, {"a": 1}) == {"a": 1}


class TestExtractTyreFlags:
    def test_reads_genuine_new_flag_not_an_age_guess(self):
        # Real shape: Lines keyed by driver number as a string, each with a
        # Stints list; New is the string "true"/"false" F1's feed actually
        # sends, not a Python bool.
        state = {
            "TimingAppData": {
                "Lines": {
                    "12": {"Stints": [
                        {"Compound": "MEDIUM", "New": "true", "TotalLaps": 6},
                        {"Compound": "SOFT", "New": "true", "TotalLaps": 3},
                        {"Compound": "SOFT", "New": "false", "TotalLaps": 3},
                    ]},
                }
            }
        }
        flags = extract_tyre_flags(state)
        assert flags[12] == [
            {"compound": "MEDIUM", "new": True, "total_laps": 6},
            {"compound": "SOFT", "new": True, "total_laps": 3},
            {"compound": "SOFT", "new": False, "total_laps": 3},
        ]

    def test_stints_as_dict_keyed_by_index_gets_ordered(self):
        # Some delta messages carry Stints as a dict keyed by string index
        # rather than a list -- must still come out in stint order.
        state = {
            "TimingAppData": {
                "Lines": {
                    "1": {"Stints": {
                        "1": {"Compound": "HARD", "New": "false", "TotalLaps": 10},
                        "0": {"Compound": "SOFT", "New": "true", "TotalLaps": 5},
                    }}
                }
            }
        }
        flags = extract_tyre_flags(state)
        assert [s["compound"] for s in flags[1]] == ["SOFT", "HARD"]

    def test_missing_timing_app_data_returns_empty(self):
        assert extract_tyre_flags({}) == {}
        assert extract_tyre_flags({"TimingAppData": {}}) == {}

    def test_driver_with_no_stints_yet_is_skipped(self):
        state = {"TimingAppData": {"Lines": {"1": {"Stints": []}}}}
        assert extract_tyre_flags(state) == {}

    def test_non_numeric_driver_key_is_skipped_not_raised(self):
        state = {"TimingAppData": {"Lines": {"_kf": {"Stints": [
            {"Compound": "SOFT", "New": "true", "TotalLaps": 1}
        ]}}}}
        assert extract_tyre_flags(state) == {}


class TestSessionFinished:
    def test_finalised_status_is_finished(self):
        assert _session_finished({"SessionStatus": {"Status": "Finalised"}})

    def test_started_status_is_not_finished(self):
        assert not _session_finished({"SessionStatus": {"Status": "Started"}})

    def test_no_status_yet_is_not_finished(self):
        assert not _session_finished({})


class TestLoadCapturedFlags:
    def test_missing_file_returns_none(self, tmp_path):
        assert load_captured_flags(99999, cache_dir=str(tmp_path)) is None

    def test_existing_file_loads_with_int_driver_keys(self, tmp_path):
        path = os.path.join(str(tmp_path), "123.json")
        with open(path, "w") as f:
            json.dump({"12": [{"compound": "SOFT", "new": True, "total_laps": 3}]}, f)
        flags = load_captured_flags(123, cache_dir=str(tmp_path))
        assert flags == {12: [{"compound": "SOFT", "new": True, "total_laps": 3}]}
