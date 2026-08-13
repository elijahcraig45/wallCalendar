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
const agendaView = document.getElementById("agenda-view");
const noAccounts = document.getElementById("no-accounts");
const staleBadge = document.getElementById("stale-badge");
const prevBtn = document.getElementById("prev-month");
const nextBtn = document.getElementById("next-month");
const overlay = document.getElementById("day-overlay");
const overlayDate = document.getElementById("day-overlay-date");
const overlayEvents = document.getElementById("day-overlay-events");

const timegrid = document.getElementById("timegrid");
const timegridWrap = document.getElementById("timegrid-wrap");
const dayDetail = document.getElementById("day-detail");
const dayDetailHeader = document.getElementById("day-detail-header");
const dayDetailList = document.getElementById("day-detail-list");
const timegridHeadDays = document.getElementById("timegrid-head-days");
const timegridAllDayCols = document.getElementById("timegrid-allday-cols");
const timegridScroll = document.getElementById("timegrid-scroll");
const timegridGutter = document.getElementById("timegrid-gutter");
const timegridCols = document.getElementById("timegrid-cols");

function todayIso() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function addDaysIso(iso, delta) {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + delta);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/* ---------- view switcher (day / week / month / agenda) ---------- */

let currentView = localStorage.getItem("calendar_view") || "month";
// One anchor date drives both day and week - switching between them keeps you
// on the same date rather than snapping back to today.
let dayAnchor = todayIso();

function applyViewVisibility() {
  document.querySelectorAll(".view-tab").forEach((tab) => {
    tab.setAttribute("aria-selected", tab.dataset.view === currentView ? "true" : "false");
  });
  weekdayRow.classList.toggle("hidden", currentView !== "month");
  monthGrid.classList.toggle("hidden", currentView !== "month");
  timegridWrap.classList.toggle("hidden", currentView !== "week" && currentView !== "day");
  dayDetail.classList.toggle("hidden", currentView !== "day");
  agendaView.classList.toggle("hidden", currentView !== "agenda");
  // Prev/next don't map cleanly onto agenda's rolling forward-looking window.
  prevBtn.classList.toggle("hidden", currentView === "agenda");
  nextBtn.classList.toggle("hidden", currentView === "agenda");
}

document.querySelectorAll(".view-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    setView(tab.dataset.view);
  });
});

function setView(next) {
  currentView = next;
  localStorage.setItem("calendar_view", currentView);
  applyViewVisibility();
  loadCurrentView();
}

function loadCurrentView() {
  if (currentView === "day") return loadDay();
  if (currentView === "week") return loadWeek();
  if (currentView === "agenda") return loadAgenda();
  return loadMonth();
}

/* Every load takes a ticket and only paints if it's still the newest one.
   Without this, tapping through months faster than the API answers lets a slow
   response for a month you've left land *after* a faster one and overwrite the
   screen - the header says August while the grid shows September. Very easy to
   hit on a Pi over wifi, where a cache-miss month can take seconds. */
let renderToken = 0;

async function loadMonth() {
  const token = ++renderToken;
  applyMonthTheme(month);
  monthLabel.textContent = `${MONTH_NAMES[month - 1]} ${year}`;
  const resp = await fetch(`/api/calendar/${year}/${month}`);
  const grid = await resp.json();
  if (token !== renderToken) return;
  renderGrid(grid);
  updateAccountErrorBadge(grid.errors || []);
  updateStaleIndicator(grid);
}

async function loadWeek() {
  const token = ++renderToken;
  const [wy, wm, wd] = dayAnchor.split("-").map(Number);
  const resp = await fetch(`/api/calendar/week/${wy}/${wm}/${wd}`);
  const data = await resp.json();
  if (token !== renderToken) return;
  const from = new Date(data.from + "T00:00:00");
  const to = new Date(data.to + "T00:00:00");
  const fmt = { month: "short", day: "numeric" };
  // Themed by the month the visible week mostly falls in, so a week straddling
  // two months doesn't flicker between accents as you page through.
  applyMonthTheme(from.getMonth() + 1);
  monthLabel.textContent = `${from.toLocaleDateString(undefined, fmt)} – ${to.toLocaleDateString(undefined, fmt)}`;
  renderTimeGrid(data.days);
  updateAccountErrorBadge(data.errors || []);
  updateStaleIndicator(data);
}

async function loadDay() {
  const token = ++renderToken;
  const [dy, dm, dd] = dayAnchor.split("-").map(Number);
  const resp = await fetch(`/api/calendar/day/${dy}/${dm}/${dd}`);
  const data = await resp.json();
  if (token !== renderToken) return;
  applyMonthTheme(new Date(dayAnchor + "T00:00:00").getMonth() + 1);
  monthLabel.textContent = new Date(dayAnchor + "T00:00:00").toLocaleDateString(undefined, {
    weekday: "long", month: "long", day: "numeric",
  });
  renderTimeGrid(data.days);
  renderDayDetail(data.days[0]);
  updateAccountErrorBadge(data.errors || []);
  updateStaleIndicator(data);
}

function renderDayDetail(day) {
  const events = day ? day.events : [];
  dayDetailHeader.textContent =
    events.length === 0 ? "Nothing scheduled" :
    events.length === 1 ? "1 event" : `${events.length} events`;

  dayDetailList.innerHTML = "";
  events.forEach((ev) => {
    const card = renderEventCard(ev);
    attachEventOpen(card, ev);
    dayDetailList.appendChild(card);
  });

  const addRow = document.createElement("li");
  addRow.className = "event-card add-event-row";
  addRow.textContent = "+ Add event";
  addRow.addEventListener("click", () => openAddEventModal(dayAnchor));
  dayDetailList.appendChild(addRow);
}

async function loadAgenda() {
  const token = ++renderToken;
  const resp = await fetch("/api/calendar/agenda?days=30");
  const data = await resp.json();
  if (token !== renderToken) return;
  monthLabel.textContent = "Next 30 days";
  if (data.days.length === 0) {
    agendaView.innerHTML = "";
    const li = document.createElement("li");
    li.className = "agenda-day-group";
    li.textContent = "Nothing coming up";
    agendaView.appendChild(li);
  } else {
    renderDayGroups(agendaView, data.days, "agenda-day-group", "agenda-day-header", "agenda-day-events", null);
  }
  updateAccountErrorBadge(data.errors || []);
  updateStaleIndicator(data);
}

/* ---------- time grid (week + day) ---------- */

/* The grid shows a window of hours, not a fixed midnight-to-midnight 24. A wall
   that spends half its height on empty overnight hours is wasting the half of
   the screen people actually look at, so the window is derived from the events
   on screen: a waking-hours default, widened whenever something falls outside
   it. Geometry is recomputed per render and shared by the hour rules, the event
   blocks and the now-line, so they can't disagree about where 3pm is. */
const DEFAULT_START_HOUR = 7;
const DEFAULT_END_HOUR = 22;

let gridStartHour = DEFAULT_START_HOUR;
let gridEndHour = DEFAULT_END_HOUR;
let hourHeight = 56;

function minHourHeightPx() {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--hour-height");
  return parseFloat(raw) || 56;
}

function computeGridGeometry(days) {
  let earliest = DEFAULT_START_HOUR;
  let latest = DEFAULT_END_HOUR;

  days.forEach((day) => {
    day.events.forEach((ev) => {
      if (ev.all_day || !ev.start_iso || !ev.end_iso) return;
      const { startMin, endMin } = dayMinutes(ev, day.date);
      earliest = Math.min(earliest, Math.floor(startMin / 60));
      latest = Math.max(latest, Math.ceil(endMin / 60));
    });
  });

  // When today is on screen the window always covers the current hour, so the
  // now-line is never outside the rendered range (relevant at 2am, where the
  // events alone would put the window firmly in the daytime).
  if (days.some((day) => day.date === todayIso())) {
    const nowHour = new Date().getHours();
    earliest = Math.min(earliest, nowHour);
    latest = Math.max(latest, nowHour + 1);
  }

  gridStartHour = Math.max(0, earliest);
  gridEndHour = Math.min(24, Math.max(latest, gridStartHour + 6));

  // Stretch the hours to fill the available height when they'll fit, so a
  // typical week needs no scrolling at all; fall back to a scrollable grid at
  // the minimum legible hour height when the range is too tall for the panel.
  const hours = gridEndHour - gridStartHour;
  const available = timegridScroll.clientHeight;
  hourHeight = Math.max(minHourHeightPx(), available ? available / hours : 0);
}

function gridTop(minutes) {
  return (minutes / 60 - gridStartHour) * hourHeight;
}

/* Minutes-from-midnight for `ev` as seen from the column for `dateIso`,
   clamped to that day. Timestamps are parsed with Date rather than sliced out
   of the ISO string: Google returns each event in its own calendar's UTC
   offset, and the wall should show every event in the wall's local time. */
function dayMinutes(ev, dateIso) {
  const dayStart = new Date(dateIso + "T00:00:00");
  const startMin = (new Date(ev.start_iso) - dayStart) / 60000;
  const endMin = (new Date(ev.end_iso) - dayStart) / 60000;
  const clampedStart = Math.max(0, Math.min(startMin, 24 * 60));
  const clampedEnd = Math.max(clampedStart, Math.min(endMin, 24 * 60));
  return { startMin: clampedStart, endMin: clampedEnd };
}

/* Greedy column packing: events are grouped into clusters that transitively
   overlap, and within a cluster each event takes the first column whose last
   event has already ended. Every event in a cluster is then widened to 1/N of
   the column, so concurrent events sit side by side instead of on top of each
   other. */
function layoutOverlaps(items) {
  const sorted = [...items].sort(
    (a, b) => a.startMin - b.startMin || b.endMin - a.endMin
  );
  let cluster = [];
  let clusterEnd = -1;

  function flush() {
    if (cluster.length === 0) return;
    const colEnds = [];
    cluster.forEach((item) => {
      let col = colEnds.findIndex((end) => end <= item.startMin);
      if (col === -1) {
        col = colEnds.length;
        colEnds.push(item.endMin);
      } else {
        colEnds[col] = item.endMin;
      }
      item.col = col;
    });
    cluster.forEach((item) => { item.cols = colEnds.length; });
    cluster = [];
  }

  sorted.forEach((item) => {
    if (cluster.length > 0 && item.startMin >= clusterEnd) flush();
    cluster.push(item);
    clusterEnd = cluster.length === 1 ? item.endMin : Math.max(clusterEnd, item.endMin);
  });
  flush();
  return sorted;
}

const MIN_BLOCK_PX = 24;

function renderTimeGrid(days) {
  const today = todayIso();

  timegrid.style.setProperty("--day-count", days.length);

  timegridHeadDays.innerHTML = "";
  timegridAllDayCols.innerHTML = "";
  timegridGutter.innerHTML = "";
  timegridCols.innerHTML = "";

  // Pass 1: day headers and the all-day band. This has to happen before the
  // geometry is measured - the all-day band's height depends on how many
  // all-day events there are, and measuring the scroll area before it's filled
  // reports too much room and makes the hour grid overflow the screen.
  days.forEach((day) => {
    const date = new Date(day.date + "T00:00:00");
    const isToday = day.date === today;

    const head = document.createElement("div");
    head.className = "timegrid-day-head";
    if (isToday) head.classList.add("today");
    const weekday = document.createElement("span");
    weekday.className = "timegrid-day-weekday";
    weekday.textContent = date.toLocaleDateString(undefined, { weekday: "short" });
    const num = document.createElement("span");
    num.className = "timegrid-day-number";
    num.textContent = date.getDate();
    head.append(weekday, num);
    timegridHeadDays.appendChild(head);

    const allDayCol = document.createElement("div");
    allDayCol.className = "timegrid-allday-col";
    day.events.filter((ev) => ev.all_day).forEach((ev) => {
      const pill = document.createElement("div");
      pill.className = "event-pill";
      pill.style.background = ev.color;
      // Google's chips are light with dark text; white would be unreadable.
      pill.style.color = ev.text_color || "#1d1d1d";
      pill.appendChild(pillTitle(ev.title));
      attachEventOpen(pill, ev);
      allDayCol.appendChild(pill);
    });
    timegridAllDayCols.appendChild(allDayCol);
  });

  computeGridGeometry(days);

  for (let hour = gridStartHour + 1; hour < gridEndHour; hour += 1) {
    const label = document.createElement("div");
    label.className = "hour-label";
    label.style.top = `${gridTop(hour * 60)}px`;
    const d = new Date(2000, 0, 1, hour);
    label.textContent = d.toLocaleTimeString(undefined, { hour: "numeric" });
    timegridGutter.appendChild(label);
  }

  // Pass 2: the hour rules and the timed events themselves, now that an hour
  // has a known height.
  const minBlockMinutes = (MIN_BLOCK_PX / hourHeight) * 60;

  days.forEach((day) => {
    const col = document.createElement("div");
    col.className = "timegrid-col";
    if (day.date === today) col.classList.add("today");

    for (let hour = gridStartHour + 1; hour < gridEndHour; hour += 1) {
      const line = document.createElement("div");
      line.className = "hour-line";
      line.style.top = `${gridTop(hour * 60)}px`;
      col.appendChild(line);
    }

    const timed = day.events
      .filter((ev) => !ev.all_day && ev.start_iso && ev.end_iso)
      .map((ev) => {
        const { startMin, endMin } = dayMinutes(ev, day.date);
        return {
          ev,
          startMin,
          // Short events are drawn taller than their real duration so they stay
          // readable and tappable, so the packer has to treat that drawn height
          // as the extent it occupies. Otherwise back-to-back short events
          // (8:45-9:00 then 9:00-9:20) don't count as overlapping and get
          // stacked directly on top of each other.
          endMin: Math.max(endMin, startMin + minBlockMinutes),
          drawEndMin: endMin,
        };
      });

    layoutOverlaps(timed).forEach((item) => {
      const block = document.createElement("div");
      block.className = "event-block";
      block.style.background = item.ev.color;
      block.style.color = item.ev.text_color || "#1d1d1d";
      const top = Math.max(0, gridTop(item.startMin));
      const height = Math.max(gridTop(item.drawEndMin) - top, MIN_BLOCK_PX);
      block.style.top = `${top}px`;
      block.style.height = `${height}px`;
      if (height < 36) block.classList.add("event-block--compact");
      block.style.left = `${(item.col / item.cols) * 100}%`;
      // 2px shaved off so side-by-side concurrent events read as separate
      // blocks instead of one continuous band of color.
      block.style.width = `calc(${(1 / item.cols) * 100}% - 2px)`;

      const title = document.createElement("div");
      title.className = "event-block-title";
      title.textContent = item.ev.title;
      const time = document.createElement("div");
      time.className = "event-block-time";
      time.textContent = item.ev.start_time;
      block.append(title, time);

      attachEventOpen(block, item.ev);
      col.appendChild(block);
    });

    timegridCols.appendChild(col);
  });

  const gridHeight = (gridEndHour - gridStartHour) * hourHeight;
  timegridCols.style.height = `${gridHeight}px`;
  timegridGutter.style.height = `${gridHeight}px`;

  renderNowLine(days);
  scrollTimeGridIntoView(days, gridHeight);
}

let nowLineTimer = null;

function renderNowLine(days) {
  // Cleared up front, before any early return: this reschedules itself every
  // minute over a captured `days`, so a pending timer from a previous render is
  // holding a stale week. Left alive it would append a now-line to whatever
  // column index today used to occupy - a column that now belongs to a
  // different week, or doesn't exist at all in single-column day view - and
  // would also clear the legitimate timer out from under the current render.
  clearTimeout(nowLineTimer);
  document.querySelectorAll(".now-line").forEach((el) => el.remove());

  const index = days.findIndex((day) => day.date === todayIso());
  const column = timegridCols.children[index];
  if (index === -1 || !column) return;

  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  // Only drawn when the current time is inside the rendered window - outside
  // it, a line pinned to the top or bottom edge would be actively misleading.
  if (minutes < gridStartHour * 60 || minutes > gridEndHour * 60) return;

  const line = document.createElement("div");
  line.className = "now-line";
  line.style.top = `${gridTop(minutes)}px`;
  column.appendChild(line);

  nowLineTimer = setTimeout(() => renderNowLine(days), 60 * 1000);
}

function scrollTimeGridIntoView(days, gridHeight) {
  const available = timegridScroll.clientHeight;
  if (gridHeight <= available) {
    timegridScroll.scrollTop = 0;
    return;
  }
  const showsToday = days.some((day) => day.date === todayIso());
  // Land an hour before now when today is on screen, otherwise at the top of
  // the window - either way the wall opens on the part of the day in use.
  const focusHour = showsToday ? Math.max(gridStartHour, new Date().getHours() - 1) : gridStartHour;
  timegridScroll.scrollTop = gridTop(focusHour * 60);
}

/* ---------- agenda / list rendering ---------- */

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
      day.events.forEach((ev) => {
        const card = renderEventCard(ev);
        attachEventOpen(card, ev);
        eventsList.appendChild(card);
      });
    }
    li.appendChild(eventsList);

    container.appendChild(li);
  });
}

/* Says so when the grid is last-known-good data because a refresh failed. The
   server keeps serving the previous payload rather than blanking the month (see
   calendar_service._last_good), which is only honest if the wall admits it. */
function updateStaleIndicator(payload) {
  if (!payload.stale) {
    staleBadge.classList.add("hidden");
    return;
  }
  const when = payload.fetched_at
    ? new Date(payload.fetched_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    : "earlier";
  staleBadge.textContent = `Offline \u00b7 last updated ${when}`;
  staleBadge.classList.remove("hidden");
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

/* ---------- month grid ----------

   All-day events are drawn as bars that span the days they cover, not as a
   separate chip repeated in every cell. A four-day trip used to look like four
   unrelated one-day events, which is the single most misleading thing a month
   view can do.

   Structure per week: one 7-column grid of day cells (number + timed events),
   with an absolutely-positioned 7-column grid of span bars laid over it, offset
   below the day numbers. The cells reserve exactly as much vertical space as that
   week needs for its lanes, so weeks with no all-day events give the room back to
   timed events instead of leaving a permanent gap. */

const MAX_SPAN_LANES = 3;

/* Every all-day event touching this week, clipped to the week and annotated with
   where it starts/ends and whether it runs off either edge. Single-day all-day
   events are just spans of width one, which keeps one code path. */
function collectSpans(week, daysByDate) {
  const first = week[0];
  const last = week[week.length - 1];
  const seen = new Map();

  week.forEach((date) => {
    (daysByDate[date] || []).forEach((ev) => {
      if (!ev.all_day || seen.has(ev.uid)) return;
      const startIdx = week.indexOf(ev.start_date < first ? first : ev.start_date);
      const endIdx = week.indexOf(ev.end_date > last ? last : ev.end_date);
      if (startIdx === -1 || endIdx === -1) return;
      seen.set(ev.uid, {
        ev,
        startIdx,
        endIdx,
        continuesLeft: ev.start_date < first,
        continuesRight: ev.end_date > last,
      });
    });
  });

  // Longest-first within a start day keeps the big spans on the top lanes, which
  // is both tidier and how every other calendar does it.
  return [...seen.values()].sort(
    (a, b) =>
      a.startIdx - b.startIdx ||
      b.endIdx - b.startIdx - (a.endIdx - a.startIdx) ||
      a.ev.title.localeCompare(b.ev.title)
  );
}

/* Greedy lane packing: each span takes the first lane with no overlap. Returns
   how many lanes were needed. */
function assignSpanLanes(spans) {
  const laneEnds = [];
  spans.forEach((span) => {
    let lane = laneEnds.findIndex((end) => end < span.startIdx);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(span.endIdx);
    } else {
      laneEnds[lane] = span.endIdx;
    }
    span.lane = lane;
  });
  return laneEnds.length;
}

function renderGrid(grid) {
  monthGrid.innerHTML = "";
  const today = todayIso();
  const dates = Object.keys(grid.days).sort();

  const weeks = [];
  for (let i = 0; i < dates.length; i += 7) weeks.push(dates.slice(i, i + 7));

  weeks.forEach((week) => {
    const weekEl = document.createElement("div");
    weekEl.className = "week-row";

    const spans = collectSpans(week, grid.days);
    const lanesNeeded = assignSpanLanes(spans);
    const laneCount = Math.min(MAX_SPAN_LANES, lanesNeeded);
    const hidden = spans.filter((span) => span.lane >= laneCount);
    // A capped week keeps one lane back for the "+N more" marker.
    const visibleLanes = hidden.length > 0 ? Math.max(1, laneCount - 1) : laneCount;
    const shown = spans.filter((span) => span.lane < visibleLanes);
    const overflow = spans.filter((span) => span.lane >= visibleLanes);
    const usedLanes = visibleLanes + (overflow.length ? 1 : 0);
    weekEl.style.setProperty("--lanes", usedLanes);

    const cells = document.createElement("div");
    cells.className = "week-cells";

    week.forEach((dateStr) => {
      const cell = document.createElement("div");
      cell.className = "day-cell";
      const dayNum = parseInt(dateStr.slice(8, 10), 10);
      if (parseInt(dateStr.slice(5, 7), 10) !== grid.month) cell.classList.add("outside-month");
      if (dateStr === today) cell.classList.add("today");

      const numEl = document.createElement("div");
      numEl.className = "day-number";
      numEl.textContent = dayNum;
      cell.appendChild(numEl);

      // Holds open exactly the space the span layer occupies above the timed list.
      const spacer = document.createElement("div");
      spacer.className = "day-span-space";
      cell.appendChild(spacer);

      // Everything is rendered, then trimmed to fit by measurement in
      // trimCellsToFit(). Computing a capacity up front kept getting the
      // arithmetic wrong - it has to account for the day number, this week's span
      // lanes, cell padding, grid gaps and the font's real line height, and a miss
      // shows up as silently clipped events.
      const timed = (grid.days[dateStr] || []).filter((ev) => !ev.all_day);

      timed.forEach((ev) => {
        const pill = document.createElement("div");
        pill.className = "event-pill event-pill--timed";
        const dot = document.createElement("span");
        dot.className = "event-dot";
        dot.style.background = ev.color;
        const when = document.createElement("span");
        when.className = "event-pill-time";
        when.textContent = ev.start_time;
        pill.append(dot, when, pillTitle(ev.title));
        cell.appendChild(pill);
      });

      cell.addEventListener("click", () => openDayOverlay(dateStr, grid.days[dateStr] || []));
      cells.appendChild(cell);
    });

    weekEl.appendChild(cells);

    const spansEl = document.createElement("div");
    spansEl.className = "week-spans";

    shown.forEach((span) => {
      const bar = document.createElement("div");
      bar.className = "span-bar";
      bar.style.gridColumn = `${span.startIdx + 1} / span ${span.endIdx - span.startIdx + 1}`;
      bar.style.gridRow = String(span.lane + 1);
      bar.style.background = span.ev.color;
      // Google's palette is light chips with dark text; using the foreground it
      // hands us is what keeps a yellow event readable.
      bar.style.color = span.ev.text_color || "#1d1d1d";
      // Square off the cut end so a bar that continues past the week edge reads as
      // continuing rather than as ending there.
      if (span.continuesLeft) bar.classList.add("span-bar--open-left");
      if (span.continuesRight) bar.classList.add("span-bar--open-right");

      const label = document.createElement("span");
      label.className = "span-bar-label";
      label.textContent = (span.continuesLeft ? "\u2039 " : "") + span.ev.title;
      bar.appendChild(label);

      attachEventOpen(bar, span.ev);
      spansEl.appendChild(bar);
    });

    if (overflow.length > 0) {
      const from = Math.min(...overflow.map((span) => span.startIdx));
      const to = Math.max(...overflow.map((span) => span.endIdx));
      const more = document.createElement("div");
      more.className = "span-bar span-bar--more";
      more.style.gridColumn = `${from + 1} / span ${to - from + 1}`;
      more.style.gridRow = String(visibleLanes + 1);
      more.textContent = `+${overflow.length} more`;
      spansEl.appendChild(more);
    }

    weekEl.appendChild(spansEl);
    monthGrid.appendChild(weekEl);
  });

  trimCellsToFit();
}

/* Drops timed events from the bottom of any cell that can't fit them, replacing
   them with a "+N more" line. Measured against what the browser actually laid
   out, so it's right regardless of font metrics, padding, gaps, or how many span
   lanes the week reserved above. */
function trimCellsToFit() {
  document.querySelectorAll("#month-grid .day-cell").forEach((cell) => {
    const pills = [...cell.querySelectorAll(".event-pill--timed")];
    if (pills.length === 0) return;

    let more = null;
    let hidden = 0;

    while (cell.scrollHeight > cell.clientHeight + 1 && pills.length > 0) {
      pills.pop().remove();
      hidden += 1;
      if (!more) {
        // Added on first hide, so its own height is part of what gets measured.
        more = document.createElement("div");
        more.className = "event-overflow";
        cell.appendChild(more);
      }
      more.textContent = `+${hidden} more`;
    }
  });
}

/* The title always goes in its own span, never as a bare text node on the pill:
   .event-pill is a flex container, and text-overflow: ellipsis has no effect on
   a flex container's own text - a long all-day title clipped mid-word instead of
   ellipsising. */
function pillTitle(text) {
  const span = document.createElement("span");
  span.className = "event-pill-title";
  span.textContent = text;
  return span;
}

function renderEventCard(ev) {
  const li = document.createElement("li");
  li.className = "event-card";
  li.style.borderLeftColor = ev.color;

  const time = document.createElement("div");
  time.className = "event-card-time";
  time.textContent = ev.all_day ? "All day" : `${ev.start_time} – ${ev.end_time}`;
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

/* Makes any rendered event tappable-to-edit. Previously only the day overlay
   wired this up, so an event visible in week or agenda view couldn't be opened
   at all without first finding its day in month view. */
function attachEventOpen(element, ev) {
  if (ev.access_role !== "owner" && ev.access_role !== "writer") return;
  element.classList.add("event-card--editable");
  element.addEventListener("click", (e) => {
    e.stopPropagation();
    dayPanel.close();
    openEditEventModal(ev);
  });
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
    attachEventOpen(card, ev);
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

/* ---------- date navigation ---------- */

function stepBy(direction) {
  if (currentView === "day") {
    dayAnchor = addDaysIso(dayAnchor, direction);
  } else if (currentView === "week") {
    dayAnchor = addDaysIso(dayAnchor, direction * 7);
  } else {
    month += direction;
    if (month < 1) { month = 12; year -= 1; }
    if (month > 12) { month = 1; year += 1; }
  }
  loadCurrentView();
}

prevBtn.addEventListener("click", () => stepBy(-1));
nextBtn.addEventListener("click", () => stepBy(1));

function jumpToToday() {
  const now = new Date();
  year = now.getFullYear();
  month = now.getMonth() + 1;
  dayAnchor = todayIso();
  loadCurrentView();
}

document.getElementById("today-jump").addEventListener("click", jumpToToday);

/* A wall left showing next March should not still be showing it later. After
   IDLE_MS of nobody touching the screen, close whatever's open and return to
   the month of today - the most useful thing to be showing unattended. */
onIdle(() => {
  dayPanel.close();
  calendarsPanel.close();
  // The add/edit sheet is deliberately left open. Someone can easily be four
  // minutes into filling it in - checking a date on their phone, asking someone
  // else - without ever touching the screen, and discarding half-entered input
  // is worse than leaving a stale form up.
  const now = new Date();
  year = now.getFullYear();
  month = now.getMonth() + 1;
  dayAnchor = todayIso();
  setView("month");
});

/* Re-render on resize so pills-per-cell and the time grid's geometry follow
   the actual viewport - relevant when the kiosk browser starts windowed and
   goes full-screen a moment later. */
let resizeTimer = null;
function scheduleRelayout() {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(loadCurrentView, 250);
}

window.addEventListener("resize", scheduleRelayout);

/* The severe-weather banner appears and disappears without a window resize, and it
   takes real vertical space - on a 600px panel that left 72 day cells clipping
   their own content, because trimCellsToFit() had already run against the taller
   layout. */
window.addEventListener("wallcal:layoutchange", scheduleRelayout);

/* And a belt-and-braces observer for anything else that changes the room available:
   the demo banner, a font swap, the browser going full-screen. Guarded on an actual
   height change, because re-rendering is itself a resize of the observed element
   and would otherwise loop forever. */
let lastContentHeight = 0;
if (window.ResizeObserver) {
  const contentEl = document.getElementById("content");
  if (contentEl) {
    new ResizeObserver((entries) => {
      const height = Math.round(entries[0].contentRect.height);
      if (Math.abs(height - lastContentHeight) < 8) return;
      lastContentHeight = height;
      scheduleRelayout();
    }).observe(contentEl);
  }
}

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

/* An unconfigured wall showed an empty grid with nothing explaining why. */
async function checkAccountsPresent() {
  const resp = await fetch("/api/calendar/accounts");
  const accounts = await resp.json();
  noAccounts.classList.toggle("hidden", accounts.length > 0);
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
  openAddEventModal(currentView === "month" ? todayIso() : dayAnchor);
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
checkAccountsPresent();
