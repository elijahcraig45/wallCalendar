/* ============================================================================
   WALL CALENDAR THEMES  —  edit this file to make your own
   ============================================================================

   A theme controls the surfaces the calendar is drawn ON. It never touches event
   colours: those come from Google, where each event takes its calendar's colour,
   so "Family" is the same orange here as on your phone. The theme's job is to sit
   behind them without fighting them.

   The default themes are LIGHT, and that is a correction rather than a taste call.
   This started dark; on the actual panel - a glossy touchscreen in a lit room - a
   dark ground behaved like a mirror, every low-contrast tint read as muddy haze,
   and it fought the events, because Google's palette is light pastel chips with
   dark text designed for a light background. A dark palette is still perfectly
   supported (see NIGHT_THEME) - it just isn't the right default for a wall.

   --------------------------------------------------------------------------
   THE SHAPE OF A THEME
   --------------------------------------------------------------------------

     {
       name:    "August — heat",  // for your reference only
       accent:  "#c2662c",        // REQUIRED
       base:    "#f7f4ef",        // the room-facing ground
       surface: "#ffffff",        // day cells, panels, cards
       lines:   "#ebe4db",        // the hairline grid
       text:    "#1f2124",        // body text
       textDim: "#6b6f76",        // labels and secondary text
       strength: 1.0,             // how strongly the accent tints things
     }

   Only `accent` is required. Everything else is derived, so this is a complete,
   valid theme:

     { name: "Just one colour", accent: "#4f86c6" }

   What each field does:

     accent    the one colour that must read on its own. It paints today's cell
               and date, the rule under the header, and the active rail item.
               Used decisively in a few places rather than smeared everywhere -
               an earlier version tinted every surface and just looked muddy
     base      the ground behind everything
     surface   day cells and panels. Usually white, or barely off it
     lines     the grid between days. Wants to be clearly visible but quiet -
               this is what makes the grid read as a grid
     text      body text. Derived from `base`'s lightness if you omit it, so a
               dark `base` automatically gets light text
     textDim   labels, weekday names, secondary detail
     strength  scales the accent tints (today's fill, the header rule):
                 0    no accent tinting at all
                 1.0  default
                 1.6  bolder; useful on a wall seen from further away

   --------------------------------------------------------------------------
   HOW TO MAKE YOUR OWN
   --------------------------------------------------------------------------

   1. Try it live, no deploy needed. On the wall (or a browser pointed at it),
      open devtools and run:

        localStorage.wallcal_theme = JSON.stringify({
          name: "test", accent: "#4f86c6", base: "#f2f4f7",
          surface: "#ffffff", lines: "#dde3ea"
        }); location.reload()

      That pins ONE theme for every month - the fastest way to judge a palette.
      Undo it with:

        localStorage.removeItem("wallcal_theme"); location.reload()

   2. To override the whole year, pass twelve (January first):

        localStorage.wallcal_themes = JSON.stringify([ {...}, ... ]);
        location.reload()

   3. Happy with it? Put it in MONTHLY_THEMES below and push. The wall redeploys
      itself within seconds.

   4. Off entirely, back to the plain default palette:

        localStorage.calendar_themes = "off"; location.reload()

   --------------------------------------------------------------------------
   PICKING COLOURS THAT WORK
   --------------------------------------------------------------------------

   - Judge it on the wall, from where you actually stand. A palette that looks
     refined on a laptop six inches away can vanish into glare across a room.
     Two attempts at this were tuned on screenshots and both were wrong.
   - Google's event colours are soft pastels: #a4bdfc #7ae7bf #dbadff #ff887c
     #fbd75b #ffb878 #46d6db #5484ed #51b749 #dc2127. Keep `accent` away from the
     ones your own calendars use, or today's highlight will look like an event.
   - `accent` needs enough depth to hold its own against white - mid-tone and
     saturated. Pale accents disappear; near-black ones stop reading as a colour.
   - `lines` too faint and the grid dissolves; too dark and it looks like a
     spreadsheet. Around 10-15% darker than `surface` is the useful range.
   - Keep `base` close to neutral. A warm cream ground under a warm accent is
     still the brown family, and on the wall it reads as a stain rather than as
     paper. Let the accent carry the month; the ground should be almost unnoticed.
   ========================================================================== */

/* Copy this whole block, rename it, change the colours. */
const THEME_TEMPLATE = {
  name: "Template — copy me",
  accent: "#4f86c6",     // required: today, active rail, the header rule
  base: "#f4f5f7",       // the room-facing ground
  surface: "#ffffff",    // day cells, panels, cards
  lines: "#e3e6ea",      // hairline grid
  text: "#1f2124",       // body text
  textDim: "#6b6f76",    // labels, secondary text
  strength: 1.0,         // 0 = no accent tinting, 1 = default
};

/* January first.

   These are light on purpose. The wall is a glossy touchscreen in a lit room: a
   dark ground turns it into a mirror, and it fought the events, since Google's
   palette is light pastel chips meant for a light background.

   Each month only shifts its accent and warms or cools its paper very slightly -
   enough that August isn't February, not so much that it looks like a different
   app. The accent shows up on today, the header rule and the active rail item. */
const MONTHLY_THEMES = [
  { name: "January — cold light",   accent: "#5b7fa8", base: "#f3f5f7", surface: "#ffffff", lines: "#e3e7ec" },
  { name: "February — late winter", accent: "#a3628a", base: "#f6f3f5", surface: "#ffffff", lines: "#e9e2e7" },
  { name: "March — first green",    accent: "#4f8a63", base: "#f3f6f3", surface: "#ffffff", lines: "#e3e9e3" },
  { name: "April — spring",         accent: "#5d9a4e", base: "#f4f6f2", surface: "#ffffff", lines: "#e5eae1" },
  { name: "May — full leaf",        accent: "#6f9a3a", base: "#f5f6f1", surface: "#ffffff", lines: "#e7eae0" },
  { name: "June — midsummer",       accent: "#2f8f86", base: "#f1f6f5", surface: "#ffffff", lines: "#e0eae8" },
  { name: "July — high summer",     accent: "#b8791f", base: "#f7f5ef", surface: "#ffffff", lines: "#eae5da" },
  { name: "August — heat",          accent: "#c2662c", base: "#f7f4ef", surface: "#ffffff", lines: "#ebe4db" },
  { name: "September — turning",    accent: "#a85f2a", base: "#f6f4f0", surface: "#ffffff", lines: "#eae2d9" },
  { name: "October — rust",         accent: "#a8501f", base: "#f7f3f0", surface: "#ffffff", lines: "#ebdfd7" },
  { name: "November — bare",        accent: "#8d5334", base: "#f5f3f0", surface: "#ffffff", lines: "#e8e0d9" },
  { name: "December — cold blue",   accent: "#41709e", base: "#f2f4f7", surface: "#ffffff", lines: "#e1e6ec" },
];

/* Kept for after dark, or if you simply prefer it. Pin it with:
     localStorage.wallcal_theme = JSON.stringify(NIGHT_THEME)
   ...or copy these values into MONTHLY_THEMES. Note that a dark ground needs
   light text, which is why text/textDim are part of a theme at all. */
const NIGHT_THEME = {
  name: "Night",
  accent: "#7aa2d6",
  base: "#12141a",
  surface: "#1b1e26",
  lines: "#2c303a",
  text: "#f0f0f0",
  textDim: "#8a8f9c",
  strength: 1.0,
};

/* ==========================================================================
   Plumbing below. You shouldn't need to touch this to make a theme.
   ========================================================================== */

const THEME_OFF = {
  name: "off",
  accent: "#4285F4",
  base: "#f4f5f7",
  surface: "#ffffff",
  lines: "#e3e6ea",
  text: "#1f2124",
  textDim: "#6b6f76",
  strength: 0,
};

function parseHex(hex) {
  const clean = String(hex || "").trim().replace("#", "");
  const full = clean.length === 3 ? clean.split("").map((c) => c + c).join("") : clean;
  const n = parseInt(full, 16);
  if (full.length !== 6 || Number.isNaN(n)) return null;
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const toHex = (rgb) =>
  "#" + rgb.map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");

/** Linear blend, used to derive the fields a theme leaves out. */
function mix(aHex, bHex, t) {
  const a = parseHex(aHex);
  const b = parseHex(bHex);
  if (!a || !b) return aHex;
  return toHex(a.map((v, i) => v + (b[i] - v) * t));
}

/** Relative luminance, used to decide whether a palette is light or dark so text
 *  can default sensibly instead of the theme having to spell it out. */
function luminance(hex) {
  const rgb = parseHex(hex) || [255, 255, 255];
  return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
}

/** Fills in everything a theme omitted, so `{ accent: "#4f86c6" }` alone is a
 *  valid theme. Text defaults follow the ground's lightness, which is what lets a
 *  dark palette work without every field being restated. */
function resolveTheme(theme) {
  const accent = parseHex(theme && theme.accent) ? theme.accent : THEME_OFF.accent;
  const base = theme.base || THEME_OFF.base;
  const surface = theme.surface || mix(base, "#ffffff", 0.6);
  const isDark = luminance(base) < 0.5;

  return {
    name: theme.name || "",
    accent,
    base,
    surface,
    lines: theme.lines || mix(surface, isDark ? "#ffffff" : "#000000", 0.12),
    text: theme.text || (isDark ? "#f0f0f0" : "#1f2124"),
    textDim: theme.textDim || (isDark ? "#8a8f9c" : "#6b6f76"),
    // Faint fills have to darken a light ground and lighten a dark one.
    tint: isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.04)",
    tintStrong: isDark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.08)",
    // Over the blurred album art behind the now-playing pane. Strong enough that
    // the text reads whatever is playing; sheer enough that the album's colour
    // still comes through.
    veil: isDark ? "rgba(0,0,0,0.62)" : "rgba(255,255,255,0.80)",
    // Text placed directly on the accent.
    onAccent: luminance(accent) > 0.6 ? "#1d1d1d" : "#ffffff",
    strength: theme.strength == null ? 1 : Number(theme.strength),
  };
}

function readStoredTheme(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    // A malformed override must not leave the wall unthemed and unexplained.
    console.warn(`wallcal: ignoring malformed ${key} in localStorage`, e);
    return null;
  }
}

/** The theme for a month (1-12), honouring localStorage overrides. */
function themeForMonth(monthNumber) {
  if (localStorage.getItem("calendar_themes") === "off") return THEME_OFF;

  const pinned = readStoredTheme("wallcal_theme");
  if (pinned && pinned.accent) return pinned;

  const year = readStoredTheme("wallcal_themes");
  if (Array.isArray(year) && year.length === 12) return year[(monthNumber - 1) % 12];

  return MONTHLY_THEMES[(monthNumber - 1) % 12];
}

/** Applies a month's theme. Called by the shell on load, and by calendar.js when
 *  a different month comes into view. */
function applyMonthTheme(monthNumber) {
  const t = resolveTheme(themeForMonth(monthNumber) || THEME_OFF);
  const rgb = (hex) => (parseHex(hex) || [66, 133, 244]).join(" ");
  const root = document.documentElement;

  root.style.setProperty("--accent", t.accent);
  root.style.setProperty("--accent-rgb", rgb(t.accent));
  root.style.setProperty("--bg", t.base);
  root.style.setProperty("--surface", t.surface);
  // A slightly shifted surface for active/hovered things, in whichever direction
  // this palette has room to move.
  root.style.setProperty(
    "--surface-hi",
    mix(t.surface, luminance(t.surface) < 0.5 ? "#ffffff" : "#000000", 0.05)
  );
  root.style.setProperty("--border", t.lines);
  root.style.setProperty("--text", t.text);
  root.style.setProperty("--text-dim", t.textDim);
  root.style.setProperty("--tint", t.tint);
  root.style.setProperty("--tint-strong", t.tintStrong);
  root.style.setProperty("--veil", t.veil);
  root.style.setProperty("--on-accent", t.onAccent);
  root.style.setProperty(
    "--theme-strength",
    String(Number.isFinite(t.strength) ? t.strength : 1)
  );
  root.dataset.theme = t.name;
}
