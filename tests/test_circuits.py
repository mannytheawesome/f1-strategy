"""
Tests for engine.circuits, including resurfacing_caveat -- a manually
curated caveat (not a numerical correction) for races on a recently
resurfaced or newly-returning circuit. Built after directly measuring a
real, clean example: Spa (resurfaced June 2024, before that year's
Belgian GP) showed a FP-vs-race degradation gap ~4x the following
season's and near zero two seasons later -- a real effect, but with too
few known events across the cache to fit a reliable numerical correction,
hence a caveat rather than an adjustment.
"""
from engine.circuits import resurfacing_caveat


def test_event_year_gets_the_strong_caveat():
    caveat = resurfacing_caveat("Spa-Francorchamps", 2024)
    assert caveat is not None
    assert "new this season" in caveat


def test_following_year_gets_the_weaker_caveat():
    caveat = resurfacing_caveat("Spa-Francorchamps", 2025)
    assert caveat is not None
    assert "settling" in caveat


def test_two_years_on_no_caveat():
    assert resurfacing_caveat("Spa-Francorchamps", 2026) is None


def test_unrelated_circuit_no_caveat():
    assert resurfacing_caveat("Silverstone", 2026) is None


def test_matching_is_substring_based_like_other_circuit_lookups():
    # Mirrors is_street_circuit's own convention -- case-insensitive
    # substring match against circuit_short_name.
    assert resurfacing_caveat("spa-francorchamps", 2024) is not None
    assert resurfacing_caveat("SPA-FRANCORCHAMPS", 2024) is not None


def test_no_year_no_caveat():
    assert resurfacing_caveat("Spa-Francorchamps", None) is None
