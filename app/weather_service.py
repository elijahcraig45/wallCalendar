"""Weather, from Open-Meteo.

Chosen over the usual suspects because it needs no API key and no account: there
is no credential here to expire, get revoked, or leak into the repo - which
matters for an appliance meant to run untouched for months.

Also the source of sunrise/sunset, which the night-dimming behaviour uses instead
of a hardcoded hour so the wall dims with the actual seasons.
"""

import datetime as dt
import time

import requests

from app.config import DEMO_MODE, WEATHER_LABEL, WEATHER_LAT, WEATHER_LON

API_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 8
CACHE_TTL_SECONDS = 900          # conditions don't move fast; 15 min is plenty
ERROR_CACHE_TTL_SECONDS = 120    # but don't hammer a failing endpoint either

# WMO weather interpretation codes -> (label, icon key). Grouped rather than
# listed one-per-code: the wall needs "is it raining" legible from across a room,
# not the difference between light and moderate drizzle.
_WMO = {
    0: ("Clear", "clear"),
    1: ("Mostly clear", "clear"),
    2: ("Partly cloudy", "partly"),
    3: ("Overcast", "cloudy"),
    45: ("Fog", "fog"), 48: ("Freezing fog", "fog"),
    51: ("Light drizzle", "drizzle"), 53: ("Drizzle", "drizzle"), 55: ("Heavy drizzle", "drizzle"),
    56: ("Freezing drizzle", "sleet"), 57: ("Freezing drizzle", "sleet"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "sleet"), 67: ("Freezing rain", "sleet"),
    71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Showers", "rain"), 81: ("Showers", "rain"), 82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"), 86: ("Snow showers", "snow"),
    95: ("Thunderstorm", "storm"),
    96: ("Thunderstorm with hail", "storm"), 99: ("Thunderstorm with hail", "storm"),
}

_cache: tuple[float, dict] | None = None
_last_good: dict | None = None


def describe(code: int | None) -> tuple[str, str]:
    return _WMO.get(code, ("Unknown", "cloudy"))


def _parse(payload: dict) -> dict:
    """Turns an Open-Meteo response into what the wall renders. Kept separate from
    the fetch so it can be exercised against a captured real payload - useful
    anywhere the live call can't be made (a TLS-inspecting corporate network, for
    instance)."""
    current = payload.get("current", {})
    daily = payload.get("daily", {})

    def day(index, key, default=None):
        values = daily.get(key) or []
        return values[index] if index < len(values) else default

    label, icon = describe(current.get("weather_code"))

    days = []
    for index, date in enumerate(daily.get("time", [])):
        day_label, day_icon = describe(day(index, "weather_code"))
        days.append(
            {
                "date": date,
                "label": day_label,
                "icon": day_icon,
                "high": _round(day(index, "temperature_2m_max")),
                "low": _round(day(index, "temperature_2m_min")),
                "precip_chance": day(index, "precipitation_probability_max"),
                "sunrise": day(index, "sunrise"),
                "sunset": day(index, "sunset"),
            }
        )

    return {
        "place": WEATHER_LABEL,
        "observed_at": current.get("time"),
        "temperature": _round(current.get("temperature_2m")),
        "feels_like": _round(current.get("apparent_temperature")),
        "humidity": current.get("relative_humidity_2m"),
        "wind": _round(current.get("wind_speed_10m")),
        "is_day": bool(current.get("is_day", 1)),
        "label": label,
        "icon": icon,
        # Today's sun times, hoisted for the dimming schedule and the overview.
        "sunrise": days[0]["sunrise"] if days else None,
        "sunset": days[0]["sunset"] if days else None,
        "days": days,
        "errors": [],
    }


def _round(value):
    return None if value is None else round(value)


def _fetch() -> dict:
    response = requests.get(
        API_URL,
        params={
            "latitude": WEATHER_LAT,
            "longitude": WEATHER_LON,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                       "is_day,precipitation,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max,sunrise,sunset",
            "timezone": "auto",
            "forecast_days": 4,
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return _parse(response.json())


def get_weather() -> dict:
    """Never raises. Weather is decoration on a calendar - a failure here must not
    be able to take a page down, so a failed fetch falls back to the last good
    reading (marked stale) or an empty shape the client renders as absent."""
    global _cache, _last_good

    if DEMO_MODE:
        from app import demo_weather

        return demo_weather.get_weather()

    now = time.monotonic()
    if _cache is not None:
        ttl = ERROR_CACHE_TTL_SECONDS if _cache[1].get("errors") else CACHE_TTL_SECONDS
        if (now - _cache[0]) < ttl:
            return _cache[1]

    try:
        result = _fetch()
        result["stale"] = False
        result["fetched_at"] = dt.datetime.now().isoformat(timespec="seconds")
        _last_good = result
    except Exception as exc:  # noqa: BLE001 - see docstring
        message = f"Couldn't reach the weather service ({type(exc).__name__})."
        if _last_good is not None:
            result = {**_last_good, "stale": True, "errors": [message]}
        else:
            result = {
                "place": WEATHER_LABEL,
                "available": False,
                "stale": False,
                "days": [],
                "errors": [message],
            }

    result.setdefault("available", True)
    _cache = (now, result)
    return result
