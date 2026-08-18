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
_NAV = {"mlb": "date", "cfb": "week", "nfl": "week", "epl": "date"}
_LABELS = {
    "mlb": ("MLB", "baseball"),
    "cfb": ("College Football", "football"),
    "nfl": ("NFL", "football"),
    "epl": ("Premier League", "soccer"),
}


def scoreboard(league: str, date: str | None = None, week: int | None = None) -> dict:
    """The same three games whatever day or week is asked for.

    Stepping the date must change the *label* without changing the fixture set -
    layout assertions count rows, and a demo that emptied itself on the next day
    would make the navigation untestable rather than more realistic.
    """
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
        "nav": _NAV[league],
        "date": date,
        "week": week or 3,
        "season": 2026,
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


# ---------- news ----------
#
# Six per league, matching what ESPN returns. Deliberately mundane copy: fixtures
# that read as jokes make screenshots useless for judging whether the real thing
# looks right.

_NEWS = {
    "mlb": [
        ("Braves clinch series with late rally in Minneapolis",
         "Atlanta scored three in the eighth to take the set from the Twins."),
        ("Trade deadline reshaped the NL East, one month on",
         "Three contenders, three very different approaches, and early returns."),
        ("Rookie catcher earns everyday role", "A defensive turnaround nobody saw coming in April."),
        ("Bullpen usage is up league-wide again", "Starters are throwing fewer innings than at any point on record."),
        ("Wild card race tightens to four teams", "Two games separate the field with six weeks left."),
        ("Injury report: what to expect in September", "Return timelines for a dozen contributors."),
    ],
    "cfb": [
        ("Georgia Tech opens at home against Colorado",
         "A Thursday night kickoff in Atlanta to start the season."),
        ("Preseason AP poll: Ohio State on top", "The Buckeyes edge Oregon in the closest vote in a decade."),
        ("ACC quarterback room ranked", "Who returns, who transferred, and who wins the league."),
        ("Playoff format enters its third year", "What changed, and what the committee says it weighs."),
        ("Best non-conference games of September", "Six matchups worth planning a Saturday around."),
        ("Transfer portal winners", "The rosters that improved most over the summer."),
    ],
    "nfl": [
        ("Falcons finalise the 53", "Atlanta's roster cuts leave questions at the back of the secondary."),
        ("Training camp intel from all 32 teams", "What coaches are saying, and what the practice reports show."),
        ("Rule changes for the new season", "Kickoffs, replay assist, and a tweak to overtime."),
        ("Rookie quarterbacks who will start Week 1", "Three teams commit, two are still deciding."),
        ("Injury designations explained", "What each label actually means for game day."),
        ("Divisional preview: NFC South", "The most open division in football, again."),
    ],
    "epl": [
        ("Arsenal edge Liverpool in Anfield thriller", "A late winner settles the weekend's headline fixture."),
        ("Summer window closes with record spend", "Premier League clubs outspent the rest of Europe combined."),
        ("Promoted sides face familiar problems", "Early fixtures have been unkind to all three."),
        ("Title race predictions after two weeks", "Too early to matter, early enough to argue about."),
        ("New signings still settling", "Which arrivals have started, and which are waiting."),
        ("Fixture congestion returns in December", "Clubs push back on the expanded calendar."),
    ],
}


def news(league: str) -> dict:
    label, _sport = _LABELS[league]
    articles = [
        {
            "headline": headline,
            "description": description,
            # Staggered so the "published" ordering is visible in the layout.
            "published": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=i * 5)).isoformat(),
            "image": None,
            "byline": "Wall Calendar fixtures",
        }
        for i, (headline, description) in enumerate(_NEWS[league])
    ]
    return {
        "available": True, "errors": [], "league": league,
        "label": label, "articles": articles, "games": [],
    }


# ---------- rankings ----------

_AP_TOP = [
    ("Ohio State", "OSU", "0-0"), ("Oregon", "ORE", "0-0"), ("Georgia", "UGA", "0-0"),
    ("Texas", "TEX", "0-0"), ("Penn State", "PSU", "0-0"), ("Notre Dame", "ND", "0-0"),
    ("Alabama", "ALA", "0-0"), ("Michigan", "MICH", "0-0"), ("Clemson", "CLEM", "0-0"),
    ("LSU", "LSU", "0-0"), ("Miami", "MIA", "0-0"), ("Tennessee", "TENN", "0-0"),
    ("Ole Miss", "MISS", "0-0"), ("Florida", "FLA", "0-0"), ("Oklahoma", "OU", "0-0"),
    ("South Carolina", "SC", "0-0"), ("Kansas State", "KSU", "0-0"), ("Texas A&M", "TAMU", "0-0"),
    ("Louisville", "LOU", "0-0"), ("Illinois", "ILL", "0-0"), ("Indiana", "IU", "0-0"),
    ("Georgia Tech", "GT", "0-0"), ("Iowa State", "ISU", "0-0"), ("Boise State", "BSU", "0-0"),
    ("Utah", "UTAH", "0-0"),
]


def rankings(league: str = "cfb") -> dict:
    return {
        "available": True,
        "errors": [],
        "league": league,
        "label": "AP Top 25",
        "teams": [
            {
                "rank": i + 1,
                "previous": i + 1,
                "name": name,
                "abbr": abbr,
                "record": record,
                "points": 1550 - i * 60,
                # Georgia Tech's gold, kept so the fixture exercises the one colour
                # most likely to be unreadable if it ever leaks into text.
                "color": "#B3A369" if abbr == "GT" else None,
            }
            for i, (name, abbr, record) in enumerate(_AP_TOP)
        ],
        "games": [],
    }
