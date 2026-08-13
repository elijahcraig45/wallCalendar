import requests

from app.auth import spotify_auth
from app.config import DEMO_MODE

PLAYLIST_ITEMS_URL = "https://api.spotify.com/v1/playlists/{playlist_id}/items"


class SpotifyForbidden(RuntimeError):
    """Spotify refused a request that this app is simply not allowed to make -
    a Development Mode restriction rather than anything wrong locally, so it
    needs to reach the user as an explanation, not a 500."""


class SpotifyNotConfigured(RuntimeError):
    """No Spotify account is signed in. Its own type (rather than a bare
    ValueError) so server.py can answer it with a clear status instead of an
    HTML 500 page."""


def _client():
    accounts = spotify_auth.signed_in_accounts()
    if not accounts:
        raise SpotifyNotConfigured(
            "No Spotify account signed in. Run `python cli.py spotify`."
        )
    return spotify_auth.get_client(accounts[0])


def get_access_token() -> str:
    accounts = spotify_auth.signed_in_accounts()
    if not accounts:
        raise SpotifyNotConfigured(
            "No Spotify account signed in. Run `python cli.py spotify`."
        )
    return spotify_auth.get_access_token(accounts[0])


def devices() -> list[dict]:
    return _client().devices()["devices"]


def transfer_playback(device_id: str, play: bool = True) -> None:
    _client().transfer_playback(device_id, force_play=play)


def _track_summary(track: dict) -> dict:
    images = track.get("album", {}).get("images", [])
    return {
        "uri": track["uri"],
        "name": track["name"],
        "artist": ", ".join(a["name"] for a in track.get("artists", [])),
        # smallest available image - these render as small tiles, not hero art
        "image": images[-1]["url"] if images else None,
    }


def now_playing() -> dict | None:
    # "Nothing is playing" is the honest answer when no account is signed in, and
    # it's already a state every caller renders. This matters more than it looks:
    # the shell polls this endpoint from *every* page every few seconds, so
    # raising here filled the service log with tracebacks on any install where
    # Google was set up but Spotify wasn't - which is the default after setup.
    if not spotify_auth.signed_in_accounts():
        return None

    playback = _client().current_playback()
    if playback is None or playback.get("item") is None:
        return None

    item = playback["item"]
    images = item.get("album", {}).get("images", [])
    device = playback.get("device") or {}
    context = playback.get("context") or {}
    return {
        "is_playing": playback.get("is_playing", False),
        "track": item.get("name"),
        "artist": ", ".join(a["name"] for a in item.get("artists", [])),
        "album_art": images[0]["url"] if images else None,
        "progress_ms": playback.get("progress_ms"),
        "duration_ms": item.get("duration_ms"),
        "shuffle_state": playback.get("shuffle_state", False),
        "repeat_state": playback.get("repeat_state", "off"),
        "volume_percent": device.get("volume_percent"),
        "supports_volume": device.get("supports_volume", True),
        # Surfaced so the wall can say *where* it's playing without a second
        # round trip to /devices - on a shared speaker that's the first thing
        # someone walking up wants to know.
        "device_name": device.get("name"),
        "context_uri": context.get("uri"),
    }


def seek(position_ms: int) -> None:
    _client().seek_track(position_ms)


def set_volume(volume_percent: int) -> None:
    _client().volume(volume_percent)


def set_repeat(state: str) -> None:  # "off" | "context" | "track"
    _client().repeat(state)


def queue(limit: int = 20) -> dict:
    data = _client().queue()
    current = _track_summary(data["currently_playing"]) if data.get("currently_playing") else None
    upcoming = [_track_summary(t) for t in data.get("queue", [])[:limit]]
    return {"current": current, "upcoming": upcoming}


def liked_songs(limit: int = 100, offset: int = 0) -> list[dict]:
    # me/tracks caps at 50/page and nests under items[].track like
    # recently_played - paginate with plain spotipy calls, no deprecation
    # issue here unlike playlist_tracks.
    tracks, page_offset = [], offset
    while len(tracks) < limit:
        page = _client().current_user_saved_tracks(limit=min(50, limit - len(tracks)), offset=page_offset)
        items = page["items"]
        if not items:
            break
        tracks.extend(_track_summary(i["track"]) for i in items)
        page_offset += len(items)
    return tracks[:limit]


def album_tracks(album_id: str, limit: int = 50) -> list[dict]:
    # /albums/{id}/tracks returns simplified track objects (no "album" key,
    # so _track_summary's image lookup yields None) - the client backfills
    # each row's image with the overlay's own header art instead. If this
    # ever 403s the way the deprecated playlist /tracks path did, the fix is
    # the same raw-requests-with-bearer-token pattern PLAYLIST_ITEMS_URL
    # already uses, hitting https://api.spotify.com/v1/albums/{id}/tracks.
    results = _client().album_tracks(album_id, limit=min(limit, 50))
    tracks = [_track_summary(t) for t in results["items"]]
    while results.get("next") and len(tracks) < limit:
        results = _client().next(results)
        tracks.extend(_track_summary(t) for t in results["items"])
    return tracks[:limit]


def play_uris(uris: list[str], offset_uri: str | None = None) -> None:
    # Backs Liked Songs, which has no context_uri to hang play_context off
    # of. Spotify caps uris at 100 - pairs with liked_songs(limit=100).
    _client().start_playback(uris=uris, offset={"uri": offset_uri} if offset_uri else None)


def play() -> None:
    _client().start_playback()


def pause() -> None:
    _client().pause_playback()


def next_track() -> None:
    _client().next_track()


def previous_track() -> None:
    _client().previous_track()


def play_uri(uri: str) -> None:
    _client().start_playback(uris=[uri])


def play_context(uri: str) -> None:
    _client().start_playback(context_uri=uri)


def play_context_at(context_uri: str, track_uri: str) -> None:
    _client().start_playback(context_uri=context_uri, offset={"uri": track_uri})


def set_shuffle(state: bool) -> None:
    _client().shuffle(state)


def playlist_tracks(playlist_id: str, limit: int = 100) -> list[dict]:
    # spotipy's playlist_items() still calls /playlists/{id}/tracks, which
    # Spotify deprecated (403s for Development Mode apps) in its March 2026
    # API migration. The replacement /items endpoint isn't wrapped by our
    # installed spotipy version yet, so call it directly.
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = PLAYLIST_ITEMS_URL.format(playlist_id=playlist_id)
    params = {"limit": min(limit, 100)}

    tracks = []
    while url and len(tracks) < limit:
        resp = requests.get(url, headers=headers, params=params)
        # Observed against a real account: /items succeeds for playlists the
        # signed-in user owns but 403s for some owned by other people, while the
        # deprecated /tracks path 403s for all of them. Spotify's exact rule
        # isn't discoverable from outside, and there's no fallback left to try -
        # so this surfaces as an explanation rather than an unhandled 500.
        if resp.status_code == 403:
            raise SpotifyForbidden(
                "Spotify won't let this app read that playlist. That's a "
                "Development Mode restriction, not a problem with the wall - "
                "playlists you own yourself do work."
            )
        resp.raise_for_status()
        data = resp.json()
        for entry in data.get("items", []):
            item = entry.get("item")
            if not item or item.get("type") != "track":
                continue
            tracks.append(_track_summary(item))
        url = data.get("next")
        params = None  # 'next' already carries its own query params

    return tracks[:limit]


def _artist_summary(artist: dict) -> dict:
    images = artist.get("images", [])
    return {
        "id": artist["id"],
        "name": artist["name"],
        "image": images[-1]["url"] if images else None,
    }


def _album_summary(album: dict) -> dict:
    images = album.get("images", [])
    return {
        "uri": album["uri"],
        "name": album["name"],
        "artist": ", ".join(a["name"] for a in album.get("artists", [])),
        "image": images[-1]["url"] if images else None,
    }


def search(query: str, limit: int = 10) -> dict:
    # Spotify caps /search's limit at 10 for apps without extended quota
    # access, even though the docs say up to 50 - anything higher 400s.
    if not query:
        return {"tracks": [], "artists": [], "albums": []}
    results = _client().search(q=query, type="track,artist,album", limit=limit)
    return {
        "tracks": [_track_summary(t) for t in results["tracks"]["items"]],
        "artists": [_artist_summary(a) for a in results["artists"]["items"]],
        "albums": [_album_summary(a) for a in results["albums"]["items"]],
    }


def artist_albums(artist_id: str, limit: int = 10) -> list[dict]:
    # Same undocumented cap as /search - apps without extended quota access
    # 400 above 10 regardless of what the docs claim.
    results = _client().artist_albums(artist_id, album_type="album,single", limit=limit)
    # Spotify often lists the same release multiple times (deluxe/remaster/
    # regional editions) - collapse exact-name duplicates.
    seen = set()
    albums = []
    for a in results["items"]:
        key = a["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        albums.append(_album_summary(a))
    return albums


def recently_played(limit: int = 12) -> list[dict]:
    results = _client().current_user_recently_played(limit=limit)
    seen = set()
    tracks = []
    for item in results["items"]:
        track = item["track"]
        if track["uri"] in seen:
            continue
        seen.add(track["uri"])
        tracks.append(_track_summary(track))
    return tracks


def playlists(limit: int = 50) -> list[dict]:
    # 50 is the endpoint's per-page maximum. The old limit of 12 was sized for a
    # single horizontal strip on a phone; the landscape browse grid shows far
    # more than that at once.
    results = _client().current_user_playlists(limit=min(limit, 50))
    out = []
    for p in results["items"]:
        images = p.get("images", [])
        out.append(
            {
                "uri": p["uri"],
                "name": p["name"],
                "image": images[0]["url"] if images else None,
            }
        )
    return out


if DEMO_MODE:
    from app import demo_spotify

    # Demo mode replaces this module's public surface wholesale, so server.py's
    # routes are untouched and there's no `if DEMO_MODE` threaded through 24
    # functions. The names are listed explicitly rather than swept from dir():
    # a function present here but missing from demo_spotify raises immediately
    # on import, instead of a demo run quietly reaching the live Spotify API.
    for _name in (
        "get_access_token", "devices", "transfer_playback", "now_playing",
        "play", "pause", "next_track", "previous_track", "seek", "set_volume",
        "set_shuffle", "set_repeat", "queue", "liked_songs", "album_tracks",
        "play_uri", "play_uris", "play_context", "play_context_at",
        "playlist_tracks", "artist_albums", "search", "recently_played",
        "playlists",
    ):
        globals()[_name] = getattr(demo_spotify, _name)
    del _name
