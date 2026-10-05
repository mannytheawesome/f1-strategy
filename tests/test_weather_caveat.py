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


class TestForwardLookingForecast:
    """2026-10-05: a race (Bahrain, meeting 1308) was predicted "low" rain
    risk -- no rain anywhere in FP1-3, not a historically wet-prone circuit
    -- and then started genuinely wet, overriding the whole dry strategy
    table. Not a bug in the old logic, which was working exactly as
    designed: it only ever looked backward at practice. These tests cover
    the fix -- a real forecast for the race's own start time, via
    engine.weather_forecast.get_rain_forecast."""

    def _dry_practice(self, monkeypatch):
        monkeypatch.setattr(prerace, "get_weather_summary",
                            lambda *a, **k: {"rainfall": False, "track_temp_avg": 30.0})

    def test_high_forecast_elevates_risk_even_with_dry_practice(self, monkeypatch):
        self._dry_practice(monkeypatch)
        monkeypatch.setattr("engine.weather_forecast.get_rain_forecast",
                            lambda *a, **k: {"rain_probability": 0.7, "temp_c": 22.0})
        outlook = _weather_outlook([{"session_key": 1}], "sakhir",
                                   race_datetime="2026-10-04T07:00:00+00:00")
        assert outlook["rain_risk"] == "high"
        assert outlook["forecast"]["rain_probability"] == 0.7
        assert "70%" in outlook["note"]
        assert "70%" in outlook["strategy_caveat"]

    def test_moderate_forecast_is_elevated_not_high(self, monkeypatch):
        self._dry_practice(monkeypatch)
        monkeypatch.setattr("engine.weather_forecast.get_rain_forecast",
                            lambda *a, **k: {"rain_probability": 0.3, "temp_c": 22.0})
        outlook = _weather_outlook([{"session_key": 1}], "sakhir",
                                   race_datetime="2026-10-04T07:00:00+00:00")
        assert outlook["rain_risk"] == "elevated"

    def test_low_forecast_is_treated_as_noise_not_elevated(self, monkeypatch):
        self._dry_practice(monkeypatch)
        monkeypatch.setattr("engine.weather_forecast.get_rain_forecast",
                            lambda *a, **k: {"rain_probability": 0.05, "temp_c": 22.0})
        outlook = _weather_outlook([{"session_key": 1}], "sakhir",
                                   race_datetime="2026-10-04T07:00:00+00:00")
        assert outlook["rain_risk"] == "low"

    def test_no_race_datetime_falls_back_to_practice_only(self, monkeypatch):
        # Backward compatible: every existing call site that doesn't pass
        # race_datetime (or a circuit/forecast failure) behaves exactly as
        # before -- this is the same case the pre-existing tests above cover.
        self._dry_practice(monkeypatch)
        outlook = _weather_outlook([{"session_key": 1}], "monza")
        assert outlook["forecast"] is None
        assert outlook["rain_risk"] == "low"

    def test_forecast_fetch_failure_falls_back_gracefully(self, monkeypatch):
        self._dry_practice(monkeypatch)
        def raise_error(*a, **k):
            raise RuntimeError("network down")
        monkeypatch.setattr("engine.weather_forecast.get_rain_forecast", raise_error)
        outlook = _weather_outlook([{"session_key": 1}], "monza",
                                   race_datetime="2026-10-04T07:00:00+00:00")
        assert outlook["forecast"] is None
        assert outlook["rain_risk"] == "low"

    def test_low_forecast_at_a_wet_prone_circuit_keeps_historys_floor(self, monkeypatch):
        # A low-but-imperfect forecast doesn't erase a circuit's own known
        # volatility (Spa's microclimate is notoriously unpredictable) --
        # risk is the max of the two signals, not a forecast-only override.
        self._dry_practice(monkeypatch)
        monkeypatch.setattr("engine.weather_forecast.get_rain_forecast",
                            lambda *a, **k: {"rain_probability": 0.05, "temp_c": 22.0})
        outlook = _weather_outlook([{"session_key": 1}], "spa-francorchamps",
                                   race_datetime="2026-10-04T07:00:00+00:00")
        assert outlook["rain_risk"] == "elevated"

    def test_high_forecast_overrides_dry_history_at_a_normally_dry_circuit(self, monkeypatch):
        # The actual Bahrain case this fix was built for: not wet-prone, dry
        # in practice, but a real forecast says otherwise for this race.
        self._dry_practice(monkeypatch)
        monkeypatch.setattr("engine.weather_forecast.get_rain_forecast",
                            lambda *a, **k: {"rain_probability": 0.6, "temp_c": 22.0})
        outlook = _weather_outlook([{"session_key": 1}], "sakhir",
                                   race_datetime="2026-10-04T07:00:00+00:00")
        assert outlook["rain_risk"] == "high"
