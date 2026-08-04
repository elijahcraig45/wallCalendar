import requests

from app.auth import spotify_auth

PLAYLIST_ITEMS_URL = "https://api.spotify.com/v1/playlists/{playlist_id}/items"


def _client():
    accounts = spotify_auth.signed_in_accounts()
    if not accounts:
        raise ValueError("No Spotify account signed in. Run `python cli.py spotify`.")
    return spotify_auth.get_client(accounts[0])


def get_access_token() -> str:
    accounts = spotify_auth.signed_in_accounts()
    if not accounts:
        raise ValueError("No Spotify account signed in. Run `python cli.py spotify`.")
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


def playlists(limit: int = 12) -> list[dict]:
    results = _client().current_user_playlists(limit=limit)
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
