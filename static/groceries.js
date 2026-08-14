/* The household grocery list, out of Daisy's Kitchen (app/groceries_service.py).
 *
 * Every global here is prefixed `groc` on purpose: page scripts share one global
 * scope with the five shell scripts, and a page script declaring `render` once
 * replaced timers.js's and threw on every tick. tests/api_checks.py enforces it.
 *
 * Mutations are optimistic-then-reconciled. On a wall you tap a checkbox with wet
 * hands on the way past and expect it to tick now, not after a Firestore round
 * trip; a failure re-fetches, so the screen can't sit there lying about what was
 * saved.
 */

const grocAisles = document.getElementById("groc-aisles");
const grocDoneBlock = document.getElementById("groc-done-block");
const grocDoneList = document.getElementById("groc-done");
const grocForm = document.getElementById("groc-form");
const grocInput = document.getElementById("groc-input");
const grocSetup = document.getElementById("groc-setup");
const grocSetupText = document.getElementById("groc-setup-text");
const grocCount = document.getElementById("groc-count");
const grocClear = document.getElementById("groc-clear");

// The last payload, so an optimistic re-render needs no round trip.
let grocCached = { items: [], groups: [], available: true, errors: [] };

async function grocApi(path, body) {
  const resp = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || `Request failed (${resp.status})`);
  return data;
}

function grocCheckbox(item, onToggle) {
  const check = document.createElement("button");
  check.className = "groc-check";
  check.setAttribute("aria-label", item.done ? "Put back" : "Tick off");
  check.innerHTML = item.done
    ? '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg>'
    : "";
  check.addEventListener("click", onToggle);
  return check;
}

function grocRow(item) {
  const li = document.createElement("li");
  li.className = item.done ? "groc-row groc-row--done" : "groc-row";
  li.appendChild(grocCheckbox(item, () => grocToggle(item)));

  const text = document.createElement("div");
  text.className = "groc-text";

  const name = document.createElement("span");
  name.className = "groc-name";
  name.textContent = item.display;
  text.appendChild(name);

  if (item.quantity_label) {
    const qty = document.createElement("span");
    qty.className = "groc-qty";
    qty.textContent = item.quantity_label;
    text.appendChild(qty);
  }

  // Which recipe put it on the list. Answers "why is there a pound of orzo on
  // here" without opening the phone.
  if (item.source_titles && item.source_titles.length) {
    const sub = document.createElement("div");
    sub.className = "groc-source";
    sub.textContent = `for ${item.source_titles.join(", ")}`;
    text.appendChild(sub);
  }
  li.appendChild(text);

  const remove = document.createElement("button");
  remove.className = "groc-delete";
  remove.setAttribute("aria-label", "Remove");
  remove.textContent = "×";
  remove.addEventListener("click", () => grocRemove(item));
  li.appendChild(remove);

  return li;
}

function grocRender(payload) {
  grocCached = payload;

  const configured = payload.available !== false;
  grocSetup.classList.toggle("hidden", configured);
  grocForm.classList.toggle("hidden", !configured);
  if (!configured) {
    grocSetupText.textContent = payload.errors[0] || "The grocery list is unavailable.";
    grocAisles.innerHTML = "";
    grocDoneBlock.classList.add("hidden");
    grocCount.textContent = "";
    grocClear.classList.add("hidden");
    return;
  }

  grocAisles.innerHTML = "";
  if (!payload.groups.length) {
    const empty = document.createElement("p");
    empty.className = "groc-empty";
    empty.textContent = payload.done_count
      ? "Everything on the list is in the trolley."
      : "The list is empty.";
    grocAisles.appendChild(empty);
  }

  // Groups arrive already in store order from the server, so the wall and the
  // phone walk the shop the same direction.
  payload.groups.forEach((group) => {
    const section = document.createElement("section");
    section.className = "groc-aisle";
    section.dataset.aisle = group.aisle;

    const head = document.createElement("h3");
    head.className = "groc-aisle-head";
    head.textContent = group.label;
    const badge = document.createElement("span");
    badge.className = "groc-aisle-count";
    badge.textContent = group.items.length;
    head.appendChild(badge);
    section.appendChild(head);

    const list = document.createElement("ul");
    group.items.forEach((item) => list.appendChild(grocRow(item)));
    section.appendChild(list);
    grocAisles.appendChild(section);
  });

  // Ticked items sink to their own block rather than disappearing - "did I get
  // that?" is a question people ask a list mid-shop.
  const done = payload.items.filter((item) => item.done);
  grocDoneBlock.classList.toggle("hidden", done.length === 0);
  grocDoneList.innerHTML = "";
  done.forEach((item) => grocDoneList.appendChild(grocRow(item)));

  grocCount.textContent = payload.open_count
    ? `${payload.open_count} to get`
    : "nothing to get";
  grocClear.classList.toggle("hidden", done.length === 0);
}

async function grocRefresh() {
  try {
    grocRender(await grocApi("/api/groceries"));
  } catch (err) {
    showToast(err.message);
  }
}

/** Re-derives the aisle groups client-side after an optimistic change.
 *  The server builds `groups` and would rebuild them on the next fetch, but the
 *  optimistic pass has to move a ticked row out of its aisle immediately. */
function grocRegroup(items) {
  const groups = [];
  grocCached.groups.forEach((group) => {
    const members = items.filter((item) => item.aisle === group.aisle && !item.done);
    if (members.length) groups.push({ ...group, items: members });
  });
  return groups;
}

function grocOptimistic(items) {
  grocRender({
    ...grocCached,
    items,
    groups: grocRegroup(items),
    open_count: items.filter((item) => !item.done).length,
    done_count: items.filter((item) => item.done).length,
  });
}

async function grocToggle(item) {
  grocOptimistic(
    grocCached.items.map((row) => (row.id === item.id ? { ...row, done: !row.done } : row))
  );
  try {
    await grocApi(`/api/groceries/${encodeURIComponent(item.id)}/done`, { done: !item.done });
  } catch (err) {
    showToast(err.message);
  }
  grocRefresh();
}

async function grocRemove(item) {
  grocOptimistic(grocCached.items.filter((row) => row.id !== item.id));
  try {
    await grocApi(`/api/groceries/${encodeURIComponent(item.id)}/delete`, {});
  } catch (err) {
    showToast(err.message);
  }
  grocRefresh();
}

grocForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = grocInput.value.trim();
  if (!text) return;
  grocInput.value = "";
  try {
    await grocApi("/api/groceries/add", { text });
  } catch (err) {
    showToast(err.message);
  }
  grocRefresh();
});

grocClear.addEventListener("click", async () => {
  try {
    const result = await grocApi("/api/groceries/clear-done", {});
    if (result.cleared) showToast(`Cleared ${result.cleared} item(s).`);
  } catch (err) {
    showToast(err.message);
  }
  grocRefresh();
});

document.getElementById("groc-refresh").addEventListener("click", grocRefresh);

grocRefresh();
// Someone is in the shop ticking things off on their phone; keep the wall current.
setInterval(grocRefresh, 60 * 1000);
