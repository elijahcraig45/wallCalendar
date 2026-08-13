# Wall Calendar

A touchscreen wall calendar for a Raspberry Pi 5 (**landscape mount**): shared
Google Calendar view plus Spotify control. Runs as a local Flask app, meant to be
opened full-screen in a kiosk browser.

The shell is a persistent left rail — Today / Calendar / Recipes / Music / Web / Accounts — so every
destination is one tap from anywhere. It replaced a hamburger drawer, which cost
two taps and hid where you could go.

## What's on it

| Destination | What it does |
|---|---|
| **Today** | The morning screen: weather, today's schedule, and the next few days. Composed purely from the other endpoints, so it can't disagree with them. |
| **Calendar** | Day / Week / Month / Agenda (see below) |
| **Recipes** | Your own Daisy's Kitchen library, read straight from its Firestore, with a hands-free cooking mode |
| **Music** | Spotify (see Music, below) |
| **Web** | A framed browser that cannot strand the wall |
| **Accounts** | Google sign-in and per-account health |

Shell furniture on every page: a clock, a weather chip, a kitchen-timer chip, and
a now-playing chip.

### Weather

Conditions, hourly, and ten days come from **Open-Meteo** — no API key, no account,
nothing to expire. Set `WALLCAL_LAT`, `WALLCAL_LON` and `WALLCAL_PLACE` in `.env`;
it defaults to Atlanta. It also supplies the real sunrise/sunset that night dimming
keys off.

The `/weather` page adds three more sources, each degrading independently so one
outage never blanks the page:

| Data | Source | Key needed | Cadence |
|---|---|---|---|
| Conditions, hourly, 10 days | Open-Meteo | no | 15 min |
| Severe alerts | NWS `api.weather.gov` | no | 3 min |
| Radar loop | NWS RIDGE (animated GIF) | no | 4 min |
| Air quality (US AQI) | Open-Meteo air-quality | no | 30 min |
| Pollen | Google Pollen, else pollen.com | optional | 30 min |

**On lightning:** there is no free public feed of individual strikes, so the page
does not pretend to be a detector. Open-Meteo accepts a `lightning_potential`
variable and returns all nulls for US locations — it's a European-model field.
Thunderstorms are covered by NWS severe-thunderstorm/tornado warnings, CAPE as an
instability measure, and the radar loop.

#### Pollen

Two providers. **Google's Pollen API** is used when `WALLCAL_POLLEN_KEY` is set: it
is documented and supported, and it gives separate grass/tree/weed indices, the
specific plants in season, and a health note. Without a key — or if Google fails —
it falls back to **pollen.com**, which needs no credential but is an *undocumented*
endpoint (it answers 405 without a `Referer`) and may vanish without notice.

The two use different scales: Google's Universal Pollen Index is **0–5**, pollen.com's
is **0–12**. They are never mixed — each reading carries its own scale, the dial is
coloured against that scale, and the range is printed next to the source. A "4"
means High on one and Low-medium on the other.

To set up the Google key:

1. In the GCP project, enable **Pollen API**.
2. Create an API key and **restrict it to the Pollen API only** (Credentials →
   the key → API restrictions). It is otherwise usable against every enabled API
   in the project.
3. Add it to `.env` — which is gitignored — as `WALLCAL_POLLEN_KEY=...`, then
   restart: `sudo systemctl restart wallcalendar`.
4. Check it took, without printing the key:
   `curl -s localhost:5000/api/weather/air | python3 -m json.tool | grep source`

The key is sent to Google as an `X-Goog-Api-Key` **header**, never as a `?key=`
query parameter: `requests` includes the request URL in its exception messages, so
in query form a single logged traceback would print the credential. Error messages
here deliberately carry only the exception class for the same reason, and
`tests/api_checks.py` enforces both.

Pollen is billed under Google Maps Platform rather than being free. At one request
per 30 minutes this is roughly 1,500 calls a month; check the current free tier and
set a budget alert rather than taking that as a promise.

### Notes — removed for now

Notes was built on **Google Tasks** and then taken back out: it wasn't good enough
to keep on the wall. The work is in git rather than deleted - bring it back with
`git revert <the removal commit>`, or cherry-pick the pieces.

Worth recording so it isn't rediscovered: **Google Keep cannot be used.** Its API is
Workspace-only, needs a service account with domain-wide delegation, and is
unavailable to personal accounts. Tasks was the consumer-account substitute, and it
does put notes on your phone in the Tasks app and inside Google Calendar - the
mechanism was fine, the wall-side experience wasn't. Reinstating it needs the
`auth/tasks` scope back in `GOOGLE_SCOPES` plus a one-time `python cli.py google`
re-consent.

### Recipes

`firestore.rules` in [daisys-kitchen](https://github.com/elijahcraig45/daisys-kitchen)
grants `allow read: if true` on the recipes collection, so the wall reads it over
plain HTTPS with **no auth, no API key and no Firebase SDK** — just
`WALLCAL_RECIPES_PROJECT` (default `recipe-f644f`). Reading the source of truth
rather than framing the Flutter app is what makes a **cooking mode** possible: one
step at a time in type readable across a kitchen, with the step's timer one tap
away. The deployed app is still reachable from the Web page as a fallback.

The schema already carries `timerSeconds`/`timerLabel` per step; none of the real
recipes set them yet, and when they do the timer button appears automatically.

### Kitchen timers

Multiple named countdowns, a WebAudio chime (no audio file to ship), and state
stored as **absolute end timestamps in localStorage** — so a timer started from a
recipe keeps running while you walk over to the calendar, and survives a page
reload without drifting. Browsers refuse audio before a user gesture, so the audio
context is primed on first touch; a timer that finishes before anyone has touched
the screen still shows visually and wakes a dimmed display.

### Ambient

The screen dims after dark and any touch wakes it for a few minutes. The schedule
follows real sunset/sunrise from the weather rather than a fixed hour, falling back
to 22:00–06:00 when weather is unavailable.

### Event colours come from Google

An event takes its own `colorId` if it has one, otherwise its **calendar's** colour
— so "Family" is the same orange on the wall as on a phone. Measured against the
real account: 0 of 156 events set an explicit colorId, so in practice the calendar
colour is what shows. Google's palette is light chips with dark text, and the
foreground it supplies is carried through — white on `#fbd75b` would be unreadable.

Events are the one thing a theme never recolours, for exactly this reason.

### Multi-day events span their days

All-day events render as **bars spanning the days they cover**, packed into lanes,
not as a chip repeated in every cell — a four-day trip previously looked like four
unrelated one-day events. A bar clipped by the week edge is squared off on that side
and prefixed with `‹` when it continues from the previous week.

Month cells render every timed event and are then **trimmed to fit by measurement**
(`trimCellsToFit`), replacing what doesn't fit with "+N more". An earlier version
computed a capacity up front and kept getting it wrong — it has to account for the
day number, that week's span lanes, cell padding, grid gaps and the font's real line
height, and any miss shows up as silently clipped events.

### Themes — `static/themes.js`

That file is the whole theming system and is written to be edited. A theme is a
palette:

```js
{ name: "August — heat", accent: "#e0873c", secondary: "#8c4a2f",
  base: "#15100c", surface: "#241a13", lines: "#4a3527", strength: 1.0 }
```

Only `accent` is required; everything else is derived from it, so
`{ accent: "#8a6fd4" }` is a valid theme. `strength` scales every translucent tint
at once (0 = off, 1 = default, 1.6 = bold). Text colour, contrast and type never
change at any strength — this is read from across a room.

Try one live without deploying, from devtools on the wall:

```js
localStorage.wallcal_theme = JSON.stringify({ name: "test", accent: "#8a6fd4", strength: 1.4 });
location.reload();
```

`wallcal_themes` (an array of twelve) overrides the whole year;
`calendar_themes = "off"` returns to flat dark mode. Full instructions, and notes on
which colours actually work over a dark ground, are in the header of `themes.js`.

The first attempt at theming changed only the accent and a 6%-alpha wash — measured
at 900 of 1,906,560 pixels, 0.05% of the screen, and invisible from a chair. If you
tighten it again, check it on the wall, not in a browser a foot from your face.

## Views

| View | What it's for |
|---|---|
| Day | Hour grid for one day plus a detail pane listing that day's events with location and owner |
| Week | Seven-column hour grid, all-day band on top, current-time line |
| Month | 7×N grid; all-day events as color bars, timed events as dot + time + title |
| Agenda | Next 30 days as balanced columns across the full width |

Layout notes worth knowing before changing them:

- **The time grid shows a window of hours, not midnight-to-midnight.** The window
  is derived from the events on screen (waking-hours default, widened for
  anything outside it, always covering the current hour when today is visible),
  and hours stretch to fill the available height. A normal week needs no
  scrolling at all.
- **Month cells compute how many events they can show** from measured cell
  height rather than a fixed count — a 1024×600 panel has roughly half the cell
  height of a 1080p one. `--pill-height` / `--day-number-height` /
  `--overflow-height` are plain px per breakpoint *on purpose*: `calendar.js`
  reads them back with `getPropertyValue()`, and a `clamp()` expression comes
  back as literal text rather than a number.
- **Everything sizes in `rem`** off a single `clamp()`ed root font-size, so the
  whole UI scales with the panel.
- **`.hidden` carries `!important`, on purpose.** It's the one utility the whole
  app toggles from JS, and any `#thing { display: flex }` outranks a plain class
  regardless of source order. That trap was hit four separate times (a rail chip
  shipped visible where it should have been suppressed; all three Recipes views
  rendered stacked; the stale badge and weather chip could not be hidden). Each
  time the element was present, correct, and simply would not go away. `npm test`
  asserts the `!important` is still there.
- **The frontend is plain scripts sharing one global scope, not modules.** Four
  shell scripts load on every page, then one page script — and a page script
  declaring the same top-level name silently replaces the shell's. `timers.js` had
  `render()`, `notes.js` had `render(payload)`, and the shell's per-second tick
  then called the notes renderer with no argument, throwing every second on that
  page. `npm test` now detects name collisions statically; shell-wide files use
  prefixed names (`renderTimers`, `loadTimers`) for the same reason.
- **Watch asterisks inside CSS comments.** `#device-*/#playlist-*` contains `*/`,
  which closes the comment early; the leftover prose then parses as a broken
  selector whose error recovery swallows the *next whole rule*. That silently
  killed `.modal-overlay` for a long time, so the day-event overlay rendered inline
  in the page instead of as a centered modal.
- After 4 minutes of no touch the calendar closes anything open and returns to
  the current month, so a wall left on next March doesn't stay there.

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

Open `http://localhost:5000` - defaults to the calendar month view. The left rail
reaches Music, Web and Accounts.

### Demo mode

```bash
WALLCAL_DEMO=1 python server.py                          # two synthetic people
WALLCAL_DEMO=1 WALLCAL_DEMO_ACCOUNTS=1 python server.py  # one, as the real wall is today
```

Swaps every Google Calendar read for synthetic fixtures (`app/demo_data.py`) -
deliberately dense, with overlapping, multi-day, all-day and late-night events,
so layout work can be done and screenshotted without touching a real calendar.
Writes raise rather than being faked, so a demo run can never look like it saved
something that went nowhere.

Demo mode covers Spotify too (`app/demo_spotify.py`), and it exists for a
different reason: the live API answers `now_playing` with null and `devices` with
`[]` whenever nothing happens to be playing, so the biggest surface on the Music
page can't be designed or verified against a real account at all. Two deliberate
differences from the calendar fixtures — playback commands are **faked rather than
refused** (there's no real data to corrupt, and the UI is only testable if
pressing play actually plays), and cover art is generated inline as SVG data URIs,
so a demo run makes no external image requests. The Web Playback SDK isn't loaded
in demo mode; it has no session to authenticate and only produces console noise.

## Layout tests

```bash
npm install && npx playwright install chromium   # once
npm test
```

Playwright starts two app instances itself - :5000 with two synthetic people and
:5001 with none (for the empty state) - so **stop any `server.py` you have running
first**; both ports must be free or the run fails immediately, on purpose.

Playwright starts the app in demo mode itself and checks every view at
**1024×600** (official Pi 7" DSI), **1280×800** (newer 7") and **1920×1080**.
These are correctness checks, not pixel comparisons: cells clipping their own
content, a time grid that overflows or opens scrolled, concurrent events drawn on
top of each other, a page that scrolls sideways, sheets off-screen.

`tests/wall.spec.js` covers the calendar and shell; `tests/spotify.spec.js`
covers the Music page. Because demo playback state is real, the Spotify tests
assert round-trips — play/pause flips, Next lands on a different track, tapping a
row in a playlist starts *that* track — rather than just that the buttons exist.

`npm test` also runs `tests/api_checks.py` first — plain Python, no pytest, so
nothing extra has to be installed on the Pi:

```bash
npm run test:api     # server-side checks only
npm run test:ui      # Playwright only
```

Those cover states that need the server *rigged* rather than driven, which a
browser can't do: an install with no Spotify account signed in (the default after
setup — this used to make the shell's poll 500 every five seconds forever), demo
mode refusing calendar writes, the month-grid bounds arithmetic, and two static
checks that exist because their bugs were invisible at runtime — global script name
collisions, and `.hidden` keeping its `!important`.

### A note on developing this on a work laptop

The Home Depot's TLS-inspecting proxy re-signs HTTPS, and Python's `requests` uses
certifi rather than the macOS keychain — so `curl` works and `requests` fails with
`SSLError` for weather, recipes and anything else outbound. Nothing is wrong with
the code and **certificate verification is not disabled**; set `REQUESTS_CA_BUNDLE`
to a bundle containing the corporate root if you want it working there. On the Pi at
home there's no proxy. Where the live call couldn't be made here, the parser was
verified against a real payload captured over `curl` instead.

One lesson encoded in both suites: **assert geometry, not counts.** The queue view
once rendered with bullet points and a full-width album cover, and a row-count
assertion passed the entire time because all the rows were present.

One test re-runs the month and week views with everything forced to **Verdana**.
Raspberry Pi OS has none of `-apple-system` / Segoe UI / Roboto and renders in
DejaVu Sans, which is wider than any Mac default - Verdana is wider still, so
passing under it means the layout has real slack rather than being tuned to
macOS font metrics. Screenshots land in `test-results/shots/` (override with
`SHOT_DIR`).

If your panel isn't one of those three resolutions, add it to `VIEWPORTS` in
`tests/wall.spec.js` and re-run before trusting the layout on it.

## Music

Two panes, not the phone shape this started as. Now-playing holds permanent space
on the left (large art, transport, scrub, volume, current speaker); browse, search
and every detail view share the column on the right. What used to be a
mini-player that expanded to a full-screen overlay plus four bottom sheets is now
one pane you never have to dismiss to see what's playing.

- **Detail views are panes, not sheets.** `initPane` in `static/spotify.js` keeps
  `initPanel`'s `{open, close}` shape, so the fetch/render logic that drove the
  old sheets is unchanged. A small back stack means Back walks album → artist →
  home rather than always dumping you at home.
- **The search field is in the pane's persistent header**, so typing while a
  detail view is open resets the pane to home first — results render there, and
  without the reset typing appeared to do nothing.
- **A now-playing chip lives in the rail on every page**, so music is visible and
  pausable from the calendar. One shared poller in `nav.js` feeds both it and the
  Music page rather than each polling separately — every 5s on the Music page,
  where a progress bar has to look live, and every 20s elsewhere.
- **Any page other than the calendar returns to the calendar after 10 minutes
  idle** (`nav.js`). The calendar's own 4-minute reset only ever ran on the
  calendar; the rail made "left on Music forever, showing no calendar at all" the
  more likely failure.

### Playback: two routes, and the browser one is the fragile one

The in-page Web Playback SDK needs Widevine DRM **and** Premium on the display
itself, and Chromium on Pi OS arm64 is a shaky place to depend on that — driving
the page under headless Chromium fails with `No supported keysystem was found`,
exactly what a Widevine-less build reports. When the SDK never registers a
device, the device picker now says so instead of offering a display that can't
play anything.

The sturdier route is `bash deploy/librespot-setup.sh`, which makes the Pi a
Spotify Connect speaker: everyone casts from the full Spotify app on their own
phone with their own account, which sidesteps every limit listed below —
Development Mode's 25-user cap, the 10-result search, the missing radio. The two
coexist; the Pi shows up in the wall's own device picker as another speaker.
**That script has never run on hardware.** See `deploy/README.md`.

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
- **Some playlists can't be read at all.** Measured against the real account:
  `/tracks` 403s for *every* playlist (as above), and `/items` 403s for *some* -
  it correlates with playlists owned by other people, though not reliably (one
  other-user playlist read fine). Spotify's actual rule isn't discoverable from
  outside and there's no remaining endpoint to fall back to, so the app reports
  it: the track list shows an explanation and a toast instead of spinning on
  "Loading..." forever. This is the clearest ongoing argument for the Connect
  route - a phone casting to the Pi has no such restriction.
