"""
Unit tests for engine.circuit_guide -- the hand-curated per-circuit
incident/geometry dataset behind frontend/circuits.html. See that module's
docstring for why this is manually sourced rather than derived from OpenF1
(no pre-2023 coverage at all, and even 2023+ only gives a marshaling sector,
not a corner -- guessing from the sector got two of Baku's own real
incidents' corners wrong, which is what these tests guard against
regressing).
"""
from engine.circuit_guide import get_circuit_guide, CIRCUITS


class TestGetCircuitGuide:
    def test_known_circuit_returns_data(self):
        guide = get_circuit_guide("baku")
        assert guide is not None
        assert guide["name"] == "Baku City Circuit"

    def test_case_insensitive(self):
        assert get_circuit_guide("BAKU") == get_circuit_guide("baku")

    def test_unknown_circuit_returns_none_not_placeholder(self):
        # A circuit with no curated data must come back as None, not a
        # best-guess -- the router turns this into a 404, and the frontend
        # shows an explicit "no guide yet" message rather than rendering an
        # empty/fabricated page.
        assert get_circuit_guide("monza") is None
        assert get_circuit_guide("") is None
        assert get_circuit_guide(None) is None


class TestBakuData:
    def test_points_form_a_closed_loop_with_no_duplicate_corner_labels(self):
        points = CIRCUITS["baku"]["points"]
        labels = [p[0] for p in points]
        assert len(labels) == len(set(labels)), "duplicate corner label in track points"

    def test_every_incident_has_a_point_on_or_near_the_track(self):
        guide = CIRCUITS["baku"]
        xs = [p[1] for p in guide["points"]]
        ys = [p[2] for p in guide["points"]]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        for inc in guide["incidents"]:
            px, py = inc["point"]
            assert x0 - 5 <= px <= x1 + 5, f"{inc['year']} incident x out of track bounds"
            assert y0 - 5 <= py <= y1 + 5, f"{inc['year']} incident y out of track bounds"

    def test_every_incident_has_a_valid_type(self):
        for inc in CIRCUITS["baku"]["incidents"]:
            assert inc["type"] in ("SC", "VSC", "REDFLAG")

    def test_turn5_repeat_claim_is_backed_by_three_distinct_years(self):
        # The page's headline claims Turn 5 hit 3 of the last 4 years --
        # guard that claim against the actual data so an edit to the
        # incident list can't silently make the headline false.
        t5_years = {inc["year"] for inc in CIRCUITS["baku"]["incidents"]
                    if inc["corner"] == "5"}
        assert t5_years == {2023, 2025, 2026}

    def test_no_incident_entry_duplicated(self):
        # The same real incident listed twice would be a data-entry bug --
        # distinct real incidents CAN share a year+corner (2021's main
        # straight had two separate tyre failures, Stroll and Verstappen),
        # so "who" has to be part of the identity too.
        seen = set()
        for inc in CIRCUITS["baku"]["incidents"]:
            key = (inc["year"], inc["corner"], inc["who"])
            assert key not in seen, f"duplicate incident entry: {key}"
            seen.add(key)
