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

import requests
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
    shell = ["panel.js", "themes.js", "weather.js", "nav.js", "timers.js", "brightness.js"]
    pages = ["calendar.js", "spotify.js", "recipes.js", "today.js",
             "browser.js", "accounts.js", "groceries.js", "system.js",
             "sports.js"]
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



def check_shell_subscriptions_come_last():
    """A page script's onWeather()/onAlerts()/onNowPlaying() calls must appear after
    its top-level declarations.

    Those helpers invoke the listener IMMEDIATELY when data has already arrived, and
    pending network callbacks run between script tags - so a fast server means the
    listener executes while the page script is still being evaluated. Registered
    near the top, wxpage.js reached wxRenderThunder() before `const WX_CAPE_BANDS`
    was initialised and threw a temporal-dead-zone ReferenceError. It only appeared
    when the response was quick, which is the worst kind of bug to own.
    """
    print("shell subscription ordering")
    static = pathlib.Path(__file__).resolve().parent.parent / "static"
    subscribers = ("onWeather(", "onAlerts(", "onNowPlaying(")

    for path in sorted(static.glob("*.js")):
        # Shell scripts define these; only page scripts consume them.
        if path.name in {"weather.js", "nav.js", "alerts.js"}:
            continue
        lines = path.read_text().splitlines()

        calls = [i for i, line in enumerate(lines) if line.startswith(subscribers)]
        if not calls:
            continue

        last_decl = max(
            (i for i, line in enumerate(lines)
             if line.startswith("const ") or line.startswith("let ")),
            default=-1,
        )
        check(
            f"{path.name} subscribes after its declarations",
            min(calls) > last_decl,
            f"subscribes at line {min(calls) + 1}, last top-level declaration at "
            f"line {last_decl + 1}",
        )



def check_recipes_fetch_survives_the_visibility_migration():
    """The recipe fetch has to work at every point in Daisy's Kitchen's migration to
    per-recipe visibility, because that migration is a sequence and this wall is a
    separate deploy.

    Before the composite index exists the filtered query is a 400; before the migration
    runs it legitimately matches nothing; after the rules tighten the unfiltered list is
    refused. The original plan was a documented deploy order, which is one accidental push
    away from a blank Recipes page.
    """
    print("recipes fetch across the migration")
    from unittest.mock import patch
    from app import recipes_service

    doc = {
        "name": "projects/p/databases/(default)/documents/recipes/abc",
        "fields": {"title": {"stringValue": "Lemon Orzo"}},
    }

    # 1. Index missing: the filtered query fails, the unfiltered list answers.
    with patch.object(recipes_service, "_fetch_public",
                      side_effect=requests.exceptions.HTTPError("400")), \
         patch.object(recipes_service, "_fetch_all_unfiltered", return_value=[doc]) as fallback:
        result = recipes_service._fetch()
    check("a missing index falls back to the unfiltered list",
          len(result["recipes"]) == 1 and fallback.called)

    # 2. Index exists but nothing is migrated yet: no match, so fall back rather than
    #    render an empty cookbook.
    with patch.object(recipes_service, "_fetch_public", return_value=[]), \
         patch.object(recipes_service, "_fetch_all_unfiltered", return_value=[doc]) as fallback:
        result = recipes_service._fetch()
    check("an empty filtered result falls back rather than showing nothing",
          len(result["recipes"]) == 1 and fallback.called)

    # 3. Fully migrated: the filtered query answers and the fallback is never called,
    #    which matters because after the rules tighten it would be refused.
    with patch.object(recipes_service, "_fetch_public", return_value=[doc]), \
         patch.object(recipes_service, "_fetch_all_unfiltered") as fallback:
        result = recipes_service._fetch()
    check("a successful filtered query does not touch the unfiltered list",
          len(result["recipes"]) == 1 and not fallback.called)


def check_groceries_degrade_without_a_credential():
    """The grocery list is the one feature here that needs a credential the wall may
    not have yet, so "not set up" has to be a rendered state rather than a failure.

    Two separate things are checked because they fail differently: the read must
    answer 200 with the explanation in the payload (the Today page carries this
    block and must not lose the rest of the screen over it), while a write must
    answer JSON - an unhandled RuntimeError would reach Flask's HTML 500 page and
    the client would report "Unexpected token '<'" instead of the real reason.
    """
    print("groceries without a credential")
    import server
    from app import groceries_service

    client = server.app.test_client()
    missing = pathlib.Path("/nonexistent/service_account.json")

    with patch.object(groceries_service, "DEMO_MODE", False), \
         patch.object(groceries_service, "GROCERY_SA_FILE", missing):
        resp = client.get("/api/groceries")
        payload = resp.get_json()
        check(
            "the read answers 200 with an explanation, not an error",
            resp.status_code == 200
            and payload["available"] is False
            and payload["configured"] is False
            and payload["items"] == []
            and payload["errors"],
            f"got {resp.status_code} {payload}",
        )

        for path in ("/api/groceries/add", "/api/groceries/clear-done"):
            resp = client.post(path, json={"text": "milk"})
            check(
                f"{path} explains itself as JSON",
                resp.status_code == 503 and "error" in (resp.get_json() or {}),
                f"got {resp.status_code} {resp.content_type}",
            )


def check_grocery_ordering_and_grouping():
    """Aisle order and the rule that ticked items sink rather than vanish.

    Both are contracts with the phone app, not preferences: R3.6 says the list is
    grouped in a consistent store order, and GroceryService.watchItems sorts
    exactly this way. A wall that walked the shop backwards would be useless next
    to the same list on a phone.
    """
    print("grocery ordering and grouping")
    from app import groceries_service

    items = sorted(
        [
            {"id": "a", "display": "orzo", "aisle": "pantry", "done": False},
            {"id": "b", "display": "milk", "aisle": "dairy", "done": False},
            {"id": "c", "display": "apples", "aisle": "produce", "done": False},
            {"id": "d", "display": "avocado", "aisle": "produce", "done": False},
            # Ticked, and in the FIRST aisle - so if done-ness were not the primary
            # key this would lead the list.
            {"id": "e", "display": "bananas", "aisle": "produce", "done": True},
        ],
        key=groceries_service._sort_key,
    )
    check(
        "unticked items lead, then store order, then alphabetical",
        [item["id"] for item in items] == ["c", "d", "b", "a", "e"],
        f"got {[item['id'] for item in items]}",
    )

    groups = groceries_service._group(items)
    check(
        "groups follow the app's aisle order",
        [group["aisle"] for group in groups] == ["produce", "dairy", "pantry"],
        f"got {[g['aisle'] for g in groups]}",
    )
    check(
        "a ticked item is not in any aisle group",
        all(item["id"] != "e" for group in groups for item in group["items"]),
    )

    # An aisle the app adds later must land in Other rather than disappearing, and
    # must not raise on the sort's aisleOrder.indexOf.
    odd = groceries_service._shape(
        {"name": "x/y/z/unknown", "fields": {"aisle": {"stringValue": "petfood"},
                                             "display": {"stringValue": "kibble"}}}
    )
    check("an unknown aisle falls into Other", odd["aisle"] == "other",
          f"got {odd['aisle']}")
    check("...and can still be sorted", isinstance(groceries_service._sort_key(odd), tuple))


def check_grocery_parser_matches_the_dart_original():
    """The wall's canonical-name/aisle port, pinned against Daisy's Kitchen's Dart.

    This exists because of a specific failure mode, not for tidiness. The canonical
    name is the key GroceryService.addRecipe merges on: if Python decides "tomatoes"
    is `tomatoes` where Dart says `tomato`, adding a recipe on a phone puts a SECOND
    tomato row on the list instead of merging into the wall's. So the keyword table
    and the never-singularise set have to stay identical, and the only way to know
    they have is to read the Dart.

    Skipped when the recipes repo isn't checked out beside this one - the wall has
    to build on the Pi, where it isn't.
    """
    print("grocery parser vs the Dart original")
    from app import groceries_service

    dart = (
        pathlib.Path(__file__).resolve().parent.parent.parent.parent
        / "recipes" / "lib" / "services" / "ingredient_parser.dart"
    )
    if not dart.exists():
        print(f"  skip  the recipes repo is not checked out at {dart.parent.parent.parent}")
        return

    source = dart.read_text()
    import re as _re

    # aisleOrder: a plain list of quoted strings.
    order_block = source.split("aisleOrder = [", 1)[1].split("];", 1)[0]
    dart_order = _re.findall(r"'([a-z]+)'", order_block)
    check(
        "the aisle order matches, in order",
        dart_order == groceries_service.AISLE_ORDER,
        f"dart {dart_order} vs python {groceries_service.AISLE_ORDER}",
    )

    never_block = source.split("_neverSingularise = {", 1)[1].split("};", 1)[0]
    check(
        "the never-singularise set matches",
        set(_re.findall(r"'([^']+)'", never_block)) == groceries_service.NEVER_SINGULARISE,
        f"dart-only {set(_re.findall(r'{chr(39)}([^{chr(39)}]+){chr(39)}', never_block)) - groceries_service.NEVER_SINGULARISE}",
    )

    # Each aisle's keyword list, which is where a silent divergence would actually live.
    keyword_block = source.split("_aisleKeywords = {", 1)[1]
    mismatches = []
    for aisle, expected in groceries_service.AISLE_KEYWORDS.items():
        segment = keyword_block.split(f"'{aisle}': [", 1)
        if len(segment) < 2:
            mismatches.append(f"{aisle}: absent from the Dart")
            continue
        dart_words = _re.findall(r"'([^']+)'", segment[1].split("]", 1)[0])
        if dart_words != expected:
            only_dart = [w for w in dart_words if w not in expected]
            only_py = [w for w in expected if w not in dart_words]
            mismatches.append(f"{aisle}: dart-only {only_dart}, python-only {only_py}")
    check("every aisle's keywords match the Dart", not mismatches, "; ".join(mismatches))

    # And the behaviour the tables are for. "ground cinnamon" is the case the Dart
    # carries a comment about: a bare 'ground' keyword made it a meat, because the
    # first matching aisle wins.
    for text, canonical, aisle in [
        ("2 lemons", "lemon", "produce"),
        ("tomatoes, finely chopped", "tomato", "produce"),
        ("ground cinnamon", "ground cinnamon", "spices"),
        ("molasses", "molasses", "pantry"),
        ("berries", "berry", "produce"),
        ("olive oil (extra virgin)", "olive oil", "pantry"),
    ]:
        _, name = groceries_service._split_amount(text)
        got = groceries_service._canonical_name(name)
        check(f"{text!r} canonicalises to {canonical!r}", got == canonical, f"got {got!r}")
        check(f"...and lands in {aisle}", groceries_service._aisle_for(got) == aisle,
              f"got {groceries_service._aisle_for(got)}")

    # A quantity typed by a person, and the trap in reading one: "2 lemons" must not
    # read "lemons" as a unit and lose the name.
    check("a bare count keeps its name", groceries_service._split_amount("2 lemons") == ("2", "lemons"),
          f"got {groceries_service._split_amount('2 lemons')}")
    check("a real unit is separated", groceries_service._split_amount("1 1/2 cups flour") == ("1 1/2 cups", "flour"),
          f"got {groceries_service._split_amount('1 1/2 cups flour')}")


def check_demo_groceries_writes_are_stateful():
    """The page is only testable if ticking an item actually ticks it - the same
    reason demo_spotify accepts playback commands."""
    print("demo grocery writes")
    from app import demo_groceries

    before = demo_groceries.get_groceries()["open_count"]
    # Something the fixture does not already contain, on purpose: with a duplicate
    # name the lookup below can match the FIXTURE's row and assert against its
    # quantity instead of the added one - a check that passes whatever add does.
    demo_groceries.add_item("3 zucchini")
    added = demo_groceries.get_groceries()
    check("adding an item adds one", added["open_count"] == before + 1,
          f"{before} -> {added['open_count']}")

    new = [i for i in added["items"] if i["display"] == "zucchini"]
    check("exactly one row was added", len(new) == 1, f"got {len(new)}")
    check("...parsed into an aisle with its quantity",
          new and new[0]["aisle"] == "produce" and new[0]["quantity_label"] == "3",
          f"got {new}")

    demo_groceries.set_done(new[0]["id"], True)
    ticked = demo_groceries.get_groceries()
    check("ticking moves it out of the aisle groups",
          all(i["id"] != new[0]["id"] for g in ticked["groups"] for i in g["items"]))

    # Still present, and after everything unticked. NOT asserted as the last item:
    # done items stay sorted by aisle among themselves, so a ticked produce item
    # legitimately precedes a ticked dairy one.
    ids = [i["id"] for i in ticked["items"]]
    open_ids = [i["id"] for i in ticked["items"] if not i["done"]]
    check("...but it is still on the list, below everything unticked",
          new[0]["id"] in ids
          and ids.index(new[0]["id"]) > max(ids.index(i) for i in open_ids),
          f"order is {[i['display'] for i in ticked['items']]}")

    cleared = demo_groceries.clear_done()
    check("clearing done removes them", cleared >= 1 and
          demo_groceries.get_groceries()["done_count"] == 0, f"cleared {cleared}")


def check_timed_events_send_rfc3339():
    """Google rejected every *timed* event with a bare 400 "Bad Request" because
    the dateTime came straight from an <input type="datetime-local">, whose value
    has no seconds field - and RFC3339 makes seconds mandatory. All-day events use
    the date field and were fine, which is why this read as intermittent.

    Verified against the real API at the time: "2026-12-30T09:00" is refused and
    "2026-12-30T09:00:00" is accepted, with everything else in the body identical.
    """
    print("timed events are sent as RFC3339")
    from app.calendar_service import _rfc3339_local

    check(
        "datetime-local minutes gain a seconds field",
        _rfc3339_local("2026-12-30T09:00") == "2026-12-30T09:00:00",
        _rfc3339_local("2026-12-30T09:00"),
    )
    check(
        "a value that already has seconds is unchanged",
        _rfc3339_local("2026-12-30T09:00:30") == "2026-12-30T09:00:30",
    )
    # No offset: it rides alongside an explicit timeZone, and adding one here
    # would pin the event to whatever zone the *server* thinks it is in.
    check(
        "no UTC offset is invented",
        "+" not in _rfc3339_local("2026-12-30T09:00")
        and not _rfc3339_local("2026-12-30T09:00").endswith("Z"),
    )


def check_prefs_setters_do_not_clobber_each_other():
    """set_calendar_excluded() used to call save_prefs() with a freshly built
    one-key dict, replacing the whole file. That was harmless while calendar
    exclusions were the only setting in it, and silently destructive the moment
    the System page started storing hidden sections in the same file: hiding
    Groceries, then unticking any calendar, brought Groceries back."""
    print("prefs setters merge rather than replace")
    import json
    import tempfile
    from unittest.mock import patch

    from app import preferences

    with tempfile.TemporaryDirectory() as tmp:
        prefs_file = pathlib.Path(tmp) / "calendar_prefs.json"
        with patch.object(preferences, "PREFS_FILE", prefs_file):
            preferences.set_section_hidden("groceries", True)
            preferences.set_calendar_excluded("work@example.com", True)

            stored = json.loads(prefs_file.read_text())
            check(
                "a calendar toggle keeps hidden_sections",
                stored.get("hidden_sections") == ["groceries"],
                repr(stored),
            )
            check(
                "and the exclusion is stored too",
                stored.get("excluded_calendar_ids") == ["work@example.com"],
                repr(stored),
            )

            # And the other direction.
            preferences.set_section_hidden("weather", True)
            stored = json.loads(prefs_file.read_text())
            check(
                "hiding a section keeps excluded_calendar_ids",
                stored.get("excluded_calendar_ids") == ["work@example.com"],
                repr(stored),
            )
            check(
                "an unknown section is refused rather than stored",
                _raises(ValueError, preferences.set_section_hidden, "nonsense", True),
            )


def _raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type:
        return True
    except Exception:
        return False
    return False


def check_touch_calibration_maths():
    """The calibration fit has to invert the panel's error, and - the part that is
    easy to get wrong - it has to *compose* with the matrix already in force.

    Samples are collected through the existing matrix, so treating the fit as an
    absolute replacement applies the old correction twice and each pass overshoots
    further instead of converging. The idempotence check below is what pins that.
    """
    print("touch calibration maths")
    from app import system_service as sysx

    targets = [(0.12, 0.14), (0.88, 0.14), (0.50, 0.50), (0.12, 0.86), (0.88, 0.86)]

    # A panel reading 4% over-scaled in x, 2% under in y, and offset a little.
    def distort(tx, ty):
        return (tx * 1.04 + 0.03, ty * 0.98 + 0.02)

    samples = [{"target": [tx, ty], "observed": list(distort(tx, ty))} for tx, ty in targets]
    matrix = sysx._compose(sysx._solve_affine(samples), sysx.IDENTITY)
    sysx._sanity_check(matrix)

    a, b, c, d, e, f = matrix
    worst = max(
        max(abs(a * ox + b * oy + c - tx), abs(d * ox + e * oy + f - ty))
        for (tx, ty), s in zip(targets, samples)
        for ox, oy in [s["observed"]]
    )
    check("the fit maps taps back onto their targets", worst < 1e-9, f"worst {worst}")

    already_right = [{"target": [tx, ty], "observed": [tx, ty]} for tx, ty in targets]
    again = sysx._compose(sysx._solve_affine(already_right), matrix)
    check(
        "re-calibrating a good panel is a no-op (composition, not replacement)",
        all(abs(x - y) < 1e-9 for x, y in zip(matrix, again)),
        f"{matrix} -> {again}",
    )

    collinear = [{"target": [v, v], "observed": [v, v]} for v in (0.1, 0.5, 0.9)]
    check(
        "collinear taps are refused, not flattened onto one axis",
        _raises(sysx.SystemActionFailed, sysx._solve_affine, collinear),
    )
    check(
        "fewer than three points is refused",
        _raises(sysx.SystemActionFailed, sysx._solve_affine, collinear[:2]),
    )
    # The auto-revert is the real safety net, but rejecting obvious nonsense saves
    # whoever is standing there 45 seconds of an unusable touchscreen.
    for label, bad in [
        ("a 3x stretch", (3.0, 0.0, 0.0, 0.0, 1.0, 0.0)),
        ("an off-screen shift", (1.0, 0.0, 0.9, 0.0, 1.0, 0.0)),
        ("a heavy skew", (1.0, 0.8, 0.0, 0.0, 1.0, 0.0)),
    ]:
        check(
            f"{label} is rejected",
            _raises(sysx.SystemActionFailed, sysx._sanity_check, bad),
        )


def check_rc_xml_render_is_well_formed():
    """~/.config/labwc/rc.xml is generated, and a malformed one costs the
    touchscreen its output mapping. Two traps, both hit for real while building
    this: XML comments cannot contain a doubled hyphen (the template quotes
    Chromium switches), and str.format substitutes placeholders *inside* comments,
    which pasted a calibration matrix into the middle of the header block."""
    print("labwc rc.xml renders well-formed")
    import xml.etree.ElementTree as ET

    from app import system_service as sysx

    NS = {"o": "http://openbox.org/3.4/rc"}
    device = "Weida Hi-Tech                CoolTouchR System            (USB 3-1.3)"

    calibrated = sysx.render_rc_xml((0.98, 0.0, 0.01, 0.0, 1.01, -0.005), device, "HDMI-A-1")
    root = ET.fromstring(calibrated)
    found = root.findall(".//o:calibrationMatrix", NS)
    check("exactly one calibrationMatrix element", len(found) == 1, f"{len(found)} found")

    touch = root.find(".//o:touch", NS)
    # The interior whitespace in the device name is significant - labwc matches it
    # literally, and a normalised space silently stops the mapping applying.
    check(
        "the device name survives verbatim, whitespace and all",
        touch is not None and touch.get("deviceName") == device,
        repr(touch.get("deviceName")) if touch is not None else "no <touch>",
    )

    uncalibrated = ET.fromstring(sysx.render_rc_xml(None, device, "HDMI-A-1"))
    check(
        "an uncalibrated wall gets no matrix at all",
        not uncalibrated.findall(".//o:calibrationMatrix", NS),
    )
    check(
        "identity is written as no matrix rather than as 1 0 0 0 1 0",
        not ET.fromstring(
            sysx.render_rc_xml(sysx.IDENTITY, device, "HDMI-A-1")
        ).findall(".//o:calibrationMatrix", NS),
    )

    rule = ET.fromstring(calibrated).find(".//o:windowRule", NS)
    # Chromium's app_id is "chrome-127.0.0.1__-Default" in --app mode and plain
    # "chromium" under --kiosk; a chrome-* rule matching nothing was a real dead end.
    check(
        "the kiosk window rule targets Chromium's app-mode app_id",
        rule is not None and rule.get("identifier") == "chrome-*",
        rule.get("identifier") if rule is not None else "no rule",
    )


def check_sports_degrades_instead_of_failing():
    """ESPN's site API is undocumented and unversioned, so it will fail eventually.

    When it does, /api/sports must answer 200 with an explanation - never a 503. The
    Today page reads it on a wall that is on all day, so an error status would be a
    failed request every few minutes forever, and the layout tests treat a console
    error on any page as a regression. This is the same contract groceries follows,
    and the same lesson /api/system/display taught the hard way.
    """
    print("sports degrades instead of failing")
    from unittest.mock import patch

    import requests

    from app import sports_service
    import server

    client = server.app.test_client()

    with (
        patch.object(sports_service, "DEMO_MODE", False),
        patch.object(sports_service, "_cache", {}),
        patch.object(
            sports_service.requests,
            "get",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ),
    ):
        for path in ("/api/sports/scoreboard/mlb", "/api/sports/following"):
            resp = client.get(path)
            body = resp.get_json()
            check(f"{path} answers 200 when ESPN is down", resp.status_code == 200,
                  f"got {resp.status_code}")
            check(f"{path} says it is unavailable", body.get("available") is False)
            check(f"{path} explains why", bool(body.get("errors")), repr(body)[:120])

    # An unknown league is a bad request from the page, not an upstream failure - but
    # it still must not throw.
    resp = client.get("/api/sports/scoreboard/quidditch")
    check("an unknown league degrades too", resp.status_code == 200
          and resp.get_json().get("available") is False)


def check_sports_normalises_both_status_shapes():
    """ESPN puts a game's status in two different places.

    /scoreboard carries it alongside the event; a team's `nextEvent` nests it under
    the competition. Reading only the event level left every Today row with a blank
    status - "ATL @ MIN" with no start time beside it - which is exactly what shipped
    to the wall before this was caught.
    """
    print("sports status normalisation")
    from app.sports_service import _game

    side = lambda abbr, home: {  # noqa: E731
        "team": {"abbreviation": abbr, "shortDisplayName": abbr, "color": "13274F"},
        "homeAway": "home" if home else "away",
        "score": "3",
    }
    status = {"type": {"state": "pre", "shortDetail": "8/18 - 7:40 PM EDT"}}
    competitors = [side("MIN", True), side("ATL", False)]

    scoreboard_shape = {
        "id": "1", "shortName": "ATL @ MIN", "date": "2026-08-18T23:40Z",
        "status": status, "competitions": [{"competitors": competitors}],
    }
    next_event_shape = {
        "id": "1", "shortName": "ATL @ MIN", "date": "2026-08-18T23:40Z",
        "competitions": [{"competitors": competitors, "status": status}],
    }

    for label, event in (("scoreboard", scoreboard_shape), ("nextEvent", next_event_shape)):
        game = _game(event)
        check(f"{label}: status is found", game["detail"] == "8/18 - 7:40 PM EDT", repr(game["detail"]))
        check(f"{label}: state is read", game["state"] == "pre" and not game["live"])
        # ESPN lists home first for US sports and away first for soccer; the page
        # renders "away @ home" without knowing which sport it is looking at.
        check(f"{label}: home and away are sorted out", game["away"]["abbr"] == "ATL"
              and game["home"]["abbr"] == "MIN")


def check_display_settings_validation():
    """Brightness and sleep settings, and the floor under brightness.

    The floor is not cosmetic. This panel has no software backlight - no DDC/CI, no
    /sys/class/backlight - so brightness darkens the image while the lamp stays lit.
    Below about 0.2 the picture is gone but the wall still glows, so lower values buy
    nothing and just look broken. Clamping in the setter is what stops a stray POST
    (or a slider someone dragged to 0) from getting there.
    """
    print("display settings")
    import tempfile
    from unittest.mock import patch

    from app import preferences

    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(preferences, "PREFS_FILE", pathlib.Path(tmp) / "prefs.json"):
            defaults = preferences.display_settings()
            check("full brightness by default", defaults["brightness"] == 1.0)
            check("sleep on by default", defaults["sleep_enabled"] is True)
            check("night-gated by default", defaults["sleep_at_night_only"] is True,
                  "a wall that hides the calendar at 2pm is not a calendar")

            check(
                "brightness is clamped to the floor, not honoured at 0",
                preferences.set_display_settings(brightness=0.0)["brightness"]
                == preferences.MIN_BRIGHTNESS,
            )
            check(
                "and clamped at the top",
                preferences.set_display_settings(brightness=4.0)["brightness"] == 1.0,
            )
            check(
                "a sane value is kept",
                preferences.set_display_settings(brightness=0.45)["brightness"] == 0.45,
            )
            check(
                "nonsense is refused rather than stored",
                _raises(ValueError, preferences.set_display_settings, brightness="bright"),
            )

            # The screen-off delay drives swayidle's command line, so only known
            # values are allowed through.
            check(
                "an unlisted screen-off delay is refused",
                _raises(ValueError, preferences.set_display_settings, display_off_minutes=7),
            )
            check(
                "0 means never, and is allowed",
                preferences.set_display_settings(display_off_minutes=0)["display_off_minutes"] == 0,
            )
            # Two minutes is the floor: less and the wall blanks while someone reads it.
            check(
                "sleep delay has a floor",
                preferences.set_display_settings(sleep_after_minutes=0)["sleep_after_minutes"] == 2,
            )
            check(
                "unknown keys are ignored rather than stored",
                "nonsense" not in preferences.load_prefs(),
            )

            # And it must not clobber neighbours in the same file.
            preferences.set_section_hidden("groceries", True)
            preferences.set_display_settings(brightness=0.6)
            check(
                "saving brightness keeps hidden_sections",
                preferences.hidden_sections() == {"groceries"},
            )


def check_dimmers_compose_without_going_black():
    """The three dimmers in nav.js multiply, and the product has to be clamped.

    brightness x night x sleep at their minimums is about 0.008 - a black screen. A
    black screen cannot be tapped back to life, because you cannot see what to tap,
    and the only recovery would be SSH. This mirrors nav.js's arithmetic so the
    clamp cannot be dropped without a failure here.
    """
    print("dimmer composition")
    import re

    nav = (pathlib.Path(__file__).resolve().parent.parent / "static" / "nav.js").read_text()

    def constant(name):
        match = re.search(rf"^const {name} = ([0-9.]+);", nav, re.MULTILINE)
        return float(match.group(1)) if match else None

    night = constant("NIGHT_FACTOR")
    sleep = constant("SLEEP_FACTOR")
    max_dim = constant("MAX_DIM_OPACITY")
    floor = 0.2  # preferences.MIN_BRIGHTNESS

    check("nav.js still defines all three constants", None not in (night, sleep, max_dim),
          f"night={night} sleep={sleep} max={max_dim}")
    check("the clamp leaves something visible", max_dim is not None and max_dim < 1.0,
          f"MAX_DIM_OPACITY={max_dim}")

    worst = floor * night * sleep
    clamped = min(max_dim, max(0.0, 1 - worst))
    check(
        "the worst case (min brightness, night, asleep) is not fully black",
        clamped <= max_dim and 1 - clamped > 0.0,
        f"unclamped opacity would be {1 - worst:.4f}, clamped to {clamped}",
    )

    # The tap that wakes the wall must be gated on the resting *states*, not on the
    # overlay being on screen - the overlay is now visible at any brightness below
    # 100%, and swallowing the first tap at a brightness someone chose would make the
    # wall feel broken at every setting but full.
    check(
        "the wake handler keys off asleep/night, not overlay visibility",
        "if (asleep || nightDimActive())" in nav,
    )
    check(
        "and it is still registered in the capture phase",
        re.search(r'addEventListener\(\s*"pointerdown",[\s\S]{0,400}?true\s*\)', nav) is not None,
    )


def check_manual_screen_off_can_always_be_woken():
    """Turning the panel off by hand must never strand the wall dark.

    Two measured facts make this delicate. labwc does NOT wake a powered-off output on
    input, and swayidle only fires `resume` for an idle period *it* started. So calling
    `wlopm --off` directly - the obvious implementation - produces a black screen that
    no amount of tapping recovers, and only SSH can undo.

    The implementation therefore restarts swayidle with a 2-second timeout and lets
    *it* blank the panel, which arms it to un-blank on the next touch. What this pins:
    that the off path never blanks directly, that a resume hook is attached to put the
    configured timeout back, and that the state expires on its own if that hook is
    lost.
    """
    print("manual screen-off is always wakeable")
    from unittest.mock import patch

    from app import system_service as sysx

    spawned = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            spawned.append(args)

    with (
        patch.object(sysx.subprocess, "Popen", FakePopen),
        patch.object(sysx, "_run", return_value=_ok()),
        patch.object(sysx.threading, "Timer") as timer,
    ):
        result = sysx.screen_off_now()

    check("it reports the grace period", result["off_in_seconds"] == sysx.MANUAL_OFF_DELAY_SECONDS)
    check("exactly one swayidle is started", len(spawned) == 1, repr(spawned))

    argv = spawned[0]
    check("it is swayidle, not a direct wlopm --off", argv[0] == "swayidle", repr(argv[0]))
    joined = " ".join(argv)
    check(
        "swayidle is the thing that blanks the panel, so it can un-blank it",
        f"wlopm --off {sysx.OUTPUT_NAME}" in joined,
    )
    check(
        "a resume action turns the output back on",
        "resume" in argv and f"wlopm --on {sysx.OUTPUT_NAME}" in joined,
    )
    check(
        "the timeout is the short manual grace period",
        str(sysx.MANUAL_OFF_DELAY_SECONDS) in argv,
        repr(argv),
    )
    # Without this the 2-second timeout would survive being woken, and the wall would
    # blank again two seconds after every idle moment.
    check(
        "resume calls back to restore the configured timeout",
        sysx.RESUME_HOOK_URL in joined,
        joined,
    )
    check("and a fallback timer is armed in case that hook is lost", timer.called)

    # The scheduled fallback must be the restore, not something else.
    check(
        "the fallback restores from prefs",
        timer.call_args is not None
        and timer.call_args[0][1] is sysx.sync_display_off_from_prefs,
        repr(timer.call_args),
    )

    # And the normal path must NOT attach a resume hook - only the manual state needs
    # restoring, and a hook on the 40-minute timeout would fire a request on every wake.
    spawned.clear()
    with (
        patch.object(sysx.subprocess, "Popen", FakePopen),
        patch.object(sysx, "_run", return_value=_ok()),
    ):
        sysx.apply_display_off(40)
    check(
        "the scheduled timeout carries no resume hook",
        spawned and sysx.RESUME_HOOK_URL not in " ".join(spawned[0]),
        repr(spawned),
    )
    check("...and uses the configured delay in seconds", spawned and "2400" in spawned[0])


def check_bluetooth_success_strings():
    """bluetoothctl exits 0 whether an action worked or not, so success is decided
    by matching its prose - and it uses different words per verb.

    "remove" is the trap: it answers "Device has been removed", which contains
    neither "successful" nor "succeeded". A shared check on those two made every
    successful Forget report a failure while the device disappeared anyway. Strings
    below are transcribed from BlueZ 5.82 on the wall, not guessed.
    """
    print("bluetooth success strings")
    from unittest.mock import patch

    from app import bluetooth_service as bt

    real_replies = {
        "pair": "Attempting to pair with 00:11:22:33:44:55\nPairing successful",
        "connect": "Attempting to connect to 00:11:22:33:44:55\nConnection successful",
        "disconnect": "Attempting to disconnect\nSuccessful disconnected",
        "trust": "Changing 00:11:22:33:44:55 trust succeeded",
        "remove": "[DEL] Device 00:11:22:33:44:55 Speaker\nDevice has been removed",
    }
    for verb, reply in real_replies.items():
        with patch.object(bt, "_run", return_value=reply):
            result = bt._action(verb, "00:11:22:33:44:55")
        check(f"{verb} is read as success", result["ok"], repr(result))

    # The failure shape is the same one line for every verb.
    with patch.object(bt, "_run", return_value="Device 00:11:22:33:44:55 not available"):
        for verb in real_replies:
            result = bt._action(verb, "00:11:22:33:44:55")
            check(
                f"{verb} failure is reported, with the reason",
                not result["ok"] and "not available" in result["error"],
                repr(result),
            )


def check_bluetooth_autoconnect():
    """BlueZ won't reconnect a speaker that was switched off and back on - trusting
    only makes the wall *accept* a connection, and the [Policy] plugin only retries
    after an unexpected disconnect. So the wall reaches out on a timer.

    The two behaviours worth pinning are the ones that would be annoying rather than
    merely broken: a deliberate Disconnect must not be undone a minute later, and a
    speaker that is simply off must not be paged once a minute forever.
    """
    print("bluetooth auto-reconnect")
    import tempfile
    from unittest.mock import patch

    from app import bluetooth_service as bt
    from app import preferences

    # paired=False on purpose: this is the real shape of a disconnected speaker that
    # pairs without bonding, which is what broke the first version of the loop.
    paired_off = {
        "address": "AA:BB:CC:DD:EE:FF",
        "name": "Speaker",
        "known": True,
        "paired": False,
        "bonded": False,
        "trusted": True,
        "connected": False,
    }

    def run_pass(connect_ok, extra_devices=()):
        calls = []

        def fake_action(verb, mac, timeout=30):
            calls.append((verb, mac))
            return {"ok": connect_ok} if connect_ok else {"ok": False, "error": "not available"}

        with (
            patch.object(bt, "adapter", return_value={"powered": True}),
            patch.object(bt, "devices", return_value=[paired_off, *extra_devices]),
            patch.object(bt, "_action", side_effect=fake_action),
        ):
            attempted = bt.reconnect_once()
        return calls, attempted

    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(preferences, "PREFS_FILE", pathlib.Path(tmp) / "prefs.json"):
            bt._reconnect_state.clear()

            check("enabled by default", bt.autoconnect_enabled())

            calls, attempted = run_pass(connect_ok=True)
            check("a trusted, disconnected device is connected even though paired=False", calls == [("connect", paired_off["address"])], repr(calls))
            check("and the attempt is reported", attempted and attempted[0]["ok"])

            # A device that is off: first pass tries, the next must not.
            bt._reconnect_state.clear()
            calls1, _ = run_pass(connect_ok=False)
            calls2, _ = run_pass(connect_ok=False)
            check("a failing device is tried once...", len(calls1) == 1, repr(calls1))
            check("...then backed off rather than paged every cycle", calls2 == [], repr(calls2))

            # A person tapping "reconnect" outranks the backoff. Without force the
            # manual path answered "attempted nothing" whenever the background loop
            # had already failed against a switched-off speaker - indistinguishable
            # from a broken button.
            forced = []

            def fake_forced(verb, mac, timeout=30):
                forced.append((verb, mac))
                return {"ok": False, "error": "not available"}

            with (
                patch.object(bt, "adapter", return_value={"powered": True}),
                patch.object(bt, "devices", return_value=[paired_off]),
                patch.object(bt, "_action", side_effect=fake_forced),
            ):
                bt.reconnect_once(force=True)
            check("a forced pass ignores the backoff", len(forced) == 1, repr(forced))

            # A deliberate Disconnect has to stick.
            bt._reconnect_state.clear()
            with patch.object(bt, "_action", return_value={"ok": True}):
                bt.disconnect(paired_off["address"])
            check(
                "Disconnect records an opt-out",
                paired_off["address"] in bt._optouts(),
                repr(bt._optouts()),
            )
            calls3, _ = run_pass(connect_ok=True)
            check("...and auto-reconnect leaves it alone", calls3 == [], repr(calls3))

            # Connecting by hand clears it again.
            with patch.object(bt, "_action", return_value={"ok": True}):
                bt.connect(paired_off["address"])
            check("Connect clears the opt-out", paired_off["address"] not in bt._optouts())
            bt._reconnect_state.clear()
            calls4, _ = run_pass(connect_ok=True)
            check("...so it is looked after again", len(calls4) == 1, repr(calls4))

            # Unpaired or untrusted devices are never touched: connecting to a
            # neighbour's phone that happens to be in range would be worse than
            # doing nothing.
            bt._reconnect_state.clear()
            strangers = [
                {"address": "11:11:11:11:11:11", "name": "Phone", "known": False, "paired": False, "trusted": False, "connected": False},
                {"address": "22:22:22:22:22:22", "name": "Untrusted", "known": False, "paired": True, "trusted": False, "connected": False},
                {"address": "33:33:33:33:33:33", "name": "Already on", "known": True, "paired": True, "trusted": True, "connected": True},
            ]
            with (
                patch.object(bt, "adapter", return_value={"powered": True}),
                patch.object(bt, "devices", return_value=strangers),
                patch.object(bt, "_action", side_effect=AssertionError("must not connect")),
            ):
                check("untrusted and already-connected devices are skipped", bt.reconnect_once() == [])

            # And the whole thing is off when switched off.
            bt.set_autoconnect(False)
            bt._reconnect_state.clear()
            with patch.object(bt, "_action", side_effect=AssertionError("must not connect")):
                check("switching it off stops all attempts", bt.reconnect_once() == [])
            bt.set_autoconnect(True)

            # A wall with no adapter must not take the loop down with it.
            with patch.object(bt, "adapter", side_effect=bt.BluetoothUnavailable("no adapter")):
                check("no adapter is survivable", bt.reconnect_once() == [])


def check_unconfirmed_calibration_cannot_survive_a_restart():
    """A trial calibration lives in a threading.Timer, so a restart during the 45
    seconds would take the revert with it and leave an unconfirmed matrix in
    rc.xml forever - while prefs still said "not calibrated".

    That mismatch is the dangerous part, not the stray file: the next calibration
    composes against the matrix prefs report, so it would compound the stray one.
    sync_rc_from_prefs() at startup makes prefs authoritative again.
    """
    print("an unconfirmed calibration cannot survive a restart")
    import tempfile
    from unittest.mock import patch

    from app import preferences
    from app import system_service as sysx

    with tempfile.TemporaryDirectory() as tmp:
        rc_path = pathlib.Path(tmp) / "rc.xml"
        prefs_file = pathlib.Path(tmp) / "calendar_prefs.json"
        reloads = []

        with (
            patch.object(sysx, "RC_PATH", str(rc_path)),
            patch.object(preferences, "PREFS_FILE", prefs_file),
            patch.object(sysx, "_run", side_effect=lambda *a, **k: reloads.append(a) or _ok()),
            patch.object(sysx, "touch_devices", return_value=["Fixture Touchscreen"]),
            patch.object(sysx, "_outputs", return_value=["HDMI-A-1"]),
        ):
            # Simulate the orphan: a matrix on disk, nothing stored in prefs.
            sysx._write_rc_and_reload((1.0, 0.0, -0.02, 0.0, 1.0, -0.02), "Fixture Touchscreen", "HDMI-A-1")
            check("the trial matrix is on disk", "calibrationMatrix>1." in rc_path.read_text())
            check("but prefs do not claim a calibration", not preferences.load_prefs().get("touch_calibration"))

            # ...and now the service starts up again.
            sysx.sync_rc_from_prefs()
            body = rc_path.read_text()
            # The word appears in the template's comment; the element does not.
            check(
                "startup removes the orphaned matrix element",
                "<calibrationMatrix>" not in body,
                body[body.find("<libinput") : body.find("</libinput>")],
            )

            # A *confirmed* calibration must survive the same restart.
            preferences.update_prefs(
                touch_calibration=[1.0, 0.0, -0.02, 0.0, 1.0, -0.02],
                touch_device="Fixture Touchscreen",
                touch_output="HDMI-A-1",
            )
            sysx.sync_rc_from_prefs()
            check(
                "a confirmed calibration is restored on startup",
                "<calibrationMatrix>" in rc_path.read_text(),
            )


def _ok():
    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    return R()


def check_hidden_sections_hide_the_rail_not_the_route():
    """"Disable, don't delete": a switched-off section loses its rail icon while its
    route keeps serving. The Today page's grocery block also has to disappear, and
    today.js has to survive the element being absent - it renders events, weather
    and groceries in one pass, so an unguarded null would take the others down."""
    print("hidden sections hide the rail, not the route")
    import json
    import tempfile
    from unittest.mock import patch

    from app import preferences
    import server

    with tempfile.TemporaryDirectory() as tmp:
        prefs_file = pathlib.Path(tmp) / "calendar_prefs.json"
        with patch.object(preferences, "PREFS_FILE", prefs_file):
            client = server.app.test_client()

            shown = client.get("/").get_data(as_text=True)
            check('the rail links Groceries by default', 'data-nav="/groceries"' in shown)

            preferences.set_section_hidden("groceries", True)

            hidden_home = client.get("/").get_data(as_text=True)
            check(
                "hiding it removes the rail link",
                'data-nav="/groceries"' not in hidden_home,
            )
            check(
                "and leaves the Calendar link, which is not hideable",
                'data-nav="/"' in hidden_home,
            )
            check(
                "the Today block goes too",
                "today-groceries" not in client.get("/today").get_data(as_text=True),
            )
            # The point of disabling rather than deleting.
            check("the page still serves", client.get("/groceries").status_code == 200)
            check("the API still serves", client.get("/api/groceries").status_code == 200)

            reported = json.loads(client.get("/api/system/sections").get_data(as_text=True))
            check(
                "the System page reports it as hidden",
                {s["name"]: s["hidden"] for s in reported["sections"]}["groceries"] is True,
            )

    # today.js must not assume the element exists.
    today_js = (pathlib.Path(__file__).parent.parent / "static" / "today.js").read_text()
    check(
        "today.js guards on the grocery list being absent",
        "if (!groceriesList) return;" in today_js,
    )


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
        check_recipes_fetch_survives_the_visibility_migration,
        check_air_quality_and_pollen,
        check_radar_regions_are_verified,
        check_google_pollen_parsing,
        check_pollen_key_never_rides_in_a_url,
        check_pollen_provider_fallback,
        check_shell_subscriptions_come_last,
        check_groceries_degrade_without_a_credential,
        check_grocery_ordering_and_grouping,
        check_grocery_parser_matches_the_dart_original,
        check_demo_groceries_writes_are_stateful,
        check_timed_events_send_rfc3339,
        check_prefs_setters_do_not_clobber_each_other,
        check_touch_calibration_maths,
        check_rc_xml_render_is_well_formed,
        check_sports_degrades_instead_of_failing,
        check_sports_normalises_both_status_shapes,
        check_display_settings_validation,
        check_dimmers_compose_without_going_black,
        check_manual_screen_off_can_always_be_woken,
        check_bluetooth_success_strings,
        check_bluetooth_autoconnect,
        check_unconfirmed_calibration_cannot_survive_a_restart,
        check_hidden_sections_hide_the_rail_not_the_route,
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
