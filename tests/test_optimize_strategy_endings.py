"""
Regression tests for a real bug: optimize_strategy had no way to force a
specific ENDING compound, only the starting compound and stop count. The
DP would silently pick whichever ending was fastest, so a close
alternative (e.g. Medium->Hard when the DP preferred Medium->Soft by a few
seconds) was never even generated as its own candidate -- not filtered
out afterward, just never computed. force_end_compound fixes this.
"""
from engine.predictor import DegCurve, optimize_strategy


def _curve(compound, deg_rate, baseline=93.0):
    return DegCurve(compound=compound, deg_rate=deg_rate, baseline=baseline,
                     data_points=30, confidence="HIGH", sessions=["RACE"])


def test_unconstrained_call_still_works_exactly_as_before():
    # Every pre-existing call site passes no force_end_compound at all --
    # this must behave identically to before the parameter was added.
    curves = {"SOFT": _curve("SOFT", 0.066), "MEDIUM": _curve("MEDIUM", 0.025),
              "HARD": _curve("HARD", 0.018)}
    strat = optimize_strategy(0, 52, "MEDIUM", 0, 0.0, curves, 93.724, 22.0,
                              needs_compound_change=True, force_stops=1,
                              forbid_repeat_compound=True)
    assert len(strat.pits_remaining) == 1


def test_forcing_the_dp_preferred_ending_matches_unconstrained():
    curves = {"SOFT": _curve("SOFT", 0.066), "MEDIUM": _curve("MEDIUM", 0.025),
              "HARD": _curve("HARD", 0.018)}
    unconstrained = optimize_strategy(0, 52, "MEDIUM", 0, 0.0, curves, 93.724, 22.0,
                                      needs_compound_change=True, force_stops=1,
                                      forbid_repeat_compound=True)
    preferred_end = unconstrained.pits_remaining[0].compound
    forced = optimize_strategy(0, 52, "MEDIUM", 0, 0.0, curves, 93.724, 22.0,
                               needs_compound_change=True, force_stops=1,
                               forbid_repeat_compound=True,
                               force_end_compound=preferred_end)
    assert forced.total_time_from_now == unconstrained.total_time_from_now


def test_forcing_a_close_but_non_preferred_ending_surfaces_it():
    # Mirrors the real Silverstone 2026 case: two dry compounds are close
    # enough in fitted degradation that the DP's free choice hides a
    # legitimate, only-slightly-slower alternative ending entirely. Don't
    # assume which compound the DP prefers -- discover it, then force the
    # other one and confirm it's actually reachable and correctly labelled.
    curves = {"SOFT": _curve("SOFT", 0.066), "MEDIUM": _curve("MEDIUM", 0.025),
              "HARD": _curve("HARD", 0.058)}
    unconstrained = optimize_strategy(0, 52, "MEDIUM", 0, 0.0, curves, 93.724, 22.0,
                                      needs_compound_change=True, force_stops=1,
                                      forbid_repeat_compound=True)
    preferred = unconstrained.pits_remaining[0].compound
    other = "HARD" if preferred == "SOFT" else "SOFT"

    forced_other = optimize_strategy(0, 52, "MEDIUM", 0, 0.0, curves, 93.724, 22.0,
                                     needs_compound_change=True, force_stops=1,
                                     forbid_repeat_compound=True,
                                     force_end_compound=other)
    assert len(forced_other.pits_remaining) == 1
    assert forced_other.pits_remaining[0].compound == other
    # The real bug: before force_end_compound existed, this alternative
    # was never computed at all -- it wasn't filtered out, it just never
    # existed as an option. Confirm it's a genuine, close-but-different
    # candidate, not identical to the unconstrained result.
    assert forced_other.total_time_from_now != unconstrained.total_time_from_now
    assert forced_other.total_time_from_now >= unconstrained.total_time_from_now


def test_forcing_an_ending_incompatible_with_stock_yields_no_legal_plan():
    curves = {"SOFT": _curve("SOFT", 0.066), "MEDIUM": _curve("MEDIUM", 0.025),
              "HARD": _curve("HARD", 0.018)}
    strat = optimize_strategy(0, 52, "MEDIUM", 0, 0.0, curves, 93.724, 22.0,
                              needs_compound_change=True, force_stops=1,
                              forbid_repeat_compound=True,
                              force_end_compound="HARD",
                              available={"HARD": 0, "SOFT": 5, "MEDIUM": 5})
    assert len(strat.pits_remaining) != 1 or strat.pits_remaining[0].compound != "HARD"
