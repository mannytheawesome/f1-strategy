"""
Unit tests for engine.weather_forecast.get_rain_forecast -- the forward-
looking Open-Meteo forecast added 2026-10-05 after a real race (Bahrain,
meeting 1308) started genuinely wet despite weather_outlook saying "low"
risk, because that field had only ever looked backward at practice
sessions, never forward to the race itself.

All HTTP calls are monkeypatched (no network) -- requests.get is replaced
directly on the module, matching how other HTTP-touching modules in this
project are tested.
"""
import engine.weather_forecast as wf
from engine.weather_forecast import get_rain_forecast, CIRCUIT_COORDS


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _hourly_payload(times, temps, rain_probs):
    return {"hourly": {"time": times, "temperature_2m": temps,
                       "precipitation_probability": rain_probs}}


class TestGetRainForecast:
    def test_unknown_circuit_returns_none(self):
        assert get_rain_forecast("not-a-real-circuit", "2026-10-10T12:00:00+00:00") is None

    def test_no_datetime_returns_none(self):
        assert get_rain_forecast("silverstone", None) is None
        assert get_rain_forecast("silverstone", "") is None

    def test_known_circuit_has_coordinates(self):
        # Every circuit this project's own CIRCUIT_LAPS table knows about
        # should have a forecast coordinate -- a silent gap here would mean
        # weather_outlook quietly falls back to the no-forecast path for
        # that circuit with no indication why.
        for key in ("sakhir", "monza", "spa-francorchamps", "zandvoort",
                    "monte carlo", "baku", "silverstone"):
            assert key in CIRCUIT_COORDS

    def test_kuala_lumpur_resolves_to_sakhir_coordinates(self):
        # Same conclusion reached independently elsewhere this session
        # (engine.circuit_guide's ALIASES, engine.predictor's SC_RATE_CIRCUIT
        # comment): OpenF1's 2026 "Kuala Lumpur" key is a mislabeled Sakhir
        # session, not a real Sepang race.
        assert CIRCUIT_COORDS["kuala lumpur"] == CIRCUIT_COORDS["sakhir"]

    def test_picks_the_hourly_slot_closest_to_race_time(self, monkeypatch):
        payload = _hourly_payload(
            times=["2026-10-10T10:00", "2026-10-10T11:00", "2026-10-10T12:00"],
            temps=[20.0, 22.0, 25.0],
            rain_probs=[10, 80, 5],
        )
        monkeypatch.setattr(wf.requests, "get", lambda *a, **k: _FakeResponse(payload))
        wf._cache.clear()
        result = get_rain_forecast("silverstone", "2026-10-10T11:05:00+00:00")
        assert result["temp_c"] == 22.0
        assert result["rain_probability"] == 0.8

    def test_rain_probability_is_normalised_to_0_1(self, monkeypatch):
        payload = _hourly_payload(
            times=["2026-10-10T12:00"], temps=[20.0], rain_probs=[45],
        )
        monkeypatch.setattr(wf.requests, "get", lambda *a, **k: _FakeResponse(payload))
        wf._cache.clear()
        result = get_rain_forecast("silverstone", "2026-10-10T12:00:00+00:00")
        assert result["rain_probability"] == 0.45

    def test_api_failure_returns_none_not_raises(self, monkeypatch):
        def raise_error(*a, **k):
            raise RuntimeError("connection failed")
        monkeypatch.setattr(wf.requests, "get", raise_error)
        wf._cache.clear()
        assert get_rain_forecast("silverstone", "2026-10-10T12:00:00+00:00") is None

    def test_empty_hourly_data_returns_none(self, monkeypatch):
        monkeypatch.setattr(wf.requests, "get",
                            lambda *a, **k: _FakeResponse({"hourly": {"time": []}}))
        wf._cache.clear()
        assert get_rain_forecast("silverstone", "2026-10-10T12:00:00+00:00") is None

    def test_result_is_cached_and_does_not_refetch(self, monkeypatch):
        calls = []
        payload = _hourly_payload(
            times=["2026-10-10T12:00"], temps=[20.0], rain_probs=[30],
        )
        def fake_get(*a, **k):
            calls.append(1)
            return _FakeResponse(payload)
        monkeypatch.setattr(wf.requests, "get", fake_get)
        wf._cache.clear()
        get_rain_forecast("silverstone", "2026-10-10T12:00:00+00:00")
        get_rain_forecast("silverstone", "2026-10-10T12:00:00+00:00")
        assert len(calls) == 1
