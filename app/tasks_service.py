"""Notes, backed by Google Tasks.

Google Keep was the obvious first choice and cannot be used: the Keep API is
Workspace-only, unavailable to personal Google accounts, and requires a service
account with domain-wide delegation. Google Tasks is the consumer-account
equivalent and satisfies the actual requirement - notes added on the wall show up
on phones immediately, both in the Google Tasks app and inside Google Calendar,
with no extra account and no separate sync to build.

It reuses the Google OAuth this app already has, plus one scope. Tokens issued
before that scope existed keep working for the calendar and get refused here, so
the missing-scope case is a first-class, explained state rather than a crash.
"""

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.auth import google_auth
from app.auth.errors import ACCOUNT_FETCH_ERRORS
from app.config import DEMO_MODE

# The wall is a shared household surface, so notes live in one list everyone sees
# rather than being scattered across each person's private lists.
LIST_TITLE = "Wall Calendar"


class TasksNotAuthorized(RuntimeError):
    """The signed-in token predates the Tasks scope (or it was declined). The fix
    is a one-time re-consent, so this carries that instruction rather than
    surfacing as a generic failure."""


class TasksUnavailable(RuntimeError):
    """Something transient - network, Google being unreachable, no account."""


def _account() -> str:
    accounts = google_auth.signed_in_accounts()
    if not accounts:
        raise TasksUnavailable("No Google account signed in yet.")
    # Deliberately the first account, matching how Spotify picks one: notes are a
    # single shared list, not per-person.
    return sorted(accounts)[0]


def _service():
    try:
        creds = google_auth.get_credentials(_account())
    except ACCOUNT_FETCH_ERRORS as exc:
        raise TasksUnavailable(f"Couldn't reach Google ({type(exc).__name__}).") from exc
    return build("tasks", "v1", credentials=creds)


def _translate(exc: HttpError) -> Exception:
    status = exc.status_code or 0
    if status in (401, 403):
        return TasksNotAuthorized(
            "Notes needs one more Google permission. Reconnect the account from "
            "Accounts (or run `python cli.py google`) to grant it."
        )
    return TasksUnavailable(f"Google Tasks returned {status}.")


def _list_id(service) -> str:
    """The wall's own task list, created on first use. Its id is looked up by
    title rather than stored, so deleting the list on a phone self-heals instead
    of leaving a dangling id."""
    try:
        for item in service.tasklists().list(maxResults=100).execute().get("items", []):
            if item.get("title") == LIST_TITLE:
                return item["id"]
        created = service.tasklists().insert(body={"title": LIST_TITLE}).execute()
        return created["id"]
    except HttpError as exc:
        raise _translate(exc) from exc


def _shape(task: dict) -> dict:
    return {
        "id": task["id"],
        "title": task.get("title") or "",
        "notes": task.get("notes") or None,
        "done": task.get("status") == "completed",
        "due": task.get("due"),
        "updated": task.get("updated"),
    }


def get_notes() -> dict:
    """Never raises - Notes failing must not take the page (or the overview) down.
    Errors come back in the payload so the UI can explain them in place."""
    if DEMO_MODE:
        from app import demo_tasks

        return demo_tasks.get_notes()

    try:
        service = _service()
        list_id = _list_id(service)
        response = (
            service.tasks()
            .list(tasklist=list_id, showCompleted=True, showHidden=False, maxResults=100)
            .execute()
        )
    except (TasksNotAuthorized, TasksUnavailable) as exc:
        return {
            "notes": [],
            "available": False,
            "needs_reauth": isinstance(exc, TasksNotAuthorized),
            "errors": [str(exc)],
        }
    except HttpError as exc:
        translated = _translate(exc)
        return {
            "notes": [],
            "available": False,
            "needs_reauth": isinstance(translated, TasksNotAuthorized),
            "errors": [str(translated)],
        }

    items = [_shape(task) for task in response.get("items", [])]
    # Open items first, then most recently touched - the wall should lead with
    # what still needs doing.
    items.sort(key=lambda note: (note["done"], -_epoch(note["updated"])))
    return {"notes": items, "available": True, "needs_reauth": False, "list": LIST_TITLE, "errors": []}


def _epoch(timestamp: str | None) -> float:
    if not timestamp:
        return 0.0
    import datetime as dt

    try:
        return dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def add_note(title: str, notes: str | None = None) -> dict:
    if DEMO_MODE:
        from app import demo_tasks

        return demo_tasks.add_note(title, notes)

    title = (title or "").strip()
    if not title:
        raise TasksUnavailable("A note needs some text.")

    service = _service()
    try:
        created = (
            service.tasks()
            .insert(tasklist=_list_id(service), body={"title": title, "notes": notes or None})
            .execute()
        )
    except HttpError as exc:
        raise _translate(exc) from exc
    return _shape(created)


def set_done(task_id: str, done: bool) -> dict:
    if DEMO_MODE:
        from app import demo_tasks

        return demo_tasks.set_done(task_id, done)

    service = _service()
    try:
        updated = (
            service.tasks()
            .patch(
                tasklist=_list_id(service),
                task=task_id,
                # Clearing `completed` matters: Google keeps the old completion
                # timestamp otherwise and the task reads as done despite status.
                body={"status": "completed" if done else "needsAction", "completed": None},
            )
            .execute()
        )
    except HttpError as exc:
        raise _translate(exc) from exc
    return _shape(updated)


def delete_note(task_id: str) -> None:
    if DEMO_MODE:
        from app import demo_tasks

        return demo_tasks.delete_note(task_id)

    service = _service()
    try:
        service.tasks().delete(tasklist=_list_id(service), task=task_id).execute()
    except HttpError as exc:
        raise _translate(exc) from exc
