"""Air quality and pollen.

Air quality is Open-Meteo's air-quality API: same provider as the forecast, no key,
and `us_aqi` is populated for US locations.

Pollen has two providers, in this order:

  1. Google's Pollen API, when WALLCAL_POLLEN_KEY is set. Documented and
     supported, and it says considerably more than the alternative: separate
     grass/tree/weed indices, which specific plants are actually in season, and a
     health note. Scale is the Universal Pollen Index, 0-5.
  2. pollen.com (IQVIA) otherwise, and as a fallback if Google fails - so a quota
     or billing problem degrades to the keyless source rather than to nothing.
     Scale is 0-12. This one is an UNDOCUMENTED endpoint: it answers 405 without a
     Referer header, meaning it's intended for their own site. Stable for years and
     the only keyless US option, but it may vanish without notice.

The two scales are never mixed. Each answer carries its own `scale_max` and its own
source name, and both are shown on screen, so a reading is always displayed against
the scale it was actually measured on.

Not Open-Meteo, for pollen: it *accepts* pollen variables and returns all nulls
here - they come from CAMS Europe, so US locations get nothing. Verified against
this wall's own coordinates before looking elsewhere, which is the same trap
`lightning_potential` set in alerts_service.

Every fetch here is independent: pollen failing must not cost you the AQI, and vice
versa.
"""

import datetime as dt
import json
import time

import requests

from app.config import (
    DEMO_MODE,
    POLLEN_API_KEY,
    PROJECT_ROOT,
    WEATHER_LAT,
    WEATHER_LON,
    WEATHER_ZIP,
)

AQI_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
POLLEN_URL = "https://www.pollen.com/api/forecast/current/pollen"
GOOGLE_POLLEN_URL = "https://pollen.googleapis.com/v1/forecast:lookup"

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


# ---------------------------------------------------------------------------
# Google Pollen
# ---------------------------------------------------------------------------
#
# Preferred when a key is configured. It is a documented, supported API rather
# than a scraped endpoint, and it says considerably more: separate grass/tree/weed
# indices, which specific plants are actually in season, and a health note.
#
# Its scale is the Universal Pollen Index, 0-5, NOT pollen.com's 0-12. The two are
# never mixed - each answer carries its own `scale_max` and its own source name, so
# a reading is always displayed against the scale it was measured on.

# UPI category names come from Google rather than being derived here: it's their
# index, and their bands. This is only the fallback for a response that omits it.
_UPI_FALLBACK = ["None", "Very low", "Low", "Moderate", "High", "Very high"]


def _upi_label(info: dict) -> str | None:
    category = (info or {}).get("category")
    if category:
        return category
    value = (info or {}).get("value")
    if value is None:
        return None
    return _UPI_FALLBACK[min(int(value), len(_UPI_FALLBACK) - 1)]


def _parse_google_day(day: dict) -> dict:
    """One day of Google's forecast, in the same shape the pollen.com parser
    produces, so the UI never has to know which provider answered."""
    types = []
    best = None
    recommendation = None

    for entry in day.get("pollenTypeInfo") or []:
        info = entry.get("indexInfo") or {}
        value = info.get("value")
        types.append(
            {
                "name": entry.get("displayName") or entry.get("code"),
                "index": value,
                "label": _upi_label(info),
                "in_season": entry.get("inSeason"),
            }
        )
        if value is not None and (best is None or value > best):
            best = value
            notes = entry.get("healthRecommendations") or []
            recommendation = notes[0] if notes else None

    # The plants actually driving it, which is the part pollen.com can't do: it
    # lists the same three triggers every day regardless of season.
    triggers = [
        plant.get("displayName") or plant.get("code")
        for plant in day.get("plantInfo") or []
        if plant.get("inSeason") and ((plant.get("indexInfo") or {}).get("value") or 0) > 0
    ]

    return {
        "index": best,
        "label": _upi_label({"value": best}) if best is not None else None,
        "triggers": [t for t in triggers if t],
        "types": types,
        "recommendation": recommendation,
    }


def _parse_google_pollen(payload: dict) -> dict:
    days = payload.get("dailyInfo") or []
    today = _parse_google_day(days[0]) if days else {"index": None}
    tomorrow = _parse_google_day(days[1]) if len(days) > 1 else {"index": None}

    # Google's own category for the day's peak, when it gave us one, rather than
    # the label derived from the bare number.
    if days:
        peak = max(
            (
                (e.get("indexInfo") or {})
                for e in days[0].get("pollenTypeInfo") or []
                if (e.get("indexInfo") or {}).get("value") is not None
            ),
            key=lambda i: i.get("value", -1),
            default={},
        )
        if peak.get("category"):
            today["label"] = peak["category"]

    return {
        "available": today.get("index") is not None,
        "place": None,          # Google answers for coordinates, not a named place
        "today": today,
        "tomorrow": tomorrow,
        # Google's forecast starts today; there is no yesterday to report.
        "yesterday": {"index": None, "label": None, "triggers": []},
        "source": "Google Pollen",
        "scale_max": 5,
    }


def _fetch_google_pollen() -> dict:
    response = requests.get(
        GOOGLE_POLLEN_URL,
        params={
            "location.latitude": WEATHER_LAT,
            "location.longitude": WEATHER_LON,
            "days": 2,
            # Plant pictures and long descriptions are a lot of payload for a
            # wall that shows names only.
            "plantsDescription": "false",
        },
        # The key goes in a header, never the query string: requests puts the URL
        # into exception messages, so one logged traceback would print a `?key=`.
        headers={"User-Agent": USER_AGENT, "X-Goog-Api-Key": POLLEN_API_KEY},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return _parse_google_pollen(response.json())


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

    # Google when a key is configured, pollen.com otherwise - and pollen.com as a
    # fallback if Google fails, so a quota or billing problem degrades to the
    # keyless source rather than to nothing. Note the messages carry only the
    # exception CLASS: a Google error's str() can contain the request URL.
    pollen = {"available": False, "source": "pollen.com"}
    if POLLEN_API_KEY:
        try:
            pollen = _fetch_google_pollen()
        except Exception as exc:  # noqa: BLE001 - see docstring
            errors.append(f"Couldn't reach Google Pollen ({type(exc).__name__}).")

    if not pollen.get("available"):
        try:
            pollen = _fetch_pollen()
        except Exception as exc:  # noqa: BLE001 - see docstring
            pollen.setdefault("source", "pollen.com")
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
