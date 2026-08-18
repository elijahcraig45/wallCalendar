"""Synthetic scoreboards, in the same shape sports_service normalises ESPN into.

Two jobs. Demo mode has to render without touching the network, and the dev machine
sits behind a TLS-inspecting proxy that blocks the live call outright - so without
these the sports page could not be developed or layout-tested at all.

Deliberately covers all three game states in every league: one in progress, one
finished, one still to come. The interesting styling is on the live and final rows,
and a fixture set of nothing but scheduled games would leave both untested.
"""

import datetime as dt

# Fixed relative to "now" so the times read sensibly whenever the demo runs, but the
# *set* of games never changes - layout assertions need a stable number of rows.
def _at(hours: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)).isoformat()


def _side(abbr, name, color, score=None, *, home=False, winner=False, rank=None, record=None):
    return {
        "abbr": abbr,
        "name": name,
        "logo": None,
        "color": color,
        "score": score,
        "winner": winner,
        "home": home,
        "rank": rank,
        "record": record,
    }


def _game(gid, name, state, detail, away, home, start, broadcast=None, venue=None):
    return {
        "id": gid,
        "name": name,
        "start": start,
        "state": state,
        "live": state == "in",
        "final": state == "post",
        "detail": detail,
        "away": away,
        "home": home,
        "broadcast": broadcast,
        "venue": venue,
    }


_BRAVES = _side("ATL", "Braves", "#13274F", record="74-51")
_GT = _side("GT", "Yellow Jackets", "#B3A369", record="3-0")


def _mlb():
    return [
        _game(
            "d-mlb-1", "ATL @ MIN", "in", "Bot 7th",
            _side("ATL", "Braves", "#13274F", "4", record="74-51"),
            _side("MIN", "Twins", "#002B5C", "3", home=True, record="60-65"),
            _at(-1.5), broadcast="FDSSO", venue="Target Field",
        ),
        _game(
            "d-mlb-2", "NYY @ BAL", "post", "Final",
            _side("NYY", "Yankees", "#0C2340", "7", winner=True, record="71-54"),
            _side("BAL", "Orioles", "#DF4601", "2", home=True, record="55-70"),
            _at(-5),
        ),
        _game(
            "d-mlb-3", "LAD @ SD", "pre", "10:10 PM EDT",
            _side("LAD", "Dodgers", "#005A9C", record="78-47"),
            _side("SD", "Padres", "#2F241D", home=True, record="66-59"),
            _at(3),
        ),
    ]


def _cfb():
    return [
        _game(
            "d-cfb-1", "COLO @ GT", "in", "2nd 8:14",
            _side("COLO", "Buffaloes", "#CFB87C", "10", record="2-1"),
            _side("GT", "Yellow Jackets", "#B3A369", "17", home=True, rank=22, record="3-0"),
            _at(-1), broadcast="ESPN", venue="Bobby Dodd Stadium",
        ),
        _game(
            "d-cfb-2", "BAMA @ UGA", "post", "Final",
            _side("BAMA", "Crimson Tide", "#9E1B32", "24", record="2-1"),
            _side("UGA", "Bulldogs", "#BA0C2F", "31", home=True, winner=True, rank=3, record="3-0"),
            _at(-6),
        ),
        _game(
            "d-cfb-3", "CLEM @ FSU", "pre", "Sat 3:30 PM EDT",
            _side("CLEM", "Tigers", "#F56600", rank=9, record="3-0"),
            _side("FSU", "Seminoles", "#782F40", home=True, record="2-1"),
            _at(30),
        ),
    ]


def _nfl():
    return [
        _game(
            "d-nfl-1", "NO @ ATL", "in", "3rd 11:02",
            _side("NO", "Saints", "#D3BC8D", "13", record="1-1"),
            _side("ATL", "Falcons", "#A71930", "20", home=True, record="2-0"),
            _at(-2), broadcast="FOX",
        ),
        _game(
            "d-nfl-2", "KC @ BUF", "post", "Final/OT",
            _side("KC", "Chiefs", "#E31837", "27", winner=True, record="3-0"),
            _side("BUF", "Bills", "#00338D", "24", home=True, record="2-1"),
            _at(-24),
        ),
        _game(
            "d-nfl-3", "DAL @ PHI", "pre", "Sun 8:20 PM EDT",
            _side("DAL", "Cowboys", "#041E42", record="1-2"),
            _side("PHI", "Eagles", "#004C54", home=True, record="3-0"),
            _at(50),
        ),
    ]


def _epl():
    return [
        _game(
            "d-epl-1", "ARS @ LIV", "in", "67'",
            _side("ARS", "Arsenal", "#EF0107", "1", record="2-0-1"),
            _side("LIV", "Liverpool", "#C8102E", "2", home=True, record="3-0-0"),
            _at(-1.2), broadcast="USA",
        ),
        _game(
            "d-epl-2", "MCI @ TOT", "post", "FT",
            _side("MCI", "Man City", "#6CABDD", "2", record="2-1-0"),
            _side("TOT", "Spurs", "#132257", "2", home=True, record="1-1-1"),
            _at(-28),
        ),
        _game(
            "d-epl-3", "CHE @ MUN", "pre", "Sat 12:30 PM EDT",
            _side("CHE", "Chelsea", "#034694", record="1-2-0"),
            _side("MUN", "Man United", "#DA291C", home=True, record="2-0-1"),
            _at(40),
        ),
    ]


_BY_LEAGUE = {"mlb": _mlb, "cfb": _cfb, "nfl": _nfl, "epl": _epl}
_LABELS = {
    "mlb": ("MLB", "baseball"),
    "cfb": ("College Football", "football"),
    "nfl": ("NFL", "football"),
    "epl": ("Premier League", "soccer"),
}


def scoreboard(league: str) -> dict:
    games = _BY_LEAGUE[league]()
    label, sport = _LABELS[league]
    return {
        "available": True,
        "errors": [],
        "league": league,
        "label": label,
        "sport": sport,
        "games": games,
        "has_live": any(g["live"] for g in games),
        "day": dt.date.today().isoformat(),
    }


def team(league: str, team_id: str) -> dict:
    """The followed team's own game - the first fixture in its league, which is
    deliberately the live one so the Today block renders its in-progress state."""
    games = _BY_LEAGUE[league]()
    game = games[0]
    label, _sport = _LABELS[league]
    side = _BRAVES if league == "mlb" else _GT
    return {
        "available": True,
        "errors": [],
        "league": league,
        "label": label,
        "team": {
            "abbr": side["abbr"],
            "name": "Atlanta Braves" if league == "mlb" else "Georgia Tech",
            "short": side["name"],
            "logo": None,
            "color": side["color"],
            "record": side["record"],
        },
        "game": game,
        "games": [game],
        "has_live": game["live"],
    }
