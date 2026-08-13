"""Severe weather alerts and radar, from the National Weather Service.

Open-Meteo - which supplies every number on the weather page - has no alerts
feed at all, so warnings come from api.weather.gov instead. It needs no API key
and no account, same as Open-Meteo, which is the property that matters for an
appliance meant to run untouched for months. It does require a User-Agent that
identifies you; NWS returns 403 for the default one.

US only. That is fine for this wall, but it is the reason nothing here is wired
into the main weather fetch: if the alerts endpoint is unreachable, or you're
outside its coverage, the page still shows conditions and a forecast.

On lightning, since that was the question that prompted this:
  - There is no free public feed of individual strikes, so "lightning 4 miles
    away" is not something this can honestly show. Those feeds are commercial
    (Vaisala, Earth Networks) or hobbyist networks with terms that don't suit an
    always-on appliance.
  - Open-Meteo accepts a `lightning_potential` variable, and it comes back all
    nulls for US locations - the parameter exists for European models only.
    Verified against this wall's own coordinates before relying on it.
  - So thunderstorms are covered three honest ways instead: NWS Severe
    Thunderstorm and Tornado warnings (the actionable signal, issued by humans
    watching radar), CAPE as an instability measure, and the radar loop, which
    shows where the storms actually are.
"""

import datetime as dt
import json
import time

import requests

from app.config import DEMO_MODE, PROJECT_ROOT, WEATHER_LAT, WEATHER_LON

API_ROOT = "https://api.weather.gov"

# NWS asks for a contact in the User-Agent and 403s the default python-requests
# one. This is the documented way to identify a client.
USER_AGENT = "wallCalendar (https://github.com/elijahcraig45/wallCalendar)"

TIMEOUT_SECONDS = 20

# Alerts are the time-critical part of the page - a tornado warning is worth
# having within a couple of minutes - so this polls harder than the forecast
# (15 min) while staying polite.
CACHE_TTL_SECONDS = 180
ERROR_CACHE_TTL_SECONDS = 120

# The radar station for a point never changes, so this is looked up once and then
# kept for a day. It's a separate request from the alerts, and a failure here must
# not cost you the warnings.
STATION_TTL_SECONDS = 24 * 60 * 60

# Rank for display: the top of the list should be the thing you'd act on. NWS
# severity is a documented enum; anything unrecognised sorts last rather than
# first, so an unfamiliar value can't outrank a tornado warning.
_SEVERITY_ORDER = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3, "Unknown": 4}

# Events worth shouting about, used to mark an alert as urgent in the UI. Matched
# on a substring so "Tornado Warning" and "Tornado Watch" both count while the
# list stays short.
_URGENT_EVENTS = ("Tornado", "Severe Thunderstorm", "Flash Flood", "Hurricane", "Extreme Wind")

_cache: tuple[float, dict] | None = None
_last_good: dict | None = None
_station: tuple[float, dict] | None = None

_CACHE_FILE = PROJECT_ROOT / "data" / "alerts_cache.json"


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


def _get(url: str, params: dict | None = None) -> dict:
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _shape_alert(feature: dict) -> dict:
    """One NWS alert feature, reduced to what the wall renders.

    Kept separate from the fetch so it can be exercised against a captured real
    payload - which is how it was built, since there were no active alerts here
    at the time and a corporate TLS proxy blocks the live call from the dev
    machine anyway.
    """
    props = feature.get("properties") or {}
    event = props.get("event") or "Weather alert"
    severity = props.get("severity") or "Unknown"

    return {
        "id": props.get("id") or feature.get("id"),
        "event": event,
        "severity": severity,
        "urgency": props.get("urgency"),
        # The headline already reads as a sentence ("Heat Advisory issued August
        # 13 at 12:36PM CDT until..."), which is better than anything assembled
        # from the parts here.
        "headline": props.get("headline"),
        "area": props.get("areaDesc"),
        "onset": props.get("onset"),
        "ends": props.get("ends") or props.get("expires"),
        "expires": props.get("expires"),
        "sender": props.get("senderName"),
        "description": props.get("description"),
        "instruction": props.get("instruction"),
        "urgent": any(word in event for word in _URGENT_EVENTS),
    }


def _parse(payload: dict) -> dict:
    features = payload.get("features") or []
    alerts = [_shape_alert(f) for f in features]

    # Deduplicate on id. The same alert can be listed more than once when it
    # covers several zones the point falls in.
    seen: set[str] = set()
    unique = []
    for alert in alerts:
        key = alert["id"] or f"{alert['event']}|{alert['onset']}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(alert)

    unique.sort(key=lambda a: (_SEVERITY_ORDER.get(a["severity"], 99), a["event"] or ""))

    return {
        "alerts": unique,
        "count": len(unique),
        "urgent_count": sum(1 for a in unique if a["urgent"]),
        "errors": [],
    }


def _fetch_alerts() -> dict:
    payload = _get(
        f"{API_ROOT}/alerts/active",
        {"point": f"{WEATHER_LAT},{WEATHER_LON}", "status": "actual"},
    )
    return _parse(payload)


# State -> NWS RIDGE regional loop. Every name in here was probed against
# radar.weather.gov and returned 200; the plausible-sounding ones that 404 are
# deliberately absent (NORTHERNPLAINS, SOUTHWEST, NORTHWEST and friends don't
# exist). A state that isn't listed simply gets no regional tab rather than a
# broken image, which is why this maps only what was verified.
_REGION_LOOPS = {
    "SOUTHEAST": ("AL", "GA", "FL", "SC", "NC", "TN", "VA", "KY", "WV", "MS"),
    "NORTHEAST": ("ME", "NH", "VT", "MA", "RI", "CT", "NY", "NJ", "PA", "MD", "DE", "DC"),
    "SOUTHMISSVLY": ("AR", "LA", "MO"),
    "UPPERMISSVLY": ("MN", "IA", "WI", "SD", "ND", "NE"),
    "CENTGRLAKES": ("MI", "OH", "IN", "IL"),
    "SOUTHPLAINS": ("TX", "OK", "KS"),
    "SOUTHROCKIES": ("CO", "NM", "UT", "AZ"),
    "NORTHROCKIES": ("MT", "WY", "ID"),
    "PACSOUTHWEST": ("CA", "NV"),
    "PACNORTHWEST": ("OR", "WA"),
    "ALASKA": ("AK",),
    "HAWAII": ("HI",),
    "CARIB": ("PR", "VI"),
}

_STATE_TO_REGION = {
    state: region for region, states in _REGION_LOOPS.items() for state in states
}


def _loop(name: str) -> str:
    return f"https://radar.weather.gov/ridge/standard/{name}_loop.gif"


def radar_station() -> dict:
    """The nearest radar and the RIDGE loop for it.

    Never raises. Radar is the most decorative thing on the page and the least
    urgent, so a failure here returns an absent shape rather than propagating.
    """
    global _station

    if DEMO_MODE:
        return {"available": False, "reason": "demo mode"}

    now = time.monotonic()
    if _station is not None and (now - _station[0]) < STATION_TTL_SECONDS:
        return _station[1]

    try:
        props = _get(f"{API_ROOT}/points/{WEATHER_LAT},{WEATHER_LON}").get("properties") or {}
        station = props.get("radarStation")
        if not station:
            result = {"available": False, "reason": "no radar station for this point"}
        else:
            state = ((props.get("relativeLocation") or {}).get("properties") or {}).get("state")
            region = _STATE_TO_REGION.get((state or "").upper())
            result = {
                "available": True,
                "station": station,
                "state": state,
                "region": region,
                # A plain animated GIF, which is the whole appeal: no map library,
                # no tile server, no API key, and it animates by itself.
                "loop_url": _loop(station),
                "still_url": f"https://radar.weather.gov/ridge/standard/{station}_0.gif",
                # Local is the storm on top of you; regional is the line of storms
                # on the way, which the single-site view crops out entirely.
                "regional_url": _loop(region) if region else None,
                "national_url": _loop("CONUS"),
            }
    except Exception as exc:  # noqa: BLE001 - see docstring
        result = {"available": False, "reason": f"Couldn't reach the radar index ({type(exc).__name__})."}

    _station = (now, result)
    return result


def get_alerts() -> dict:
    """Never raises. A failure falls back to the last good answer, marked stale.

    Staleness matters more here than for the forecast: an expired warning left on
    screen is worse than no warning, so anything past its `expires` is dropped on
    the way out even when it came from the cache.
    """
    global _cache, _last_good

    if DEMO_MODE:
        from app import demo_weather

        return demo_weather.get_alerts()

    now = time.monotonic()
    if _cache is not None:
        ttl = ERROR_CACHE_TTL_SECONDS if _cache[1].get("errors") else CACHE_TTL_SECONDS
        if (now - _cache[0]) < ttl:
            return _drop_expired(_cache[1])

    try:
        result = _fetch_alerts()
        result["stale"] = False
        result["fetched_at"] = dt.datetime.now().isoformat(timespec="seconds")
        _last_good = result
        _persist(result)
    except Exception as exc:  # noqa: BLE001 - see docstring
        message = f"Couldn't reach the alerts service ({type(exc).__name__})."
        fallback = _last_good or _load_persisted()
        if fallback is not None:
            result = {**fallback, "stale": True, "errors": [message]}
        else:
            result = {"alerts": [], "count": 0, "urgent_count": 0, "stale": False, "errors": [message]}

    result.setdefault("available", True)
    _cache = (now, result)
    return _drop_expired(result)


def _drop_expired(payload: dict) -> dict:
    """Hide alerts whose `expires` has passed.

    The cache is only three minutes deep, but the persisted copy can be hours old
    after a restart, and showing a lapsed tornado warning would be actively
    misleading. Alerts with no or unparseable `expires` are kept - dropping an
    alert because its timestamp was odd is the worse failure.
    """
    now = dt.datetime.now(dt.timezone.utc)
    kept = []
    for alert in payload.get("alerts") or []:
        expires = alert.get("expires")
        if expires:
            try:
                stamp = dt.datetime.fromisoformat(expires)
                # NWS sends an offset ("...-05:00"), but a naive timestamp would
                # raise TypeError on the comparison rather than ValueError on the
                # parse - a different exception, past the guard, and a 500 on the
                # only endpoint that carries tornado warnings. Assume local time,
                # which is what a stamp with no offset means in practice.
                if stamp.tzinfo is None:
                    stamp = stamp.astimezone()
                if stamp < now:
                    continue
            except (ValueError, TypeError, OSError):
                pass
        kept.append(alert)

    if len(kept) == len(payload.get("alerts") or []):
        return payload
    return {
        **payload,
        "alerts": kept,
        "count": len(kept),
        "urgent_count": sum(1 for a in kept if a.get("urgent")),
    }
