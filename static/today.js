/* The morning overview.
 *
 * Deliberately built only from endpoints that already exist - today's events, the
 * agenda, weather, notes. It introduces no server-side view of its own, so it
 * can't disagree with the pages it summarises, and anything fixed there is fixed
 * here too.
 */

const heading = document.getElementById("today-heading");
const weatherBlock = document.getElementById("today-weather");
const eventsList = document.getElementById("today-events");
const notesList = document.getElementById("today-notes");
const nextList = document.getElementById("today-next");

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

/* ---------- weather ---------- */

// weather.js already polls and publishes; subscribing avoids a second request.
onWeather((data) => {
  if (!data || data.available === false) {
    weatherBlock.innerHTML = '<p class="today-empty">Weather unavailable</p>';
    return;
  }
  const today = data.days && data.days[0];
  weatherBlock.innerHTML = `
    <div class="today-weather-icon">${weatherIcon(data.icon)}</div>
    <div class="today-weather-temp">${data.temperature}°</div>
    <div class="today-weather-label">${data.label}</div>
    ${today ? `<div class="today-weather-range">High ${today.high}° · low ${today.low}°${
      today.precip_chance ? ` · ${today.precip_chance}% rain` : ""}</div>` : ""}
    <div class="today-weather-sun">${
      data.sunset
        ? "Sunset " + new Date(data.sunset).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
        : ""}</div>`;
});

/* ---------- schedule ---------- */

function eventRow(event, { showDay = false } = {}) {
  const li = document.createElement("li");
  li.className = "today-event";
  li.style.borderLeftColor = event.color;

  const when = event.all_day
    ? "All day"
    : `${event.start_time}`;
  const prefix = showDay
    ? new Date(event.start_date + "T00:00:00").toLocaleDateString(undefined, { weekday: "short" }) + " · "
    : "";

  li.innerHTML = `<div class="today-event-when">${prefix}${when}</div>
    <div class="today-event-title">${escapeText(event.title)}</div>
    <div class="today-event-meta">${escapeText(
      [event.owner_label, event.location].filter(Boolean).join(" · ")
    )}</div>`;
  return li;
}

function escapeText(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : text;
  return div.innerHTML;
}

async function loadToday() {
  const iso = todayIso();
  const [y, m, d] = iso.split("-");
  try {
    const resp = await fetch(`/api/calendar/day/${+y}/${+m}/${+d}`);
    const data = await resp.json();
    const events = (data.days && data.days[0] && data.days[0].events) || [];

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

async function loadUpcoming() {
  try {
    const resp = await fetch("/api/calendar/agenda?days=7");
    const data = await resp.json();
    const iso = todayIso();
    const days = (data.days || []).filter((day) => day.date > iso);

    nextList.innerHTML = "";
    if (days.length === 0) {
      empty(nextList, "Nothing in the next week.");
      return;
    }
    days.slice(0, 4).forEach((day) => {
      day.events.slice(0, 3).forEach((event) => {
        nextList.appendChild(eventRow(event, { showDay: true }));
      });
    });
  } catch (e) {
    nextList.innerHTML = "";
    empty(nextList, "Couldn't load the week.");
  }
}

async function loadNotes() {
  try {
    const resp = await fetch("/api/notes");
    const data = await resp.json();
    notesList.innerHTML = "";

    if (data.available === false) {
      const li = document.createElement("li");
      li.className = "today-empty";
      li.innerHTML = `${escapeText(data.errors[0] || "Notes unavailable")} <a href="/notes">Set up</a>`;
      notesList.appendChild(li);
      return;
    }

    const open = data.notes.filter((note) => !note.done).slice(0, 6);
    if (open.length === 0) {
      empty(notesList, "The list is clear.");
      return;
    }
    open.forEach((note) => {
      const li = document.createElement("li");
      li.className = "today-note";
      li.textContent = note.title;
      notesList.appendChild(li);
    });
  } catch (e) {
    notesList.innerHTML = "";
    empty(notesList, "Couldn't load notes.");
  }
}

function refreshAll() {
  loadToday();
  loadUpcoming();
  loadNotes();
}

refreshAll();
setInterval(refreshAll, 5 * 60 * 1000);
