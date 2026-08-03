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
SPOTIFY_SCOPES = (
    "streaming user-read-email user-read-private "
    "user-read-playback-state user-modify-playback-state user-read-currently-playing "
    "user-read-recently-played playlist-read-private"
)
