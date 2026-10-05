"""
Unit tests for engine.whatif._validate_edited's Intermediate-tyre support.

User-reported 2026-10-05: the what-if editor on a real wet race's debrief
(Bahrain, meeting 1308, VER's actual stints were Intermediate(1 lap) ->
Soft -> Soft) rejected the plan outright -- _validate_edited treated any
non-DRY compound as unsupported, so even the race's own real, unedited
stints failed validation the moment the editor auto-loaded them, before the
user touched anything. The underlying simulation math
(engine.predictor._lap_t/_stint_time) was already compound-agnostic and a
real INTERMEDIATE degradation curve was already being fitted -- only this
validation gate (and the tyre-inventory check right after it, which has no
data for Intermediate/Wet at all and would reject with a false "0
available") were blocking it.
"""
from engine.whatif import _validate_edited


def _stint(compound, lap_start, lap_end, tyre_age=0):
    return {"compound": compound, "lap_start": lap_start, "lap_end": lap_end,
            "tyre_age": tyre_age}


class TestIntermediateIsSupported:
    def test_intermediate_then_one_dry_compound_is_valid(self):
        # The actual real-world shape this bug was found from: VER's real
        # Bahrain stints, a single lap on Intermediates then Soft the rest
        # of the way -- only ONE dry compound used overall.
        stints = [_stint("INTERMEDIATE", 1, 1), _stint("SOFT", 2, 55)]
        assert _validate_edited(stints, total_laps=55, sets_available=None) is None

    def test_wet_is_still_rejected_no_fitted_model(self):
        stints = [_stint("WET", 1, 5), _stint("SOFT", 6, 55)]
        err = _validate_edited(stints, total_laps=55, sets_available=None)
        assert err is not None
        assert "WET" in err

    def test_intermediate_waives_the_two_dry_compound_rule(self):
        # Without any wet running, one dry compound alone is illegal.
        dry_only = [_stint("SOFT", 1, 55)]
        assert _validate_edited(dry_only, total_laps=55, sets_available=None) is not None
        # The same single dry compound, but preceded by a genuine
        # Intermediate stint, is legal -- the real regulation (Article
        # B6.3.3-adjacent "two compound" rule) is waived once wet-weather
        # tyres were used at all.
        with_inter = [_stint("INTERMEDIATE", 1, 3), _stint("SOFT", 4, 55)]
        assert _validate_edited(with_inter, total_laps=55, sets_available=None) is None

    def test_still_requires_two_dry_compounds_when_never_wet(self):
        stints = [_stint("SOFT", 1, 20), _stint("SOFT", 21, 55)]
        err = _validate_edited(stints, total_laps=55, sets_available=None)
        assert err is not None
        assert "two different dry compounds" in err

    def test_intermediate_stint_is_not_checked_against_dry_tyre_inventory(self):
        # sets_available only ever tracks the FIA dry-compound allocation
        # (engine.tyre_inventory) -- it has no Intermediate/Wet key at all.
        # Before this fix, looking it up would default to {} -> 0 available
        # and falsely reject every Intermediate stint as "not enough tyres".
        stints = [_stint("INTERMEDIATE", 1, 3), _stint("SOFT", 4, 55)]
        sets_available = {"SOFT": {"new": 2, "used": 1},
                          "MEDIUM": {"new": 1, "used": 0},
                          "HARD": {"new": 2, "used": 0}}
        assert _validate_edited(stints, total_laps=55, sets_available=sets_available) is None

    def test_dry_inventory_limits_still_enforced_alongside_intermediate(self):
        # The inventory check must still apply to the DRY stints in a plan
        # that also contains Intermediate -- skipping the check for
        # Intermediate shouldn't accidentally skip it for everything.
        stints = [_stint("INTERMEDIATE", 1, 3), _stint("SOFT", 4, 30),
                 _stint("SOFT", 31, 55)]  # needs 2 new Soft sets
        sets_available = {"SOFT": {"new": 1, "used": 0},
                          "MEDIUM": {"new": 1, "used": 0},
                          "HARD": {"new": 2, "used": 0}}
        err = _validate_edited(stints, total_laps=55, sets_available=sets_available)
        assert err is not None
        assert "SOFT" in err
