"""
Tests for the partially-pooled, per-circuit-and-compound FP-vs-race
degradation correction (engine.race_deg_shrink), added after Mexico City
2026: the pre-race forecast recommended Hard-heavy 2-stop strategies and
not one of the 22 real drivers used Hard at all. Recalibrating with the
completed race's own laps (build_deg_curves' existing FP_WEIGHTS["RACE"]
support) showed Soft and Medium's real-race deg_rate was roughly half what
FP-only running predicted.

A flat global-per-compound version was tried next (after sweeping the full
2023-2026 cache, sweep_degradation_shrink.py, 68 races, confirmed the
FP-overstates-wear DIRECTION holds everywhere) but flipped Mexico City
2026's own recommendation back to Hard-heavy, the exact thing the
single-race version it replaced had gotten right. Resolved with partial
pooling: each circuit's own small sample is blended toward the global
default, weighted by weight = min(1, n/8) -- reusing build_deg_curves' own
MEDIUM-confidence threshold (pts>=8), not a new invented constant.
"""
from engine.race_deg_shrink import (
    race_deg_shrink_for, GLOBAL_RACE_DEG_SHRINK, CIRCUIT_RACE_DEG_SHRINK,
)
from engine.predictor import build_deg_curves

# MEDIUM's flat physical floor -- mirrors engine.predictor.build_deg_curves'
# own local MIN_DEG (not importable: it's defined inside the function).
MEDIUM_MIN_DEG = 0.025


def _stint(driver, compound, lap_start, lap_end, tyre_age_at_start=0, stint_number=1):
    return {"driver_number": driver, "compound": compound, "lap_start": lap_start,
            "lap_end": lap_end, "tyre_age_at_start": tyre_age_at_start,
            "stint_number": stint_number}


def _laps(driver, lap_times, start_lap=1):
    return [{"driver_number": driver, "lap_number": start_lap + i, "lap_duration": t,
             "is_pit_out_lap": False} for i, t in enumerate(lap_times)]


class TestRaceDegShrinkLookup:
    def test_circuit_with_a_measured_entry_returns_its_pooled_value(self):
        assert race_deg_shrink_for("MEDIUM", "Mexico City") == \
            CIRCUIT_RACE_DEG_SHRINK["mexico city"]["MEDIUM"]

    def test_lookup_is_case_insensitive_for_both_args(self):
        assert race_deg_shrink_for("medium", "MEXICO CITY") == \
            CIRCUIT_RACE_DEG_SHRINK["mexico city"]["MEDIUM"]

    def test_unmeasured_circuit_falls_back_to_the_global_default(self):
        assert race_deg_shrink_for("MEDIUM", "a circuit never raced") == \
            GLOBAL_RACE_DEG_SHRINK["MEDIUM"]

    def test_no_circuit_given_falls_back_to_the_global_default(self):
        assert race_deg_shrink_for("MEDIUM") == GLOBAL_RACE_DEG_SHRINK["MEDIUM"]

    def test_measured_circuit_but_unmeasured_compound_still_falls_back_global(self):
        # Mexico City has no SOFT entry (never got enough cached samples)
        # -- a known circuit shouldn't accidentally mask the global default
        # for a compound it happens not to have data for.
        assert "SOFT" not in CIRCUIT_RACE_DEG_SHRINK["mexico city"]
        assert race_deg_shrink_for("SOFT", "Mexico City") == GLOBAL_RACE_DEG_SHRINK["SOFT"]

    def test_unmeasured_compound_defaults_to_no_adjustment(self):
        assert race_deg_shrink_for("INTERMEDIATE") == 1.0

    def test_empty_compound_defaults_to_no_adjustment(self):
        assert race_deg_shrink_for("") == 1.0

    def test_pooled_value_sits_between_global_and_nothing(self):
        # Partial pooling's whole point: a circuit with a real but thin
        # sample lands somewhere between "trust it completely" (its own
        # raw median) and "ignore it completely" (the global default) --
        # never exactly at either endpoint for a thin (n<8) sample.
        pooled = CIRCUIT_RACE_DEG_SHRINK["mexico city"]["MEDIUM"]
        assert pooled != GLOBAL_RACE_DEG_SHRINK["MEDIUM"]
        assert 0.0 < pooled < 1.0


class TestBuildDegCurvesAppliesTheCorrection:
    def test_fp_only_estimate_gets_shrunk_when_requested(self):
        # A clean, well-measured Medium long run -- no track-evolution or
        # floor shenanigans, just a genuine fitted slope. No circuit given,
        # so this uses the global default.
        med_laps = _laps(1, [90.0 + 0.20 * i for i in range(12)])
        stints = [_stint(1, "MEDIUM", 1, 12)]
        fp_data = [("FP1", med_laps, stints)]

        plain = build_deg_curves(fp_data)
        corrected = build_deg_curves(fp_data, apply_race_shrink=True)

        shrink = race_deg_shrink_for("MEDIUM")
        expected = max(plain["MEDIUM"].deg_rate * shrink, MEDIUM_MIN_DEG)
        assert abs(corrected["MEDIUM"].deg_rate - expected) < 1e-6
        assert corrected["MEDIUM"].deg_rate < plain["MEDIUM"].deg_rate

    def test_known_circuit_uses_its_own_pooled_value_not_the_global_one(self):
        med_laps = _laps(1, [90.0 + 0.20 * i for i in range(12)])
        stints = [_stint(1, "MEDIUM", 1, 12)]
        fp_data = [("FP1", med_laps, stints)]

        global_corrected = build_deg_curves(fp_data, apply_race_shrink=True)
        circuit_corrected = build_deg_curves(fp_data, apply_race_shrink=True,
                                             circuit="Mexico City")

        shrink = race_deg_shrink_for("MEDIUM", "Mexico City")
        plain = build_deg_curves(fp_data)
        expected = max(plain["MEDIUM"].deg_rate * shrink, MEDIUM_MIN_DEG)
        assert abs(circuit_corrected["MEDIUM"].deg_rate - expected) < 1e-6
        assert circuit_corrected["MEDIUM"].deg_rate != global_corrected["MEDIUM"].deg_rate

    def test_not_requested_leaves_the_estimate_untouched(self):
        med_laps = _laps(1, [90.0 + 0.20 * i for i in range(12)])
        stints = [_stint(1, "MEDIUM", 1, 12)]
        fp_data = [("FP1", med_laps, stints)]

        plain = build_deg_curves(fp_data)
        same = build_deg_curves(fp_data, apply_race_shrink=False, circuit="Mexico City")
        assert plain["MEDIUM"].deg_rate == same["MEDIUM"].deg_rate

    def test_real_race_data_already_present_skips_the_correction(self):
        # Once this weekend's own race laps are already in fp_data (the
        # retrospective path used after a race finishes), that's strictly
        # better evidence than a historical correction factor -- applying
        # both would double-count the same effect.
        med_laps = _laps(1, [90.0 + 0.20 * i for i in range(12)])
        stints = [_stint(1, "MEDIUM", 1, 12)]
        fp_only = [("FP1", med_laps, stints)]
        with_race = [("FP1", med_laps, stints), ("RACE", med_laps, stints)]

        corrected_fp_only = build_deg_curves(fp_only, apply_race_shrink=True,
                                             circuit="Mexico City")
        corrected_with_race = build_deg_curves(with_race, apply_race_shrink=True,
                                               circuit="Mexico City")
        plain_with_race = build_deg_curves(with_race)

        assert corrected_with_race["MEDIUM"].deg_rate == plain_with_race["MEDIUM"].deg_rate
        assert corrected_with_race["MEDIUM"].deg_rate != corrected_fp_only["MEDIUM"].deg_rate
