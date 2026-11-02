"""
Tests for the per-circuit FP-vs-race degradation correction
(engine.circuit_degradation), added after Mexico City 2026: the pre-race
forecast recommended Hard-heavy 2-stop strategies and not one of the 22
real drivers used Hard at all. Recalibrating with the completed race's own
laps (build_deg_curves' existing FP_WEIGHTS["RACE"] support) showed Soft and
Medium's real-race deg_rate was roughly half what FP-only running predicted
-- this module persists that correction for the next time this circuit is
predicted FP-only, before its own race exists to fold in directly.
"""
from engine.circuit_degradation import race_deg_shrink_for, CIRCUIT_RACE_DEG_SHRINK
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
    def test_measured_circuit_returns_its_factor(self):
        assert race_deg_shrink_for("Mexico City") == CIRCUIT_RACE_DEG_SHRINK["mexico city"]

    def test_lookup_is_case_insensitive(self):
        assert race_deg_shrink_for("MEXICO CITY") == CIRCUIT_RACE_DEG_SHRINK["mexico city"]

    def test_unmeasured_circuit_defaults_to_no_adjustment(self):
        assert race_deg_shrink_for("some circuit never raced") == 1.0

    def test_empty_circuit_defaults_to_no_adjustment(self):
        assert race_deg_shrink_for("") == 1.0


class TestBuildDegCurvesAppliesTheCorrection:
    def test_fp_only_estimate_at_a_measured_circuit_gets_shrunk(self):
        # A clean, well-measured Medium long run -- no track-evolution or
        # floor shenanigans, just a genuine fitted slope -- at a circuit
        # with a known FP-vs-race correction factor.
        med_laps = _laps(1, [90.0 + 0.20 * i for i in range(12)])
        stints = [_stint(1, "MEDIUM", 1, 12)]
        fp_data = [("FP1", med_laps, stints)]

        plain = build_deg_curves(fp_data)
        corrected = build_deg_curves(fp_data, circuit="Mexico City")

        shrink = race_deg_shrink_for("Mexico City")
        expected = max(plain["MEDIUM"].deg_rate * shrink, MEDIUM_MIN_DEG)
        assert abs(corrected["MEDIUM"].deg_rate - expected) < 1e-6
        assert corrected["MEDIUM"].deg_rate < plain["MEDIUM"].deg_rate

    def test_unmeasured_circuit_is_unaffected(self):
        med_laps = _laps(1, [90.0 + 0.20 * i for i in range(12)])
        stints = [_stint(1, "MEDIUM", 1, 12)]
        fp_data = [("FP1", med_laps, stints)]

        plain = build_deg_curves(fp_data)
        same = build_deg_curves(fp_data, circuit="a circuit with no history")
        assert plain["MEDIUM"].deg_rate == same["MEDIUM"].deg_rate

    def test_real_race_data_already_present_skips_the_correction(self):
        # Once this weekend's own race laps are already in fp_data (the
        # retrospective path used after a race finishes), that's strictly
        # better evidence than a past race's correction factor -- applying
        # both would double-count the same effect.
        med_laps = _laps(1, [90.0 + 0.20 * i for i in range(12)])
        stints = [_stint(1, "MEDIUM", 1, 12)]
        fp_only = [("FP1", med_laps, stints)]
        with_race = [("FP1", med_laps, stints), ("RACE", med_laps, stints)]

        corrected_fp_only = build_deg_curves(fp_only, circuit="Mexico City")
        corrected_with_race = build_deg_curves(with_race, circuit="Mexico City")
        plain_with_race = build_deg_curves(with_race)

        assert corrected_with_race["MEDIUM"].deg_rate == plain_with_race["MEDIUM"].deg_rate
        assert corrected_with_race["MEDIUM"].deg_rate != corrected_fp_only["MEDIUM"].deg_rate
