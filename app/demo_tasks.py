"""Synthetic Notes for demo mode.

Writes are faked rather than refused, matching demo_spotify's reasoning: there's
no real data to corrupt, and a note list is only testable if adding a note
actually adds one. State lives in the process and resets with the server.
"""

import datetime as dt
import itertools

_counter = itertools.count(100)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _negated(timestamp: str) -> float:
    """Sorts newest-first when used as a sort key alongside other ascending keys."""
    return -dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()


_notes = [
    {"id": "demo-1", "title": "Milk, eggs, coffee beans", "notes": None, "done": False, "due": None, "updated": _now()},
    {"id": "demo-2", "title": "Call the vet about Bandit's teeth", "notes": None, "done": False, "due": None, "updated": _now()},
    {"id": "demo-3", "title": "Return the Amazon box by Friday", "notes": "Label is on the counter", "done": False, "due": None, "updated": _now()},
    {"id": "demo-4", "title": "Book oil change", "notes": None, "done": True, "due": None, "updated": _now()},
]


def get_notes() -> dict:
    # Must match tasks_service's ordering exactly - open items first, then most
    # recently touched - or the demo teaches the wrong thing about where a new
    # note appears.
    items = sorted(_notes, key=lambda note: (note["done"], _negated(note["updated"])))
    return {
        "notes": [dict(note) for note in items],
        "available": True,
        "needs_reauth": False,
        "list": "Wall Calendar",
        "errors": [],
    }


def add_note(title: str, notes: str | None = None) -> dict:
    note = {
        "id": f"demo-{next(_counter)}",
        "title": title.strip(),
        "notes": notes or None,
        "done": False,
        "due": None,
        "updated": _now(),
    }
    _notes.insert(0, note)
    return dict(note)


def set_done(task_id: str, done: bool) -> dict:
    for note in _notes:
        if note["id"] == task_id:
            note["done"] = done
            note["updated"] = _now()
            return dict(note)
    raise ValueError(f"No demo note {task_id}")


def delete_note(task_id: str) -> None:
    global _notes
    _notes = [note for note in _notes if note["id"] != task_id]
