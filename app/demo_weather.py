"""Synthetic weather for demo mode.

Built by handing `weather_service._parse` an Open-Meteo-shaped payload rather than
hand-writing the parsed result, so the fixtures exercise the same parsing code the
live path uses - if the parser breaks, the demo breaks too, which is the point.

Deliberately varied across the four days (clear, storm, rain, cloud) so the
forecast strip shows more than one icon in a screenshot.
"""

import datetime as dt


def _payload() -> dict:
    today = dt.date.today()
    # A full week now that the weather page shows seven days.
    dates = [(today + dt.timedelta(days=i)).isoformat() for i in range(7)]

    return {
        "timezone": "America/New_York",
        "current": {
            "time": dt.datetime.now().replace(second=0, microsecond=0).isoformat(timespec="minutes"),
            "temperature_2m": 80.5,
            "relative_humidity_2m": 80,
            "apparent_temperature": 88.8,
            "is_day": 1,
            "precipitation": 0.0,
            "weather_code": 2,
            "wind_speed_10m": 4.2,
        },
        "daily": {
            "time": dates,
            # clear / thunderstorm / rain / overcast / fog / clear / partly
            "weather_code": [1, 95, 63, 3, 45, 0, 2],
            "temperature_2m_max": [95.6, 88.1, 79.3, 84.0, 86.2, 90.4, 92.0],
            "temperature_2m_min": [75.7, 72.4, 68.9, 70.2, 71.5, 73.1, 74.6],
            "precipitation_probability_max": [13, 82, 61, 8, 20, 4, 11],
            "sunrise": [f"{d}T06:58" for d in dates],
            "sunset": [f"{d}T20:26" for d in dates],
            "wind_speed_10m_max": [9, 21, 14, 7, 5, 8, 10],
            "uv_index_max": [8, 5, 4, 7, 6, 9, 9],
        },
        # 48 hours, so the hourly strip has something to scroll through. Starts at
        # local midnight like the real series does, which is what makes the
        # "anchor to now" slicing worth exercising here at all.
        "hourly": _hourly(dates),
    }


def _hourly(dates: list[str]) -> dict:
    """Two days of hourly values, shaped exactly like Open-Meteo's."""
    times, temps, probs, codes, feels, winds, capes = [], [], [], [], [], [], []
    for day_index, date in enumerate(dates[:2]):
        for hour in range(24):
            times.append(f"{date}T{hour:02d}:00")
            # A plausible daily curve: coolest before dawn, peak mid-afternoon.
            warmth = -8 if hour < 6 else (10 if 13 <= hour <= 17 else 0)
            temps.append(82 + warmth + day_index * -4)
            feels.append(88 + warmth + day_index * -4)
            # Afternoon storms on both days. On one day only, whether the thunder
            # row and CAPE peak appeared depended on the time the screenshot was
            # taken, since both are measured forward from now.
            storm = 14 <= hour <= 19
            codes.append(95 if storm else (2 if 10 <= hour <= 20 else 1))
            probs.append(80 if storm else (15 if hour > 12 else 5))
            winds.append(14 if storm else 5)
            capes.append(2600 if storm else (900 if hour > 11 else 300))
    return {
        "time": times,
        "temperature_2m": temps,
        "apparent_temperature": feels,
        "precipitation_probability": probs,
        "weather_code": codes,
        "wind_speed_10m": winds,
        "cape": capes,
    }


# One of each kind the UI treats differently: an urgent event (so the urgent
# styling and count are exercised), an ordinary advisory, and an expired one that
# must be filtered out rather than displayed.
def _alert_payload() -> dict:
    now = dt.datetime.now(dt.timezone.utc).astimezone()
    def stamp(hours):
        return (now + dt.timedelta(hours=hours)).isoformat(timespec="seconds")

    return {
        "features": [
            {
                "id": "demo-alert-severe",
                "properties": {
                    "id": "demo-alert-severe",
                    "event": "Severe Thunderstorm Warning",
                    "severity": "Severe",
                    "urgency": "Immediate",
                    "headline": f"Severe Thunderstorm Warning issued until {(now + dt.timedelta(hours=1)).strftime('%I:%M %p')}",
                    "areaDesc": "Fulton; DeKalb; Cobb",
                    "onset": stamp(0),
                    "ends": stamp(1),
                    "expires": stamp(1),
                    "senderName": "NWS Peachtree City GA",
                    "description": "At 2:14 PM, a severe thunderstorm was located near "
                                   "Douglasville, moving east at 35 mph. HAZARD: 60 mph wind "
                                   "gusts and quarter size hail.",
                    "instruction": "For your protection move to an interior room on the "
                                   "lowest floor of a building.",
                },
            },
            {
                "id": "demo-alert-heat",
                "properties": {
                    "id": "demo-alert-heat",
                    "event": "Heat Advisory",
                    "severity": "Moderate",
                    "urgency": "Expected",
                    "headline": "Heat Advisory in effect until 8:00 PM EDT",
                    "areaDesc": "North and Central Georgia",
                    "onset": stamp(0),
                    "ends": stamp(6),
                    "expires": stamp(6),
                    "senderName": "NWS Peachtree City GA",
                    "description": "Heat index values up to 108 expected.",
                    "instruction": "Drink plenty of fluids and stay out of the sun.",
                },
            },
            {
                "id": "demo-alert-lapsed",
                "properties": {
                    "id": "demo-alert-lapsed",
                    "event": "Flood Advisory",
                    "severity": "Minor",
                    "urgency": "Past",
                    "headline": "Flood Advisory has expired",
                    "areaDesc": "Fulton",
                    "onset": stamp(-4),
                    "ends": stamp(-1),
                    "expires": stamp(-1),
                    "senderName": "NWS Peachtree City GA",
                    "description": "Minor flooding was reported.",
                    "instruction": None,
                },
            },
        ]
    }


def get_alerts() -> dict:
    """Built through the real parser and the real expiry filter, so the demo can't
    pass while the live path is broken."""
    from app import alerts_service

    result = alerts_service._parse(_alert_payload())
    result["stale"] = False
    result["available"] = True
    result["fetched_at"] = dt.datetime.now().isoformat(timespec="seconds")
    return alerts_service._drop_expired(result)


def get_weather() -> dict:
    from app import weather_service

    result = weather_service._parse(_payload())
    result["stale"] = False
    result["available"] = True
    result["fetched_at"] = dt.datetime.now().isoformat(timespec="seconds")
    return result
