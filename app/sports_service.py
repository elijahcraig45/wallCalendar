"""Scoreboards and schedules for the four leagues this house watches.

Source is ESPN's public site API (`site.api.espn.com`). One shape covers baseball,
American football and soccer, it needs no key, and it answers for college football -
which the keyed alternatives either charge for or cover badly.

It is also **undocumented and unversioned**. ESPN publishes no contract for it and
can change or withdraw it without notice, which is why every read here degrades to an
explained empty state rather than an error: see `_unavailable`. The wall must not
start logging console errors on every page because a scoreboard moved.

That degradation is not theoretical politeness. /api/sports is read by the Today page
on a wall that is on all day, so a 503 from here would be a failed request every few
minutes forever, and the layout tests treat a console error on any page as a
regression.

All four leagues are normalised into one game shape by `_game`, deliberately in this
one module: when ESPN changes something, this is the only file to fix.
"""

import datetime as dt
import json
import time

import requests

from app.config import DEMO_MODE, PROJECT_ROOT

BASE = "https://site.api.espn.com/apis/site/v2/sports"

# Order matters: it is the tab order on the page, and the first is the default.
LEAGUES = {
    "mlb": {"path": "baseball/mlb", "label": "MLB", "sport": "baseball"},
    "cfb": {"path": "football/college-football", "label": "College Football", "sport": "football"},
    "nfl": {"path": "football/nfl", "label": "NFL", "sport": "football"},
    "epl": {"path": "soccer/eng.1", "label": "Premier League", "sport": "soccer"},
}

# Teams followed on the Today page. Keyed by league so the same code serves both.
DEFAULT_FOLLOWING = [
    {"league": "mlb", "team": "atl"},
    {"league": "cfb", "team": "gt"},
]

# A live game's score changes every few minutes; a schedule days out does not. The
# short TTL only applies while something is actually in progress, so an idle wall
# makes one request per league every ten minutes rather than one every thirty
# seconds all day.
LIVE_TTL_SECONDS = 45
IDLE_TTL_SECONDS = 600

CACHE_FILE = PROJECT_ROOT / "data" / "sports_cache.json"
REQUEST_TIMEOUT = 12

_cache: dict[str, tuple[float, dict]] = {}


class SportsUnavailable(RuntimeError):
    """ESPN unreachable, slow, or answering something unparseable."""


def _unavailable(message: str, **extra) -> dict:
    """The shape every public function returns when it cannot answer.

    200-with-an-explanation, never an exception escaping to the route - see the
    module docstring.
    """
    return {"available": False, "errors": [message], "games": [], **extra}


def _get(path: str) -> dict:
    try:
        response = requests.get(f"{BASE}/{path}", timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        raise SportsUnavailable(f"Couldn't reach the scores service ({type(exc).__name__}).") from exc
    except ValueError as exc:
        raise SportsUnavailable("The scores service sent something unreadable.") from exc


def _competitor(side: dict) -> dict:
    team = side.get("team") or {}
    return {
        "abbr": team.get("abbreviation") or team.get("shortDisplayName") or "?",
        "name": team.get("shortDisplayName") or team.get("displayName") or "",
        "logo": team.get("logo"),
        # Used as an accent only - never as text or a text background. ESPN hands
        # out the real team colours, and Georgia Tech gold on a cream ground fails
        # the contrast sweep outright.
        "color": f"#{team['color']}" if team.get("color") else None,
        "score": side.get("score"),
        "winner": bool(side.get("winner")),
        "home": side.get("homeAway") == "home",
        # College football only; None everywhere else.
        "rank": (side.get("curatedRank") or {}).get("current")
        if (side.get("curatedRank") or {}).get("current", 99) <= 25
        else None,
        "record": next(
            (r.get("summary") for r in (side.get("records") or []) if r.get("type") == "total"),
            None,
        ),
    }


def _game(event: dict) -> dict:
    competition = (event.get("competitions") or [{}])[0]
    # Status lives in two different places depending on which endpoint this came
    # from: alongside the event on /scoreboard, but nested under the competition in a
    # team's `nextEvent`. Reading only the event level left every Today row with a
    # blank status - "ATL @ MIN" with no kick-off time next to it.
    status = event.get("status") or competition.get("status") or {}
    state = (status.get("type") or {}).get("state")  # pre | in | post
    competitors = [_competitor(c) for c in competition.get("competitors", [])]

    # ESPN lists home first for US sports and away first for soccer. Normalise so
    # the page can always render "away @ home" without knowing the sport.
    away = next((c for c in competitors if not c["home"]), None)
    home = next((c for c in competitors if c["home"]), None)

    return {
        "id": event.get("id"),
        "name": event.get("shortName"),
        "start": event.get("date"),
        "state": state,
        "live": state == "in",
        "final": state == "post",
        # "8/18 - 7:40 PM EDT" before, "Bot 7th" / "45'" during, "Final" after.
        "detail": (status.get("type") or {}).get("shortDetail"),
        "away": away,
        "home": home,
        "broadcast": next(
            (b.get("names", [None])[0] for b in competition.get("broadcasts", []) if b.get("names")),
            None,
        ),
        "venue": ((competition.get("venue") or {}).get("fullName")),
    }


def _cached(key: str, build) -> dict:
    """TTL cache whose length depends on what came back.

    Anything in progress is re-read on LIVE_TTL_SECONDS; everything else waits
    IDLE_TTL_SECONDS. Stale data is served if the rebuild fails, because a score
    from four minutes ago beats an empty panel.
    """
    now = time.monotonic()
    entry = _cache.get(key)
    if entry:
        cached_at, payload = entry
        ttl = LIVE_TTL_SECONDS if payload.get("has_live") else IDLE_TTL_SECONDS
        if now - cached_at < ttl:
            return payload

    try:
        payload = build()
    except SportsUnavailable as exc:
        if entry:
            # Serve the stale copy, but say so rather than pretending it's current.
            stale = dict(entry[1])
            stale["errors"] = [str(exc)]
            stale["stale"] = True
            return stale
        return _unavailable(str(exc))

    _cache[key] = (now, payload)
    _write_cache_file()
    return payload


def _write_cache_file() -> None:
    """A copy on disk purely so a restart doesn't start from nothing.

    Best-effort: the in-memory cache is the real one, and failing to write must
    never cost a caller its answer.
    """
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps({k: {"at": v[0], "payload": v[1]} for k, v in _cache.items()})
        )
    except OSError:
        pass


def scoreboard(league: str) -> dict:
    if league not in LEAGUES:
        return _unavailable(f"{league!r} is not a league this wall follows.")
    if DEMO_MODE:
        from app import demo_sports

        return demo_sports.scoreboard(league)

    def build() -> dict:
        data = _get(f"{LEAGUES[league]['path']}/scoreboard")
        games = [_game(e) for e in data.get("events", [])]
        return {
            "available": True,
            "errors": [],
            "league": league,
            "label": LEAGUES[league]["label"],
            "sport": LEAGUES[league]["sport"],
            "games": games,
            "has_live": any(g["live"] for g in games),
            "day": (data.get("day") or {}).get("date"),
        }

    return _cached(f"scoreboard:{league}", build)


def team(league: str, team_id: str) -> dict:
    """One team's record and its current-or-next game - what Today needs."""
    if league not in LEAGUES:
        return _unavailable(f"{league!r} is not a league this wall follows.")
    if DEMO_MODE:
        from app import demo_sports

        return demo_sports.team(league, team_id)

    def build() -> dict:
        data = _get(f"{LEAGUES[league]['path']}/teams/{team_id}")
        info = data.get("team") or {}
        events = info.get("nextEvent") or []
        game = _game(events[0]) if events else None
        return {
            "available": True,
            "errors": [],
            "league": league,
            "label": LEAGUES[league]["label"],
            "team": {
                "abbr": info.get("abbreviation"),
                "name": info.get("displayName"),
                "short": info.get("shortDisplayName"),
                "logo": (info.get("logos") or [{}])[0].get("href"),
                "color": f"#{info['color']}" if info.get("color") else None,
                "record": next(
                    (i.get("summary") for i in (info.get("record") or {}).get("items", [])),
                    None,
                ),
            },
            "game": game,
            "games": [game] if game else [],
            "has_live": bool(game and game["live"]),
        }

    return _cached(f"team:{league}:{team_id}", build)


def following(teams: list[dict] | None = None) -> dict:
    """The Today page's block: every followed team, each independent.

    One team failing must not cost the others theirs - the same rule air quality and
    pollen follow.
    """
    wanted = teams or DEFAULT_FOLLOWING
    entries = []
    errors = []
    for entry in wanted:
        result = team(entry["league"], entry["team"])
        if result.get("available"):
            entries.append(result)
        else:
            errors.extend(result.get("errors", []))
    return {
        "available": bool(entries),
        "errors": errors,
        "teams": entries,
        "has_live": any(e.get("has_live") for e in entries),
    }


def leagues() -> list[dict]:
    return [
        {"key": key, "label": value["label"], "sport": value["sport"]}
        for key, value in LEAGUES.items()
    ]
