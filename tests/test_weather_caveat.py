"""
Unit tests for _weather_outlook's strategy_caveat -- part of the same
investigation as _track_position_cost: the "Expected Pit Stop Strategies"
table is a deterministic dry-only search with no rain branch modelled at
all. Rather than blend rain_risk numerically into that search (which would
need real wet-vs-dry strategy data to calibrate honestly), this surfaces a
caveat instead, the same choice already made for circuits.resurfacing_caveat.
"""
import engine.prerace as prerace
from engine.prerace import _weather_outlook


class TestStrategyWeatherCaveat:
    def test_no_caveat_for_a_dry_circuit_with_no_rain_seen(self, monkeypatch):
        monkeypatch.setattr(prerace, "get_weather_summary",
                            lambda *a, **k: {"rainfall": False, "track_temp_avg": 30.0})
        outlook = _weather_outlook([{"session_key": 1}], "monza")
        assert outlook["rain_risk"] == "low"
        assert outlook["strategy_caveat"] is None

    def test_caveat_for_a_wet_prone_circuit_even_if_dry_so_far(self, monkeypatch):
        monkeypatch.setattr(prerace, "get_weather_summary",
                            lambda *a, **k: {"rainfall": False, "track_temp_avg": 22.0})
        outlook = _weather_outlook([{"session_key": 1}], "spa-francorchamps")
        assert outlook["rain_risk"] == "elevated"
        assert outlook["strategy_caveat"] is not None
        assert "history of rain" in outlook["strategy_caveat"]

    def test_stronger_caveat_when_rain_already_seen_this_weekend(self, monkeypatch):
        monkeypatch.setattr(prerace, "get_weather_summary",
                            lambda *a, **k: {"rainfall": True, "track_temp_avg": 18.0})
        outlook = _weather_outlook([{"session_key": 1}], "monza")
        assert outlook["rain_risk"] == "high"
        assert outlook["strategy_caveat"] is not None
        assert "already fallen" in outlook["strategy_caveat"]

    def test_caveat_is_distinct_from_the_doors_implication_text(self, monkeypatch):
        # Regression guard: strategy_caveat is written for the pit-stop
        # table specifically, not a copy of `implication` (which is
        # written for the grid-value/doors section).
        monkeypatch.setattr(prerace, "get_weather_summary",
                            lambda *a, **k: {"rainfall": True, "track_temp_avg": 18.0})
        outlook = _weather_outlook([{"session_key": 1}], "monza")
        assert outlook["strategy_caveat"] != outlook["implication"]
