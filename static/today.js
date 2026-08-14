/* The morning overview.
 *
 * Deliberately built only from endpoints that already exist - today's events, the
 * agenda and weather. It introduces no server-side view of its own, so it
 * can't disagree with the pages it summarises, and anything fixed there is fixed
 * here too.
 */

const heading = document.getElementById("today-heading");
const weatherBlock = document.getElementById("today-weather");
const forecastBlock = document.getElementById("today-forecast");
const nextUpBlock = document.getElementById("today-next-up");
const eventsList = document.getElementById("today-events");
const nextList = document.getElementById("today-next");
const hoursStrip = document.getElementById("today-hours");
const groceriesList = document.getElementById("today-groceries");
const airBlock = document.getElementById("today-air");

/* How many grocery lines the overview shows before collapsing to "+N more".
   Sized to the column rather than to the list: this block sits under "Coming up"
   and gets roughly this many rows before it would start scrolling. */
const GROCERY_PREVIEW_LIMIT = 18;

function todayIso() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

heading.textContent = new Date().toLocaleDateString(undefined, {
  weekday: "long", month: "long", day: "numeric",
});

function empty(list, message) {
  const li = document.createElement("li");
  li.className = "today-empty";
  li.textContent = message;
  list.appendChild(li);
}

function escapeText(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : text;
  return div.innerHTML;
}

/* ---------- colour ---------- */

/** The event's Google colour, mixed down over the card surface.
 *
 * Returns a SOLID colour rather than a translucent one on purpose. A wash was
 * the obvious way to write this, but the contrast test walks computed
 * `backgroundColor`, and a translucent fill - or worse, a gradient - hides the
 * real background from it. Blending here keeps the rendered colour and the
 * measured colour the same thing.
 */
function washFor(hex, amount) {
  const surface = getComputedStyle(document.documentElement)
    .getPropertyValue("--surface").trim() || "#ffffff";
  const parse = (value) => {
    const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(value || "").trim());
    if (!m) return null;
    const full = m[1].length === 3 ? m[1].split("").map((c) => c + c).join("") : m[1];
    const n = parseInt(full, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };
  const event = parse(hex);
  const base = parse(surface) || [255, 255, 255];
  if (!event) return surface;
  const mixed = base.map((b, i) => Math.round(b + (event[i] - b) * amount));
  return `rgb(${mixed.join(", ")})`;
}

/* ---------- weather ---------- */

/** Clock time from an Open-Meteo stamp. Those carry no offset - timezone=auto
 *  already localised them - so they must NOT go through `new Date()` on a machine
 *  in another zone. Read the hour out of the string instead. */
function hourLabel(stamp) {
  const hour = Number(String(stamp).slice(11, 13));
  if (!Number.isFinite(hour)) return "";
  const suffix = hour < 12 ? "am" : "pm";
  const twelve = hour % 12 === 0 ? 12 : hour % 12;
  return `${twelve}${suffix}`;
}

/** The next ten hours. Same series the weather page uses, and the same anchoring
 *  rule: from the current hour, not from the start of the array - that array
 *  begins at local midnight, so slicing from zero shows this morning at teatime.
 *
 *  Compared on the whole `YYYY-MM-DDTHH` prefix rather than on the hour number,
 *  which matters because the series spans a week. Filtering on `hour >= 15` alone
 *  also matched TOMORROW's 3pm, so at half three the strip ran 3pm…11pm and then
 *  jumped back to "3pm". The prefix is lexicographically ordered, so a plain string
 *  comparison is also the chronological one, and the strip crosses midnight into
 *  12am rather than stopping at the end of the day. */
function renderHours(hours) {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const nowKey =
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
    `T${pad(now.getHours())}`;
  const upcoming = (hours || [])
    .filter((hour) => String(hour.time).slice(0, 13) >= nowKey)
    .slice(0, 10);

  hoursStrip.innerHTML = upcoming.length
    ? upcoming
        .map(
          (hour, index) => `
        <div class="today-hour${index === 0 ? " today-hour--now" : ""}">
          <div class="today-hour-when">${index === 0 ? "Now" : escapeText(hourLabel(hour.time))}</div>
          <div class="today-hour-icon">${weatherIcon(hour.icon)}</div>
          <div class="today-hour-temp">${hour.temperature}°</div>
          <div class="today-hour-rain">${
            hour.precip_chance >= 20 ? `${hour.precip_chance}%` : ""
          }</div>
        </div>`
        )
        .join("")
    : "";
}

/** Sunrise, sunset and how long the day is. */
function sunLine(data, today) {
  const clock = (iso) =>
    new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const parts = [];
  if (data.sunrise) parts.push(`↑ ${clock(data.sunrise)}`);
  if (data.sunset) parts.push(`↓ ${clock(data.sunset)}`);
  if (today && today.daylight_minutes) {
    const minutes = today.daylight_minutes;
    parts.push(`${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m of light`);
  }
  return parts.join(" · ");
}

// weather.js already polls and publishes; subscribing avoids a second request.
onWeather((data) => {
  if (!data || data.available === false) {
    weatherBlock.innerHTML = '<p class="today-empty">Weather unavailable</p>';
    forecastBlock.innerHTML = "";
    hoursStrip.innerHTML = "";
    return;
  }
  const today = data.days && data.days[0];
  weatherBlock.innerHTML = `
    <div class="today-weather-icon">${weatherIcon(data.icon)}</div>
    <div class="today-weather-temp">${data.temperature}°</div>
    <div class="today-weather-label">${escapeText(data.label)}</div>
    ${today ? `<div class="today-weather-range">High ${today.high}° · low ${today.low}°${
      today.precip_chance ? ` · ${today.precip_chance}% rain` : ""}</div>` : ""}
    <div class="today-weather-feels">${
      data.feels_like != null && data.feels_like !== data.temperature
        ? `Feels like ${data.feels_like}°`
        : ""}</div>
    <div class="today-weather-sun">${escapeText(sunLine(data, today))}</div>`;

  renderHours(data.hours);

  // The next few days. Same data the weather panel already fetched, so this
  // costs nothing but the markup.
  const rest = (data.days || []).slice(1, 4);
  forecastBlock.innerHTML = rest.length
    ? rest.map((day) => `
        <div class="today-forecast-day">
          <div class="today-forecast-name">${escapeText(shortDay(day.date))}</div>
          <div class="today-forecast-icon">${weatherIcon(day.icon)}</div>
          <div class="today-forecast-temps"><strong>${day.high}°</strong> ${day.low}°</div>
        </div>`).join("")
    : "";
});

/* ---------- schedule ---------- */

/** "Sat", or "Sat–Tue" for something that spans days.
 *
 * The day label used to come from `event.start_date` for every occurrence, so
 * each of the four days of a trip was labelled with the day the trip began -
 * three rows all reading "Sat" under "Coming up". */
function dayLabel(event, dayIso) {
  const weekday = (iso) =>
    new Date(iso + "T00:00:00").toLocaleDateString(undefined, { weekday: "short" });
  const start = event.start_date;
  const end = event.end_date;
  if (event.all_day && end && end !== start) return `${weekday(start)}–${weekday(end)}`;
  return weekday(dayIso || start);
}

function eventRow(event, { showDay = false, dayIso = null } = {}) {
  const li = document.createElement("li");
  li.className = "today-event";
  li.style.borderLeftColor = event.color;
  // A faint tint of the event's own colour, so the calendar an event belongs to
  // is readable at a glance instead of every row being the same grey.
  li.style.backgroundColor = washFor(event.color, 0.16);

  const when = event.all_day ? "All day" : event.start_time;
  const prefix = showDay ? dayLabel(event, dayIso) : "";

  li.innerHTML = `<div class="today-event-when">${
      prefix ? `<span class="today-event-day">${escapeText(prefix)}</span>` : ""
    }<span class="today-event-time">${escapeText(when)}</span></div>
    <div class="today-event-body">
      <div class="today-event-title">${escapeText(event.title)}</div>
      <div class="today-event-meta">${escapeText(
        [event.owner_label, event.location].filter(Boolean).join(" · ")
      )}</div>
    </div>`;
  return li;
}

/* ---------- up next ---------- */

/** The next thing today, with how long until it. The single most useful line on
 *  a morning screen, and the page previously didn't have it. */
function renderNextUp(events) {
  const now = new Date();
  const upcoming = events.filter(
    (event) => !event.all_day && event.start_iso && new Date(event.start_iso) > now
  );
  if (upcoming.length === 0) {
    const allDay = events.filter((event) => event.all_day);
    nextUpBlock.innerHTML = `<div class="today-next-up-label">Up next</div>
      <div class="today-next-up-empty">${
        allDay.length ? "Nothing else scheduled today." : "Nothing scheduled today."
      }</div>`;
    return;
  }

  const event = upcoming[0];
  const minutes = Math.round((new Date(event.start_iso) - now) / 60000);
  const until =
    minutes < 1 ? "now"
    : minutes < 60 ? `in ${minutes} min`
    : `in ${Math.floor(minutes / 60)}h ${minutes % 60 ? `${minutes % 60}m` : ""}`.trim();

  nextUpBlock.innerHTML = `<div class="today-next-up-label">Up next</div>
    <div class="today-next-up-when">${escapeText(until)}</div>
    <div class="today-next-up-title">${escapeText(event.title)}</div>
    <div class="today-next-up-meta">${escapeText(
      [event.start_time, event.owner_label, event.location].filter(Boolean).join(" · ")
    )}</div>`;
  nextUpBlock.style.borderLeftColor = event.color;
}

async function loadToday() {
  const iso = todayIso();
  const [y, m, d] = iso.split("-");
  try {
    const resp = await fetch(`/api/calendar/day/${+y}/${+m}/${+d}`);
    const data = await resp.json();
    const events = (data.days && data.days[0] && data.days[0].events) || [];

    renderNextUp(events);

    eventsList.innerHTML = "";
    if (events.length === 0) {
      empty(eventsList, "Nothing scheduled today.");
    } else {
      // Past events are dimmed rather than hidden: "did I miss it" is a question
      // people ask the wall, and hiding the answer is unhelpful.
      const nowMinutes = new Date().getHours() * 60 + new Date().getMinutes();
      events.forEach((event) => {
        const row = eventRow(event);
        if (!event.all_day && event.end_iso) {
          const end = new Date(event.end_iso);
          const endMinutes = end.getHours() * 60 + end.getMinutes();
          if (endMinutes < nowMinutes) row.classList.add("today-event--past");
        }
        eventsList.appendChild(row);
      });
    }
  } catch (e) {
    eventsList.innerHTML = "";
    empty(eventsList, "Couldn't load today's events.");
  }
}

/** Identity across days, for collapsing a multi-day event to one row.
 *  The agenda repeats a spanning event under every day it covers - correct for a
 *  day-by-day view, wrong for a list of what's coming. */
function eventKey(event) {
  return event.event_id || `${event.title}|${event.start_date}|${event.start_time || ""}`;
}

async function loadUpcoming() {
  try {
    const resp = await fetch("/api/calendar/agenda?days=7");
    const data = await resp.json();
    const iso = todayIso();
    const days = (data.days || []).filter((day) => day.date > iso);

    nextList.innerHTML = "";
    const seen = new Set();
    let shown = 0;
    for (const day of days) {
      for (const event of day.events) {
        const key = eventKey(event);
        if (seen.has(key)) continue;
        seen.add(key);
        nextList.appendChild(eventRow(event, { showDay: true, dayIso: day.date }));
        shown += 1;
      }
    }
    if (shown === 0) empty(nextList, "Nothing in the next week.");
  } catch (e) {
    nextList.innerHTML = "";
    empty(nextList, "Couldn't load the week.");
  }
}

/** Air quality and pollen.
 *
 * Its own fetch rather than a shell subscription, because unlike weather there is
 * no publisher to subscribe to - /weather is the only other page that reads this.
 * The two halves fail independently by design (pollen comes from an undocumented
 * endpoint that will break one day), so each is rendered only if it answered.
 */
async function loadAir() {
  try {
    const resp = await fetch("/api/weather/air");
    const data = await resp.json();
    const rows = [];

    if (data.aqi && data.aqi.available) {
      rows.push({
        label: "Air",
        value: `${data.aqi.aqi} · ${data.aqi.label}`,
        note: data.aqi.note || "",
      });
    }
    if (data.pollen && data.pollen.available && data.pollen.today) {
      const today = data.pollen.today;
      rows.push({
        label: "Pollen",
        // The scale is part of the reading: pollen.com's index runs 0-12 and
        // Google's 0-5, so a bare "7.6" means opposite things depending on which
        // answered. /weather makes the same point at more length.
        value: `${today.index} of ${data.pollen.scale_max} · ${today.label}`,
        note: (today.triggers || []).slice(0, 3).join(", "),
      });
    }

    airBlock.innerHTML = rows.length
      ? rows
          .map(
            (row) => `
        <div class="today-air-row">
          <span class="today-air-label">${escapeText(row.label)}</span>
          <span class="today-air-value">${escapeText(row.value)}</span>
          <span class="today-air-note">${escapeText(row.note)}</span>
        </div>`
          )
          .join("")
      : "";
  } catch (e) {
    // Decoration. A failure here leaves the block empty and collapsed rather than
    // putting an error on a morning screen.
    airBlock.innerHTML = "";
  }
}

/** What's on the shopping list, grouped by aisle.
 *
 * A glance, not a tool: no checkboxes here. Ticking things off wants the tap
 * targets on /groceries, and a mis-tap from across the kitchen that silently
 * removes something from the list is worse than walking over.
 */
async function loadGroceries() {
  try {
    const resp = await fetch("/api/groceries");
    const data = await resp.json();
    groceriesList.innerHTML = "";

    if (data.available === false) {
      const li = document.createElement("li");
      li.className = "today-empty";
      // Not "broken": the usual reason is that the wall has no credential for the
      // list yet, and the list is still fine on everyone's phone.
      li.innerHTML = `${escapeText(data.errors[0] || "Grocery list unavailable")}`;
      groceriesList.appendChild(li);
      return;
    }

    if (!data.open_count) {
      empty(groceriesList, data.done_count ? "All picked up." : "Nothing to buy.");
      return;
    }

    // Aisle by aisle, in the same store order as the page, capped so a big shop
    // doesn't push "Coming up" off the screen.
    let shown = 0;
    for (const group of data.groups) {
      if (shown >= GROCERY_PREVIEW_LIMIT) break;
      const li = document.createElement("li");
      li.className = "today-grocery-aisle";
      const names = group.items
        .slice(0, GROCERY_PREVIEW_LIMIT - shown)
        .map((item) => item.display);
      shown += names.length;
      li.innerHTML = `<span class="today-grocery-label">${escapeText(group.label)}</span>
        <span class="today-grocery-items">${escapeText(names.join(", "))}</span>`;
      groceriesList.appendChild(li);
    }

    const remaining = data.open_count - shown;
    if (remaining > 0) {
      const li = document.createElement("li");
      li.className = "today-grocery-more";
      li.textContent = `+ ${remaining} more`;
      groceriesList.appendChild(li);
    }
  } catch (e) {
    groceriesList.innerHTML = "";
    empty(groceriesList, "Couldn't load the grocery list.");
  }
}

function refreshAll() {
  loadToday();
  loadUpcoming();
  loadGroceries();
  loadAir();
}

refreshAll();
setInterval(refreshAll, 5 * 60 * 1000);
