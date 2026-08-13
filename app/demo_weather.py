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
    dates = [(today + dt.timedelta(days=i)).isoformat() for i in range(4)]

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
            # clear / thunderstorm / rain / overcast
            "weather_code": [1, 95, 63, 3],
            "temperature_2m_max": [95.6, 88.1, 79.3, 84.0],
            "temperature_2m_min": [75.7, 72.4, 68.9, 70.2],
            "precipitation_probability_max": [13, 82, 61, 8],
            "sunrise": [f"{d}T06:58" for d in dates],
            "sunset": [f"{d}T20:26" for d in dates],
        },
    }


def get_weather() -> dict:
    from app import weather_service

    result = weather_service._parse(_payload())
    result["stale"] = False
    result["available"] = True
    result["fetched_at"] = dt.datetime.now().isoformat(timespec="seconds")
    return result
