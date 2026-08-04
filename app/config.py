import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRETS_DIR = PROJECT_ROOT / "secrets"
TOKENS_DIR = SECRETS_DIR / "tokens"
TOKENS_DIR.mkdir(parents=True, exist_ok=True)

GOOGLE_CLIENT_SECRET_FILE = SECRETS_DIR / "google_client_secret.json"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    # lets us ask Google "who did you just sign in?" so tokens can be keyed
    # by whatever email comes back, instead of a pre-named account list.
    "https://www.googleapis.com/auth/userinfo.email",
    # requested explicitly because Google adds it server-side regardless;
    # omitting it here causes oauthlib to reject the granted-scope mismatch.
    "openid",
]

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
SPOTIFY_REDIRECT_URI = os.environ.get(
    "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback/spotify"
)
# streaming + user-read-* let this device register itself as a Spotify Connect
# playback target (Web Playback SDK), not just remote-control other speakers.
# user-library-read is for Liked Songs (GET /me/tracks) - added after the
# fact, so the already-signed-in account must re-run `python cli.py spotify`
# once to re-consent; Spotify doesn't retroactively grant new scopes to an
# existing refresh token, and spotipy invalidates the cached token entirely
# (breaking every endpoint, not just the new one) until that happens.
SPOTIFY_SCOPES = (
    "streaming user-read-email user-read-private "
    "user-read-playback-state user-modify-playback-state user-read-currently-playing "
    "user-read-recently-played playlist-read-private user-library-read"
)

# Must be loopback (127.0.0.1/localhost) to match the Google OAuth client's
# "Desktop app" type - and the kiosk must always be browsed at this exact
# host string, since both Flask's session cookie and Google's redirect-URI
# match are host-string-exact (mixing 127.0.0.1 and localhost surfaces as a
# confusing "state mismatch" error that isn't actually a bug).
GOOGLE_OAUTH_REDIRECT_URI = os.environ.get(
    "GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:5000/auth/google/callback"
)
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-insecure-change-me")
