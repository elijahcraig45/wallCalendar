/* The brightness and sleep panel, behind the top-bar chip.
 *
 * Shell furniture, like timers: it has to be one tap away from wherever the wall
 * happens to be, because the moment you want it is the moment the wall is too bright
 * to read comfortably.
 *
 * The dimming itself lives in nav.js, which owns the overlay and the sleep state and
 * composes brightness, after-dark dimming and sleep into one opacity. This file only
 * moves the settings and asks nav.js to re-apply.
 */

const brightnessPanel = initPanel("brightness-overlay", "brightness-close");
const brightnessRange = document.getElementById("brightness-range");
const brightnessValue = document.getElementById("brightness-value");
const sleepEnabled = document.getElementById("sleep-enabled");
const sleepEnabledSub = document.getElementById("sleep-enabled-sub");
const sleepNightOnly = document.getElementById("sleep-night-only");
const displayOffSelect = document.getElementById("display-off-minutes");

document.getElementById("brightness-chip").addEventListener("click", () => {
  // Re-read on open rather than trusting what was last rendered: the settings are
  // per-wall and could have been changed from a phone on the LAN.
  renderDisplaySettings();
  brightnessPanel.open();
});

function offLabel(minutes) {
  if (!minutes) return "Never";
  if (minutes % 60 === 0) return `${minutes / 60} hour${minutes === 60 ? "" : "s"}`;
  return `${minutes} minutes`;
}

function renderDisplaySettings() {
  const settings = displaySettings();
  brightnessRange.min = String(Math.round((settings.min_brightness || 0.2) * 100));
  brightnessRange.value = String(Math.round(settings.brightness * 100));
  brightnessValue.textContent = `${brightnessRange.value}%`;
  sleepEnabled.checked = settings.sleep_enabled;
  sleepNightOnly.checked = settings.sleep_at_night_only;
  sleepNightOnly.disabled = !settings.sleep_enabled;
  sleepEnabledSub.textContent = `Shows a faint clock after ${settings.sleep_after_minutes} minutes of no touches.`;

  if (!displayOffSelect.options.length) {
    (settings.allowed_display_off_minutes || [0, 30, 60, 120]).forEach((minutes) => {
      const option = document.createElement("option");
      option.value = String(minutes);
      option.textContent = offLabel(minutes);
      displayOffSelect.append(option);
    });
  }
  displayOffSelect.value = String(settings.display_off_minutes);
}

async function saveDisplaySettings(changes) {
  try {
    const resp = await fetch("/api/system/display", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      showToast(data.error || "Couldn't save that");
      return null;
    }
    const settings = await resp.json();
    applyDisplaySettings(settings);
    renderDisplaySettings();
    return settings;
  } catch (e) {
    showToast("Couldn't save that");
    return null;
  }
}

/* The slider previews live and only writes on release.
   `input` fires on every pixel of a drag, so saving there would be dozens of POSTs
   for one gesture - and each one rewrites the prefs file. Applying locally on `input`
   is what makes the drag feel like it is controlling the screen rather than lagging
   behind it. */
brightnessRange.addEventListener("input", () => {
  brightnessValue.textContent = `${brightnessRange.value}%`;
  previewBrightness(Number(brightnessRange.value) / 100);
});

["change", "pointerup"].forEach((evt) => {
  brightnessRange.addEventListener(evt, () => {
    saveDisplaySettings({ brightness: Number(brightnessRange.value) / 100 });
  });
});

sleepEnabled.addEventListener("change", () => {
  saveDisplaySettings({ sleep_enabled: sleepEnabled.checked });
});

sleepNightOnly.addEventListener("change", () => {
  saveDisplaySettings({ sleep_at_night_only: sleepNightOnly.checked });
});

displayOffSelect.addEventListener("change", () => {
  saveDisplaySettings({ display_off_minutes: Number(displayOffSelect.value) });
});

document.getElementById("sleep-now").addEventListener("click", () => {
  // Close first: the panel is a modal overlay and would otherwise sit on top of the
  // sleep screen, and the tap that dismissed it would be the tap that wakes it.
  brightnessPanel.close();
  setTimeout(sleepNow, 150);
});
