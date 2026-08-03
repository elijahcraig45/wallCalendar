import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import spotipy
from spotipy.cache_handler import CacheHandler, MemoryCacheHandler
from spotipy.oauth2 import SpotifyPKCE

from app.config import SPOTIFY_CLIENT_ID, SPOTIFY_REDIRECT_URI, SPOTIFY_SCOPES
from app.token_store import list_accounts, load_token, save_token

PROVIDER = "spotify"


class _StoreCacheHandler(CacheHandler):
    """Backs spotipy's auto-refresh with our own token store instead of its
    default per-file cache, so lookups stay keyed by account email."""

    def __init__(self, email: str):
        self.email = email

    def get_cached_token(self):
        return load_token(PROVIDER, self.email)

    def save_token_to_cache(self, token_info):
        save_token(PROVIDER, self.email, token_info)


class _OneShotCallbackServer:
    """Captures a single OAuth redirect (?code=...) on the registered
    redirect URI, then shuts itself down."""

    def __init__(self, redirect_uri: str):
        parsed = urllib.parse.urlparse(redirect_uri)
        self.host = parsed.hostname
        self.port = parsed.port

    def wait_for_code(self) -> str:
        captured = {"code": None}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                query = urllib.parse.urlparse(self.path).query
                params = urllib.parse.parse_qs(query)
                captured["code"] = params.get("code", [None])[0]
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body>Signed in - you can close this tab.</body></html>"
                )

            def log_message(self, *args):
                pass

        server = HTTPServer((self.host, self.port), Handler)
        server.handle_request()  # blocks for exactly one request
        server.server_close()
        return captured["code"]


def sign_in() -> str:
    """Opens a browser for the interactive OAuth flow. Whoever signs in there
    is whoever gets saved - there's no pre-named account list. Returns their
    Spotify account email (or id if the account has no public email)."""
    auth_manager = SpotifyPKCE(
        client_id=SPOTIFY_CLIENT_ID,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPES,
        cache_handler=MemoryCacheHandler(),
        open_browser=False,
    )

    authorize_url = auth_manager.get_authorize_url()
    callback_server = _OneShotCallbackServer(SPOTIFY_REDIRECT_URI)

    webbrowser.open(authorize_url)
    code = callback_server.wait_for_code()
    auth_manager.get_access_token(code, check_cache=False)
    # get_access_token() only returns the bare access token string, but it
    # saves the full token dict (with refresh_token) into the cache handler
    # as a side effect - pull it back out from there.
    token_info = auth_manager.cache_handler.get_cached_token()

    sp = spotipy.Spotify(auth=token_info["access_token"])
    me = sp.current_user()
    identifier = me.get("email") or me["id"]

    save_token(PROVIDER, identifier, token_info)
    return identifier


def get_client(email: str) -> spotipy.Spotify:
    if load_token(PROVIDER, email) is None:
        raise ValueError(f"No saved Spotify token for {email}. Run sign_in() first.")

    auth_manager = SpotifyPKCE(
        client_id=SPOTIFY_CLIENT_ID,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPES,
        cache_handler=_StoreCacheHandler(email),
        open_browser=False,
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def signed_in_accounts() -> list[str]:
    return list_accounts(PROVIDER)


def get_access_token(email: str) -> str:
    """A bare access token string, refreshed if needed - for handing to the
    Web Playback SDK, which runs in the browser and manages its own auth
    header rather than going through spotipy."""
    if load_token(PROVIDER, email) is None:
        raise ValueError(f"No saved Spotify token for {email}. Run sign_in() first.")

    auth_manager = SpotifyPKCE(
        client_id=SPOTIFY_CLIENT_ID,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPES,
        cache_handler=_StoreCacheHandler(email),
        open_browser=False,
    )
    return auth_manager.get_access_token()
