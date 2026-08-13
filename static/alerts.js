/* Severe weather, on every page.
 *
 * This is shell furniture rather than part of the weather page, because a tornado
 * warning that only appears if you happen to walk over and tap "Weather" is not
 * doing its job. The wall spends its life showing a calendar; that is where the
 * warning has to arrive.
 *
 * It also owns the alert POLL for the whole app, the same way weather.js owns the
 * weather poll. The weather page subscribes via onAlerts() instead of fetching
 * again - otherwise being on /weather would double the request rate against the
 * National Weather Service.
 *
 * Deliberately no sound. The obvious instinct for a tornado warning is a chime,
 * and browser autoplay policy means it would only play if someone had already
 * touched the screen at some point since load. A siren that works sometimes is
 * worse than no siren, because you would come to rely on it.
 */

const ALERT_POLL_MS = 3 * 60 * 1000;

const alertBanner = document.getElementById("alert-banner");
const alertBannerEvent = document.getElementById("alert-banner-event");
const alertBannerWhen = document.getElementById("alert-banner-when");
const alertBannerArea = document.getElementById("alert-banner-area");
const alertBannerDismiss = document.getElementById("alert-banner-dismiss");

const alertListeners = [];
let alertsPayload = null;

/** Pages subscribe rather than polling again. Fires immediately with whatever is
 *  already known, so a page opened between polls isn't blank for three minutes. */
function onAlerts(listener) {
  alertListeners.push(listener);
  if (alertsPayload) listener(alertsPayload);
}

/* Dismissal is per alert id, and only for as long as that alert lives.
 *
 * The tempting shortcut - a single "dismissed" flag - is wrong in a way that
 * matters here: dismiss a heat advisory at noon and a tornado warning at 6pm would
 * be silently suppressed. Ids are held in memory only, so a reload brings the
 * banner back; that's the safer direction to fail in. */
const dismissed = new Set();

/* The id currently on the banner. wakeScreen() must fire when a warning ARRIVES,
   not on every poll: calling it each cycle meant an active advisory kept the wall
   permanently awake and it could never dim at night.
   The first payload is seeded WITHOUT waking, so an alert that was already running
   when the page loaded doesn't light the room - reloading the wall at 3am during an
   ongoing advisory shouldn't, and a deploy reload would otherwise do it nightly. */
let shownAlertId = null;
let seededFirstPayload = false;

function urgentAlerts(payload) {
  return ((payload && payload.alerts) || []).filter((alert) => alert.urgent);
}

function renderBanner(payload) {
  const urgent = urgentAlerts(payload).filter((alert) => !dismissed.has(alert.id));

  if (urgent.length === 0) {
    alertBanner.classList.add("hidden");
    shownAlertId = null;
    announceBannerChange();
    return;
  }

  // Most severe first is already the server's ordering, so the head of the list
  // is the one to show. A count covers the rest rather than stacking banners.
  const alert = urgent[0];
  alertBanner.classList.remove("hidden");
  alertBanner.dataset.alertId = alert.id || "";

  alertBannerEvent.textContent =
    urgent.length > 1 ? `${alert.event} (+${urgent.length - 1} more)` : alert.event;

  alertBannerWhen.textContent = alert.ends
    ? `until ${new Date(alert.ends).toLocaleTimeString(undefined, {
        hour: "numeric",
        minute: "2-digit",
      })}`
    : "";

  alertBannerArea.textContent = alert.area || "";

  // Only on arrival, and never for whatever was already in force at load.
  const isNew = alert.id !== shownAlertId;
  shownAlertId = alert.id;
  if (isNew && seededFirstPayload) wakeScreen();
  announceBannerChange();
}

/* The banner occupies space, so showing or hiding it changes how much room the
   page has. The month grid trims pills to fit and had already done so before this
   appeared, leaving every cell clipping its own content. window.resize doesn't
   fire for this, so pages that care are told directly. */
function announceBannerChange() {
  window.dispatchEvent(new CustomEvent("wallcal:layoutchange"));
}

async function refreshAlerts() {
  try {
    const resp = await fetch("/api/weather/alerts");
    if (!resp.ok) throw new Error(`alerts responded ${resp.status}`);
    alertsPayload = await resp.json();
  } catch (e) {
    // An alert already known must not vanish because one poll failed - but with
    // nothing cached, subscribers need to be told it's an outage rather than shown
    // "no active alerts", which would be a lie in exactly the wrong direction.
    alertsPayload = alertsPayload || {
      alerts: [],
      count: 0,
      urgent_count: 0,
      errors: ["Couldn't reach the alerts service."],
    };
  }
  renderBanner(alertsPayload);
  seededFirstPayload = true;
  alertListeners.forEach((listener) => listener(alertsPayload));
}

if (alertBanner) {
  alertBannerDismiss.addEventListener("click", (event) => {
    event.stopPropagation();
    const id = alertBanner.dataset.alertId;
    if (id) dismissed.add(id);
    renderBanner(alertsPayload);
  });

  // Tapping the banner itself goes to the full text rather than dismissing, which
  // is the likelier intent when something says "Tornado Warning".
  alertBanner.addEventListener("click", () => {
    if (window.location.pathname !== "/weather") window.location.assign("/weather");
  });

  refreshAlerts();
  setInterval(refreshAlerts, ALERT_POLL_MS);
}
