"""
Unit tests for engine.briefing.validate_tyre_claims against the "beats"
narrative schema (NARRATIVE_SCHEMA, bumped at PACK_VERSION 12): the hallucination
guardrail used to join only the narrative's top-level string values into one
blob of prose. `beats` is a list of dicts, so a tyre-sequence hallucination
buried inside a beat's `text` field would have been silently invisible to the
checker -- found while redesigning the schema, fixed by having
validate_tyre_claims recurse through lists/dicts via _all_strings.
"""
from engine.briefing import validate_tyre_claims, NARRATIVE_SCHEMA


def _result(acronym, compound_sequence):
    return {"acronym": acronym, "compound_sequence": compound_sequence}


class TestValidateTyreClaimsRecursesIntoBeats:
    def test_hallucination_inside_a_beat_is_caught(self):
        results = [_result("VER", "INTERMEDIATE-SOFT-SOFT-SOFT-SOFT")]
        narrative = {
            "headline": "x",
            "lede": "a clean afternoon",
            "beats": [
                {"acronym": "VER", "tag": "strategy", "stat": "+1.2s",
                 "text": "VER ran a HARD-HARD-HARD sequence to the flag."},
            ],
            "tyre_verdict": "fine",
            "stops_verdict": "fine",
        }
        warnings = validate_tyre_claims(narrative, results)
        assert warnings and "HARD-HARD-HARD" in warnings[0]

    def test_a_real_sequence_inside_a_beat_is_not_flagged(self):
        results = [_result("VER", "INTERMEDIATE-SOFT-SOFT-SOFT-SOFT")]
        narrative = {
            "headline": "x",
            "lede": "a clean afternoon",
            "beats": [
                {"acronym": "VER", "tag": "strategy", "stat": "+1.2s",
                 "text": "VER's SOFT-SOFT-SOFT run anchored the win."},
            ],
            "tyre_verdict": "fine",
            "stops_verdict": "fine",
        }
        assert validate_tyre_claims(narrative, results) == []

    def test_empty_beats_list_is_fine(self):
        narrative = {"headline": "x", "lede": "y", "beats": [],
                     "tyre_verdict": "fine", "stops_verdict": "fine"}
        assert validate_tyre_claims(narrative, []) == []

    def test_no_narrative_returns_no_warnings(self):
        assert validate_tyre_claims(None, []) == []


class TestNarrativeSchemaShape:
    def test_beats_field_is_an_array_of_objects_with_the_expected_keys(self):
        beats_schema = NARRATIVE_SCHEMA["properties"]["beats"]
        assert beats_schema["type"] == "array"
        item_props = set(beats_schema["items"]["properties"].keys())
        assert item_props == {"acronym", "tag", "stat", "text"}

    def test_required_fields_no_longer_include_the_old_prose_blocks(self):
        required = set(NARRATIVE_SCHEMA["required"])
        assert required == {"headline", "lede", "beats", "tyre_verdict", "stops_verdict"}
        for removed in ("race_story", "tyre_story", "the_stops", "strategy_verdicts"):
            assert removed not in NARRATIVE_SCHEMA["properties"]
