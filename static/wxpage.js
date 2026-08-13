/* The weather page.
 *
 * Every name here is prefixed `wx`. weather.js is a shell script loaded on every
 * page and already owns `weatherIcon`, `onWeather`, `shortDay`, `renderWeather`
 * and friends; a page script redefining one of those silently shadows it for the
 * whole page, which has broken this app before (timers.js vs notes.js, both with
 * a `render`). tests/api_checks.py fails the build on a collision now.
 *
 * Update cadences, since they differ on purpose:
 *   conditions/forecast  15 min  - Open-Meteo's own data moves about hourly
 *   alerts                3 min  - a tornado warning is worth having promptly
 *   radar                 4 min  - roughly how often NWS publishes a new frame
 */

const wxNow = document.getElementById("wx-now");
const wxThunder = document.getElementById("wx-thunder");
const wxHourly = document.getElementById("wx-hourly");
const wxDays = document.getElementById("wx-days");
const wxAlerts = document.getElementById("wx-alerts");
const wxAlertCount = document.getElementById("wx-alert-count");
const wxRadar = document.getElementById("wx-radar");
const wxRadarBig = document.getElementById("wx-radar-big");
const wxRadarCaption = document.getElementById("wx-radar-caption");
const wxAir = document.getElementById("wx-air");
const wxSun = document.getElementById("wx-sun");
const wxUpdated = document.getElementById("wx-updated");

const WX_ALERTS_MS = 3 * 60 * 1000;
const WX_RADAR_MS = 4 * 60 * 1000;
// Air quality moves over hours and pollen is published once a day.
const WX_AIR_MS = 30 * 60 * 1000;

function wxEscape(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : text;
  return div.innerHTML;
}

function wxTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function wxHourLabel(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "numeric" });
}

/* ---------- conditions ---------- */

// Subscribes to the shell's poller rather than adding a second one.
onWeather((data) => {
  if (!data || data.available === false) {
    wxNow.innerHTML = '<p class="wx-empty">Weather unavailable.</p>';
    wxHourly.innerHTML = "";
    wxDays.innerHTML = "";
    wxThunder.innerHTML = "";
    return;
  }

  const today = data.days && data.days[0];
  wxNow.innerHTML = `
    <div class="wx-now-icon">${weatherIcon(data.icon)}</div>
    <div class="wx-now-temp">${data.temperature}°</div>
    <div class="wx-now-label">${wxEscape(data.label)}</div>
    <div class="wx-now-place">${wxEscape(data.place || "")}</div>
    <dl class="wx-now-grid">
      <div><dt>Feels like</dt><dd>${data.feels_like}°</dd></div>
      <div><dt>Humidity</dt><dd>${data.humidity}%</dd></div>
      <div><dt>Wind</dt><dd>${data.wind}${
        // Gusts only when they're meaningfully above the steady wind; "8 mph,
        // gusting 9" is noise.
        data.gusts != null && data.gusts >= data.wind + 5 ? ` <span class="wx-gust">g${data.gusts}</span>` : ""
      } mph</dd></div>
      <div><dt>UV now</dt><dd>${data.uv_index ?? "—"}${
        today && today.uv_max != null ? `<span class="wx-sub"> peak ${today.uv_max}</span>` : ""
      }</dd></div>
      <div><dt>Dew point</dt><dd>${data.dew_point ?? "—"}°</dd></div>
      <div><dt>Cloud</dt><dd>${data.cloud_cover ?? "—"}%</dd></div>
      <div><dt>Sunrise</dt><dd>${wxTime(data.sunrise)}</dd></div>
      <div><dt>Sunset</dt><dd>${wxTime(data.sunset)}</dd></div>
    </dl>
    ${data.stale ? '<p class="wx-stale">Showing the last reading — couldn\'t reach the service.</p>' : ""}`;

  wxRenderSun(data);
  wxRenderThunder(data);
  wxRenderHourly(data.hours || []);
  wxRenderDays(data.days || []);
  if (data.fetched_at) {
    wxUpdated.textContent = `Updated ${wxTime(data.fetched_at)}`;
  }
});

/* ---------- thunderstorm outlook ----------
 * This is the honest version of "lightning proximity". There is no free feed of
 * individual strikes, so nothing here claims to know where lightning is - it
 * reports instability (CAPE) and whether the forecast has thunder in it, and
 * leans on the NWS warnings panel and the radar loop for anything actionable.
 */

// J/kg. Rough operational bands: below 1000 is quiet, 1000-2500 is a real
// chance given a trigger, above 2500 supports strong storms.
const WX_CAPE_BANDS = [
  { limit: 1000, label: "Stable", note: "Thunderstorms unlikely." },
  { limit: 2500, label: "Unstable", note: "Thunderstorms possible if something sets them off." },
  { limit: Infinity, label: "Very unstable", note: "Strong storms possible." },
];

function wxRenderThunder(data) {
  const cape = data.cape_peak;
  const thunderHours = data.thunder_hours || [];

  if (cape == null && thunderHours.length === 0) {
    wxThunder.innerHTML = "";
    return;
  }

  const band = WX_CAPE_BANDS.find((b) => (cape ?? 0) < b.limit);
  const first = thunderHours[0];

  /* "No thunder in the next 24 hours" sat directly above "Very unstable - strong
     storms possible", with live radar showing storms 30 miles away. All three were
     true at once: the hourly codes had no thunder in them, the air was unstable,
     and cells were firing. Saying only the first of those is how a wall display
     loses your trust, so an unstable-but-not-forecast sky says so. */
  const unstable = cape != null && cape >= 1000;
  const headline = thunderHours.length
    ? `Thunder in the forecast from ${wxHourLabel(first)}`
    : unstable
      ? "No thunder in the hourly forecast, but the air is unstable"
      : "No thunder in the next 24 hours";

  wxThunder.innerHTML = `
    <h3>Storm outlook</h3>
    <div class="wx-thunder-body${thunderHours.length || unstable ? " wx-thunder-body--active" : ""}">
      <div class="wx-thunder-head">${wxEscape(headline)}</div>
      ${cape != null
        ? `<div class="wx-thunder-cape"><strong>${band.label}</strong> · CAPE ${cape} J/kg</div>
           <div class="wx-thunder-note">${wxEscape(band.note)}</div>`
        : ""}
      <div class="wx-thunder-caveat">Strike-level lightning data isn't publicly
        available, so this is a forecast, not a detector. Warnings below and the
        radar loop are the real-time picture.</div>
    </div>`;
}

/* ---------- hourly ---------- */

function wxRenderHourly(hours) {
  const upcoming = hours
    .filter((h) => new Date(h.time) >= new Date(Date.now() - 60 * 60 * 1000))
    .slice(0, 24);

  if (upcoming.length === 0) {
    wxHourly.innerHTML = '<p class="wx-empty">No hourly forecast.</p>';
    return;
  }

  wxHourly.innerHTML = upcoming
    .map(
      (h) => `
      <div class="wx-hour">
        <div class="wx-hour-time">${wxEscape(wxHourLabel(h.time))}</div>
        <div class="wx-hour-icon">${weatherIconAt(h.icon, h.is_day)}</div>
        <div class="wx-hour-temp">${h.temperature}°</div>
        <div class="wx-hour-precip${h.precip_chance >= 40 ? " wx-hour-precip--likely" : ""}">${
          h.precip_chance != null ? `${h.precip_chance}%` : ""
        }</div>
      </div>`
    )
    .join("");
}

/* ---------- the week ---------- */

/** Rain totals at two decimals, and nothing at all below a twentieth of an inch.
 *  Open-Meteo returns the raw figure, so the list was printing 0.004" and 0.035" -
 *  four significant figures of drizzle, which reads as precision the forecast
 *  doesn't have and is not a number anyone acts on. */
function wxRainTotal(inches) {
  if (inches == null || inches < 0.05) return "";
  return `<span class="wx-sub"> ${inches.toFixed(2)}"</span>`;
}

function wxRenderDays(days) {
  if (days.length === 0) {
    wxDays.innerHTML = "";
    return;
  }

  const highs = days.map((d) => d.high).filter((v) => v != null);
  const lows = days.map((d) => d.low).filter((v) => v != null);
  const top = Math.max(...highs);
  const bottom = Math.min(...lows);
  const span = Math.max(1, top - bottom);

  wxDays.innerHTML = days
    .map((day, index) => {
      // A bar spanning the day's low-to-high against the week's range, which
      // makes "Thursday is the cold one" readable without comparing numbers.
      const left = ((day.low - bottom) / span) * 100;
      const width = Math.max(4, ((day.high - day.low) / span) * 100);
      return `
      <li class="wx-day">
        <div class="wx-day-name">${index === 0 ? "Today" : wxEscape(shortDay(day.date))}${
          // Ten days runs past one weekday cycle, so "Sat" alone is ambiguous
          // once you're a week out.
          index >= 7 ? `<span class="wx-sub"> ${new Date(day.date + "T00:00:00").getDate()}</span>` : ""
        }</div>
        <div class="wx-day-icon">${weatherIcon(day.icon)}</div>
        <div class="wx-day-precip">${day.precip_chance ? `${day.precip_chance}%` : ""}${
          wxRainTotal(day.precip_total)
        }</div>
        <div class="wx-day-low">${day.low}°</div>
        <div class="wx-day-track">
          <span class="wx-day-bar" style="left:${left}%;width:${width}%"></span>
        </div>
        <div class="wx-day-high">${day.high}°</div>
      </li>`;
    })
    .join("");
}

/* ---------- alerts ---------- */

/** NWS lists every zone an alert covers, which for a regional heat advisory is
 *  thirty-odd county names - five wrapped lines that buried the two alerts under
 *  them. The first few, then a count; the full list is in the expanded detail. */
const WX_AREA_NAMES = 4;

function wxShortArea(area) {
  if (!area) return "";
  const names = area.split(";").map((n) => n.trim()).filter(Boolean);
  if (names.length <= WX_AREA_NAMES) return names.join(", ");
  return `${names.slice(0, WX_AREA_NAMES).join(", ")} + ${names.length - WX_AREA_NAMES} more`;
}

function wxRenderAlerts(payload) {
  const alerts = (payload && payload.alerts) || [];

  wxAlertCount.classList.toggle("hidden", alerts.length === 0);
  wxAlertCount.textContent = String(alerts.length);
  wxAlertCount.classList.toggle("wx-count--urgent", (payload?.urgent_count || 0) > 0);

  if (alerts.length === 0) {
    const problem = payload && payload.errors && payload.errors.length;
    wxAlerts.innerHTML = `<li class="wx-empty">${
      problem ? wxEscape(payload.errors[0]) : "No active alerts."
    }</li>`;
    return;
  }

  wxAlerts.innerHTML = alerts
    .map(
      (alert, index) => `
      <li class="wx-alert${alert.urgent ? " wx-alert--urgent" : ""}">
        <button class="wx-alert-head" type="button" data-wx-alert="${index}" aria-expanded="false">
          <span class="wx-alert-event">${wxEscape(alert.event)}</span>
          <span class="wx-alert-when">${
            alert.ends ? `until ${wxEscape(wxTime(alert.ends))}` : ""
          }</span>
        </button>
        <div class="wx-alert-area">${wxEscape(wxShortArea(alert.area))}</div>
        <div class="wx-alert-detail hidden" data-wx-detail="${index}">
          ${alert.headline ? `<p class="wx-alert-headline">${wxEscape(alert.headline)}</p>` : ""}
          ${alert.area ? `<p class="wx-alert-fullarea">${wxEscape(alert.area)}</p>` : ""}
          ${alert.description ? `<p class="wx-alert-desc">${wxEscape(alert.description)}</p>` : ""}
          ${alert.instruction
            ? `<p class="wx-alert-instruction">${wxEscape(alert.instruction)}</p>`
            : ""}
          <p class="wx-alert-sender">${wxEscape(alert.sender || "")}</p>
        </div>
      </li>`
    )
    .join("");

  if (payload.stale) {
    const note = document.createElement("li");
    note.className = "wx-stale";
    note.textContent = "Couldn't refresh alerts — showing the last known set.";
    wxAlerts.appendChild(note);
  }
}

// Delegated, because the list is replaced wholesale on every poll and per-row
// listeners would be re-attached (or leak) each time.
wxAlerts.addEventListener("click", (event) => {
  const head = event.target.closest("[data-wx-alert]");
  if (!head) return;
  const detail = wxAlerts.querySelector(`[data-wx-detail="${head.dataset.wxAlert}"]`);
  if (!detail) return;
  const nowOpen = detail.classList.contains("hidden");
  detail.classList.toggle("hidden", !nowOpen);
  head.setAttribute("aria-expanded", String(nowOpen));
});

async function wxLoadAlerts() {
  try {
    const resp = await fetch("/api/weather/alerts");
    wxRenderAlerts(resp.ok ? await resp.json() : null);
  } catch (e) {
    wxRenderAlerts({ alerts: [], errors: ["Couldn't reach the alerts service."] });
  }
}



/* ---------- daylight ----------
 * From data already fetched. Worth a card on a kitchen wall because the number
 * people actually want in August is "how much evening is left", and in December
 * it's "is it getting better yet" - and the day-over-day change answers the second
 * one in a way sunset time alone doesn't.
 */

function wxDuration(minutes) {
  if (minutes == null) return "";
  const whole = Math.round(minutes);
  // Minutes only under an hour: the daily change is a couple of minutes and
  // "0h 02m shorter tomorrow" is a silly way to say "2m".
  if (whole < 60) return `${whole}m`;
  return `${Math.floor(whole / 60)}h ${String(whole % 60).padStart(2, "0")}m`;
}

function wxRenderSun(data) {
  const days = data.days || [];
  const today = days[0];
  const tomorrow = days[1];
  if (!today || today.daylight_minutes == null) {
    wxSun.innerHTML = "";
    return;
  }

  const change =
    tomorrow && tomorrow.daylight_minutes != null
      ? tomorrow.daylight_minutes - today.daylight_minutes
      : null;
  // Rounded to the minute, and "about the same" rather than "0 minutes longer",
  // which is what it says for a week either side of a solstice.
  const changeText =
    change == null
      ? ""
      : Math.abs(change) < 1
        ? "About the same tomorrow"
        : `${wxDuration(Math.abs(Math.round(change)))} ${change > 0 ? "longer" : "shorter"} tomorrow`;

  wxSun.innerHTML = `<h3>Daylight</h3>
    <div class="wx-sun-body">
      <div class="wx-sun-length">${wxDuration(today.daylight_minutes)}</div>
      <div class="wx-sun-change">${wxEscape(changeText)}</div>
      <div class="wx-sun-times">
        <span>${wxEscape(wxTime(data.sunrise))}</span>
        <span class="wx-sun-arc" aria-hidden="true"></span>
        <span>${wxEscape(wxTime(data.sunset))}</span>
      </div>
    </div>`;
}

/* ---------- air quality and pollen ----------
 * Two providers: AQI from Open-Meteo, pollen from pollen.com, because Open-Meteo's
 * pollen variables are null for US locations (they're CAMS Europe). They fail
 * independently, so one being absent must not blank the other.
 */

// AQI colours are the EPA's own, which people already recognise from air-quality
// maps - inventing a palette here would be worse than borrowing the standard one.
const WX_AQI_COLORS = [
  { limit: 50, color: "#3ea72d" },
  { limit: 100, color: "#c8a415" },
  { limit: 150, color: "#d8762a" },
  { limit: 200, color: "#c0272d" },
  { limit: 300, color: "#8f3f97" },
  { limit: Infinity, color: "#7e0023" },
];

/* Pollen arrives on one of two scales - Google's Universal Pollen Index is 0-5,
   pollen.com's is 0-12 - so the colour has to be chosen against whichever scale
   answered. Colouring a 4 as "low" because the other provider's 4 is low would be
   actively misleading: on Google's scale 4 is High. Normalise to a fraction of the
   scale's own maximum and band that. */
const WX_POLLEN_COLORS = [
  { limit: 0.2, color: "#3ea72d" },
  { limit: 0.4, color: "#9bbf30" },
  { limit: 0.6, color: "#c8a415" },
  { limit: 0.8, color: "#d8762a" },
  { limit: Infinity, color: "#c0272d" },
];

const wxPollenColor = (index, scaleMax) =>
  wxColorFor(WX_POLLEN_COLORS, (index || 0) / (scaleMax || 12));

const wxColorFor = (scale, value) =>
  (scale.find((b) => value <= b.limit) || scale[scale.length - 1]).color;

/** Black or white, whichever reads on the given fill.
 *  The dials were white-on-colour throughout, which is fine on the reds and the
 *  purple and badly wrong on the greens and yellows - white on the "Moderate"
 *  yellow (#c8a415) measures 2.3:1. Caught by the contrast sweep, which is exactly
 *  the class of thing it exists for. */
function wxTextOn(hex) {
  const n = parseInt(hex.replace("#", ""), 16);
  const channel = (v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  const lum =
    0.2126 * channel((n >> 16) & 255) +
    0.7152 * channel((n >> 8) & 255) +
    0.0722 * channel(n & 255);
  // Compare both candidates rather than guessing a threshold.
  const onWhite = 1.05 / (lum + 0.05);
  const onBlack = (lum + 0.05) / 0.05;
  return onBlack >= onWhite ? "#1b1b1b" : "#ffffff";
}

function wxRenderAir(payload) {
  const aqi = (payload && payload.aqi) || {};
  const pollen = (payload && payload.pollen) || {};

  if (!aqi.available && !pollen.available) {
    const why = payload && payload.errors && payload.errors.length
      ? payload.errors[0]
      : "Air quality and pollen unavailable.";
    wxAir.innerHTML = `<h3>Air</h3><p class="wx-empty">${wxEscape(why)}</p>`;
    return;
  }

  const aqiBlock = aqi.available
    ? `<div class="wx-air-row">
         <div class="wx-air-dial" style="--wx-dial:${wxColorFor(WX_AQI_COLORS, aqi.aqi)};--wx-dial-fg:${wxTextOn(wxColorFor(WX_AQI_COLORS, aqi.aqi))}">
           <span class="wx-air-value">${aqi.aqi}</span>
         </div>
         <div class="wx-air-text">
           <div class="wx-air-label">AQI · ${wxEscape(aqi.label || "")}</div>
           <div class="wx-air-note">${wxEscape(aqi.note || "")}</div>
           <div class="wx-air-parts">${
             // Named because the reason matters: an Atlanta summer AQI is almost
             // always ozone, and ozone is a reason to go out earlier, not to shut
             // the windows.
             [
               aqi.ozone != null ? `ozone ${aqi.ozone}` : null,
               aqi.pm2_5 != null ? `PM2.5 ${aqi.pm2_5}` : null,
               aqi.pm10 != null ? `PM10 ${aqi.pm10}` : null,
             ].filter(Boolean).map(wxEscape).join(" · ")
           }</div>
         </div>
       </div>`
    : `<p class="wx-empty">Air quality unavailable.</p>`;

  const today = pollen.today || {};
  const tomorrow = pollen.tomorrow || {};
  const pollenBlock = pollen.available
    ? `<div class="wx-air-row">
         <div class="wx-air-dial" style="--wx-dial:${wxPollenColor(today.index, pollen.scale_max)};--wx-dial-fg:${wxTextOn(wxPollenColor(today.index, pollen.scale_max))}">
           <span class="wx-air-value">${today.index}</span>
           <span class="wx-air-scale">/${pollen.scale_max}</span>
         </div>
         <div class="wx-air-text">
           <div class="wx-air-label">Pollen · ${wxEscape(today.label || "")}</div>
           <div class="wx-air-note">${
             today.triggers && today.triggers.length
               ? wxEscape(today.triggers.join(", "))
               : "Nothing in season"
           }</div>
           <div class="wx-air-parts">${
             // Grass/tree/weed separately, which only Google supplies. Types with
             // no reading at all are dropped rather than shown as a dash.
             (today.types || []).filter((t) => t.index != null).length
               ? (today.types || [])
                   .filter((t) => t.index != null)
                   .map((t) => `${wxEscape(t.name)} ${t.index}`)
                   .join(" · ")
               : ""
           }</div>
           <div class="wx-air-parts">${
             tomorrow.index != null
               ? `Tomorrow ${tomorrow.index} · ${wxEscape(tomorrow.label || "")}`
               : ""
           }</div>
         </div>
       </div>
       ${
         today.recommendation
           ? `<div class="wx-air-advice">${wxEscape(today.recommendation)}</div>`
           : ""
       }`
    : `<p class="wx-empty">Pollen unavailable.</p>`;

  wxAir.innerHTML = `<h3>Air</h3>
    <div class="wx-air-body">
      ${aqiBlock}
      ${pollenBlock}
      <div class="wx-air-source">Air quality: Open-Meteo · Pollen: ${wxEscape(
        pollen.source || "pollen.com"
      )}${
        // The scale is part of the attribution: 4 means different things on the
        // two providers' indices, so the reader has to know which one this is.
        pollen.available ? ` (0–${pollen.scale_max})` : ""
      }${payload.stale ? " · showing the last reading" : ""}</div>
    </div>`;
}

async function wxLoadAir() {
  try {
    const resp = await fetch("/api/weather/air");
    wxRenderAir(resp.ok ? await resp.json() : null);
  } catch (e) {
    wxRenderAir(null);
  }
}

/* ---------- radar ----------
 * A single NWS RIDGE animated GIF: no map library, no tile server, no key, and it
 * animates itself. 600x550, which is legible in a column but not much more, hence
 * the full-screen view.
 */

let wxRadarInfo = null;
let wxRadarView = "local";

function wxRadarSrcFor(view) {
  if (!wxRadarInfo) return null;
  if (view === "regional") return wxRadarInfo.regional_url;
  if (view === "national") return wxRadarInfo.national_url;
  return wxRadarInfo.loop_url;
}

function wxRadarCaptionFor(view) {
  if (!wxRadarInfo) return "";
  if (view === "regional") return `${wxRadarInfo.region || "Regional"} — storms on the way`;
  if (view === "national") return "Continental US";
  return `${wxRadarInfo.station} — nearest radar`;
}

/** Builds a fresh <img> rather than setting .src on the existing one.
 *  NWS serves these with a long cache life so the changing query string is what
 *  actually fetches a new frame, and replacing the element avoids showing the old
 *  loop while the new one downloads. */
function wxRadarImage(view) {
  const src = wxRadarSrcFor(view);
  if (!src) return null;
  const img = document.createElement("img");
  img.className = "wx-radar-img";
  img.alt = `Weather radar loop, ${view}`;
  img.src = `${src}?t=${Date.now()}`;
  return img;
}

async function wxLoadRadar() {
  try {
    const resp = await fetch("/api/weather/radar");
    const data = resp.ok ? await resp.json() : null;
    if (!data || !data.available) {
      wxRadar.innerHTML = `<p class="wx-empty">${wxEscape(
        (data && data.reason) || "Radar unavailable."
      )}</p>`;
      wxRadarInfo = null;
      return;
    }
    wxRadarInfo = data;
    // A region this state isn't mapped to would render a 404 image, so the tab
    // only appears when the server actually supplied a URL.
    document
      .querySelector('[data-wx-radar="regional"]')
      .classList.toggle("hidden", !data.regional_url);
    wxRefreshRadar();
  } catch (e) {
    wxRadar.innerHTML = '<p class="wx-empty">Radar unavailable.</p>';
  }
}

function wxRefreshRadar() {
  const thumb = wxRadarImage("local");
  if (thumb) {
    thumb.onerror = () => {
      wxRadar.innerHTML = '<p class="wx-empty">Radar image didn\'t load.</p>';
    };
    wxRadar.replaceChildren(thumb);
  }
  // Only redraw the big one while it's actually on screen; otherwise this would
  // pull a 600KB GIF every four minutes for a hidden overlay.
  if (!document.getElementById("wx-radar-overlay").classList.contains("hidden")) {
    wxShowRadarView(wxRadarView);
  }
}

function wxShowRadarView(view) {
  wxRadarView = view;
  document.querySelectorAll("[data-wx-radar]").forEach((tab) => {
    tab.classList.toggle("wx-radar-tab--active", tab.dataset.wxRadar === view);
  });
  const img = wxRadarImage(view);
  if (img) wxRadarBig.replaceChildren(img);
  wxRadarCaption.textContent = wxRadarCaptionFor(view);
}

const wxRadarPanel = initPanel("wx-radar-overlay", "wx-radar-close");

wxRadar.addEventListener("click", () => {
  if (!wxRadarInfo) return;
  wxShowRadarView(wxRadarView);
  wxRadarPanel.open();
});

document.querySelectorAll("[data-wx-radar]").forEach((tab) => {
  tab.addEventListener("click", () => wxShowRadarView(tab.dataset.wxRadar));
});

/* ---------- wiring ---------- */

document.getElementById("wx-refresh").addEventListener("click", () => {
  wxLoadAlerts();
  wxLoadAir();
  wxRefreshRadar();
  refreshWeather();
});

wxLoadAlerts();
wxLoadAir();
wxLoadRadar();
setInterval(wxLoadAlerts, WX_ALERTS_MS);
setInterval(wxLoadAir, WX_AIR_MS);
setInterval(wxRefreshRadar, WX_RADAR_MS);

// Collapse any opened alert when nobody's been here for a while, so the page is
// back to its overview state next time someone walks up.
onIdle(() => {
  wxRadarPanel.close();
  wxAlerts.querySelectorAll("[data-wx-detail]").forEach((el) => el.classList.add("hidden"));
  wxAlerts.querySelectorAll("[data-wx-alert]").forEach((el) =>
    el.setAttribute("aria-expanded", "false")
  );
});
