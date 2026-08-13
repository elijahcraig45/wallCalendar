/* ============================================================================
   WALL CALENDAR THEMES  —  edit this file to make your own
   ============================================================================

   A theme controls the surfaces the calendar is drawn ON. It never touches event
   colours: those come from Google, where each event takes its calendar's colour,
   so "Family" is the same orange here as on your phone. The theme's job is to sit
   behind them without fighting them.

   --------------------------------------------------------------------------
   THE SHAPE OF A THEME
   --------------------------------------------------------------------------

     {
       name:      "August — heat",   // for your reference only
       accent:    "#e0873c",         // REQUIRED. today, active rail, buttons, links
       secondary: "#8c4a2f",         // the other end of every gradient
       base:      "#15100c",         // the page behind everything
       surface:   "#241a13",         // day cells, panels, the calendar's ground
       lines:     "#4a3527",         // grid lines between days
       strength:  1.0,              // how strong the translucent tints are
     }

   Only `accent` is required. Anything you leave out is derived from it, so this
   is a complete, valid theme:

     { name: "Just one colour", accent: "#8a6fd4" }

   ...and it will look like the old single-hue behaviour. Add fields as you want
   more control:

     accent      the one colour that has to be legible on its own - it paints
                 today's date pill, the active rail item, buttons and links
     secondary   pairs with accent in the header and page gradients. Pick
                 something a few steps darker or a neighbouring hue; two colours
                 far apart look like a fault rather than a gradient
     base        the darkest ground. Keep it dark - light values wreck contrast
                 with the white text, which the theme deliberately can't change
     surface     day cells and panels. Should be a little lighter than base, and
                 usually tinted toward the accent
     lines       the grid between days. Between surface and accent in lightness;
                 this is what makes the grid read as a grid rather than as gaps
     strength    multiplies every translucent tint at once:
                   0    no theming at all (same as switching themes off)
                   0.5  barely there
                   1.0  default: clearly seasonal, still calm
                   1.6  bold; good for a wall seen from across a room
                   2.5  loud. Look at it from your actual chair first

   Text colour, contrast and type NEVER change with a theme, at any strength.
   That isn't an oversight: this is read from a distance.

   --------------------------------------------------------------------------
   HOW TO MAKE YOUR OWN
   --------------------------------------------------------------------------

   1. Try it live, no deploy needed. On the wall (or a browser pointed at it),
      open devtools and run:

        localStorage.wallcal_theme = JSON.stringify({
          name: "test", accent: "#8a6fd4", secondary: "#4b3b7a",
          base: "#13111c", surface: "#1e1b2b", lines: "#3a3352", strength: 1.3
        }); location.reload()

      That pins ONE theme for every month - the fastest way to judge a palette.
      Undo it with:

        localStorage.removeItem("wallcal_theme"); location.reload()

   2. To override the whole year, pass twelve (January first):

        localStorage.wallcal_themes = JSON.stringify([ {...}, ... ]);
        location.reload()

   3. Happy with it? Put it in MONTHLY_THEMES below and push. The wall redeploys
      itself within seconds.

   4. Off entirely, back to flat dark mode and Google blue:

        localStorage.calendar_themes = "off"; location.reload()

   --------------------------------------------------------------------------
   PICKING COLOURS THAT WORK
   --------------------------------------------------------------------------

   - Google's event colours are soft pastels: #a4bdfc #7ae7bf #dbadff #ff887c
     #fbd75b #ffb878 #46d6db #5484ed #51b749 #dc2127. Don't pick an accent close
     to the ones your own calendars use, or events blend into their background.
   - `base` and `surface` want to stay dark. Around #101010–#2a2a2a is the useful
     range; past that the white text starts to struggle.
   - Keep `secondary` in the same neighbourhood as `accent`. Complementary pairs
     read as a bug.
   - Pure greys everywhere give you no theme - that's what "off" is for.
   ========================================================================== */

/* Copy this whole block, rename it, change the colours. */
const THEME_TEMPLATE = {
  name: "Template — copy me",
  accent: "#8a6fd4",     // required
  secondary: "#4b3b7a",  // gradient partner
  base: "#13111c",       // page ground
  surface: "#1e1b2b",    // day cells and panels
  lines: "#3a3352",      // grid lines
  strength: 1.0,         // 0 = off, 1 = default, >1 = bolder
};

/* January first. Seasonal rather than arbitrary: cold light through winter,
   greens through spring, teal at midsummer, amber into rust for autumn, back to
   cold blue for December. Each one shifts its ground as well as its accent, which
   is what stops February and August looking like the same screen. */
const MONTHLY_THEMES = [
  { name: "January — cold light", accent: "#7aa2d6", secondary: "#3f5b80",
    base: "#0f1319", surface: "#182029", lines: "#2c3b4d", strength: 1.0 },
  { name: "February — late winter", accent: "#c98bb0", secondary: "#7d4f68",
    base: "#141016", surface: "#211a22", lines: "#3d2d38", strength: 1.0 },
  { name: "March — first green", accent: "#6fae7c", secondary: "#3d6b4a",
    base: "#0f1411", surface: "#18211b", lines: "#2b3f31", strength: 1.0 },
  { name: "April — spring", accent: "#7bbf6a", secondary: "#467a3c",
    base: "#101410", surface: "#1a231a", lines: "#2f452c", strength: 1.0 },
  { name: "May — full leaf", accent: "#9ac45c", secondary: "#5f7f33",
    base: "#111410", surface: "#1e2418", lines: "#374428", strength: 1.0 },
  { name: "June — midsummer", accent: "#4fb3a6", secondary: "#2c6b64",
    base: "#0e1413", surface: "#16211f", lines: "#274039", strength: 1.0 },
  { name: "July — high summer", accent: "#e8a33d", secondary: "#96601c",
    base: "#15110b", surface: "#231c12", lines: "#453522", strength: 1.0 },
  { name: "August — heat", accent: "#e0873c", secondary: "#8c4a2f",
    base: "#15100c", surface: "#241a13", lines: "#4a3527", strength: 1.0 },
  { name: "September — turning", accent: "#c9772f", secondary: "#7d4522",
    base: "#14100c", surface: "#221a13", lines: "#453023", strength: 1.0 },
  { name: "October — rust", accent: "#d2652f", secondary: "#7a3418",
    base: "#150e0b", surface: "#241610", lines: "#4a2a1d", strength: 1.1 },
  { name: "November — bare", accent: "#a8613f", secondary: "#633a26",
    base: "#12100e", surface: "#1e1815", lines: "#3a2c24", strength: 1.0 },
  { name: "December — cold blue", accent: "#5f93c4", secondary: "#33527a",
    base: "#0e1116", surface: "#161d26", lines: "#283747", strength: 1.0 },
];

/* ==========================================================================
   Plumbing below. You shouldn't need to touch this to make a theme.
   ========================================================================== */

const THEME_OFF = {
  name: "off",
  accent: "#4285F4",
  secondary: "#4285F4",
  base: "#111318",
  surface: "#1c1f26",
  lines: "#2c303a",
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

/** Fills in everything a theme omitted, so `{ accent }` alone is a valid theme. */
function resolveTheme(theme) {
  const accent = parseHex(theme && theme.accent) ? theme.accent : THEME_OFF.accent;
  const base = theme.base || mix(THEME_OFF.base, accent, 0.05);
  return {
    name: theme.name || "",
    accent,
    // Default partner is a darker accent rather than a second hue - safe, and
    // still reads as a gradient.
    secondary: theme.secondary || mix(accent, "#000000", 0.45),
    base,
    surface: theme.surface || mix(base, accent, 0.08),
    lines: theme.lines || mix(theme.surface || mix(base, accent, 0.08), accent, 0.28),
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
  root.style.setProperty("--accent2", t.secondary);
  root.style.setProperty("--accent2-rgb", rgb(t.secondary));
  root.style.setProperty("--bg", t.base);
  root.style.setProperty("--surface", t.surface);
  // Slightly lifted surface, used for today's cell and the rail's active item.
  root.style.setProperty("--surface-hi", mix(t.surface, "#ffffff", 0.06));
  root.style.setProperty("--grid-line", t.lines);
  root.style.setProperty(
    "--theme-strength",
    String(Number.isFinite(t.strength) ? t.strength : 1)
  );
  root.dataset.theme = t.name;
}
