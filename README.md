# Wall Calendar

A touchscreen wall calendar for a Raspberry Pi 5 (portrait mount): shared Google
Calendar view plus Spotify control. Runs as a local Flask app, meant to be
opened full-screen in a kiosk browser.

## Stack

- Backend: Flask (`server.py`), Python 3.13
- Frontend: server-rendered Jinja templates + vanilla JS, no build step
- Calendar: Google Calendar API, OAuth "Desktop app" client, multiple Google
  accounts signed in independently (tokens keyed by whichever email signs in -
  nothing is pre-named)
- Spotify: Web API (search/playlists/browsing) + Web Playback SDK (makes the
  page itself a Spotify Connect device, so the Pi's onboard speakers are the
  default playback target)

## One-time setup

### Google

1. GCP project `wall-calendar-260801-1510` already has the Calendar API
   enabled and an OAuth consent screen configured (Production status, not
   Testing - Testing-status tokens expire after 7 days).
2. Download the **Desktop app** OAuth client JSON from Google Auth Platform →
   Clients, and save it as `secrets/google_client_secret.json`. Must have an
   `"installed"` top-level key, not `"web"` - if it's `"web"`, you created a
   Web application client by mistake, not Desktop app.

### Spotify

1. Create an app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
2. Add redirect URI `http://127.0.0.1:8888/callback/spotify`.
3. Copy `.env.example` to `.env` and fill in `SPOTIFY_CLIENT_ID` (the Client
   ID only - PKCE means no secret is needed).
4. While the app is in Development Mode, add every account that needs access
   under Users and Access (max 25).

### Local environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in SPOTIFY_CLIENT_ID
cp data/account_labels.json.example data/account_labels.json  # fill in real names
```

### Sign in accounts

```bash
python cli.py google      # opens a browser, whoever signs in gets saved
python cli.py spotify     # same, for Spotify
python cli.py calendars   # lists every calendar visible to signed-in Google accounts
python cli.py test        # sanity-checks both providers end to end
```

Run `python cli.py google` / `python cli.py spotify` again for each additional
person - tokens are stored separately per account under `secrets/tokens/`.

To hide a calendar from the display, add its `calendar_id` (from
`python cli.py calendars`) to `excluded_calendar_ids` in
`data/calendar_prefs.json`.

## Running

```bash
python server.py
```

Open `http://localhost:5000` - defaults to the calendar month view. Hamburger
menu (top-left) reaches Spotify and Browser.

## Known platform limits (not bugs)

- **Spotify `/search` and `/artist/{id}/albums` cap `limit` at 10** for apps
  without extended quota access, regardless of what the docs say (up to 50).
- **No Spotify radio/recommendations.** `/recommendations`,
  `artist_top_tracks`, and `related_artists` are all permanently blocked for
  apps without pre-existing extended quota (Spotify deprecated these in Nov
  2024 with no replacement). Artist pages show real discography (via
  `artist_albums`) instead of algorithmic picks.
- **No lyrics.** Spotify's public API has never exposed lyrics; the real app
  uses a licensed Musixmatch integration unavailable to third-party apps.
- **Playlist tracks** use `/v1/playlists/{id}/items` directly via `requests`,
  not spotipy's `playlist_items()` - spotipy still calls the old `/tracks`
  path, which Spotify deprecated (403s) in its March 2026 API migration.
