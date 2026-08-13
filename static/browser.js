/* The Web page.
 *
 * Everything here exists to keep the kiosk inside the app. The rail stays
 * visible, pages load into an iframe, and the server is asked whether a site
 * allows framing before the frame is pointed at it - a browser gives the page no
 * way to tell a refused frame from a blank one, so without asking first the
 * failure mode is an unexplained empty rectangle.
 */

const form = document.getElementById("browser-form");
const urlInput = document.getElementById("browser-url");
const status = document.getElementById("browser-status");
const frameWrap = document.getElementById("browser-frame-wrap");
const frame = document.getElementById("browser-frame");
const shortcuts = document.getElementById("browser-shortcuts");

// Somewhere to start from on a touchscreen with no keyboard nearby. Recipes has
// its own rail destination; these are the things a wall gets asked for that the
// app itself doesn't cover.
const SHORTCUTS = [
  { label: "Daisy's Kitchen", url: "https://recipe-f644f.web.app/" },
  { label: "Weather radar", url: "https://www.weather.gov/" },
  { label: "Wikipedia", url: "https://wikipedia.org/" },
];

function showStatus(message, kind = "info") {
  status.textContent = message;
  status.className = `browser-status browser-status--${kind}`;
  status.classList.remove("hidden");
}

function clearPage() {
  frame.removeAttribute("src");
  frameWrap.classList.add("hidden");
  status.classList.add("hidden");
  shortcuts.classList.remove("hidden");
  urlInput.value = "";
}

async function open(rawUrl) {
  if (!rawUrl.trim()) return;
  showStatus("Loading…");
  frameWrap.classList.add("hidden");
  shortcuts.classList.add("hidden");

  let result;
  try {
    const resp = await fetch(`/api/browser/probe?url=${encodeURIComponent(rawUrl)}`);
    result = await resp.json();
    if (!resp.ok) {
      showStatus(result.error || "Couldn't open that address.", "error");
      return;
    }
  } catch (e) {
    showStatus("Couldn't reach the wall's own server.", "error");
    return;
  }

  if (!result.frameable) {
    // No offer to "open anyway": doing so is exactly the trapdoor this replaced.
    showStatus(
      `${result.reason} It can't be shown here - open it on a phone instead.`,
      "error"
    );
    return;
  }

  urlInput.value = result.url;
  frame.src = result.url;
  frameWrap.classList.remove("hidden");
  status.classList.add("hidden");
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  open(urlInput.value);
  urlInput.blur();
});

document.getElementById("browser-home").addEventListener("click", clearPage);

SHORTCUTS.forEach((item) => {
  const button = document.createElement("button");
  button.className = "pill-button";
  button.textContent = item.label;
  button.addEventListener("click", () => open(item.url));
  shortcuts.appendChild(button);
});
