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

# Demo mode swaps every Google Calendar read for synthetic fixtures (see
# app/demo_data.py) so the layout can be developed and screenshot-verified
# without touching anyone's real calendar. Writes are rejected rather than
# faked - a demo run should never look like it saved something it didn't.
DEMO_MODE = os.environ.get("WALLCAL_DEMO") == "1"

# Weather location. Open-Meteo needs no key, so coordinates are the only config -
# defaults to Atlanta. Override in .env with WALLCAL_LAT / WALLCAL_LON /
# WALLCAL_PLACE (the label is cosmetic; only the coordinates affect the forecast).
WEATHER_LAT = float(os.environ.get("WALLCAL_LAT", "33.749"))
WEATHER_LON = float(os.environ.get("WALLCAL_LON", "-84.388"))
WEATHER_LABEL = os.environ.get("WALLCAL_PLACE", "Atlanta")
# pollen.com is keyed by ZIP rather than coordinates, and there is no keyless
# lat/lon-to-ZIP lookup worth adding a dependency for. One config value instead.
WEATHER_ZIP = os.environ.get("WALLCAL_ZIP", "30303")

# Google's Pollen API, if you have a key for it. Optional on purpose: without one,
# pollen falls back to pollen.com, which needs no credential. Enable "Pollen API"
# in the GCP project, create an API key, restrict it to that one API, and put it in
# .env as WALLCAL_POLLEN_KEY.
#
# Passed to Google as an X-Goog-Api-Key HEADER rather than a ?key= query
# parameter. Google accepts both, and the query form ends up inside request URLs -
# which requests puts into exception messages, so a single logged traceback would
# print the key. A header can't leak that way.
POLLEN_API_KEY = os.environ.get("WALLCAL_POLLEN_KEY") or None

# Daisy's Kitchen (github.com/elijahcraig45/daisys-kitchen). Its Firestore rules
# make the recipes collection publicly readable, so this project id is the only
# configuration needed - no API key, no service account, nothing secret.
RECIPES_PROJECT_ID = os.environ.get("WALLCAL_RECIPES_PROJECT", "recipe-f644f")

# The grocery list, from the same app - but unlike recipes it is NOT public. Its
# rules are `signedIn() && sharesHousehold(...)`, so a keyless GET is refused and
# this needs a real credential: a service account on the recipes project with
# roles/datastore.user. A service-account token is admin access, so Firestore
# rules do not apply to it and no household membership has to be plumbed through.
#
# Optional on purpose, in the same way POLLEN_API_KEY is: without the key the
# Groceries page renders an explained "not set up" state instead of failing, and
# every other page is unaffected. See app/groceries_service.py for the setup steps.
GROCERY_SA_FILE = Path(
    os.environ.get("WALLCAL_GROCERY_SA_FILE", str(SECRETS_DIR / "recipes_service_account.json"))
)
# Which household's list to show. Discovered automatically when the project has
# exactly one list, so this only has to be set for a multi-household project.
GROCERY_HOUSEHOLD_ID = os.environ.get("WALLCAL_HOUSEHOLD_ID") or None

# How many people the fixtures pretend are signed in. Defaults to 2 to
# exercise per-person colors, but 1 is the state the real wall is in today
# (a single signed-in account), so both are worth being able to render.
DEMO_ACCOUNT_COUNT = int(os.environ.get("WALLCAL_DEMO_ACCOUNTS", "2"))
