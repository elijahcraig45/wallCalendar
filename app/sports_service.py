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
BASE_V2 = "https://site.api.espn.com/apis/v2/sports"

# Order matters: it is the tab order on the page, and the first is the default.
# `nav` is how you move through a league's fixtures, and it follows how the sport
# actually schedules rather than being uniform for its own sake: baseball and the
# Premier League play most days, so they step by date; college and pro football play
# in weeks, and stepping those day by day would walk through empty Tuesdays.
LEAGUES = {
    "mlb": {"path": "baseball/mlb", "label": "MLB", "sport": "baseball", "nav": "date"},
    "cfb": {
        "path": "football/college-football",
        "label": "College Football",
        "sport": "football",
        "nav": "week",
        # Only college football has a poll worth showing.
        "rankings": True,
    },
    "nfl": {"path": "football/nfl", "label": "NFL", "sport": "football", "nav": "week"},
    "epl": {"path": "soccer/eng.1", "label": "Premier League", "sport": "soccer", "nav": "date"},
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


def _get_v2(path: str) -> dict:
    """Standings only. ESPN serves them from apis/v2 rather than apis/site/v2, and
    the site path answers 200 with a stub carrying nothing but a link."""
    try:
        response = requests.get(f"{BASE_V2}/{path}", timeout=REQUEST_TIMEOUT)
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


def _week_calendar(data: dict) -> list[dict]:
    """Every week ESPN knows about, flattened across season types, in order.

    This is what makes stepping honest. ESPN numbers weeks *within* a season type, so
    "week 2" is preseason week 2 in August and regular-season week 2 in September -
    forcing seasontype=2 on a step in August silently jumped a month into the future,
    which is exactly what it did before this existed.

    Their labels come along too, because they are better than anything constructed
    here: "Hall of Fame Weekend", "Preseason Week 1", "Wild Card".
    """
    flat = []
    for block in ((data.get("leagues") or [{}])[0].get("calendar") or []):
        if not isinstance(block, dict):
            continue
        try:
            season_type = int(block.get("value"))
        except (TypeError, ValueError):
            continue
        for entry in block.get("entries") or []:
            try:
                number = int(entry.get("value"))
            except (TypeError, ValueError):
                continue
            flat.append(
                {
                    "seasontype": season_type,
                    "week": number,
                    "label": entry.get("label") or f"Week {number}",
                    # e.g. "Preseason" - shown when the label alone doesn't say it.
                    "season_label": block.get("label"),
                }
            )
    return flat


def scoreboard(
    league: str,
    date: str | None = None,
    week: int | None = None,
    seasontype: int | None = None,
) -> dict:
    """A day's or a week's games.

    `date` is YYYY-MM-DD and applies to the date-stepped leagues; `week` is a week
    number and applies to the football ones. Both are optional - with neither, ESPN
    answers for whatever is current, which is what the page wants on first load.
    """
    if league not in LEAGUES:
        return _unavailable(f"{league!r} is not a league this wall follows.")
    if DEMO_MODE:
        from app import demo_sports

        return demo_sports.scoreboard(league, date=date, week=week)

    query = {}
    if date:
        try:
            query["dates"] = dt.date.fromisoformat(date).strftime("%Y%m%d")
        except ValueError:
            return _unavailable(f"{date!r} is not a date.")
    if week:
        query["week"] = str(int(week))
        # Carried, never assumed. Pinning this to 2 (regular season) made a step from
        # preseason week 2 land on regular-season week 2 - a month later - and
        # labelled it plain "Week 2" with nothing saying preseason anywhere.
        if seasontype:
            query["seasontype"] = str(int(seasontype))

    def build() -> dict:
        suffix = "&".join(f"{k}={v}" for k, v in query.items())
        data = _get(f"{LEAGUES[league]['path']}/scoreboard" + (f"?{suffix}" if suffix else ""))
        games = [_game(e) for e in data.get("events", [])]
        return {
            "available": True,
            "errors": [],
            "league": league,
            "label": LEAGUES[league]["label"],
            "sport": LEAGUES[league]["sport"],
            "nav": LEAGUES[league]["nav"],
            "games": games,
            "has_live": any(g["live"] for g in games),
            "date": date,
            "week": (data.get("week") or {}).get("number") or week,
            "season": (data.get("season") or {}).get("year"),
            "season_type": (data.get("season") or {}).get("type"),
            "calendar": _week_calendar(data),
        }

    return _cached(f"scoreboard:{league}:{date}:{week}:{seasontype}", build)


def news(league: str) -> dict:
    """Headlines for a league. Cached long - this is reading, not score-watching."""
    if league not in LEAGUES:
        return _unavailable(f"{league!r} is not a league this wall follows.", articles=[])
    if DEMO_MODE:
        from app import demo_sports

        return demo_sports.news(league)

    def build() -> dict:
        data = _get(f"{LEAGUES[league]['path']}/news")
        articles = []
        for item in data.get("articles", []):
            images = item.get("images") or []
            articles.append(
                {
                    "headline": item.get("headline"),
                    "description": item.get("description"),
                    "published": item.get("published"),
                    # Smallest usable image: these render as a thumbnail, and ESPN's
                    # originals are big enough to be worth not shipping to a Pi.
                    "image": (images[0].get("url") if images else None),
                    "byline": item.get("byline"),
                    "link": ((item.get("links") or {}).get("web") or {}).get("href"),
                }
            )
        return {
            "available": True,
            "errors": [],
            "league": league,
            "label": LEAGUES[league]["label"],
            "articles": articles,
            "games": [],
        }

    return _cached(f"news:{league}", build)


def rankings(league: str = "cfb") -> dict:
    """The AP Top 25, for the one league that has a poll worth showing."""
    if not LEAGUES.get(league, {}).get("rankings"):
        return _unavailable(f"{league!r} has no rankings.", teams=[])
    if DEMO_MODE:
        from app import demo_sports

        return demo_sports.rankings(league)

    def build() -> dict:
        data = _get(f"{LEAGUES[league]['path']}/rankings")
        polls = data.get("rankings") or []
        # AP first when it's there; ESPN's order is not guaranteed.
        poll = next((p for p in polls if "AP" in (p.get("shortName") or "")), polls[0] if polls else {})
        teams = []
        for entry in poll.get("ranks", []):
            team_info = entry.get("team") or {}
            teams.append(
                {
                    "rank": entry.get("current"),
                    "previous": entry.get("previous"),
                    "name": team_info.get("nickname") or team_info.get("name"),
                    "abbr": team_info.get("abbreviation"),
                    "record": entry.get("recordSummary"),
                    "points": entry.get("points"),
                    "color": f"#{team_info['color']}" if team_info.get("color") else None,
                }
            )
        return {
            "available": True,
            "errors": [],
            "league": league,
            "label": poll.get("name") or "Rankings",
            "teams": teams,
            "games": [],
        }

    return _cached(f"rankings:{league}", build)


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
    if teams is None:
        from app import preferences

        teams = preferences.followed_teams()
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
        {
            "key": key,
            "label": value["label"],
            "sport": value["sport"],
            "nav": value["nav"],
            "rankings": bool(value.get("rankings")),
            "standings": True,
        }
        for key, value in LEAGUES.items()
    ]


def standings(league: str) -> dict:
    """Division tables - the Braves' actual race, not a 15-team league list.

    A different host prefix from everything else here: standings live under
    `apis/v2`, not `apis/site/v2`. `level=3` is what nests divisions inside each
    conference; without it MLB answers with two 15-team blocks and "NL East" does
    not exist in the payload at all.
    """
    if league not in LEAGUES:
        return _unavailable(f"{league!r} is not a league this wall follows.", groups=[])
    if DEMO_MODE:
        from app import demo_sports

        return demo_sports.standings(league)

    def build() -> dict:
        data = _get_v2(f"{LEAGUES[league]['path']}/standings?level=3")
        groups = []
        for conference in data.get("children", []):
            # Divisions when the sport has them, the conference itself when it
            # doesn't - soccer is a single table.
            divisions = conference.get("children") or [conference]
            for division in divisions:
                entries = []
                for entry in (division.get("standings") or {}).get("entries", []):
                    stats = {s.get("name"): s.get("displayValue") for s in entry.get("stats", [])}
                    team_info = entry.get("team") or {}
                    entries.append(
                        {
                            "abbr": team_info.get("abbreviation"),
                            "name": team_info.get("displayName") or team_info.get("name"),
                            "color": f"#{team_info['color']}" if team_info.get("color") else None,
                            "wins": stats.get("wins"),
                            "losses": stats.get("losses"),
                            # Soccer has draws and points; the US sports don't.
                            "ties": stats.get("ties"),
                            "points": stats.get("points"),
                            "pct": stats.get("winPercent"),
                            # "-" for the leader, "6.0" for everyone else.
                            "behind": stats.get("gamesBehind"),
                            "streak": stats.get("streak"),
                        }
                    )
                if entries:
                    groups.append({"name": division.get("name"), "teams": entries})
        return {
            "available": True,
            "errors": [],
            "league": league,
            "label": LEAGUES[league]["label"],
            "sport": LEAGUES[league]["sport"],
            "groups": groups,
            "games": [],
        }

    return _cached(f"standings:{league}", build)


def teams(league: str) -> dict:
    """Every team in a league, for the followed-teams picker on /system."""
    if league not in LEAGUES:
        return _unavailable(f"{league!r} is not a league this wall follows.", teams=[])
    if DEMO_MODE:
        from app import demo_sports

        return demo_sports.teams(league)

    def build() -> dict:
        data = _get(f"{LEAGUES[league]['path']}/teams")
        listed = []
        for wrapper in (
            data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
        ):
            info = wrapper.get("team") or {}
            listed.append(
                {
                    # `slug` is what the team endpoint accepts, and it is not always
                    # the abbreviation - Georgia Tech is "gt" but plenty are longer.
                    "id": info.get("abbreviation", "").lower() or info.get("slug"),
                    "name": info.get("displayName"),
                    "abbr": info.get("abbreviation"),
                }
            )
        listed.sort(key=lambda t: (t["name"] or "").lower())
        return {"available": True, "errors": [], "league": league, "teams": listed, "games": []}

    return _cached(f"teams:{league}", build)
