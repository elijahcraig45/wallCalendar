/* Kitchen timers, shell-wide.
 *
 * Two things drive the design:
 *
 * - A timer started from a recipe has to survive walking over to the calendar, so
 *   state lives in localStorage as absolute end timestamps rather than in a
 *   countdown variable. Reloading the page (or navigating) recomputes remaining
 *   time from the clock, so nothing drifts and nothing is lost.
 * - The chime is synthesised with WebAudio rather than shipped as an audio file:
 *   no asset to serve, and nothing to go missing on the Pi.
 */

/* Names here are prefixed on purpose. This file loads on every page, and a page
   script declaring its own `render` or `load` silently replaces the one here -
   which is exactly what happened: the notes page's render(payload) won, and this
   file's per-second tick then called it with no argument, throwing every second. */
const STORAGE_KEY = "wallcal_timers";
const PRESETS = [1, 3, 5, 10, 15, 20, 30, 45];

const timerChip = document.getElementById("timer-chip");
const timerChipText = document.getElementById("timer-chip-text");
const timerList = document.getElementById("timer-list");
const timerPresets = document.getElementById("timer-presets");
const timerForm = document.getElementById("timer-form");
const timerLabelInput = document.getElementById("timer-label");
const timerMinutesInput = document.getElementById("timer-minutes");

let timers = loadTimers();

function loadTimers() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch (e) {
    return [];
  }
}

function saveTimers() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(timers));
}

function timerRemaining(timer) {
  return Math.max(0, timer.endsAt - Date.now());
}

function formatRemaining(ms) {
  const total = Math.ceil(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/* ---------- chime ----------
   Browsers refuse to start audio before a user gesture, and a kiosk boots
   untouched - so the context is created lazily on the first interaction and
   resumed if it was suspended. A timer that finishes before anyone has ever
   touched the screen still shows visually. */

let audioContext = null;

function primeAudio() {
  if (!audioContext) {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (Ctor) audioContext = new Ctor();
  }
  if (audioContext && audioContext.state === "suspended") audioContext.resume();
}

["pointerdown", "keydown"].forEach((evt) =>
  document.addEventListener(evt, primeAudio, { passive: true })
);

function chime() {
  primeAudio();
  if (!audioContext || audioContext.state !== "running") return;
  // Three short rising beeps - audible across a kitchen without being alarming.
  [0, 0.35, 0.7].forEach((offset, index) => {
    const osc = audioContext.createOscillator();
    const gain = audioContext.createGain();
    osc.type = "sine";
    osc.frequency.value = 880 + index * 220;
    const start = audioContext.currentTime + offset;
    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(0.25, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, start + 0.3);
    osc.connect(gain).connect(audioContext.destination);
    osc.start(start);
    osc.stop(start + 0.32);
  });
}

/* ---------- timers ---------- */

function startTimer(minutesOrSeconds, label, { seconds = false } = {}) {
  const ms = (seconds ? minutesOrSeconds : minutesOrSeconds * 60) * 1000;
  if (!ms || ms <= 0) return;
  timers.push({
    id: `t${Date.now()}${Math.floor(performance.now())}`,
    label: (label || "").trim(),
    endsAt: Date.now() + ms,
    durationMs: ms,
    rang: false,
  });
  saveTimers();
  renderTimers();
  showToast(`Timer set for ${formatRemaining(ms)}`);
}

// Recipes call this to start a step's timer.
window.startKitchenTimer = (seconds, label) =>
  startTimer(seconds, label, { seconds: true });

function removeTimer(id) {
  timers = timers.filter((timer) => timer.id !== id);
  saveTimers();
  renderTimers();
}

function renderTimers() {
  const active = timers.filter((timer) => timerRemaining(timer) > 0);
  const done = timers.filter((timer) => timerRemaining(timer) === 0);

  // The chip shows whichever timer will finish first - the one that matters.
  const soonest = active.slice().sort((a, b) => a.endsAt - b.endsAt)[0];
  if (done.length > 0) {
    timerChipText.textContent = "Done!";
    timerChip.classList.add("ringing");
  } else if (soonest) {
    timerChipText.textContent = formatRemaining(timerRemaining(soonest));
    timerChip.classList.remove("ringing");
  } else {
    timerChipText.textContent = "";
    timerChip.classList.remove("ringing");
  }
  timerChip.classList.toggle("running", active.length > 0 || done.length > 0);

  timerList.innerHTML = "";
  if (timers.length === 0) {
    const empty = document.createElement("li");
    empty.className = "timer-empty";
    empty.textContent = "No timers running.";
    timerList.appendChild(empty);
  }

  timers
    .slice()
    .sort((a, b) => a.endsAt - b.endsAt)
    .forEach((timer) => {
      const left = timerRemaining(timer);
      const li = document.createElement("li");
      li.className = left === 0 ? "timer-row timer-row--done" : "timer-row";

      const text = document.createElement("div");
      text.className = "timer-text";
      text.innerHTML = `<div class="timer-time">${left === 0 ? "Done" : formatRemaining(left)}</div>
        <div class="timer-name">${timer.label || "Timer"}</div>`;
      li.appendChild(text);

      const dismiss = document.createElement("button");
      dismiss.className = "pill-button";
      dismiss.textContent = left === 0 ? "Dismiss" : "Cancel";
      dismiss.addEventListener("click", () => removeTimer(timer.id));
      li.appendChild(dismiss);

      timerList.appendChild(li);
    });
}

function tickTimers() {
  let fired = false;
  timers.forEach((timer) => {
    if (!timer.rang && timerRemaining(timer) === 0) {
      timer.rang = true;
      fired = true;
    }
  });
  if (fired) {
    saveTimers();
    chime();
    const finished = timers.filter((timer) => timerRemaining(timer) === 0);
    showToast(`${finished[finished.length - 1].label || "Timer"} finished`);
    // A finished timer is worth interrupting a dimmed screen for.
    if (typeof wakeScreen === "function") wakeScreen();
  }
  renderTimers();
}

const timerPanel = initPanel("timer-overlay", "timer-close");
timerChip.addEventListener("click", () => timerPanel.open());

PRESETS.forEach((minutes) => {
  const button = document.createElement("button");
  button.className = "pill-button";
  button.textContent = `${minutes}m`;
  button.addEventListener("click", () => startTimer(minutes, timerLabelInput.value));
  timerPresets.appendChild(button);
});

timerForm.addEventListener("submit", (e) => {
  e.preventDefault();
  startTimer(parseInt(timerMinutesInput.value, 10), timerLabelInput.value);
  timerLabelInput.value = "";
});

renderTimers();
setInterval(tickTimers, 1000);
