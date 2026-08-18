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
| **System** | Bluetooth pairing, touchscreen calibration, the on-screen keyboard, and which sections appear in the rail |

Shell furniture on every page: a clock, a weather chip, a kitchen-timer chip, and
a now-playing chip.

### System

The wall autostarts into the kiosk browser with no desktop behind it, so anything
that would normally live in a settings applet is unreachable without SSH. That is
what this page is for.

**Bluetooth.** Scan, pair, connect, disconnect, forget. Pairing also trusts and
connects in one go, because an untrusted device makes BlueZ ask for authorisation
on every reconnect and there is nobody standing there to answer — the speaker just
silently stops coming back after a power cycle.

`app/bluetooth_service.py` shells out to `bluetoothctl` rather than talking to
`org.bluez` over D-Bus. Pairing needs a registered *agent*, and `bluetoothctl`
already is one; doing it in-process would mean a D-Bus mainloop in a thread beside
Flask, and the venv has no `dbus` module anyway. The trade is that only devices
which pair without a passkey (speakers, headphones, most trackpads) work — a
device wanting a typed PIN needs an interactive agent this deliberately isn't.

Devices that never broadcast a name are filtered out of the list unless already
set up here; a scan in a house otherwise returns thirty phones showing as bare
MACs. BlueZ also *forgets* unpaired devices once discovery stops, so an empty list
right after a scan window closes is normal, not a fault.

**Auto-reconnect** (on by default) is the wall reaching out once a minute to
trusted devices that aren't connected. BlueZ does not cover this case: trusting a
device only makes the wall *accept* an incoming connection, and its `[Policy]`
reconnect plugin only retries after an *unexpected* disconnect of an
already-connected device. Neither covers what actually happens in a kitchen — the
speaker was off, and now it's on — and plenty of speakers just sit and wait rather
than initiating. Two behaviours worth knowing:

- Tapping **Disconnect** is remembered, so the loop doesn't undo it a minute later.
  Connecting or pairing again clears that.
- A device that is simply switched off backs off exponentially (1, 2, 4, 8 cycles)
  rather than being paged every minute forever. A success resets it.

**`paired` is not a reliable flag, and the code deliberately doesn't trust it.**
Measured on this wall's own speaker: it pairs without bonding (`Bonded: no`), so
BlueZ reports `Paired: no` for exactly as long as it is disconnected — which is
precisely when a reconnect is wanted. Worse, `bluetoothctl devices Paired` listed
*nothing* while `info` on the same device said `Paired: yes`; that filter appears
to track bonding. So the flags come from `bluetoothctl info` per device (only for
devices already associated with the wall, to keep the subprocess count down), and
both the UI and the reconnect loop key off **trusted**, which is what persists and
is what `pair()` sets.

"Let other devices find this wall" is off by default and times itself back off.
Pairing a speaker only needs the wall to scan, so being discoverable is exposure
with no upside.

**Touchscreen calibration.** Five crosshairs; tap the centre of each. The fit is a
least-squares affine solve (`app/system_service.py`), written into
`~/.config/labwc/rc.xml` as a libinput `<calibrationMatrix>` and applied by sending
labwc a SIGHUP.

Two things about it are load-bearing:

- It **composes** with the matrix already in force rather than replacing it. The
  taps were collected *through* the existing matrix, so treating the fit as
  absolute would apply the old correction twice and each pass would overshoot
  further instead of converging. Re-calibrating an already-good panel is a no-op,
  and `tests/api_checks.py` pins that.
- A new matrix is **on trial for 45 seconds** and undoes itself unless you tap
  "Keep it". A bad matrix makes the panel unusable, and the only other way back is
  SSH — so the revert has to happen without anyone being able to tap anything.
  Obvious nonsense (a big stretch, skew, or off-screen shift) is rejected outright
  rather than costing you the 45 seconds.

`~/.config/labwc/rc.xml` is **generated** from `deploy/labwc-rc.xml.template` —
hand edits are lost on the next calibration. Two traps if you edit the template:
XML comments cannot contain a doubled hyphen (so Chromium switches are written
there without their dashes), and `str.format` substitutes placeholders inside
comments too.

**On-screen keyboard.** The keyboard appears by itself whenever a text field takes
focus; the button here is for the one case that cannot work — a text box inside a
page embedded on the Web tab, where this page cannot see focus across origins. See
"Typing on the wall" below for why any of this needed fixing.

**Sections.** Switching a section off removes its rail icon and, for Groceries, its
block on the Today page. The route and the API keep serving, so nothing is deleted
and turning it back on is immediate. Calendar is not in the list — it is the reason
the thing is on the wall.

### Brightness and sleep

The brightness chip in the top bar (next to the timer chip) opens a slider plus the
sleep settings. It is shell furniture rather than a row on /system on purpose: the
moment you want it is the moment the wall is too bright to read comfortably, and that
should not be four taps away.

**There is no software backlight on this panel, and that shapes everything else.** It
answers no DDC/CI (`ddcutil detect` → "I2C slave address x37 is unresponsive") and an
HDMI output gets no `/sys/class/backlight` entry. So the slider darkens the *picture*
while the lamp stays lit, which means there is a floor — below roughly 20% the image
is gone but the wall still glows faintly, so `MIN_BRIGHTNESS` clamps there rather than
pretending. Anything genuinely dark has to power the output off. `ddcutil` and
`gammastep` were both installed, tried and removed; gamma was rejected because it
needs a resident process per level, snaps to full brightness if that process dies,
and is invisible to `grim`, so every change would need someone standing at the wall.

Sleep is staged, and the two stages are deliberately implemented in different places:

| Stage | After | What it is | Who owns it |
|---|---|---|---|
| Faint clock | 10 min idle, after dark | A full-bleed screen with a large dim clock | `static/nav.js` |
| Panel off | 40 min idle | The output actually powered down | `swayidle` + `wlopm` |

The split is not arbitrary. The faint-clock stage has to respond instantly and be
adjustable while you look at it, so it belongs in the page. Powering the panel off
must be wakeable when there is nothing on screen to tap *on* — if that depended on
our JavaScript, a page that had crashed or was mid-reload would leave a dark wall
recoverable only over SSH, which is the exact failure this feature is meant to avoid.
So it is `swayidle`, which listens to labwc's `ext_idle_notifier_v1` and fires
`resume` on **any** seat input before the page is involved. `wlopm` is used rather
than `wlr-randr --off` because it leaves the mode alone: the window is never
reconfigured and the page never reflows.

Auto-sleep is **night-gated by default** — a kitchen calendar that hides itself at 2pm
has stopped being a calendar. "Sleep now" works at any hour, and the gate can be
turned off.

Three things that are easy to get wrong here, all of which were:

- **The three dimmers multiply, and the product must be clamped.** brightness × night
  × sleep at their minimums is about 0.008 — a black screen, which cannot be tapped
  back because you cannot see what to tap. `MAX_DIM_OPACITY` is the guarantee that
  something stays visible; `tests/api_checks.py` mirrors the arithmetic so the clamp
  cannot quietly be dropped.
- **`#night-dim` needs `pointer-events: none`.** It is fixed and full-bleed, and it is
  now on screen at *any* brightness below 100%, so without that it hit-tests over the
  whole page and setting the wall to 90% made the calendar untappable. It got away
  with this while the overlay only appeared during after-dark dimming, where the
  capture-phase handler was consuming the tap anyway.
- **The wake handler keys off the resting *states*, not overlay visibility.** Gating
  on "is the overlay showing" would swallow the first tap at every brightness someone
  chose on purpose. Sleep swallows the waking tap; hand-dimming does not.

`/api/system/display` is read by the shell on every page load, so it returns stored
settings and nothing else. It briefly also reported the output's power state and
whether swayidle was up, which meant spawning `wlopm` and `pgrep` per page load —
enough added latency to start failing an unrelated Spotify layout test under load.
Those live at `/api/system/display/power` now.

Two things it does not fix: the 26px Chromium title strip does not dim with the page
(see below), so between the two sleep stages it is the brightest thing on the wall;
and `grim` fails outright while the output is powered off, which is worth knowing
before debugging that state.

### Typing on the wall

The on-screen keyboard was invisible for weeks, and the cause was not the keyboard.

labwc stacks a **fullscreen** window above the `wlr-layer-shell` "top" layer, and
"top" is the layer squeekboard uses. Under Chromium `--kiosk` (which implies
fullscreen) squeekboard was mapping its 1920x360 surface, loading its layout, and
reporting `Visible=true` over D-Bus the whole time — behind the page. Two earlier
rounds added the correct Chromium flags (`--enable-wayland-ime`,
`--wayland-text-input-version=3`) and concluded they didn't work. They did.

So `deploy/kiosk-launch.sh` now launches `--app=<url> --start-maximized` instead of
`--kiosk`. **Maximized, not a fixed 1920x1080**: squeekboard sets an exclusive zone,
so labwc shrinks a maximized window when the keyboard opens and the page reflows
above it rather than being covered.

Diagnosing this class of problem quickly:

```bash
# What squeekboard *thinks*. "true" with nothing on screen means a stacking
# problem, not a text-input problem.
busctl --user get-property sm.puri.OSK0 /sm/puri/OSK0 sm.puri.OSK0 Visible

# The discriminator: overlay draws above a fullscreen window, top does not.
labnag --message top --layer top --timeout 0
labnag --message overlay --layer overlay --timeout 0
```

The cost, and the dead ends, so they are not re-tried:

- `--app` mode makes Chromium draw its own 26px title strip, with minimise and
  close buttons. It is *client-side*: labwc `serverDecoration="no"`,
  `SetDecorations decorations="none"`, and a negative `<margin top="-26">` were all
  tried and none remove it. `ResizeTo`/`MoveTo` to a negative y is clamped.
- A tap on that **minimise** button would leave a blank wall that touching cannot
  recover — the browser is still running, so `kiosk-launch.sh`'s supervisor sees
  nothing wrong. `static/nav.js` watches for the document going hidden and asks the
  server to raise the window back. It has to come from the page because
  `wlrctl toplevel find state:minimized` does not work (always exits 1).
- `wf-panel-pi` is killed at launch, along with its `lwrespawn` supervisor. Its
  exclusive zone shrinks a *maximized* window; fullscreen used to just cover it.
- Chromium's Wayland `app_id` differs by mode — `chromium` under `--kiosk`,
  `chrome-127.0.0.1__-Default` under `--app`. A `chrome-*` window rule silently
  matches nothing in kiosk mode.

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
3. Add it to the Pi's `.env` — `~/calendar/wallCalendar/.env` — as
   `WALLCAL_POLLEN_KEY=...`, then `sudo systemctl restart wallcalendar`.
   `.env` is gitignored, so push-to-deploy never overwrites it and the key
   survives every deploy; equally, nothing propagates it for you.
4. Check it took, without printing the key:
   `curl -s localhost:5000/api/weather/air | python3 -m json.tool | grep source`
   — it should say `Google Pollen` rather than `pollen.com`.
5. Back it up into the private `wallCalendar-secrets` repo's `.env`, which is
   where the rest of this project's credentials are kept. That repo is a
   point-in-time backup, not a live mirror, so it needs doing by hand.

The key is sent to Google as an `X-Goog-Api-Key` **header**, never as a `?key=`
query parameter: `requests` includes the request URL in its exception messages, so
in query form a single logged traceback would print the credential. Error messages
here deliberately carry only the exception class for the same reason, and
`tests/api_checks.py` enforces both.

Pollen is billed under Google Maps Platform rather than being free. At one request
per 30 minutes this is roughly 1,500 calls a month; check the current free tier and
set a budget alert rather than taking that as a promise.

### Groceries

The household shopping list, read and written straight out of Daisy's Kitchen -
`groceryLists/{householdId}/items` on the `recipe-f644f` Firestore. A tick on the
wall shows up on the phone in the shop and vice versa, because it is the same list
and not a copy. `/groceries` groups it by aisle; `/today` carries a read-only
summary of it.

**This needs a credential, unlike Recipes.** Recipes are `allow read: if true`, so
that page is a keyless GET. Grocery lists are not - their rule is
`signedIn() && sharesHousehold(...)` - so an unauthenticated request is refused.
The wall therefore uses a **service account** on the recipes project, whose token
is admin access; Firestore rules don't apply to it, which is why no Firebase Auth
user, `users/` document or household membership has to be created for the wall.

One time, as `elijahcraig45@gmail.com`:

```bash
gcloud iam service-accounts create wall-calendar \
    --project recipe-f644f --display-name "Wall calendar"
gcloud projects add-iam-policy-binding recipe-f644f \
    --member serviceAccount:wall-calendar@recipe-f644f.iam.gserviceaccount.com \
    --role roles/datastore.user
gcloud iam service-accounts keys create secrets/recipes_service_account.json \
    --iam-account wall-calendar@recipe-f644f.iam.gserviceaccount.com \
    --project recipe-f644f
```

Then back the key up to the private `wallCalendar-secrets` repo. Override the path
with `WALLCAL_GROCERY_SA_FILE` if you keep it elsewhere.

Until that key exists the page renders an explained "not set up" state and says the
list is still on your phone - it is not an error, and nothing else on the wall is
affected. Which household's list to show is discovered automatically when the
project has exactly one; set `WALLCAL_HOUSEHOLD_ID` if there is more than one.

Two things worth not rediscovering:

- **Reads need no ingredient parsing.** Every item carries a stored `aisle` and a
  pre-rendered `quantityLabel`, put there by the app specifically so other clients
  can display the list without porting its Dart parser.
- **Adding an item by hand does.** The canonical name is the key the app merges on,
  so a Python answer that disagreed with Dart's would add a second "tomato" row
  instead of merging into the existing one. `app/groceries_service.py` ports
  `canonicalName`/`aisleFor` deliberately, and `tests/api_checks.py` reads the Dart
  source and fails if the two tables drift apart (skipped when the recipes repo
  isn't checked out beside this one).

### Notes — removed, and not coming back

Notes was built on **Google Tasks**, taken back out because the wall-side experience
wasn't good enough, and is now superseded by Groceries above - which is what it was
mostly being used for. The work is still in git if any of it is wanted.

Worth recording so it isn't rediscovered: **Google Keep cannot be used.** Its API is
Workspace-only, needs a service account with domain-wide delegation, and is
unavailable to personal accounts. Tasks was the consumer-account substitute.
Reinstating it would need the `auth/tasks` scope back in `GOOGLE_SCOPES` plus a
one-time `python cli.py google` re-consent, since Google doesn't grant scopes
retroactively.

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

Dimming is a dark overlay drawn over the page, not a backlight change, so the panel
still emits light — it just isn't showing a bright calendar. **This can't be
improved on the current monitor:** the ViewSonic TD2230 does not support DDC/CI
(probed with `ddcutil detect`; I2C slave address 0x37 is unresponsive), so there is
no way to set brightness from the Pi. Recorded here so it doesn't get investigated
twice — a different panel with DDC/CI support would allow real dimming.

A severe-weather warning overrides dimming: an urgent NWS alert wakes the screen and
draws a banner above the overlay. Only on arrival, though, never on every poll —
otherwise any active advisory would keep the wall lit all night.

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

**The wall is also a Spotify Connect target** — `bash deploy/librespot-setup.sh`,
which is installed and running on the Pi. Cast to "Wall Calendar" from any phone
on the network, with any Premium account, and none of the Development Mode limits
apply. Playback also survives a page reload, which the in-browser player does not —
and since a deploy reloads the wall, that matters.

Two things about that setup worth knowing before changing it:

- It runs as a **user** systemd service (`systemctl --user status librespot`), not
  raspotify's packaged system service, which is masked. PipeWire lives in the
  logged-in user's session, and a system unit can't reach that socket — it would be
  silent, or with the ALSA backend would take exclusive hold of the HDMI device and
  fight Chromium for it.
- A **Pi 5 has no 3.5mm jack**, so HDMI is the only output, and that works only
  because the TD2230 accepts audio over it (`/proc/asound/card0/eld#0` reports
  `speakers [0x1] FL/FR`). Swap in a monitor without speakers and you need a USB
  DAC or a Bluetooth speaker before any of this makes a sound.

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
