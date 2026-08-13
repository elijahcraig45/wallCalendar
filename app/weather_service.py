"""Weather, from Open-Meteo.

Chosen over the usual suspects because it needs no API key and no account: there
is no credential here to expire, get revoked, or leak into the repo - which
matters for an appliance meant to run untouched for months.

Also the source of sunrise/sunset, which the night-dimming behaviour uses instead
of a hardcoded hour so the wall dims with the actual seasons.
"""

import datetime as dt
import json
import time

import requests

from app.config import DEMO_MODE, PROJECT_ROOT, WEATHER_LABEL, WEATHER_LAT, WEATHER_LON

API_URL = "https://api.open-meteo.com/v1/forecast"
# The Pi's wifi is not fast; 8s was tight enough to produce real ReadTimeouts.
TIMEOUT_SECONDS = 20
# One retry, because a single timeout on a household connection is normal and the
# alternative is showing no weather for the next two minutes.
ATTEMPTS = 2
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

# The last good reading, on disk. In-memory alone wasn't enough: pushing to main
# restarts the service, so a deploy followed by one transient timeout left the wall
# with no weather at all and nothing to fall back to. A slightly stale temperature
# is strictly better than an empty header.
_CACHE_FILE = PROJECT_ROOT / "data" / "weather_cache.json"


def _load_persisted() -> dict | None:
    try:
        return json.loads(_CACHE_FILE.read_text())
    except (OSError, ValueError):
        return None


def _persist(payload: dict) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(payload))
    except OSError:
        # Losing the cache is survivable; failing a request over it is not.
        pass


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
                "wind_max": _round(day(index, "wind_speed_10m_max")),
                "uv_max": _round(day(index, "uv_index_max")),
                "precip_total": day(index, "precipitation_sum"),
                "daylight_minutes": (
                    None if day(index, "daylight_duration") is None
                    else round(day(index, "daylight_duration") / 60)
                ),
            }
        )

    hourly = payload.get("hourly", {})
    hours = []
    for index, stamp in enumerate(hourly.get("time", [])):
        def hour(key, default=None):
            values = hourly.get(key) or []
            return values[index] if index < len(values) else default

        hours.append(
            {
                "time": stamp,
                "temperature": _round(hour("temperature_2m")),
                "feels_like": _round(hour("apparent_temperature")),
                "precip_chance": hour("precipitation_probability"),
                "wind": _round(hour("wind_speed_10m")),
                "cape": _round(hour("cape")),
                # Without this the strip drew a sun at midnight, which is a small
                # thing that makes a wall display look untrustworthy.
                "is_day": bool(hour("is_day", 1)),
                **dict(zip(("label", "icon"), describe(hour("weather_code")))),
            }
        )

    return {
        "place": WEATHER_LABEL,
        "observed_at": current.get("time"),
        "temperature": _round(current.get("temperature_2m")),
        "feels_like": _round(current.get("apparent_temperature")),
        "humidity": current.get("relative_humidity_2m"),
        "wind": _round(current.get("wind_speed_10m")),
        "gusts": _round(current.get("wind_gusts_10m")),
        "dew_point": _round(current.get("dew_point_2m")),
        # The live UV, rather than the day's maximum the daily block reports - at
        # 8pm those are very different numbers and only one of them is useful.
        "uv_index": _round(current.get("uv_index")),
        "cloud_cover": current.get("cloud_cover"),
        "pressure": _round(current.get("pressure_msl")),
        "is_day": bool(current.get("is_day", 1)),
        "label": label,
        "icon": icon,
        # Today's sun times, hoisted for the dimming schedule and the overview.
        "sunrise": days[0]["sunrise"] if days else None,
        "sunset": days[0]["sunset"] if days else None,
        "days": days,
        "hours": hours,
        # From NOW, not from the start of the array. The hourly series begins at
        # local midnight, so slicing from zero asked "was it thundery overnight" -
        # which for an afternoon-storm climate is exactly the wrong 12 hours.
        "cape_peak": max(
            (h["cape"] for h in _next_hours(hours, 12) if h["cape"] is not None),
            default=None,
        ),
        "thunder_hours": [h["time"] for h in _next_hours(hours, 24) if h["icon"] == "storm"],
        "errors": [],
    }


def _round(value):
    return None if value is None else round(value)


def _next_hours(hours: list[dict], count: int) -> list[dict]:
    """The next `count` entries at or after the current local hour.

    Open-Meteo's hourly series starts at local midnight and the timestamps carry
    no offset (timezone=auto already localised them), so they compare directly
    against a naive local now.
    """
    now = dt.datetime.now().replace(minute=0, second=0, microsecond=0)
    upcoming = []
    for hour in hours:
        try:
            stamp = dt.datetime.fromisoformat(hour["time"])
        except (ValueError, KeyError):
            continue
        if stamp >= now:
            upcoming.append(hour)
        if len(upcoming) >= count:
            break
    return upcoming


def _fetch() -> dict:
    last_error: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            return _fetch_once()
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt + 1 < ATTEMPTS:
                time.sleep(1.5)
    raise last_error  # type: ignore[misc]


def _fetch_once() -> dict:
    response = requests.get(
        API_URL,
        params={
            "latitude": WEATHER_LAT,
            "longitude": WEATHER_LON,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                       "is_day,precipitation,weather_code,wind_speed_10m,"
                       "wind_gusts_10m,dew_point_2m,uv_index,cloud_cover,pressure_msl",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max,sunrise,sunset,"
                     "wind_speed_10m_max,uv_index_max,precipitation_sum,"
                     "daylight_duration",
            # CAPE is the honest thunderstorm signal available here: Open-Meteo
            # accepts `lightning_potential` but returns all nulls for US
            # locations, so instability plus the WMO thunder codes is what there
            # is. Actual strike proximity needs a commercial feed.
            "hourly": "temperature_2m,precipitation_probability,weather_code,"
                      "apparent_temperature,wind_speed_10m,cape,is_day",
            "timezone": "auto",
            "forecast_days": 10,
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
        _persist(result)
    except Exception as exc:  # noqa: BLE001 - see docstring
        message = f"Couldn't reach the weather service ({type(exc).__name__})."
        fallback = _last_good or _load_persisted()
        if fallback is not None:
            result = {**fallback, "stale": True, "errors": [message]}
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
