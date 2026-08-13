/* Shell behavior shared by every page: rail highlight, the wall clock, toasts,
   and the idle timer that individual pages hook to return themselves to a
   resting state. */

document.querySelectorAll(".rail-item").forEach((item) => {
  if (item.dataset.nav === window.location.pathname) item.classList.add("active");
});

/* ---------- wall clock ---------- */

const clockTime = document.getElementById("clock-time");
const clockDate = document.getElementById("clock-date");

function renderClock() {
  const now = new Date();
  clockTime.textContent = now.toLocaleTimeString(undefined, {
    hour: "numeric", minute: "2-digit",
  });
  clockDate.textContent = now.toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });
}

renderClock();
// Align the tick to the real minute boundary before settling into a 60s
// interval - a plain setInterval from load time would leave the displayed
// minute up to 59 seconds stale.
setTimeout(() => {
  renderClock();
  setInterval(renderClock, 60 * 1000);
}, (60 - new Date().getSeconds()) * 1000);

/* ---------- toast ---------- */

let toastTimer = null;

function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add("hidden"), 3500);
}

/* ---------- shared now-playing ----------
   One poll for the whole page, published to whoever wants it: the rail chip
   below always, and the Spotify page's own renderer when it's loaded. Two
   independent pollers would double the request rate for the same data. */

const nowPlayingListeners = [];

function onNowPlaying(listener) {
  nowPlayingListeners.push(listener);
}

async function refreshNowPlaying() {
  let data = null;
  try {
    const resp = await fetch("/api/spotify/now-playing");
    // A wall with no Spotify account signed in (or a demo-mode calendar) must
    // not spew errors every five seconds - no music is a normal state here.
    data = resp.ok ? await resp.json() : null;
  } catch (e) {
    data = null;
  }
  nowPlayingListeners.forEach((listener) => listener(data));
}

const railNowPlaying = document.getElementById("rail-now-playing");
const railArt = document.getElementById("rail-np-art");
const railTitle = document.getElementById("rail-np-title");
const railPlay = document.getElementById("rail-np-play");
const railPause = document.getElementById("rail-np-pause");
// Redundant on the Spotify page itself, which shows a full now-playing pane.
const railChipWanted = window.location.pathname !== "/spotify";

let railIsPlaying = false;

onNowPlaying((data) => {
  if (!railChipWanted || !data) {
    railNowPlaying.classList.add("hidden");
    return;
  }
  railNowPlaying.classList.remove("hidden");
  if (data.album_art) {
    railArt.src = data.album_art;
  } else {
    // Leaving a stale or empty src would show the previous track's art or a
    // broken-image icon.
    railArt.removeAttribute("src");
  }
  railTitle.textContent = data.track || "";
  railNowPlaying.title = data.artist ? `${data.track} — ${data.artist}` : data.track || "";
  railIsPlaying = !!data.is_playing;
  railPlay.classList.toggle("hidden", railIsPlaying);
  railPause.classList.toggle("hidden", !railIsPlaying);
});

document.getElementById("rail-np-toggle").addEventListener("click", async (e) => {
  e.preventDefault();
  await fetch(railIsPlaying ? "/api/spotify/pause" : "/api/spotify/play", { method: "POST" });
  refreshNowPlaying();
});

refreshNowPlaying();
// The Music page shows a progress bar that has to look live; the rail chip only
// shows art, a title and a play state. No reason to poll Spotify twelve times a
// minute forever from the page the wall actually sits on.
setInterval(refreshNowPlaying, railChipWanted ? 20000 : 5000);

/* ---------- monthly themes ----------
   The accent colour and a faint background wash shift with the month, so the wall
   feels seasonal instead of identical all year. Deliberately limited to those two
   things: text colour, contrast and type never move, because this is read from
   across a room and legibility isn't up for negotiation. Set
   localStorage.calendar_themes = "off" to switch it off.

   Lives in the shell, not on the calendar page: --accent is used by every
   page, so defining it only in calendar.js meant Today/Notes/Recipes/Music
   all sat on the default blue while the calendar was amber - which reads as a
   bug rather than a theme. calendar.js still calls this with whatever month is
   being browsed. */
const MONTH_THEMES = [
  { accent: "#7aa2d6", wash: "rgba(122, 162, 214, 0.05)" }, // Jan - cold light
  { accent: "#c98bb0", wash: "rgba(201, 139, 176, 0.05)" }, // Feb
  { accent: "#6fae7c", wash: "rgba(111, 174, 124, 0.05)" }, // Mar - first green
  { accent: "#7bbf6a", wash: "rgba(123, 191, 106, 0.06)" }, // Apr
  { accent: "#9ac45c", wash: "rgba(154, 196, 92, 0.06)" },  // May
  { accent: "#4fb3a6", wash: "rgba(79, 179, 166, 0.06)" },  // Jun
  { accent: "#e8a33d", wash: "rgba(232, 163, 61, 0.06)" },  // Jul - high summer
  { accent: "#e0873c", wash: "rgba(224, 135, 60, 0.06)" },  // Aug
  { accent: "#c9772f", wash: "rgba(201, 119, 47, 0.06)" },  // Sep
  { accent: "#d2652f", wash: "rgba(210, 101, 47, 0.07)" },  // Oct
  { accent: "#a8613f", wash: "rgba(168, 97, 63, 0.06)" },   // Nov
  { accent: "#5f93c4", wash: "rgba(95, 147, 196, 0.05)" },  // Dec
];

const DEFAULT_ACCENT = "#4285F4";

function applyMonthTheme(monthNumber) {
  const root = document.documentElement;
  if (localStorage.getItem("calendar_themes") === "off") {
    root.style.setProperty("--accent", DEFAULT_ACCENT);
    root.style.setProperty("--month-wash", "transparent");
    return;
  }
  const theme = MONTH_THEMES[(monthNumber - 1) % 12];
  root.style.setProperty("--accent", theme.accent);
  root.style.setProperty("--month-wash", theme.wash);
}

// Whatever month it is right now, before any page-specific script runs.
applyMonthTheme(new Date().getMonth() + 1);

/* ---------- night dimming ----------
   A wall display at full brightness in a dark room is the reason these things get
   unplugged. The schedule follows real sunset/sunrise from the weather data
   (weather.js publishes it) rather than a hardcoded hour, so it tracks the season;
   if weather is unavailable it falls back to a fixed evening window. Any touch
   wakes it for a few minutes. */

const NIGHT_DIM_OPACITY = 0.82;
const WAKE_MINUTES = 3;
const FALLBACK_DIM_HOUR = 22;
const FALLBACK_WAKE_HOUR = 6;

const nightDim = document.getElementById("night-dim");
let sunTimes = null;
let awakeUntil = 0;

function minutesOfDay(date) {
  return date.getHours() * 60 + date.getMinutes();
}

function isNightNow() {
  const now = new Date();
  if (sunTimes && sunTimes.sunrise && sunTimes.sunset) {
    const sunset = new Date(sunTimes.sunset);
    const sunrise = new Date(sunTimes.sunrise);
    // Compared as minutes-of-day, not absolute times: the payload's sunrise is
    // *today's*, which is in the past by evening, so comparing timestamps
    // directly would read as night all afternoon.
    const nowMinutes = minutesOfDay(now);
    // A little after sunset, not exactly at it - it isn't actually dark yet.
    const dimAt = minutesOfDay(sunset) + 30;
    const wakeAt = minutesOfDay(sunrise);
    return nowMinutes >= dimAt || nowMinutes < wakeAt;
  }
  const hour = now.getHours();
  return hour >= FALLBACK_DIM_HOUR || hour < FALLBACK_WAKE_HOUR;
}

function applyDim() {
  const shouldDim = isNightNow() && Date.now() >= awakeUntil;
  nightDim.style.opacity = shouldDim ? String(NIGHT_DIM_OPACITY) : "0";
  nightDim.classList.toggle("hidden", !shouldDim);
}

function wakeScreen() {
  awakeUntil = Date.now() + WAKE_MINUTES * 60 * 1000;
  applyDim();
}

// Capture phase, so the touch that wakes a dimmed screen isn't also treated as a
// tap on whatever happens to be underneath it.
document.addEventListener(
  "pointerdown",
  (e) => {
    if (!nightDim.classList.contains("hidden")) {
      e.preventDefault();
      e.stopPropagation();
      wakeScreen();
    }
  },
  true
);

if (typeof onWeather === "function") {
  onWeather((data) => {
    sunTimes = data && data.sunrise ? { sunrise: data.sunrise, sunset: data.sunset } : null;
    applyDim();
  });
}

applyDim();
setInterval(applyDim, 60 * 1000);

/* ---------- idle reset ----------
   A wall display someone left on next December should not still be showing
   next December an hour later. Pages register what "at rest" means for them
   via onIdle(); this only fires the callbacks, it doesn't decide the state. */

const IDLE_MS = 4 * 60 * 1000;
// Longer than the in-page reset: being sent back to the calendar mid-way through
// browsing an album is worse than a stale music page, so this waits until nobody
// has plausibly been using it for a while.
const RETURN_HOME_MS = 10 * 60 * 1000;

const idleHandlers = [];
let idleTimer = null;
let returnHomeTimer = null;

function onIdle(handler) {
  idleHandlers.push(handler);
}

function resetIdleTimer() {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => idleHandlers.forEach((fn) => fn()), IDLE_MS);

  // The calendar is the reason the thing is on the wall. Left on Music or Web,
  // it would otherwise sit there indefinitely showing no calendar at all - the
  // in-page reset only ever ran on the calendar page.
  clearTimeout(returnHomeTimer);
  if (window.location.pathname !== "/") {
    returnHomeTimer = setTimeout(() => window.location.assign("/"), RETURN_HOME_MS);
  }
}

["pointerdown", "keydown", "wheel", "touchstart"].forEach((evt) => {
  document.addEventListener(evt, resetIdleTimer, { passive: true });
});

resetIdleTimer();
