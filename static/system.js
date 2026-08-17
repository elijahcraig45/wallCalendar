/* The System page: Bluetooth, touchscreen calibration, the on-screen keyboard,
   and which sections appear in the rail.

   Everything here drives a real device, so every action reports what actually
   happened rather than optimistically re-rendering - a speaker that refused to
   pair must not look paired. */

async function post(path, body) {
  const resp = await fetch(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try {
    data = await resp.json();
  } catch (e) {
    // Non-JSON body - fall through to the generic message below.
  }
  if (!resp.ok || (data && data.ok === false)) {
    showToast((data && data.error) || "Something went wrong");
    return null;
  }
  return data || {};
}

/* ---------- Bluetooth ---------- */

const btAdapterName = document.getElementById("bt-adapter-name");
const btAdapterSub = document.getElementById("bt-adapter-sub");
const btPower = document.getElementById("bt-power");
const btScan = document.getElementById("bt-scan");
const btDiscoverable = document.getElementById("bt-discoverable");
const btAutoconnect = document.getElementById("bt-autoconnect");
const btDevices = document.getElementById("bt-devices");
const btHint = document.getElementById("bt-hint");

// While a scan is running the list changes under you, so it polls faster. At rest
// it still refreshes, because a speaker being switched on elsewhere in the room
// changes "connected" without anyone touching the wall.
const BT_POLL_IDLE_MS = 15000;
const BT_POLL_SCANNING_MS = 2000;

let btPollTimer = null;
let btBusy = false;

function deviceRow(device) {
  const li = document.createElement("li");

  const title = document.createElement("div");
  title.className = "row-title";
  const name = document.createElement("span");
  name.textContent = device.name;
  const sub = document.createElement("span");
  sub.className = "row-subtext";
  /* `known`, not `paired`. The wall's speaker pairs without bonding, so BlueZ
     reports Paired: no the whole time it is disconnected - keying off that offered
     "Pair" for a device already set up here, and hid Connect exactly when it was
     needed. See bluetooth_service._info_flags. */
  sub.textContent = device.connected
    ? "Connected"
    : device.known
      ? "Set up on this wall"
      : device.address;
  title.append(name, sub);
  li.append(title);

  // Pair does trust-and-connect too (see bluetooth_service.pair), so a new device
  // only ever needs one tap to become usable.
  const actions = device.connected
    ? [["Disconnect", "disconnect"]]
    : device.known
      ? [["Connect", "connect"], ["Forget", "forget"]]
      : [["Pair", "pair"]];

  actions.forEach(([label, action], index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = index === 0 ? "pill-button pill-button--accent" : "pill-button";
    button.textContent = label;
    button.addEventListener("click", async () => {
      // Pairing takes many seconds and a second tap would queue another attempt
      // against the same adapter, so the whole panel locks for the duration.
      if (btBusy) return;
      btBusy = true;
      const original = button.textContent;
      button.textContent = label === "Pair" ? "Pairing…" : `${label}ing…`;
      button.disabled = true;
      const result = await post(`/api/system/bluetooth/${device.address}/${action}`);
      btBusy = false;
      button.textContent = original;
      button.disabled = false;
      if (result) showToast(`${device.name} ${label.toLowerCase()}ed`);
      loadBluetooth();
    });
    li.append(button);
  });

  return li;
}

async function loadBluetooth() {
  let data;
  try {
    const resp = await fetch("/api/system/bluetooth");
    data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "unavailable");
  } catch (e) {
    btAdapterName.textContent = "Bluetooth unavailable";
    btAdapterSub.textContent = e.message === "unavailable" ? "" : e.message;
    btDevices.innerHTML = "";
    btPower.classList.add("hidden");
    btScan.classList.add("hidden");
    scheduleBluetoothPoll(false);
    return;
  }

  const { adapter, devices } = data;
  btPower.classList.remove("hidden");
  btScan.classList.remove("hidden");
  btAdapterName.textContent = adapter.name;
  btAdapterSub.textContent = adapter.powered ? adapter.address : "Turned off";
  btPower.textContent = adapter.powered ? "Turn off" : "Turn on";
  btScan.disabled = !adapter.powered;
  btScan.textContent = adapter.scanning ? "Scanning…" : "Scan";
  btDiscoverable.checked = adapter.discoverable;
  btDiscoverable.disabled = !adapter.powered;
  // Not gated on adapter.powered: this is a stored preference rather than adapter
  // state, so it stays togglable while Bluetooth is off and applies when it's on.
  btAutoconnect.checked = data.autoconnect;

  btDevices.innerHTML = "";
  devices.forEach((device) => btDevices.append(deviceRow(device)));

  if (!adapter.powered) {
    btHint.textContent = "Turn Bluetooth on to see nearby devices.";
  } else if (!devices.length) {
    btHint.textContent = adapter.scanning
      ? "Looking for devices - put the speaker into pairing mode."
      : "No devices yet. Put the speaker into pairing mode, then tap Scan.";
  } else {
    // Devices that never advertise a name are filtered out server-side, so say so
    // rather than leaving someone hunting for a speaker that is being hidden.
    btHint.textContent = "Devices that don't broadcast a name are not listed.";
  }

  scheduleBluetoothPoll(adapter.scanning);
}

function scheduleBluetoothPoll(scanning) {
  clearTimeout(btPollTimer);
  btPollTimer = setTimeout(
    loadBluetooth,
    scanning ? BT_POLL_SCANNING_MS : BT_POLL_IDLE_MS
  );
}

btPower.addEventListener("click", async () => {
  const turningOn = btPower.textContent === "Turn on";
  if (await post("/api/system/bluetooth/power", { on: turningOn })) loadBluetooth();
});

btScan.addEventListener("click", async () => {
  if (await post("/api/system/bluetooth/scan")) loadBluetooth();
});

btDiscoverable.addEventListener("change", async () => {
  const result = await post("/api/system/bluetooth/discoverable", {
    on: btDiscoverable.checked,
  });
  // Put the checkbox back if the adapter refused, so it never claims a state the
  // hardware isn't in.
  if (!result) btDiscoverable.checked = !btDiscoverable.checked;
  loadBluetooth();
});

btAutoconnect.addEventListener("change", async () => {
  const on = btAutoconnect.checked;
  const result = await post("/api/system/bluetooth/autoconnect", { on });
  if (!result) {
    btAutoconnect.checked = !on;
    return;
  }
  // Turning it on shouldn't mean waiting up to a minute to see anything happen, so
  // run a pass immediately and say what came back.
  if (on) {
    const pass = await post("/api/system/bluetooth/reconnect");
    const connected = (pass?.attempted || []).filter((a) => a.ok);
    if (connected.length) showToast(`Reconnected ${connected.map((a) => a.name).join(", ")}`);
  }
  loadBluetooth();
});

/* ---------- touchscreen calibration ----------

   Five targets, spread out enough to pin down an affine fit: the corners give the
   scale and any skew, the centre point makes a mis-tap obvious in the residual
   instead of silently bending the whole map.

   Coordinates are sent in output-normalised form (0..1 of the panel), because a
   libinput calibration matrix is defined against the output and not against this
   page's viewport - the viewport is 26px shorter than the screen thanks to
   Chromium's --app title strip, and shorter again whenever the keyboard is up. */

const TARGETS = [
  [0.12, 0.14],
  [0.88, 0.14],
  [0.50, 0.50],
  [0.12, 0.86],
  [0.88, 0.86],
];

const overlay = document.getElementById("calibrate-overlay");
const targetButton = document.getElementById("calibrate-target");
const progressText = document.getElementById("calibrate-progress");
const instructions = document.getElementById("calibrate-instructions");
const confirmBox = document.getElementById("calibrate-confirm");
const countdownText = document.getElementById("calibrate-countdown");
const touchStatus = document.getElementById("touch-status");
const touchDevice = document.getElementById("touch-device");

let samples = [];
let targetIndex = 0;
let pendingMatrix = null;
let countdownTimer = null;

async function loadTouch() {
  const state = await fetch("/api/system/touch").then((r) => r.json());
  touchStatus.textContent = state.calibrated ? "Calibrated" : "Not calibrated";
  touchDevice.textContent = state.device || "No touchscreen detected";
  document.getElementById("touch-start").disabled = !state.device;
  document.getElementById("touch-reset").disabled = !state.calibrated;
}

function placeTarget() {
  const [fx, fy] = TARGETS[targetIndex];
  targetButton.style.left = `${fx * 100}%`;
  targetButton.style.top = `${fy * 100}%`;
  progressText.textContent = `${targetIndex + 1} of ${TARGETS.length}`;
}

function startCalibration() {
  samples = [];
  targetIndex = 0;
  pendingMatrix = null;
  overlay.classList.remove("hidden");
  instructions.classList.remove("hidden");
  targetButton.classList.remove("hidden");
  confirmBox.classList.add("hidden");
  placeTarget();
}

function endCalibration() {
  overlay.classList.add("hidden");
  clearInterval(countdownTimer);
  loadTouch();
}

targetButton.addEventListener("click", async (event) => {
  // screenX/screenY are already output coordinates. The target was *drawn* in
  // viewport coordinates, so it is converted using this same event's
  // screen-minus-client delta - a constant offset for the window, which means the
  // pair of readings needs no assumption about the title strip's height.
  const offsetX = event.screenX - event.clientX;
  const offsetY = event.screenY - event.clientY;
  const rect = targetButton.getBoundingClientRect();
  const targetScreenX = rect.left + rect.width / 2 + offsetX;
  const targetScreenY = rect.top + rect.height / 2 + offsetY;

  samples.push({
    target: [targetScreenX / window.screen.width, targetScreenY / window.screen.height],
    observed: [event.screenX / window.screen.width, event.screenY / window.screen.height],
  });

  targetIndex += 1;
  if (targetIndex < TARGETS.length) {
    placeTarget();
    return;
  }

  targetButton.classList.add("hidden");
  instructions.classList.add("hidden");
  const result = await post("/api/system/touch/calibrate", { samples });
  if (!result) {
    endCalibration();
    return;
  }
  pendingMatrix = result.matrix;
  showConfirm(result.trial_seconds);
});

function showConfirm(seconds) {
  confirmBox.classList.remove("hidden");
  let left = seconds;
  const tick = () => {
    countdownText.textContent = `Undoing itself in ${left}s if you don't keep it.`;
    if (left <= 0) {
      // The server has already reverted on its own timer; just catch up.
      clearInterval(countdownTimer);
      showToast("Calibration undone");
      endCalibration();
      return;
    }
    left -= 1;
  };
  tick();
  clearInterval(countdownTimer);
  countdownTimer = setInterval(tick, 1000);
}

document.getElementById("calibrate-keep").addEventListener("click", async () => {
  if (await post("/api/system/touch/confirm", { matrix: pendingMatrix })) {
    showToast("Calibration saved");
  }
  endCalibration();
});

document.getElementById("calibrate-undo").addEventListener("click", async () => {
  await post("/api/system/touch/revert");
  showToast("Calibration undone");
  endCalibration();
});

document.getElementById("calibrate-cancel").addEventListener("click", endCalibration);
document.getElementById("touch-start").addEventListener("click", startCalibration);

document.getElementById("touch-reset").addEventListener("click", async () => {
  if (await post("/api/system/touch/reset")) showToast("Touch calibration reset");
  loadTouch();
});

/* ---------- on-screen keyboard ---------- */

document.getElementById("kb-toggle").addEventListener("click", async () => {
  const result = await post("/api/system/keyboard");
  if (result) showToast(result.visible ? "Keyboard shown" : "Keyboard hidden");
});

/* ---------- rail sections ---------- */

const SECTION_LABELS = {
  today: "Today",
  recipes: "Recipes",
  groceries: "Groceries",
  weather: "Weather",
  spotify: "Music",
  browser: "Web",
};

const sectionList = document.getElementById("section-list");

async function loadSections() {
  const { sections } = await fetch("/api/system/sections").then((r) => r.json());
  sectionList.innerHTML = "";

  sections.forEach((section) => {
    const li = document.createElement("li");
    const label = document.createElement("label");
    label.className = "system-toggle";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = !section.hidden;
    const text = document.createElement("span");
    text.textContent = SECTION_LABELS[section.name] || section.name;

    box.addEventListener("change", async () => {
      const result = await post(`/api/system/sections/${section.name}`, {
        hidden: !box.checked,
      });
      if (!result) {
        box.checked = !box.checked;
        return;
      }
      // The rail is rendered server-side in base.html, so it only changes on the
      // next load. Reloading here is what makes the toggle feel like it did
      // something instead of appearing to do nothing until you navigate.
      window.location.reload();
    });

    label.append(box, text);
    li.append(label);
    sectionList.append(li);
  });
}

loadBluetooth();
loadTouch();
loadSections();

// The page is a settings screen, not something to sit on: nav.js already sends the
// wall home after ten idle minutes, and stopping the Bluetooth poll when the page
// goes away keeps a scan from being restarted forever.
window.addEventListener("pagehide", () => clearTimeout(btPollTimer));
