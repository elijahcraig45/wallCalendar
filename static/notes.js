/* Notes, backed by Google Tasks (see app/tasks_service.py for why not Keep).
 *
 * Every mutation is optimistic-then-reconciled: on a wall you tap a checkbox and
 * expect it to tick immediately, not after a round trip to Google. A failure
 * re-fetches, so the screen can't sit there lying about what was saved.
 */

const notesList = document.getElementById("notes-list");
const noteForm = document.getElementById("note-form");
const noteInput = document.getElementById("note-input");
const notesFootnote = document.getElementById("notes-footnote");
const notesReauth = document.getElementById("notes-reauth");
const notesReauthText = document.getElementById("notes-reauth-text");

async function api(path, body) {
  const resp = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || `Request failed (${resp.status})`);
  return data;
}

// The last payload, kept so an optimistic re-render doesn't need a round trip.
let cached = { notes: [], available: true, needs_reauth: false, errors: [] };

function render(payload) {
  cached = payload;
  const needsReauth = payload.needs_reauth;
  notesReauth.classList.toggle("hidden", !needsReauth);
  if (needsReauth) notesReauthText.textContent = payload.errors[0];

  noteForm.classList.toggle("hidden", payload.available === false);

  notesList.innerHTML = "";
  if (payload.available !== false && payload.notes.length === 0) {
    const empty = document.createElement("li");
    empty.className = "note-empty";
    empty.textContent = "Nothing on the list.";
    notesList.appendChild(empty);
  }

  payload.notes.forEach((note) => {
    const li = document.createElement("li");
    li.className = note.done ? "note-row note-row--done" : "note-row";

    const check = document.createElement("button");
    check.className = "note-check";
    check.setAttribute("aria-label", note.done ? "Mark not done" : "Mark done");
    check.innerHTML = note.done
      ? '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg>'
      : "";
    check.addEventListener("click", () => toggle(note));
    li.appendChild(check);

    const text = document.createElement("div");
    text.className = "note-text";
    text.textContent = note.title;
    if (note.notes) {
      const sub = document.createElement("div");
      sub.className = "note-sub";
      sub.textContent = note.notes;
      text.appendChild(sub);
    }
    li.appendChild(text);

    const remove = document.createElement("button");
    remove.className = "note-delete";
    remove.setAttribute("aria-label", "Delete");
    remove.textContent = "×";
    remove.addEventListener("click", () => destroy(note));
    li.appendChild(remove);

    notesList.appendChild(li);
  });

  if (payload.available === false) {
    notesFootnote.textContent = "";
  } else {
    const open = payload.notes.filter((note) => !note.done).length;
    notesFootnote.textContent =
      `${open} open · syncs with Google Tasks, so it's on your phone too`;
  }
}

async function refresh() {
  try {
    render(await api("/api/notes"));
  } catch (err) {
    showToast(err.message);
  }
}

async function toggle(note) {
  // Optimistic: on a wall, a checkbox has to tick under your finger, not after a
  // round trip to Google. refresh() afterwards reconciles either way, so a
  // failure can't leave the screen lying about what was saved.
  render({ ...cached, notes: cached.notes.map((item) =>
    item.id === note.id ? { ...item, done: !item.done } : item) });
  try {
    await api(`/api/notes/${encodeURIComponent(note.id)}/done`, { done: !note.done });
  } catch (err) {
    showToast(err.message);
  }
  refresh();
}

async function destroy(note) {
  render({ ...cached, notes: cached.notes.filter((item) => item.id !== note.id) });
  try {
    await api(`/api/notes/${encodeURIComponent(note.id)}/delete`, {});
  } catch (err) {
    showToast(err.message);
  }
  refresh();
}

noteForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const title = noteInput.value.trim();
  if (!title) return;
  noteInput.value = "";
  try {
    await api("/api/notes/add", { title });
  } catch (err) {
    showToast(err.message);
  }
  refresh();
});

document.getElementById("notes-refresh").addEventListener("click", refresh);

refresh();
// Someone may add a note on their phone; keep the wall roughly current.
setInterval(refresh, 2 * 60 * 1000);
