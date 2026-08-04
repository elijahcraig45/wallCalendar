const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const view = document.getElementById("calendar-view");
let year = parseInt(view.dataset.year, 10);
let month = parseInt(view.dataset.month, 10);

const monthLabel = document.getElementById("month-label");
const monthGrid = document.getElementById("month-grid");
const weekdayRow = document.getElementById("weekday-row");
const weekView = document.getElementById("week-view");
const agendaView = document.getElementById("agenda-view");
const prevBtn = document.getElementById("prev-month");
const nextBtn = document.getElementById("next-month");
const overlay = document.getElementById("day-overlay");
const overlayDate = document.getElementById("day-overlay-date");
const overlayEvents = document.getElementById("day-overlay-events");

function todayIso() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function addDaysIso(iso, delta) {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + delta);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/* ---------- view switcher (month / week / agenda) ---------- */

let currentView = localStorage.getItem("calendar_view") || "month";
let weekAnchor = todayIso();

function applyViewVisibility() {
  document.querySelectorAll(".view-tab").forEach((tab) => {
    tab.setAttribute("aria-selected", tab.dataset.view === currentView ? "true" : "false");
  });
  weekdayRow.classList.toggle("hidden", currentView !== "month");
  monthGrid.classList.toggle("hidden", currentView !== "month");
  weekView.classList.toggle("hidden", currentView !== "week");
  agendaView.classList.toggle("hidden", currentView !== "agenda");
  // Prev/next don't map cleanly onto agenda's rolling forward-looking window.
  prevBtn.classList.toggle("hidden", currentView === "agenda");
  nextBtn.classList.toggle("hidden", currentView === "agenda");
}

document.querySelectorAll(".view-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    currentView = tab.dataset.view;
    localStorage.setItem("calendar_view", currentView);
    applyViewVisibility();
    loadCurrentView();
  });
});

function loadCurrentView() {
  if (currentView === "week") return loadWeek();
  if (currentView === "agenda") return loadAgenda();
  return loadMonth();
}

async function loadMonth() {
  monthLabel.textContent = `${MONTH_NAMES[month - 1]} ${year}`;
  const resp = await fetch(`/api/calendar/${year}/${month}`);
  const grid = await resp.json();
  renderGrid(grid);
  updateAccountErrorBadge(grid.errors || []);
}

async function loadWeek() {
  const [wy, wm, wd] = weekAnchor.split("-").map(Number);
  const resp = await fetch(`/api/calendar/week/${wy}/${wm}/${wd}`);
  const data = await resp.json();
  const from = new Date(data.from + "T00:00:00");
  const to = new Date(data.to + "T00:00:00");
  const fmt = { month: "short", day: "numeric" };
  monthLabel.textContent = `${from.toLocaleDateString(undefined, fmt)} – ${to.toLocaleDateString(undefined, fmt)}`;
  renderDayGroups(weekView, data.days, "week-day-row", "week-day-label", "week-day-events", "No events");
  updateAccountErrorBadge(data.errors || []);
}

async function loadAgenda() {
  const resp = await fetch("/api/calendar/agenda?days=30");
  const data = await resp.json();
  monthLabel.textContent = "Next 30 days";
  if (data.days.length === 0) {
    agendaView.innerHTML = "";
    const li = document.createElement("li");
    li.textContent = "Nothing coming up";
    agendaView.appendChild(li);
  } else {
    renderDayGroups(agendaView, data.days, "agenda-day-group", "agenda-day-header", "agenda-day-events", null);
  }
  updateAccountErrorBadge(data.errors || []);
}

function renderDayGroups(container, days, rowClass, labelClass, listClass, emptyText) {
  container.innerHTML = "";
  const today = todayIso();

  days.forEach((day) => {
    const li = document.createElement("li");
    li.className = rowClass;

    const label = document.createElement("div");
    label.className = labelClass;
    if (day.date === today) label.classList.add("today");
    const d = new Date(day.date + "T00:00:00");
    label.textContent = d.toLocaleDateString(undefined, {
      weekday: "long", month: "short", day: "numeric",
    });
    li.appendChild(label);

    const eventsList = document.createElement("ul");
    eventsList.className = listClass;
    if (day.events.length === 0 && emptyText) {
      const empty = document.createElement("li");
      empty.className = "week-day-empty";
      empty.textContent = emptyText;
      eventsList.appendChild(empty);
    } else {
      day.events.forEach((ev) => eventsList.appendChild(renderEventCard(ev)));
    }
    li.appendChild(eventsList);

    container.appendChild(li);
  });
}

function updateAccountErrorBadge(errors) {
  const badge = document.getElementById("manage-calendars-badge");
  const button = document.getElementById("manage-calendars-toggle");
  if (errors.length > 0) {
    badge.classList.remove("hidden");
    button.title = errors.map((e) => e.message).join("\n");
  } else {
    badge.classList.add("hidden");
    button.removeAttribute("title");
  }
}

function renderGrid(grid) {
  monthGrid.innerHTML = "";
  const today = todayIso();
  const dates = Object.keys(grid.days).sort();

  for (const dateStr of dates) {
    const cell = document.createElement("div");
    cell.className = "day-cell";
    const dayNum = parseInt(dateStr.slice(8, 10), 10);
    const cellMonth = parseInt(dateStr.slice(5, 7), 10);

    if (cellMonth !== grid.month) cell.classList.add("outside-month");
    if (dateStr === today) cell.classList.add("today");

    const numEl = document.createElement("div");
    numEl.className = "day-number";
    numEl.textContent = dayNum;
    cell.appendChild(numEl);

    const events = grid.days[dateStr];
    const maxShown = 3;
    events.slice(0, maxShown).forEach((ev) => {
      const pill = document.createElement("div");
      pill.className = "event-pill";
      pill.style.background = ev.color;
      pill.textContent = ev.title;
      cell.appendChild(pill);
    });

    if (events.length > maxShown) {
      const more = document.createElement("div");
      more.className = "event-overflow";
      more.textContent = `+${events.length - maxShown} more`;
      cell.appendChild(more);
    }

    cell.addEventListener("click", () => openDayOverlay(dateStr, events));
    monthGrid.appendChild(cell);
  }
}

function renderEventCard(ev, { showDate = false } = {}) {
  const li = document.createElement("li");
  li.className = "event-card";
  li.style.borderLeftColor = ev.color;

  const time = document.createElement("div");
  time.className = "event-card-time";
  const timeText = ev.all_day ? "All day" : `${ev.start_time} – ${ev.end_time}`;
  time.textContent = showDate
    ? `${new Date(ev.start_date + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" })} · ${timeText}`
    : timeText;
  li.appendChild(time);

  const title = document.createElement("div");
  title.className = "event-card-title";
  title.textContent = ev.title;
  li.appendChild(title);

  const meta = document.createElement("div");
  meta.className = "event-card-meta";

  const owner = document.createElement("span");
  owner.className = "event-owner";
  const dot = document.createElement("span");
  dot.className = "event-dot";
  dot.style.background = ev.color;
  owner.appendChild(dot);
  owner.appendChild(document.createTextNode(ev.owner_label));
  meta.appendChild(owner);

  if (ev.location) {
    const location = document.createElement("span");
    location.className = "event-location";
    location.textContent = ev.location;
    meta.appendChild(location);
  }

  li.appendChild(meta);
  return li;
}

function openDayOverlay(dateStr, events) {
  const d = new Date(dateStr + "T00:00:00");
  overlayDate.textContent = d.toLocaleDateString(undefined, {
    weekday: "long", month: "long", day: "numeric",
  });
  overlayEvents.innerHTML = "";

  if (events.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No events";
    overlayEvents.appendChild(li);
  }

  events.forEach((ev) => {
    const card = renderEventCard(ev);
    if (ev.access_role === "owner" || ev.access_role === "writer") {
      card.classList.add("event-card--editable");
      card.addEventListener("click", () => {
        dayPanel.close();
        openEditEventModal(ev);
      });
    }
    overlayEvents.appendChild(card);
  });

  const addRow = document.createElement("li");
  addRow.className = "event-card add-event-row";
  addRow.textContent = "+ Add event on this day";
  addRow.addEventListener("click", () => {
    dayPanel.close();
    openAddEventModal(dateStr);
  });
  overlayEvents.appendChild(addRow);

  dayPanel.open();
}

const dayPanel = initPanel("day-overlay", "day-overlay-close");

prevBtn.addEventListener("click", () => {
  if (currentView === "week") {
    weekAnchor = addDaysIso(weekAnchor, -7);
  } else {
    month -= 1;
    if (month < 1) { month = 12; year -= 1; }
  }
  loadCurrentView();
});

nextBtn.addEventListener("click", () => {
  if (currentView === "week") {
    weekAnchor = addDaysIso(weekAnchor, 7);
  } else {
    month += 1;
    if (month > 12) { month = 1; year += 1; }
  }
  loadCurrentView();
});

async function post(path, body) {
  const resp = await fetch(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!resp.ok) {
    let message = "Something went wrong";
    try {
      const data = await resp.json();
      message = data.error || message;
    } catch (e) {
      // response body wasn't JSON - keep the generic message
    }
    showToast(message);
    return false;
  }
  return true;
}

async function loadAccountLabels() {
  const resp = await fetch("/api/calendar/accounts");
  const accounts = await resp.json();
  const labelByEmail = {};
  accounts.forEach((a) => { labelByEmail[a.email] = a.label; });
  return labelByEmail;
}

/* ---------- manage calendars ---------- */

const calendarsPanel = initPanel("calendars-overlay", "calendars-close");
const calendarsList = document.getElementById("calendars-list");

document.getElementById("manage-calendars-toggle").addEventListener("click", () => {
  loadCalendars();
  calendarsPanel.open();
});

async function loadCalendars() {
  const [calResp, labelByEmail] = await Promise.all([
    fetch("/api/calendar/calendars"),
    loadAccountLabels(),
  ]);
  const data = await calResp.json();
  const excluded = new Set(data.excluded_calendar_ids);
  calendarsList.innerHTML = "";

  let lastAccount = null;
  data.calendars.forEach((cal) => {
    if (cal.account !== lastAccount) {
      const header = document.createElement("li");
      header.className = "account-group-header";
      header.textContent = labelByEmail[cal.account] || cal.account;
      calendarsList.appendChild(header);
      lastAccount = cal.account;
    }

    const li = document.createElement("li");

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = !excluded.has(cal.calendar_id);
    checkbox.addEventListener("change", async () => {
      const ok = await post("/api/calendar/calendars/visibility", {
        calendar_id: cal.calendar_id,
        excluded: !checkbox.checked,
      });
      if (ok) loadCurrentView();
    });
    li.appendChild(checkbox);

    const label = document.createElement("span");
    label.className = "row-title";
    label.textContent = cal.summary;
    li.appendChild(label);

    calendarsList.appendChild(li);
  });
}

/* ---------- add / edit event ---------- */

const addEventPanel = initPanel("add-event-overlay", "add-event-close");
const addEventForm = document.getElementById("add-event-form");
const addEventHeading = document.getElementById("add-event-heading");
const titleInput = document.getElementById("add-event-title");
const calendarSelect = document.getElementById("add-event-calendar");
const allDayCheckbox = document.getElementById("add-event-all-day");
const datetimeFields = document.getElementById("add-event-datetime-fields");
const dateFields = document.getElementById("add-event-date-fields");
const startInput = document.getElementById("add-event-start");
const endInput = document.getElementById("add-event-end");
const startDateInput = document.getElementById("add-event-start-date");
const endDateInput = document.getElementById("add-event-end-date");
const locationInput = document.getElementById("add-event-location");
const descriptionInput = document.getElementById("add-event-description");
const recurrenceField = document.getElementById("add-event-recurrence-field");
const recurrenceSelect = document.getElementById("add-event-recurrence");
const recurrenceNote = document.getElementById("add-event-recurrence-note");
const untilField = document.getElementById("add-event-until-field");
const untilInput = document.getElementById("add-event-until");
const guestsInput = document.getElementById("add-event-guests");
const submitBtn = document.getElementById("add-event-submit");
const deleteBtn = document.getElementById("add-event-delete");

let writableCalendars = [];
// Non-null in edit mode: {account, calendar_id, event_id, time_zone}.
let editingEvent = null;

document.getElementById("add-event-toggle").addEventListener("click", () => {
  openAddEventModal(todayIso());
});

allDayCheckbox.addEventListener("change", updateDateFieldVisibility);
recurrenceSelect.addEventListener("change", updateUntilVisibility);

function updateDateFieldVisibility() {
  datetimeFields.classList.toggle("hidden", allDayCheckbox.checked);
  dateFields.classList.toggle("hidden", !allDayCheckbox.checked);
}

function updateUntilVisibility() {
  untilField.classList.toggle("hidden", recurrenceSelect.value === "none");
}

async function openAddEventModal(prefillDateIso) {
  editingEvent = null;
  addEventHeading.textContent = "Add Event";
  submitBtn.textContent = "Create Event";
  deleteBtn.classList.add("hidden");
  resetDeleteArmState();
  calendarSelect.disabled = false;
  recurrenceSelect.disabled = false;
  recurrenceField.classList.remove("hidden");
  recurrenceNote.classList.add("hidden");

  const [calResp, labelByEmail] = await Promise.all([
    fetch("/api/calendar/calendars?writable_only=true"),
    loadAccountLabels(),
  ]);
  const calData = await calResp.json();
  writableCalendars = calData.calendars;

  addEventForm.reset();
  calendarSelect.innerHTML = "";

  if (writableCalendars.length === 0) {
    const opt = document.createElement("option");
    opt.textContent = "No calendars available to add events to";
    calendarSelect.appendChild(opt);
    submitBtn.disabled = true;
  } else {
    submitBtn.disabled = false;
    writableCalendars.forEach((cal, idx) => {
      const opt = document.createElement("option");
      opt.value = idx;
      opt.textContent = `${cal.summary} — ${labelByEmail[cal.account] || cal.account}`;
      calendarSelect.appendChild(opt);
    });
  }

  allDayCheckbox.checked = false;
  updateDateFieldVisibility();
  recurrenceSelect.value = "none";
  updateUntilVisibility();

  const date = prefillDateIso || todayIso();
  startDateInput.value = date;
  endDateInput.value = date;
  startInput.value = `${date}T09:00`;
  endInput.value = `${date}T10:00`;

  addEventPanel.open();
}

async function openEditEventModal(ev) {
  const [labelByEmail, detailResp] = await Promise.all([
    loadAccountLabels(),
    fetch(
      `/api/calendar/event?account=${encodeURIComponent(ev.account)}` +
      `&calendar_id=${encodeURIComponent(ev.calendar_id)}` +
      `&event_id=${encodeURIComponent(ev.event_id)}`
    ),
  ]);
  const detail = await detailResp.json();

  editingEvent = {
    account: ev.account,
    calendar_id: ev.calendar_id,
    event_id: ev.event_id,
    time_zone: detail.time_zone,
  };

  addEventHeading.textContent = "Edit Event";
  submitBtn.textContent = "Save Changes";
  submitBtn.disabled = false;
  deleteBtn.classList.remove("hidden");
  resetDeleteArmState();

  addEventForm.reset();
  calendarSelect.innerHTML = "";
  const opt = document.createElement("option");
  opt.textContent = `${ev.owner_label ? ev.owner_label + " — " : ""}${labelByEmail[ev.account] || ev.account}`;
  calendarSelect.appendChild(opt);
  calendarSelect.disabled = true;

  titleInput.value = detail.title;
  locationInput.value = detail.location || "";
  descriptionInput.value = detail.description || "";

  allDayCheckbox.checked = detail.all_day;
  updateDateFieldVisibility();
  if (detail.all_day) {
    startDateInput.value = detail.start;
    endDateInput.value = detail.end;
  } else {
    startInput.value = detail.start;
    endInput.value = detail.end;
  }

  if (detail.recurring_event_id) {
    recurrenceField.classList.add("hidden");
    recurrenceNote.classList.remove("hidden");
    recurrenceSelect.value = "none";
    recurrenceSelect.disabled = true;
  } else {
    recurrenceField.classList.remove("hidden");
    recurrenceNote.classList.add("hidden");
    recurrenceSelect.disabled = false;
    recurrenceSelect.value = "none";
  }
  updateUntilVisibility();

  guestsInput.value = detail.guests.join(", ");

  addEventPanel.open();
}

function resetDeleteArmState() {
  deleteBtn.removeAttribute("data-armed");
  deleteBtn.textContent = "Delete Event";
}

deleteBtn.addEventListener("click", async () => {
  if (!editingEvent) return;

  if (deleteBtn.dataset.armed !== "true") {
    deleteBtn.dataset.armed = "true";
    deleteBtn.textContent = "Tap again to confirm delete";
    return;
  }

  const notifyGuests = guestsInput.value.trim().length > 0;
  const ok = await post("/api/calendar/events/delete", {
    account: editingEvent.account,
    calendar_id: editingEvent.calendar_id,
    event_id: editingEvent.event_id,
    notify_guests: notifyGuests,
  });
  if (ok) {
    addEventPanel.close();
    showToast("Event deleted");
    loadCurrentView();
  } else {
    resetDeleteArmState();
  }
});

addEventForm.addEventListener("submit", async (e) => {
  e.preventDefault();

  const allDay = allDayCheckbox.checked;
  const recurrenceFreq = recurrenceSelect.value;
  const guests = guestsInput.value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const commonBody = {
    title: titleInput.value,
    location: locationInput.value,
    description: descriptionInput.value,
    all_day: allDay,
    start: allDay ? startDateInput.value : startInput.value,
    end: allDay ? endDateInput.value : endInput.value,
    recurrence_freq: recurrenceFreq,
    recurrence_until: recurrenceFreq !== "none" ? untilInput.value || null : null,
    guests,
  };

  if (editingEvent) {
    const ok = await post("/api/calendar/events/update", {
      ...commonBody,
      account: editingEvent.account,
      calendar_id: editingEvent.calendar_id,
      event_id: editingEvent.event_id,
      time_zone: editingEvent.time_zone,
    });
    if (ok) {
      addEventPanel.close();
      showToast("Event updated");
      loadCurrentView();
    }
    return;
  }

  const chosen = writableCalendars[parseInt(calendarSelect.value, 10)];
  if (!chosen) return;

  const ok = await post("/api/calendar/events", {
    ...commonBody,
    account: chosen.account,
    calendar_id: chosen.calendar_id,
    time_zone: chosen.time_zone,
  });
  if (ok) {
    addEventPanel.close();
    showToast("Event created");
    loadCurrentView();
  }
});

const POLL_INTERVAL_MS = 5 * 60 * 1000;
let pollTimer = setInterval(loadCurrentView, POLL_INTERVAL_MS);

document.getElementById("refresh-toggle").addEventListener("click", async () => {
  if (navigator.vibrate) navigator.vibrate(30);
  await post("/api/calendar/refresh");
  await loadCurrentView();
  showToast("Refreshed");
  // A manual refresh restarts the 5-minute poll clock from now, rather than
  // firing again on whatever schedule it was already on.
  clearInterval(pollTimer);
  pollTimer = setInterval(loadCurrentView, POLL_INTERVAL_MS);
});

applyViewVisibility();
loadCurrentView();
