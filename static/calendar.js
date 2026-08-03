const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const view = document.getElementById("calendar-view");
let year = parseInt(view.dataset.year, 10);
let month = parseInt(view.dataset.month, 10);

const monthLabel = document.getElementById("month-label");
const monthGrid = document.getElementById("month-grid");
const overlay = document.getElementById("day-overlay");
const overlayDate = document.getElementById("day-overlay-date");
const overlayEvents = document.getElementById("day-overlay-events");

function todayIso() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

async function loadMonth() {
  monthLabel.textContent = `${MONTH_NAMES[month - 1]} ${year}`;
  const resp = await fetch(`/api/calendar/${year}/${month}`);
  const grid = await resp.json();
  renderGrid(grid);
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
    overlayEvents.appendChild(li);
  });

  overlay.classList.remove("hidden");
}

document.getElementById("day-overlay-close").addEventListener("click", () => {
  overlay.classList.add("hidden");
});
overlay.addEventListener("click", (e) => {
  if (e.target === overlay) overlay.classList.add("hidden");
});

document.getElementById("prev-month").addEventListener("click", () => {
  month -= 1;
  if (month < 1) { month = 12; year -= 1; }
  loadMonth();
});

document.getElementById("next-month").addEventListener("click", () => {
  month += 1;
  if (month > 12) { month = 1; year += 1; }
  loadMonth();
});

loadMonth();
setInterval(loadMonth, 5 * 60 * 1000);
