"""Air quality and pollen.

Two sources, because no single keyless one covers both:

  - Air quality is Open-Meteo's air-quality API. Same provider as the forecast, no
    key, and `us_aqi` is populated for US locations.
  - Pollen is pollen.com (IQVIA). Open-Meteo *accepts* pollen variables and
    returns all nulls here - they come from CAMS Europe, so US locations get
    nothing. Verified against this wall's coordinates before looking elsewhere,
    which is the same trap `lightning_potential` set in alerts_service.

About the pollen source, plainly: it is an undocumented endpoint. It requires a
Referer header (405 without one), which means it is meant for their own site
rather than for clients like this. It has been stable for years and it is the only
keyless US option, but it may break without notice - so it is best-effort, it is
labelled with its source on screen, and it degrades to absent rather than taking
the panel down. The alternatives (Google Pollen, Ambee, AccuWeather) all want an
API key, and a credential that expires is a worse property for an appliance meant
to run untouched for months.

Both fetches are independent: pollen failing must not cost you the AQI, and vice
versa.
"""

import datetime as dt
import json
import time

import requests

from app.config import DEMO_MODE, PROJECT_ROOT, WEATHER_LAT, WEATHER_LON, WEATHER_ZIP

AQI_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
POLLEN_URL = "https://www.pollen.com/api/forecast/current/pollen"

USER_AGENT = "wallCalendar (https://github.com/elijahcraig45/wallCalendar)"

TIMEOUT_SECONDS = 20

# Air quality moves on the scale of hours; pollen is published once a day. Neither
# needs the 3-minute treatment the severe-weather alerts get.
CACHE_TTL_SECONDS = 30 * 60
ERROR_CACHE_TTL_SECONDS = 300

# US AQI breakpoints, from the EPA scale the value is already expressed in.
_AQI_BANDS = [
    (50, "Good", "Air quality is fine."),
    (100, "Moderate", "Fine for most people."),
    (150, "Unhealthy for sensitive groups", "Sensitive groups should take it easy outdoors."),
    (200, "Unhealthy", "Everyone may feel effects; limit long spells outside."),
    (300, "Very unhealthy", "Avoid prolonged exertion outdoors."),
    (10_000, "Hazardous", "Stay indoors."),
]

# IQVIA's index runs 0-12. These are their published bands.
_POLLEN_BANDS = [
    (2.4, "Low"),
    (4.8, "Low-medium"),
    (7.2, "Medium"),
    (9.6, "Medium-high"),
    (12.0, "High"),
]

_cache: tuple[float, dict] | None = None
_last_good: dict | None = None

_CACHE_FILE = PROJECT_ROOT / "data" / "air_cache.json"


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
        pass


def describe_aqi(value: float | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    for limit, label, note in _AQI_BANDS:
        if value <= limit:
            return label, note
    return None, None


def describe_pollen(index: float | None) -> str | None:
    if index is None:
        return None
    for limit, label in _POLLEN_BANDS:
        if index <= limit:
            return label
    return "High"


def _parse_aqi(payload: dict) -> dict:
    """Kept separate from the fetch so it can be exercised against a captured real
    payload, the same way the weather and alert parsers are."""
    current = payload.get("current") or {}
    aqi = current.get("us_aqi")
    label, note = describe_aqi(aqi)

    def rounded(key):
        value = current.get(key)
        return None if value is None else round(value, 1)

    return {
        "available": aqi is not None,
        "aqi": None if aqi is None else round(aqi),
        "label": label,
        "note": note,
        "observed_at": current.get("time"),
        # The components, for when you want to know WHY the number is what it is -
        # in Atlanta in August it is almost always ozone rather than particulates.
        "pm2_5": rounded("pm2_5"),
        "pm10": rounded("pm10"),
        "ozone": rounded("ozone"),
        "nitrogen_dioxide": rounded("nitrogen_dioxide"),
    }


def _parse_pollen(payload: dict) -> dict:
    """pollen.com's shape: a Location with Yesterday/Today/Tomorrow periods, each
    carrying an index and the plants driving it."""
    location = payload.get("Location") or {}
    periods = {p.get("Type"): p for p in location.get("periods") or []}

    def period(name):
        entry = periods.get(name) or {}
        index = entry.get("Index")
        return {
            "index": index,
            "label": describe_pollen(index),
            "triggers": [t.get("Name") for t in entry.get("Triggers") or [] if t.get("Name")],
        }

    today = period("Today")
    return {
        "available": today["index"] is not None,
        "place": location.get("DisplayLocation") or location.get("City"),
        "today": today,
        "tomorrow": period("Tomorrow"),
        "yesterday": period("Yesterday"),
        # Named so the UI can attribute it, because this is a third-party index
        # rather than a measurement and readers deserve to know whose it is.
        "source": "pollen.com",
        "scale_max": 12,
    }


def _fetch_aqi() -> dict:
    response = requests.get(
        AQI_URL,
        params={
            "latitude": WEATHER_LAT,
            "longitude": WEATHER_LON,
            "current": "us_aqi,pm2_5,pm10,ozone,nitrogen_dioxide",
            "timezone": "auto",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return _parse_aqi(response.json())


def _fetch_pollen() -> dict:
    # The Referer is required, not decoration: without it the endpoint answers 405.
    response = requests.get(
        f"{POLLEN_URL}/{WEATHER_ZIP}",
        headers={
            "User-Agent": USER_AGENT,
            "Referer": f"https://www.pollen.com/forecast/current/pollen/{WEATHER_ZIP}",
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return _parse_pollen(response.json())


def get_air() -> dict:
    """Never raises, and the two halves fail independently: pollen breaking must
    not cost you the AQI. The pollen endpoint is undocumented and will eventually
    go away, so this has to survive that without a deploy."""
    global _cache, _last_good

    if DEMO_MODE:
        from app import demo_weather

        return demo_weather.get_air()

    now = time.monotonic()
    if _cache is not None:
        ttl = ERROR_CACHE_TTL_SECONDS if _cache[1].get("errors") else CACHE_TTL_SECONDS
        if (now - _cache[0]) < ttl:
            return _cache[1]

    errors: list[str] = []

    try:
        aqi = _fetch_aqi()
    except Exception as exc:  # noqa: BLE001 - see docstring
        aqi = {"available": False}
        errors.append(f"Couldn't reach the air quality service ({type(exc).__name__}).")

    try:
        pollen = _fetch_pollen()
    except Exception as exc:  # noqa: BLE001 - see docstring
        pollen = {"available": False, "source": "pollen.com"}
        errors.append(f"Couldn't reach the pollen service ({type(exc).__name__}).")

    result = {"aqi": aqi, "pollen": pollen, "errors": errors, "stale": False}

    # Fall back per-half rather than wholesale, so one source failing doesn't
    # discard a good reading from the other.
    fallback = _last_good or _load_persisted()
    if fallback:
        for key in ("aqi", "pollen"):
            if not result[key].get("available") and (fallback.get(key) or {}).get("available"):
                result[key] = {**fallback[key], "stale": True}
                result["stale"] = True

    if result["aqi"].get("available") or result["pollen"].get("available"):
        result["fetched_at"] = dt.datetime.now().isoformat(timespec="seconds")
        if not errors:
            _last_good = result
            _persist(result)

    _cache = (now, result)
    return result
