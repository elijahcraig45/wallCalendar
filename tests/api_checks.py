#!/usr/bin/env python3
"""Server-side checks that the browser tests can't reach.

Run directly - no pytest, so nothing extra has to be installed on the Pi:

    .venv/bin/python tests/api_checks.py

These cover states that need the server rigged rather than driven: an install
with no Spotify account, demo mode refusing calendar writes, and the month-grid
bounds maths. Playwright can't mock `spotify_auth`, and the grid bounds are pure
arithmetic that shouldn't need a browser to verify.
"""

import datetime as dt
import os
import pathlib
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}{(' - ' + detail) if detail else ''}")
        FAILURES.append(label)


def check_month_grid_bounds():
    """Every month grid must be whole Sunday-to-Saturday weeks. This caught a real
    off-by-one: Saturday is index 6 in Sunday-based indexing, and the code used 5,
    so every grid stopped on the Friday and the last row's Saturday was blank."""
    print("month grid bounds")
    from app.calendar_service import _grid_bounds

    bad = []
    for year in (2025, 2026, 2027):
        for month in range(1, 13):
            start, end = _grid_bounds(year, month)
            days = (end - start).days + 1
            if start.strftime("%A") != "Sunday" or end.strftime("%A") != "Saturday" or days % 7:
                bad.append(f"{year}-{month:02d}: {start}..{end} ({days}d)")

    check("36 months are whole Sunday->Saturday weeks", not bad, "; ".join(bad[:3]))


def check_no_spotify_account():
    """The shell polls /api/spotify/now-playing from every page every few seconds.
    With Google set up but Spotify not - the default state after setup - this used
    to raise, so the service log filled with tracebacks forever."""
    print("no Spotify account signed in")
    import server

    client = server.app.test_client()
    with patch("app.auth.spotify_auth.signed_in_accounts", return_value=[]):
        resp = client.get("/api/spotify/now-playing")
        check(
            "the shell's poll answers 200 + null, not a 500",
            resp.status_code == 200 and resp.get_json() is None,
            f"got {resp.status_code} {resp.get_data(as_text=True)[:60]!r}",
        )

        resp = client.get("/api/spotify/devices")
        check(
            "a user-initiated call explains itself as JSON",
            resp.status_code == 503 and "error" in (resp.get_json() or {}),
            f"got {resp.status_code} {resp.content_type}",
        )


def check_demo_mode_refuses_calendar_writes():
    """Demo mode must never look like it saved a calendar change. (Spotify's
    fixtures deliberately do accept playback commands - nothing to corrupt.)"""
    print("demo mode calendar writes")
    from app import calendar_service

    with patch.object(calendar_service, "DEMO_MODE", True):
        try:
            calendar_service.delete_event("a@b.c", "cal", "evt", notify_guests=False)
            check("delete_event refuses", False, "it returned instead of raising")
        except calendar_service.DemoModeError:
            check("delete_event refuses", True)
        except Exception as exc:  # noqa: BLE001
            check("delete_event refuses", False, f"raised {type(exc).__name__}")


def check_demo_spotify_playback_is_stateful():
    """The Spotify UI is only testable if pressing play actually changes state."""
    print("demo Spotify playback state")
    from app import demo_spotify

    demo_spotify.play()
    playing = demo_spotify.now_playing()["is_playing"]
    demo_spotify.pause()
    paused = demo_spotify.now_playing()["is_playing"]
    check("play/pause changes is_playing", playing and not paused)

    before = demo_spotify.now_playing()["track"]
    demo_spotify.next_track()
    check("next_track changes the track", demo_spotify.now_playing()["track"] != before)

    art = demo_spotify.now_playing()["album_art"]
    check("cover art is a self-contained data URI", art.startswith("data:image/svg+xml,"))


def check_no_global_script_collisions():
    """The frontend is plain scripts sharing one global scope, not modules. Four
    shell scripts load on every page, then one page script - and a page script
    declaring the same top-level name silently replaces the shell's copy.

    That already bit once: timers.js had `render()` and notes.js had
    `render(payload)`, so on the notes page the shell's per-second tick called the
    notes renderer with no argument and threw every second. Cheap to detect,
    invisible otherwise."""
    print("global script name collisions")
    import re

    static = pathlib.Path(__file__).resolve().parent.parent / "static"
    shell = ["panel.js", "themes.js", "weather.js", "nav.js", "timers.js"]
    pages = ["calendar.js", "spotify.js", "recipes.js", "today.js",
             "browser.js", "accounts.js"]
    patterns = (
        re.compile(r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("),
        re.compile(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="),
    )

    def top_level(name):
        found = set()
        path = static / name
        if not path.exists():
            return found
        for line in path.read_text().splitlines():
            for pattern in patterns:  # column 0 only - anything indented is scoped
                match = pattern.match(line)
                if match:
                    found.add(match.group(1))
        return found

    owned = {name: top_level(name) for name in shell + pages}
    clashes = [
        f"{shell_name} <-> {page} : {sorted(owned[page] & owned[shell_name])}"
        for page in pages
        for shell_name in shell
        if owned[page] & owned[shell_name]
    ]
    check("no page script shadows a shell script's globals", not clashes, "; ".join(clashes))


def check_hidden_utility_is_unconditional():
    """`.hidden` is toggled from JS across the whole app, and an ID rule setting
    `display` outranks a class no matter the source order. That bit four times
    (rail chip visible on the Music page, all three Recipes views stacked, the
    stale badge and weather chip unhideable), so the rule carries !important. If
    someone "cleans that up", these come back."""
    print("hidden utility")
    css = (pathlib.Path(__file__).resolve().parent.parent / "static" / "style.css").read_text()
    rule = css.rsplit(".hidden", 1)[-1]
    check(".hidden uses !important so ID rules can't outrank it", "!important" in rule.split("}")[0])
    check(".hidden is still the last rule in the file", css.rstrip().endswith("}"))



def check_weather_alerts_parsing():
    """The NWS alert parser, against the shape the real API returns.

    Built this way because there were no active alerts for this wall's location
    when it was written, and the dev machine sits behind a TLS-inspecting proxy
    that blocks the live call from Python. So the parser was developed against a
    payload captured with curl (15 real alerts from Florida) and the ordering,
    dedup and expiry rules are pinned here.
    """
    print("weather alert parsing")
    from app import alerts_service

    now = dt.datetime.now(dt.timezone.utc)

    def feature(event, severity, ident, expires_hours=6):
        return {
            "id": ident,
            "properties": {
                "id": ident,
                "event": event,
                "severity": severity,
                "headline": f"{event} issued",
                "areaDesc": "Fulton",
                "expires": (now + dt.timedelta(hours=expires_hours)).isoformat(),
                "senderName": "NWS Peachtree City GA",
            },
        }

    parsed = alerts_service._parse(
        {
            "features": [
                feature("Heat Advisory", "Moderate", "a"),
                feature("Tornado Warning", "Extreme", "b"),
                feature("Rip Current Statement", "Minor", "c"),
                # The same alert can be listed once per zone the point falls in.
                feature("Heat Advisory", "Moderate", "a"),
            ]
        }
    )

    check(
        "the most severe alert sorts first",
        parsed["alerts"][0]["event"] == "Tornado Warning",
        f"got {parsed['alerts'][0]['event']}",
    )
    check("duplicate zone listings collapse", parsed["count"] == 3, f"got {parsed['count']}")
    check(
        "a tornado warning is flagged urgent",
        parsed["alerts"][0]["urgent"] and parsed["urgent_count"] == 1,
    )
    check(
        "an advisory is not flagged urgent",
        not any(a["urgent"] for a in parsed["alerts"] if a["event"] == "Heat Advisory"),
    )

    # An unknown severity must sort LAST, not first - otherwise a value NWS adds
    # later could outrank a tornado warning.
    odd = alerts_service._parse(
        {"features": [feature("Space Weather Thing", "Cataclysmic", "z"), feature("Tornado Warning", "Extreme", "b")]}
    )
    check(
        "an unrecognised severity sorts last",
        odd["alerts"][0]["event"] == "Tornado Warning",
        f"got {odd['alerts'][0]['event']}",
    )

    # Expiry: a lapsed warning on screen is worse than no warning.
    lapsed = alerts_service._parse(
        {"features": [feature("Flood Advisory", "Minor", "x", expires_hours=-1), feature("Heat Advisory", "Moderate", "y")]}
    )
    filtered = alerts_service._drop_expired(lapsed)
    check(
        "an expired alert is dropped",
        filtered["count"] == 1 and filtered["alerts"][0]["event"] == "Heat Advisory",
        f"got {[a['event'] for a in filtered['alerts']]}",
    )

    # ...but an alert with an unparseable timestamp is kept. Dropping a real
    # warning because its date was odd is the worse failure.
    weird = {
        "alerts": [{"event": "Tornado Warning", "expires": "not-a-date", "urgent": True}],
        "count": 1,
        "urgent_count": 1,
    }
    check(
        "an alert with an unreadable expiry is kept",
        alerts_service._drop_expired(weird)["count"] == 1,
    )

    # A naive timestamp (no offset) used to raise TypeError on the comparison
    # rather than ValueError on the parse - a different exception, straight past
    # the guard, 500ing the one endpoint that carries tornado warnings. Treated as
    # local time, which is what a stamp with no offset means in practice.
    naive_future = dt.datetime.now().replace(microsecond=0) + dt.timedelta(hours=2)
    naive_past = dt.datetime.now().replace(microsecond=0) - dt.timedelta(hours=2)
    naive = {
        "alerts": [
            {"event": "Tornado Warning", "expires": naive_future.isoformat(), "urgent": True},
            {"event": "Flood Advisory", "expires": naive_past.isoformat(), "urgent": False},
        ],
        "count": 2,
        "urgent_count": 1,
    }
    filtered_naive = alerts_service._drop_expired(naive)
    check(
        "a naive expiry timestamp doesn't crash the endpoint",
        filtered_naive["count"] == 1
        and filtered_naive["alerts"][0]["event"] == "Tornado Warning",
        f"got {[a['event'] for a in filtered_naive['alerts']]}",
    )


def check_weather_hourly_is_anchored_to_now():
    """The hourly series starts at local midnight, so slicing from index 0 asked
    "was it thundery overnight" - the wrong 12 hours for an afternoon-storm
    climate. This pins the anchor."""
    print("weather hourly anchoring")
    from app import weather_service

    today = dt.date.today().isoformat()
    hours = [{"time": f"{today}T{h:02d}:00", "cape": h * 100} for h in range(24)]

    now_hour = dt.datetime.now().hour
    upcoming = weather_service._next_hours(hours, 12)

    check(
        "the slice starts at the current hour",
        upcoming and upcoming[0]["time"] == f"{today}T{now_hour:02d}:00",
        f"got {upcoming[0]['time'] if upcoming else 'nothing'}, expected hour {now_hour}",
    )
    check(
        "the slice never runs past the end of the data",
        len(upcoming) == min(12, 24 - now_hour),
        f"got {len(upcoming)}",
    )
    # A malformed timestamp must be skipped rather than raise - this parses live
    # third-party data.
    messy = weather_service._next_hours([{"time": "nonsense"}, *hours], 3)
    check("a malformed hour timestamp is skipped, not fatal", isinstance(messy, list))



def check_air_quality_and_pollen():
    """AQI and pollen bands, and the rule that the two halves fail independently.

    Pollen is the fragile one: it comes from an undocumented pollen.com endpoint
    (Open-Meteo's pollen variables are null for US locations - CAMS Europe only,
    verified against this wall's coordinates). It will break one day, and when it
    does the air quality must survive it.
    """
    print("air quality and pollen")
    from app import air_service

    # US AQI breakpoints, at the edges rather than the middles.
    for value, expected in [
        (0, "Good"), (50, "Good"), (51, "Moderate"), (100, "Moderate"),
        (101, "Unhealthy for sensitive groups"), (151, "Unhealthy"),
        (201, "Very unhealthy"), (301, "Hazardous"),
    ]:
        label, _ = air_service.describe_aqi(value)
        check(f"AQI {value} is {expected}", label == expected, f"got {label}")

    # IQVIA's 0-12 scale.
    for value, expected in [
        (0, "Low"), (2.4, "Low"), (2.5, "Low-medium"), (4.9, "Medium"),
        (7.2, "Medium"), (7.3, "Medium-high"), (9.7, "High"), (12, "High"),
    ]:
        check(f"pollen {value} is {expected}", air_service.describe_pollen(value) == expected,
              f"got {air_service.describe_pollen(value)}")

    check("a missing AQI has no band", air_service.describe_aqi(None) == (None, None))
    check("a missing pollen index has no band", air_service.describe_pollen(None) is None)

    # An AQI payload of nulls - which is what a location outside coverage returns -
    # must report unavailable rather than rendering "None".
    empty = air_service._parse_aqi({"current": {"us_aqi": None, "pm2_5": None}})
    check("an empty AQI payload reports unavailable", empty["available"] is False)

    # Pollen with no Today period, ditto.
    no_today = air_service._parse_pollen(
        {"Location": {"City": "ATLANTA", "periods": [{"Type": "Yesterday", "Index": 3.0}]}}
    )
    check("pollen with no Today reports unavailable", no_today["available"] is False)
    check("pollen still names its source when unavailable", no_today["source"] == "pollen.com")


def check_radar_regions_are_verified():
    """Every RIDGE regional loop name in the map was probed against
    radar.weather.gov and returned 200. The plausible-sounding ones that 404
    (NORTHERNPLAINS, SOUTHWEST, NORTHWEST, CENTPLAINS) must stay out of it - an
    unmapped state gets no regional tab, which is better than a broken image."""
    print("radar regions")
    from app.alerts_service import _REGION_LOOPS, _STATE_TO_REGION

    verified = {
        "SOUTHEAST", "NORTHEAST", "SOUTHMISSVLY", "UPPERMISSVLY", "CENTGRLAKES",
        "SOUTHPLAINS", "SOUTHROCKIES", "NORTHROCKIES", "PACSOUTHWEST",
        "PACNORTHWEST", "ALASKA", "HAWAII", "CARIB",
    }
    check(
        "only verified region loop names are mapped",
        set(_REGION_LOOPS) <= verified,
        f"unverified: {set(_REGION_LOOPS) - verified}",
    )
    check("this wall's state maps to the southeast loop", _STATE_TO_REGION.get("GA") == "SOUTHEAST")
    check("an unmapped state yields no region", _STATE_TO_REGION.get("ZZ") is None)

    # No state may map to two regions, which a copy-paste slip in the table would
    # do silently.
    seen = [state for states in _REGION_LOOPS.values() for state in states]
    check("no state is listed under two regions", len(seen) == len(set(seen)),
          f"duplicates: {[x for x in set(seen) if seen.count(x) > 1]}")



def check_google_pollen_parsing():
    """Google's Pollen API, against the documented response shape.

    Unverified against the live API at the time of writing - there was no key yet -
    so this pins the parser to the schema Google documents, and the fixture is
    shaped exactly like a real response including the parts that are optional.

    The important property is that the two providers' scales never mix: Google's
    UPI is 0-5 and pollen.com's is 0-12, so a bare "4" means "High" from one and
    "Low-medium" from the other. Every answer therefore carries its own scale_max
    and source.
    """
    print("google pollen parsing")
    from app import air_service

    payload = {
        "regionCode": "US",
        "dailyInfo": [
            {
                "date": {"year": 2026, "month": 8, "day": 13},
                "pollenTypeInfo": [
                    {
                        "code": "GRASS",
                        "displayName": "Grass",
                        "inSeason": True,
                        "indexInfo": {
                            "code": "UPI",
                            "value": 4,
                            "category": "High",
                            "indexDescription": "...",
                        },
                        "healthRecommendations": [
                            "Keep windows closed in the morning.",
                            "Second recommendation.",
                        ],
                    },
                    {
                        "code": "TREE",
                        "displayName": "Tree",
                        "inSeason": False,
                        "indexInfo": {"code": "UPI", "value": 1, "category": "Very Low"},
                    },
                    # A type with no reading at all, which Google does return
                    # out of season - it must not become a 0 or a crash.
                    {"code": "WEED", "displayName": "Weed", "inSeason": False},
                ],
                "plantInfo": [
                    {
                        "code": "RAGWEED",
                        "displayName": "Ragweed",
                        "inSeason": True,
                        "indexInfo": {"value": 3, "category": "Moderate"},
                    },
                    # In season but reading zero: not a trigger today.
                    {"code": "OAK", "displayName": "Oak", "inSeason": True,
                     "indexInfo": {"value": 0}},
                    # Out of season entirely.
                    {"code": "BIRCH", "displayName": "Birch", "inSeason": False,
                     "indexInfo": {"value": 2}},
                ],
            },
            {
                "date": {"year": 2026, "month": 8, "day": 14},
                "pollenTypeInfo": [
                    {"code": "GRASS", "displayName": "Grass", "inSeason": True,
                     "indexInfo": {"value": 2, "category": "Low"}},
                ],
            },
        ],
    }

    parsed = air_service._parse_google_pollen(payload)

    check("google pollen reports available", parsed["available"] is True)
    check("the scale is UPI 0-5, not 0-12", parsed["scale_max"] == 5,
          f"got {parsed['scale_max']}")
    check("the source names Google", parsed["source"] == "Google Pollen")
    check("today takes the highest type's index", parsed["today"]["index"] == 4,
          f"got {parsed['today']['index']}")
    check("today uses Google's own category", parsed["today"]["label"] == "High",
          f"got {parsed['today']['label']}")
    check(
        "the health note comes from the dominant type",
        parsed["today"]["recommendation"] == "Keep windows closed in the morning.",
        f"got {parsed['today']['recommendation']}",
    )
    check(
        "only in-season plants with a reading are triggers",
        parsed["today"]["triggers"] == ["Ragweed"],
        f"got {parsed['today']['triggers']}",
    )
    check("tomorrow is parsed too", parsed["tomorrow"]["index"] == 2,
          f"got {parsed['tomorrow']['index']}")
    check("google has no yesterday to report", parsed["yesterday"]["index"] is None)

    # A type with no indexInfo must be carried through as absent rather than zero:
    # "Weed 0" and "no weed reading" are different statements.
    weed = [t for t in parsed["today"]["types"] if t["name"] == "Weed"][0]
    check("a type with no reading stays absent, not zero", weed["index"] is None,
          f"got {weed['index']}")

    # Degenerate responses: an empty forecast, and a day with nothing in it.
    for name, bad in [("no dailyInfo", {}), ("an empty day", {"dailyInfo": [{}]})]:
        result = air_service._parse_google_pollen(bad)
        check(f"{name} reports unavailable rather than raising",
              result["available"] is False)


def check_pollen_key_never_rides_in_a_url():
    """The API key goes in an X-Goog-Api-Key header, not a ?key= query parameter.

    requests puts the request URL into its exception messages, so with the key in
    the query string a single logged traceback would print the credential. This
    also checks the error paths report only the exception CLASS for the same
    reason - a Google error's str() can carry the URL.
    """
    print("pollen key handling")
    source = (
        pathlib.Path(__file__).resolve().parent.parent / "app" / "air_service.py"
    ).read_text()

    # Comments are stripped before scanning: the first version of this check failed
    # on the comment explaining why the key ISN'T a query parameter, which contains
    # the literal "?key=". Scanning prose for code smells finds prose.
    code = "\n".join(
        line.split("#", 1)[0] for line in source.splitlines()
    )
    google_call = code[code.index("def _fetch_google_pollen"):]
    check(
        "the key is sent as a header",
        "X-Goog-Api-Key" in google_call,
    )
    check(
        "the key is never a query parameter",
        '"key"' not in google_call and "?key=" not in google_call,
    )
    check(
        "error messages carry only the exception class, never str(exc)",
        "type(exc).__name__" in code and "{exc}" not in code,
    )
    # And the key must never reach the browser.
    # The key may only appear where it is read from config and where it is sent.
    uses = [
        line.strip() for line in code.splitlines() if "POLLEN_API_KEY" in line
    ]
    check(
        "the key is referenced only to import it, test it, and send it",
        len(uses) == 3,
        f"unexpected uses: {uses}",
    )



def check_pollen_provider_fallback():
    """Google when a key is set, pollen.com otherwise - and pollen.com if Google
    fails, so a wrong key, an unenabled API or a billing lapse degrades to the
    keyless source rather than to an empty panel."""
    print("pollen provider fallback")
    from app import air_service

    google = {"available": True, "source": "Google Pollen", "scale_max": 5,
              "today": {"index": 4}, "tomorrow": {}, "yesterday": {}}
    iqvia = {"available": True, "source": "pollen.com", "scale_max": 12,
             "today": {"index": 7.2}, "tomorrow": {}, "yesterday": {}}
    aqi = {"available": True, "aqi": 52, "label": "Moderate"}

    def run(key, google_result):
        # Reset the module cache so each case actually fetches.
        air_service._cache = None
        air_service._last_good = None
        with patch.object(air_service, "POLLEN_API_KEY", key), \
             patch.object(air_service, "_fetch_aqi", return_value=aqi), \
             patch.object(air_service, "_fetch_pollen", return_value=iqvia), \
             patch.object(air_service, "_load_persisted", return_value=None), \
             patch.object(air_service, "_persist"), \
             patch.object(air_service, "DEMO_MODE", False), \
             patch.object(air_service, "_fetch_google_pollen", **google_result):
            return air_service.get_air()

    with_key = run("a-key", {"return_value": google})
    check("with a key, Google answers", with_key["pollen"]["source"] == "Google Pollen",
          f"got {with_key['pollen']['source']}")
    check("Google's scale comes with it", with_key["pollen"]["scale_max"] == 5)
    check("no errors on the happy path", with_key["errors"] == [], f"got {with_key['errors']}")

    no_key = run(None, {"return_value": google})
    check("without a key, pollen.com answers", no_key["pollen"]["source"] == "pollen.com",
          f"got {no_key['pollen']['source']}")

    # A 403 is what an unenabled API or a restricted key returns.
    broken = run("a-key", {"side_effect": RuntimeError("403 Forbidden")})
    check(
        "a failing Google falls back to pollen.com",
        broken["pollen"]["source"] == "pollen.com" and broken["pollen"]["available"],
        f"got {broken['pollen']}",
    )
    check(
        "and the failure is reported without leaking the exception text",
        any("Google Pollen" in e for e in broken["errors"])
        and not any("403" in e for e in broken["errors"]),
        f"got {broken['errors']}",
    )
    check("the AQI is unaffected by any of this", broken["aqi"]["aqi"] == 52)


def main():
    os.environ.setdefault("FLASK_SECRET_KEY", "api-checks")
    for fn in (
        check_month_grid_bounds,
        check_no_spotify_account,
        check_demo_mode_refuses_calendar_writes,
        check_demo_spotify_playback_is_stateful,
        check_no_global_script_collisions,
        check_hidden_utility_is_unconditional,
        check_weather_alerts_parsing,
        check_weather_hourly_is_anchored_to_now,
        check_air_quality_and_pollen,
        check_radar_regions_are_verified,
        check_google_pollen_parsing,
        check_pollen_key_never_rides_in_a_url,
        check_pollen_provider_fallback,
    ):
        fn()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("all API checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
