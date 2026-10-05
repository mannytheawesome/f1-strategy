"""
Forward-looking weather forecast for a race, via Open-Meteo (free, no API
key for non-commercial use: https://open-meteo.com/en/docs). This is
deliberately separate from data.live.get_weather_summary, which only ever
reports what OpenF1's telemetry already measured during a session that has
started or finished -- it cannot say anything about a race that hasn't run
yet. A pre-race briefing generated before lights-out needs an actual
forecast, not a retrospective reading of practice conditions.

Used to feed engine.predictor.run_monte_carlo's rain_probability parameter,
which blends in the measured wet/dry SC rate (see predictor.py's
WET_SC_RATE_MULTIPLIER for the real multiplier and why DNF rate is
deliberately NOT blended) -- this module only fetches and parses the
forecast itself.
"""
import requests
import time

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 10

# Real-world lat/lon per circuit_short_name (lowercased), matching the same
# key convention as engine.prerace.CIRCUIT_LAPS -- one entry per physical
# venue, aliases pointing at the same coordinates (same pattern as
# engine.pit_loss's aliased entries).
#
# "kuala lumpur": engine.prerace.CIRCUIT_LAPS's own comment assumes this is
# Sepang (Malaysia) returning to the calendar, but the actual 2026 OpenF1
# meeting this key comes from has country_name="Bahrain"/country_code="BRN"
# and F1's own event title is "...Bahrain Grand Prix in Malaysia 2026" --
# confirmed by direct inspection this session to be the same Sakhir/Bahrain
# round, mislabeled, not a genuine Sepang race (see engine.circuit_guide's
# ALIASES for the same conclusion reached independently). Pointed at
# Sakhir's real coordinates here for that reason -- flagging the
# CIRCUIT_LAPS entry's own comment as the thing that's actually wrong,
# not re-litigating it in this file.
CIRCUIT_COORDS: dict[str, tuple[float, float]] = {
    "melbourne": (-37.8497, 144.9680),
    "shanghai": (31.3389, 121.2198),
    "suzuka": (34.8431, 136.5410),
    "sakhir": (26.0325, 50.5106),
    "kuala lumpur": (26.0325, 50.5106),  # see note above -- actually Sakhir
    "jeddah": (21.6319, 39.1044),
    "miami": (25.9581, -80.2389),
    "imola": (44.3439, 11.7167),
    "monaco": (43.7347, 7.4206),
    "monte carlo": (43.7347, 7.4206),
    "catalunya": (41.5700, 2.2611),
    "montreal": (45.5000, -73.5228),
    "spielberg": (47.2197, 14.7647),
    "silverstone": (52.0786, -1.0169),
    "spa": (50.4372, 5.9714),
    "spa-francorchamps": (50.4372, 5.9714),
    "hungaroring": (47.5789, 19.2486),
    "zandvoort": (52.3888, 4.5409),
    "monza": (45.6156, 9.2811),
    "baku": (40.3725, 49.8533),
    "singapore": (1.2914, 103.8640),
    "austin": (30.1328, -97.6411),
    "mexico city": (19.4042, -99.0907),
    "interlagos": (-23.7036, -46.6997),
    "las vegas": (36.1147, -115.1728),
    "lusail": (25.4900, 51.4542),
    "yas marina": (24.4672, 54.6031),
    "yas marina circuit": (24.4672, 54.6031),
    "madring": (40.4200, -3.6100),
    "madrid": (40.4200, -3.6100),
    "sepang": (2.7608, 101.7380),  # real Sepang, kept distinct -- see note above
}

# Tiny in-memory cache (module-level, process-lifetime) -- forecasts drift
# over time so this is intentionally a much shorter TTL than the HIST_TTL
# used for OpenF1's historical data elsewhere in this project.
FORECAST_TTL_S = 1800
_cache: dict[str, tuple[float, dict]] = {}


def get_rain_forecast(circuit: str, race_datetime_iso: str) -> dict | None:
    """Forecasted rain probability (0-1) and air temperature for a circuit
    at a specific future UTC datetime (ISO 8601, e.g. a session's
    date_start). Returns None if the circuit has no known coordinates, the
    datetime can't be parsed, or the API call fails -- callers must treat
    that as "no forecast available", not "clear skies guaranteed" (same
    graceful-degrade convention as get_weather_summary elsewhere)."""
    key = (circuit or "").lower()
    coords = CIRCUIT_COORDS.get(key)
    if not coords or not race_datetime_iso:
        return None

    cache_key = f"{key}:{race_datetime_iso}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < FORECAST_TTL_S:
        return cached[1]

    lat, lon = coords
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,precipitation_probability",
        "forecast_days": 16,
        "timezone": "UTC",
    }
    try:
        resp = requests.get(FORECAST_URL, params=params, timeout=TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    rain_probs = hourly.get("precipitation_probability") or []
    if not times:
        return None

    # Find the hourly slot closest to the race's actual start time. Open-
    # Meteo's "time" values are naive local-ish ISO strings (yyyy-mm-ddThh:mm)
    # in the timezone requested (UTC here) -- race_datetime_iso may carry a
    # "+00:00"/"Z" suffix OpenF1 always includes, so compare on the
    # yyyy-mm-ddThh:mm prefix both share rather than parsing both as full
    # datetimes (avoids a tz-library dependency for a same-zone comparison).
    target_prefix = race_datetime_iso[:16]
    best_idx = min(range(len(times)), key=lambda i: abs(_hour_distance(times[i], target_prefix)))

    if best_idx >= len(temps) or best_idx >= len(rain_probs):
        return None

    result = {
        "rain_probability": round((rain_probs[best_idx] or 0) / 100, 3),
        "temp_c": temps[best_idx],
        "forecast_time": times[best_idx],
        "source": "open-meteo",
    }
    _cache[cache_key] = (time.time(), result)
    return result


def _hour_distance(time_str: str, target_prefix: str) -> int:
    """Rough distance in hours between two yyyy-mm-ddThh:mm strings, good
    enough for picking the nearest hourly forecast slot without a datetime
    parsing dependency -- both strings share the same lexical format."""
    def to_minutes(s: str) -> int:
        date_part, time_part = s[:10], s[11:16]
        y, m, d = (int(x) for x in date_part.split("-"))
        hh, mm = (int(x) for x in time_part.split(":"))
        # days-since-epoch-ish via a simple monotonic proxy (not calendar-
        # accurate across months, but forecasts only span 16 days and this
        # is only used to rank candidates, not compute real elapsed time)
        return (((y * 12 + m) * 31 + d) * 24 + hh) * 60 + mm
    return to_minutes(time_str) - to_minutes(target_prefix)
