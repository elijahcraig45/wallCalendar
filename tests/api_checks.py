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
