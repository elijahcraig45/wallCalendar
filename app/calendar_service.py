import datetime as dt
import json
import time

from googleapiclient.discovery import build

from app.auth import google_auth
from app.config import PROJECT_ROOT

PREFS_FILE = PROJECT_ROOT / "data" / "calendar_prefs.json"
PREFS_FILE.parent.mkdir(exist_ok=True)

LABELS_FILE = PROJECT_ROOT / "data" / "account_labels.json"

# Assigned by person (account), not by Google's per-calendar colorId - two
# accounts means two colors, legible from across a room.
PERSON_COLORS = ["#4285F4", "#EA4335", "#34A853", "#FBBC05", "#8E24AA", "#00ACC1"]

CACHE_TTL_SECONDS = 300
_cache: dict[tuple[int, int], tuple[float, dict]] = {}


def _load_prefs() -> dict:
    if not PREFS_FILE.exists():
        return {"excluded_calendar_ids": []}
    return json.loads(PREFS_FILE.read_text())


def _person_color(email: str, all_emails: list[str]) -> str:
    idx = sorted(all_emails).index(email)
    return PERSON_COLORS[idx % len(PERSON_COLORS)]


def _load_labels() -> dict:
    if not LABELS_FILE.exists():
        return {}
    return json.loads(LABELS_FILE.read_text())


def _owner_label(email: str) -> str:
    return _load_labels().get(email, email)


def list_all_calendars() -> list[dict]:
    """Every calendar visible to every signed-in account - used to build the
    exclude list in data/calendar_prefs.json."""
    results = []
    for email in google_auth.signed_in_accounts():
        creds = google_auth.get_credentials(email)
        service = build("calendar", "v3", credentials=creds)
        for cal in service.calendarList().list().execute().get("items", []):
            results.append(
                {
                    "account": email,
                    "calendar_id": cal["id"],
                    "summary": cal.get("summary"),
                    "access_role": cal.get("accessRole"),
                }
            )
    return results


def _grid_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    """Sunday-start weeks covering the full month, including the leading and
    trailing days needed to fill complete weeks."""
    first_of_month = dt.date(year, month, 1)
    first_of_next_month = (
        dt.date(year + 1, 1, 1) if month == 12 else dt.date(year, month + 1, 1)
    )
    last_of_month = first_of_next_month - dt.timedelta(days=1)

    # date.weekday(): Monday=0..Sunday=6. We want Sunday-start weeks.
    days_since_sunday = (first_of_month.weekday() + 1) % 7
    grid_start = first_of_month - dt.timedelta(days=days_since_sunday)

    days_until_saturday = (5 - ((last_of_month.weekday() + 1) % 7)) % 7
    grid_end = last_of_month + dt.timedelta(days=days_until_saturday)

    return grid_start, grid_end


def _parse_event_range(event: dict) -> tuple[dt.date, dt.date, bool]:
    start, end = event["start"], event["end"]
    if "date" in start:
        # all-day: Google's end.date is exclusive, so a one-day event's
        # end.date is already the next day.
        start_date = dt.date.fromisoformat(start["date"])
        end_date = dt.date.fromisoformat(end["date"]) - dt.timedelta(days=1)
        return start_date, end_date, True
    start_date = dt.datetime.fromisoformat(start["dateTime"]).date()
    end_date = dt.datetime.fromisoformat(end["dateTime"]).date()
    return start_date, end_date, False


def _fetch_month_grid(year: int, month: int) -> dict:
    prefs = _load_prefs()
    excluded = set(prefs.get("excluded_calendar_ids", []))

    grid_start, grid_end = _grid_bounds(year, month)
    time_min = dt.datetime.combine(grid_start, dt.time.min).isoformat() + "Z"
    time_max = (
        dt.datetime.combine(grid_end + dt.timedelta(days=1), dt.time.min).isoformat()
        + "Z"
    )

    accounts = google_auth.signed_in_accounts()
    events_by_uid: dict[str, dict] = {}

    for email in accounts:
        creds = google_auth.get_credentials(email)
        service = build("calendar", "v3", credentials=creds)
        calendars = service.calendarList().list().execute().get("items", [])

        for cal in calendars:
            cal_id = cal["id"]
            if cal_id in excluded:
                continue
            is_owner = cal.get("accessRole") == "owner"

            page_token = None
            while True:
                resp = (
                    service.events()
                    .list(
                        calendarId=cal_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        singleEvents=True,
                        orderBy="startTime",
                        pageToken=page_token,
                    )
                    .execute()
                )

                for event in resp.get("items", []):
                    if "start" not in event or "end" not in event:
                        continue  # cancelled/malformed entries

                    uid = event.get("iCalUID", event["id"])
                    existing = events_by_uid.get(uid)
                    # Same event can arrive twice: once from its owner's
                    # calendar, once as a copy shared into another account.
                    # Keep the owner's copy.
                    if existing is not None and not (
                        is_owner and not existing["_is_owner_copy"]
                    ):
                        continue

                    start_date, end_date, is_all_day = _parse_event_range(event)
                    if is_all_day:
                        start_time = None
                        end_time = None
                        sort_minutes = -1  # all-day events always sort first
                    else:
                        start_dt = dt.datetime.fromisoformat(event["start"]["dateTime"])
                        end_dt = dt.datetime.fromisoformat(event["end"]["dateTime"])
                        start_time = start_dt.strftime("%-I:%M %p")
                        end_time = end_dt.strftime("%-I:%M %p")
                        sort_minutes = start_dt.hour * 60 + start_dt.minute

                    events_by_uid[uid] = {
                        "uid": uid,
                        "title": event.get("summary", "(no title)"),
                        "location": event.get("location"),
                        "start_date": start_date,
                        "end_date": end_date,
                        "all_day": is_all_day,
                        "start_time": start_time,
                        "end_time": end_time,
                        "account": email,
                        "owner_label": _owner_label(email),
                        "color": _person_color(email, accounts),
                        "_is_owner_copy": is_owner,
                        "_sort_minutes": sort_minutes,
                    }

                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

    # Convert/clean each unique event once, before distributing it across
    # every day it spans - the same dict is shared across multiple days for
    # multi-day events, so converting per-day would double-convert it.
    for event in events_by_uid.values():
        event.pop("_is_owner_copy", None)
        event["start_date"] = event["start_date"].isoformat()
        event["end_date"] = event["end_date"].isoformat()

    days: dict[str, list[dict]] = {}
    d = grid_start
    while d <= grid_end:
        days[d.isoformat()] = []
        d += dt.timedelta(days=1)

    for event in events_by_uid.values():
        d = max(dt.date.fromisoformat(event["start_date"]), grid_start)
        end = min(dt.date.fromisoformat(event["end_date"]), grid_end)
        while d <= end:
            days[d.isoformat()].append(event)
            d += dt.timedelta(days=1)

    # Sort by _sort_minutes (a real minutes-since-midnight value), not the
    # formatted "9:00 AM" display string - lexicographic string sort would
    # put "10:00 AM" before "9:00 AM".
    for day_events in days.values():
        day_events.sort(key=lambda e: e["_sort_minutes"])
    # Pop only after every day's list has been sorted - a multi-day event's
    # dict is shared across all the days it spans, so popping per-day would
    # remove the sort key before later days get to use it.
    for event in events_by_uid.values():
        event.pop("_sort_minutes", None)

    return {
        "year": year,
        "month": month,
        "grid_start": grid_start.isoformat(),
        "grid_end": grid_end.isoformat(),
        "days": days,
    }


def get_month_grid(year: int, month: int) -> dict:
    key = (year, month)
    cached = _cache.get(key)
    now = time.monotonic()
    if cached is not None and (now - cached[0]) < CACHE_TTL_SECONDS:
        return cached[1]

    grid = _fetch_month_grid(year, month)
    _cache[key] = (now, grid)
    return grid
