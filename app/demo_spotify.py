"""Synthetic Spotify fixtures with working playback state (WALLCAL_DEMO=1).

Needed for a reason the calendar fixtures weren't: the live Spotify API answers
`now_playing` with null and `devices` with [] whenever nothing happens to be
playing, so the now-playing UI - the biggest surface on the page - can't be
designed or screenshot-verified against a real account at all.

Two deliberate differences from `app/demo_data.py`:

- **Writes are faked, not refused.** The calendar refuses writes in demo mode
  because a demo must never look like it saved something. Here the "writes" are
  playback commands against fixture state - there's nothing to corrupt, and the
  UI is only meaningfully testable if pressing play actually plays.
- **Artwork is generated, not linked.** Cover art is inline SVG data URIs, so a
  demo run makes no external image requests and looks identical offline.

State lives in this module, so it survives across requests within one server
process and resets when it restarts.
"""

import time
from urllib.parse import quote

# (title, artist, album, hex colour for the generated cover)
_LIBRARY = [
    ("Ridgeline", "Foxglove Vale", "Ridgeline", "#2f6f5f"),
    ("Paper Lanterns", "Foxglove Vale", "Ridgeline", "#2f6f5f"),
    ("Slow Tide", "Foxglove Vale", "Ridgeline", "#2f6f5f"),
    ("Marble Arch", "The Standing Room", "Long Division", "#7a3b57"),
    ("Long Division", "The Standing Room", "Long Division", "#7a3b57"),
    ("Cassette Sunday", "The Standing Room", "Long Division", "#7a3b57"),
    ("Nightjar", "Ada Mbeki", "Open Water", "#1f4e79"),
    ("Open Water", "Ada Mbeki", "Open Water", "#1f4e79"),
    ("Harbour Lights", "Ada Mbeki", "Open Water", "#1f4e79"),
    ("Two Sugars", "Wither & Pine", "Kitchen Radio", "#8a5a2b"),
    ("Kitchen Radio", "Wither & Pine", "Kitchen Radio", "#8a5a2b"),
    ("Gravel Road", "Wither & Pine", "Kitchen Radio", "#8a5a2b"),
    ("Blue Hour", "Halcyon Bros", "Signal Fade", "#4b3b7a"),
    ("Signal Fade", "Halcyon Bros", "Signal Fade", "#4b3b7a"),
    ("Static Bloom", "Halcyon Bros", "Signal Fade", "#4b3b7a"),
    ("Winter Count", "Junia", "Winter Count", "#6b2f2f"),
    ("Copper Wire", "Junia", "Winter Count", "#6b2f2f"),
    ("Understory", "Junia", "Winter Count", "#6b2f2f"),
    ("Fever Dream in C", "The Long Way Down", "Bright Nothing", "#2b6b6b"),
    ("Bright Nothing", "The Long Way Down", "Bright Nothing", "#2b6b6b"),
    ("Ninety Nine Summers", "The Long Way Down", "Bright Nothing", "#2b6b6b"),
    ("Telegraph Hill", "Moss Committee", "Field Notes", "#3f6b2f"),
    ("Field Notes", "Moss Committee", "Field Notes", "#3f6b2f"),
    ("Quiet Part", "Moss Committee", "Field Notes", "#3f6b2f"),
]

_PLAYLIST_NAMES = [
    ("Kitchen Mornings", "#2f6f5f"),
    ("Dinner Party", "#7a3b57"),
    ("Focus, Loud", "#1f4e79"),
    ("Saturday Cleaning", "#8a5a2b"),
    ("Road Trip 2026", "#4b3b7a"),
    ("Wind Down", "#6b2f2f"),
    ("Kids' Requests", "#2b6b6b"),
    ("Porch Sitting", "#3f6b2f"),
]

_DEVICES = [
    {"id": "demo-display", "name": "Wall Calendar", "supports_volume": True},
    {"id": "demo-pi", "name": "Living Room (Pi)", "supports_volume": True},
    {"id": "demo-phone", "name": "Henry's iPhone", "supports_volume": True},
]

# Every fixture track is this long, so progress maths stay obvious.
_TRACK_MS = 214_000

_state = {
    "index": 6,           # Nightjar - something mid-library, not the first row
    "is_playing": True,
    # Where playback sat as of `since`, so elapsed time advances on its own and
    # the progress bar visibly moves without anything having to tick it.
    "progress_ms": 41_000,
    "since": time.monotonic(),
    "shuffle": False,
    "repeat": "off",
    "volume": 55,
    "device_id": "demo-display",
    "queue": [7, 8, 3, 12],
}


def _cover(title: str, color: str) -> str:
    """An inline SVG cover: block of colour plus the title's initials. Keeps demo
    runs free of external image requests."""
    initials = "".join(word[0] for word in title.split()[:2]).upper()
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 300 300'>"
        f"<rect width='300' height='300' fill='{color}'/>"
        f"<text x='150' y='150' fill='#ffffff' fill-opacity='0.85' "
        f"font-family='Helvetica,Arial,sans-serif' font-size='120' font-weight='bold' "
        f"text-anchor='middle' dominant-baseline='central'>{initials}</text></svg>"
    )
    return "data:image/svg+xml," + quote(svg)


def _track(index: int) -> dict:
    title, artist, album, color = _LIBRARY[index % len(_LIBRARY)]
    return {
        "uri": f"spotify:track:demo{index}",
        "name": title,
        "artist": artist,
        "image": _cover(album, color),
    }


def _elapsed_ms() -> int:
    if not _state["is_playing"]:
        return _state["progress_ms"]
    advanced = _state["progress_ms"] + int((time.monotonic() - _state["since"]) * 1000)
    return min(advanced, _TRACK_MS)


def _freeze_progress() -> None:
    _state["progress_ms"] = _elapsed_ms()
    _state["since"] = time.monotonic()


def _set_index(index: int) -> None:
    _state["index"] = index % len(_LIBRARY)
    _state["progress_ms"] = 0
    _state["since"] = time.monotonic()


def get_access_token() -> str:
    # The Web Playback SDK would reject this, which is correct: demo mode has no
    # real Spotify session and must not appear to have one.
    return "demo-mode-not-a-real-token"


def devices() -> list[dict]:
    return [
        {
            **device,
            "is_active": device["id"] == _state["device_id"],
            "volume_percent": _state["volume"],
        }
        for device in _DEVICES
    ]


def transfer_playback(device_id: str, play: bool = True) -> None:
    _state["device_id"] = device_id
    if play:
        _state["is_playing"] = True
        _state["since"] = time.monotonic()


def now_playing() -> dict | None:
    track = _track(_state["index"])
    return {
        "is_playing": _state["is_playing"],
        "track": track["name"],
        "artist": track["artist"],
        "album_art": track["image"],
        "progress_ms": _elapsed_ms(),
        "duration_ms": _TRACK_MS,
        "shuffle_state": _state["shuffle"],
        "repeat_state": _state["repeat"],
        "volume_percent": _state["volume"],
        "supports_volume": True,
        "device_name": next(
            (d["name"] for d in _DEVICES if d["id"] == _state["device_id"]), None
        ),
        "context_uri": "spotify:playlist:demo0",
    }


def play() -> None:
    _state["is_playing"] = True
    _state["since"] = time.monotonic()


def pause() -> None:
    _freeze_progress()
    _state["is_playing"] = False


def next_track() -> None:
    if _state["queue"]:
        _set_index(_state["queue"].pop(0))
    else:
        _set_index(_state["index"] + 1)
    _state["is_playing"] = True


def previous_track() -> None:
    _set_index(_state["index"] - 1)
    _state["is_playing"] = True


def seek(position_ms: int) -> None:
    _state["progress_ms"] = max(0, min(position_ms, _TRACK_MS))
    _state["since"] = time.monotonic()


def set_volume(volume_percent: int) -> None:
    _state["volume"] = max(0, min(100, volume_percent))


def set_shuffle(state: bool) -> None:
    _state["shuffle"] = bool(state)


def set_repeat(state: str) -> None:
    _state["repeat"] = state


def queue(limit: int = 20) -> dict:
    return {
        "current": _track(_state["index"]),
        "upcoming": [_track(i) for i in _state["queue"][:limit]],
    }


def _play_first_matching(uris: list[str]) -> None:
    for uri in uris:
        if uri.startswith("spotify:track:demo"):
            _set_index(int(uri.rsplit("demo", 1)[1]))
            break
    _state["is_playing"] = True


def play_uri(uri: str) -> None:
    _play_first_matching([uri])


def play_uris(uris: list[str], offset_uri: str | None = None) -> None:
    _play_first_matching([offset_uri] if offset_uri else uris)


def play_context(uri: str) -> None:
    _state["is_playing"] = True
    _set_index(_state["index"])


def play_context_at(context_uri: str, track_uri: str) -> None:
    _play_first_matching([track_uri])


def playlists(limit: int = 50) -> list[dict]:
    return [
        {"uri": f"spotify:playlist:demo{i}", "name": name, "image": _cover(name, color)}
        for i, (name, color) in enumerate(_PLAYLIST_NAMES[:limit])
    ]


def recently_played(limit: int = 12) -> list[dict]:
    return [_track(i) for i in range(limit)]


def liked_songs(limit: int = 100, offset: int = 0) -> list[dict]:
    return [_track(i) for i in range(offset, min(offset + limit, len(_LIBRARY)))]


def playlist_tracks(playlist_id: str, limit: int = 100) -> list[dict]:
    # Deterministic per playlist rather than random, so a screenshot of
    # "Dinner Party" always shows the same songs.
    seed = sum(ord(c) for c in playlist_id)
    return [_track(seed + i * 3) for i in range(min(14, limit))]


def album_tracks(album_id: str, limit: int = 50) -> list[dict]:
    seed = sum(ord(c) for c in album_id)
    # Real album tracks carry no per-track image (see spotify_service), and the
    # client backfills from the header art - mirror that so the fallback path is
    # actually exercised in demo mode too.
    return [{**_track(seed + i), "image": None} for i in range(min(9, limit))]


def artist_albums(artist_id: str, limit: int = 10) -> list[dict]:
    seen, albums = set(), []
    for title, artist, album, color in _LIBRARY:
        if album in seen:
            continue
        seen.add(album)
        albums.append(
            {
                "uri": f"spotify:album:demo{len(albums)}",
                "name": album,
                "artist": artist,
                "image": _cover(album, color),
            }
        )
    return albums[:limit]


def search(query: str, limit: int = 10) -> dict:
    if not query:
        return {"tracks": [], "artists": [], "albums": []}

    needle = query.lower()
    tracks, artists, albums = [], {}, {}
    for index, (title, artist, album, color) in enumerate(_LIBRARY):
        haystack = f"{title} {artist} {album}".lower()
        if needle not in haystack:
            continue
        if len(tracks) < limit:
            tracks.append(_track(index))
        artists.setdefault(
            artist,
            {"id": f"demo-artist-{len(artists)}", "name": artist, "image": _cover(artist, color)},
        )
        albums.setdefault(
            album,
            {
                "uri": f"spotify:album:demo{len(albums)}",
                "name": album,
                "artist": artist,
                "image": _cover(album, color),
            },
        )

    return {
        "tracks": tracks,
        "artists": list(artists.values())[:limit],
        "albums": list(albums.values())[:limit],
    }
