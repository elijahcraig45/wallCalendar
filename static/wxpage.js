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
const wxUpdated = document.getElementById("wx-updated");

const WX_ALERTS_MS = 3 * 60 * 1000;
const WX_RADAR_MS = 4 * 60 * 1000;

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
      <div><dt>Wind</dt><dd>${data.wind} mph</dd></div>
      ${today ? `<div><dt>UV index</dt><dd>${today.uv_max ?? "—"}</dd></div>` : ""}
      <div><dt>Sunrise</dt><dd>${wxTime(data.sunrise)}</dd></div>
      <div><dt>Sunset</dt><dd>${wxTime(data.sunset)}</dd></div>
    </dl>
    ${data.stale ? '<p class="wx-stale">Showing the last reading — couldn\'t reach the service.</p>' : ""}`;

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

  wxThunder.innerHTML = `
    <h3>Storm outlook</h3>
    <div class="wx-thunder-body${thunderHours.length ? " wx-thunder-body--active" : ""}">
      <div class="wx-thunder-head">${
        thunderHours.length
          ? `Thunder in the forecast from ${wxEscape(wxHourLabel(first))}`
          : "No thunder in the next 24 hours"
      }</div>
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
        <div class="wx-hour-icon">${weatherIcon(h.icon)}</div>
        <div class="wx-hour-temp">${h.temperature}°</div>
        <div class="wx-hour-precip${h.precip_chance >= 40 ? " wx-hour-precip--likely" : ""}">${
          h.precip_chance != null ? `${h.precip_chance}%` : ""
        }</div>
      </div>`
    )
    .join("");
}

/* ---------- the week ---------- */

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
        <div class="wx-day-name">${index === 0 ? "Today" : wxEscape(shortDay(day.date))}</div>
        <div class="wx-day-icon">${weatherIcon(day.icon)}</div>
        <div class="wx-day-precip">${day.precip_chance ? `${day.precip_chance}%` : ""}</div>
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
        <div class="wx-alert-area">${wxEscape(alert.area || "")}</div>
        <div class="wx-alert-detail hidden" data-wx-detail="${index}">
          ${alert.headline ? `<p class="wx-alert-headline">${wxEscape(alert.headline)}</p>` : ""}
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

/* ---------- radar ---------- */

let wxRadarUrl = null;

async function wxLoadRadar() {
  try {
    const resp = await fetch("/api/weather/radar");
    const data = resp.ok ? await resp.json() : null;
    if (!data || !data.available) {
      wxRadar.innerHTML = `<p class="wx-empty">${wxEscape(
        (data && data.reason) || "Radar unavailable."
      )}</p>`;
      wxRadarUrl = null;
      return;
    }
    wxRadarUrl = data.loop_url;
    wxRefreshRadar();
  } catch (e) {
    wxRadar.innerHTML = '<p class="wx-empty">Radar unavailable.</p>';
  }
}

function wxRefreshRadar() {
  if (!wxRadarUrl) return;
  // NWS serves this with a long cache life, so a changing query string is what
  // actually gets a new frame. Rebuilding the <img> rather than setting .src
  // avoids showing the old loop while the new one downloads.
  const img = document.createElement("img");
  img.className = "wx-radar-img";
  img.alt = "Weather radar loop";
  img.src = `${wxRadarUrl}?t=${Date.now()}`;
  img.onerror = () => {
    wxRadar.innerHTML = '<p class="wx-empty">Radar image didn\'t load.</p>';
  };
  wxRadar.replaceChildren(img);
}

/* ---------- wiring ---------- */

document.getElementById("wx-refresh").addEventListener("click", () => {
  wxLoadAlerts();
  wxRefreshRadar();
  refreshWeather();
});

wxLoadAlerts();
wxLoadRadar();
setInterval(wxLoadAlerts, WX_ALERTS_MS);
setInterval(wxRefreshRadar, WX_RADAR_MS);

// Collapse any opened alert when nobody's been here for a while, so the page is
// back to its overview state next time someone walks up.
onIdle(() => {
  wxAlerts.querySelectorAll("[data-wx-detail]").forEach((el) => el.classList.add("hidden"));
  wxAlerts.querySelectorAll("[data-wx-alert]").forEach((el) =>
    el.setAttribute("aria-expanded", "false")
  );
});
