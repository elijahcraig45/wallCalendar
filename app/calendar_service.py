import datetime as dt
import time
from zoneinfo import ZoneInfo

from google.auth.exceptions import GoogleAuthError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app import demo_data, preferences
from app.auth import google_auth
from app.auth.errors import ACCOUNT_FETCH_ERRORS, classify
from app.config import DEMO_MODE


class DemoModeError(RuntimeError):
    """Raised instead of faking a successful write while in demo mode - a demo
    run must never look like it saved something that went nowhere."""

# Fallback only. Real colours come from Google now: an event's own colorId if it
# sets one, otherwise the colour of the calendar it lives on - which is what the
# household already sees in Google Calendar, so the wall matches rather than
# inventing its own scheme. Measured against a real account: 0 of 156 events set
# an explicit colorId, so in practice the calendar colour is what shows.
PERSON_COLORS = ["#4285F4", "#EA4335", "#34A853", "#FBBC05", "#8E24AA", "#00ACC1"]

# Google's palette is light pastels paired with a dark foreground (#1d1d1d) - it
# is designed to be read as dark text on a coloured chip, which is also what
# Google Calendar's own dark mode does. Carrying the foreground through is what
# keeps a #fbd75b yellow event readable.
DEFAULT_EVENT_TEXT = "#1d1d1d"

_event_palette: dict | None = None


def _fetch_event_palette(service) -> dict:
    """Google's colorId -> {background, foreground} map. Effectively static, so it
    is fetched once per process rather than per request."""
    global _event_palette
    if _event_palette is None:
        try:
            _event_palette = service.colors().get().execute().get("event", {})
        except Exception:  # noqa: BLE001 - colours are cosmetic; never fail a fetch
            _event_palette = {}
    return _event_palette

CACHE_TTL_SECONDS = 300
ERROR_CACHE_TTL_SECONDS = 60
# Keyed by a tagged tuple so month/week/agenda share one cache:
# ("month", year, month) / ("week", week_start_iso) / ("agenda", from_iso, num_days)
_cache: dict[tuple, tuple[float, dict]] = {}
# The last payload for each key that came back with events and no errors. This is
# what makes a wifi drop survivable: a wall that replaces a good month with an
# empty grid is worse than one showing this morning's data with a marker saying
# so, and household wifi drops regularly.
_last_good: dict[tuple, dict] = {}


def invalidate_cache() -> None:
    # An event can span months, and _grid_bounds() pads each month's grid
    # with adjacent-month days, so a single date can land in two cached
    # entries. The cache holds a handful of entries with a short TTL in one
    # process - a full clear is trivially correct; computing exactly which
    # keys a given change affects isn't worth it.
    #
    # _last_good is deliberately NOT cleared: it isn't a cache of the current
    # view, it's the fallback for when a fetch fails, and a manual refresh must
    # not throw away the only good copy we have.
    _cache.clear()


def _event_count(payload: dict) -> int:
    """Total events in a payload, across both shapes: month grids key days by
    date, week/agenda/day carry an ordered list."""
    days = payload.get("days")
    if isinstance(days, dict):
        return sum(len(events) for events in days.values())
    if isinstance(days, list):
        return sum(len(day.get("events", [])) for day in days)
    return 0


def _cached(key: tuple, fetch) -> dict:
    cached = _cache.get(key)
    now = time.monotonic()
    if cached is not None:
        ttl = ERROR_CACHE_TTL_SECONDS if cached[1].get("errors") else CACHE_TTL_SECONDS
        if (now - cached[0]) < ttl:
            return cached[1]

    result = fetch()
    result["fetched_at"] = dt.datetime.now().isoformat(timespec="seconds")
    result["stale"] = False

    # "Every account failed and we got nothing" is the case worth papering over.
    # A partial failure (one of two accounts broken) still shows real events and
    # raises the existing error badge, which is the more useful signal.
    total_failure = bool(result.get("errors")) and _event_count(result) == 0
    previous = _last_good.get(key)

    if total_failure and previous is not None:
        result = {
            **previous,
            "stale": True,
            # Carry the live errors, not the stale ones, so the badge explains
            # what's wrong *now*.
            "errors": result["errors"],
        }
    elif not total_failure:
        _last_good[key] = result

    _cache[key] = (now, result)
    return result


def _person_color(email: str, all_emails: list[str]) -> str:
    idx = sorted(all_emails).index(email)
    return PERSON_COLORS[idx % len(PERSON_COLORS)]


def _owner_label(email: str) -> str:
    if DEMO_MODE:
        return demo_data.labels().get(email, email)
    return preferences.load_labels().get(email, email)


def signed_in_accounts() -> list[str]:
    """The one place anything asks "whose calendars are we showing?", so demo
    mode can answer it without google_auth needing to know demo mode exists."""
    if DEMO_MODE:
        return demo_data.accounts()
    return google_auth.signed_in_accounts()


def _require_live_mode() -> None:
    if DEMO_MODE:
        raise DemoModeError("Demo mode is on - calendar changes are disabled.")


def list_all_calendars(writable_only: bool = False) -> tuple[list[dict], list[dict]]:
    """Every calendar visible to every signed-in account - used to build the
    exclude list in data/calendar_prefs.json and the Add Event calendar picker.
    Returns (calendars, errors) - one broken account is recorded and skipped
    rather than failing the whole listing."""
    if DEMO_MODE:
        return demo_data.calendars(writable_only=writable_only), []

    results = []
    errors = []
    for email in signed_in_accounts():
        try:
            creds = google_auth.get_credentials(email)
            service = build("calendar", "v3", credentials=creds)
            calendars = service.calendarList().list().execute().get("items", [])
        except ACCOUNT_FETCH_ERRORS as exc:
            errors.append(classify(email, exc).to_dict())
            continue

        for cal in calendars:
            if writable_only and cal.get("accessRole") not in ("owner", "writer"):
                continue
            results.append(
                {
                    "account": email,
                    "calendar_id": cal["id"],
                    "summary": cal.get("summary"),
                    "access_role": cal.get("accessRole"),
                    "time_zone": cal.get("timeZone"),
                }
            )
    return results, errors


def check_accounts_health() -> list[dict]:
    """Cheap per-account probe for the Accounts page. Deliberately never
    raises - every account's failure is caught and classified, since this
    endpoint checking whether accounts are healthy must not itself 500
    because one account is unhealthy (the exact inverse of its purpose).
    get_credentials() alone isn't a sufficient probe: a token revoked
    server-side but not yet locally expired passes it cleanly, so a live
    call is needed to actually prove the credential still works."""
    if DEMO_MODE:
        return [
            {"email": email, "ok": True, "kind": None, "message": None}
            for email in demo_data.accounts()
        ]

    results = []
    for email in signed_in_accounts():
        try:
            creds = google_auth.get_credentials(email)
            service = build("calendar", "v3", credentials=creds)
            service.calendarList().list(maxResults=1).execute()
            results.append({"email": email, "ok": True, "kind": None, "message": None})
        except Exception as exc:  # noqa: BLE001 - see docstring
            err = classify(email, exc)
            results.append(
                {"email": email, "ok": False, "kind": err.kind, "message": err.message}
            )
    return results


def _week_start(d: dt.date) -> dt.date:
    """The Sunday on or before d. date.weekday(): Monday=0..Sunday=6."""
    days_since_sunday = (d.weekday() + 1) % 7
    return d - dt.timedelta(days=days_since_sunday)


def _grid_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    """Sunday-start weeks covering the full month, including the leading and
    trailing days needed to fill complete weeks."""
    first_of_month = dt.date(year, month, 1)
    first_of_next_month = (
        dt.date(year + 1, 1, 1) if month == 12 else dt.date(year, month + 1, 1)
    )
    last_of_month = first_of_next_month - dt.timedelta(days=1)

    grid_start = _week_start(first_of_month)
    # Saturday is index 6 in the Sunday-based indexing `(weekday() + 1) % 7`
    # produces (Sun=0 .. Sat=6). This read 5 - i, which lands on the Friday, so
    # every month grid stopped a day early and the last row's Saturday column
    # was always blank.
    days_until_saturday = (6 - ((last_of_month.weekday() + 1) % 7)) % 7
    grid_end = last_of_month + dt.timedelta(days=days_until_saturday)

    return grid_start, grid_end


def _group_events_by_day(
    events: list[dict], start: dt.date, end: dt.date, skip_empty: bool = False
) -> list[dict]:
    """Distributes events (each carrying ISO start_date/end_date strings)
    across every day they span within [start, end], sorted by sort_minutes.
    Returns an ordered list of {"date": iso, "events": [...]} - an ordered
    list rather than a dict since callers (week/agenda) need a guaranteed
    chronological order and, for agenda, a way to represent skipped days
    without ambiguity."""
    days: dict[str, list[dict]] = {}
    d = start
    while d <= end:
        days[d.isoformat()] = []
        d += dt.timedelta(days=1)

    for event in events:
        d = max(dt.date.fromisoformat(event["start_date"]), start)
        e = min(dt.date.fromisoformat(event["end_date"]), end)
        while d <= e:
            days[d.isoformat()].append(event)
            d += dt.timedelta(days=1)

    result = []
    for iso_date, day_events in days.items():
        day_events.sort(key=lambda ev: ev["sort_minutes"])
        if skip_empty and not day_events:
            continue
        result.append({"date": iso_date, "events": day_events})
    return result


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


def _fetch_events_for_range(
    range_start: dt.date, range_end: dt.date
) -> tuple[list[dict], list[dict]]:
    """Every non-cancelled event across every signed-in account's non-excluded
    calendars, within [range_start, range_end] inclusive. Returns
    (events, errors): a failure isolated to one account or one calendar is
    recorded in `errors` and skipped, rather than raising and losing every
    other account's events."""
    if DEMO_MODE:
        return demo_data.events_for_range(range_start, range_end, _person_color)

    prefs = preferences.load_prefs()
    excluded = set(prefs.get("excluded_calendar_ids", []))

    time_min = dt.datetime.combine(range_start, dt.time.min).isoformat() + "Z"
    time_max = (
        dt.datetime.combine(range_end + dt.timedelta(days=1), dt.time.min).isoformat()
        + "Z"
    )

    accounts = signed_in_accounts()
    events_by_uid: dict[str, dict] = {}
    errors: list[dict] = []

    for email in accounts:
        try:
            creds = google_auth.get_credentials(email)
            service = build("calendar", "v3", credentials=creds)
            calendars = service.calendarList().list().execute().get("items", [])
            palette = _fetch_event_palette(service)
        except ACCOUNT_FETCH_ERRORS as exc:
            errors.append(classify(email, exc).to_dict())
            continue

        for cal in calendars:
            cal_id = cal["id"]
            if cal_id in excluded:
                continue
            is_owner = cal.get("accessRole") == "owner"
            # The calendar's own colour is what an event inherits unless it
            # overrides it, and it's what the household already sees in Google
            # Calendar - so "Family" is the same orange on the wall as on a phone.
            cal_bg = cal.get("backgroundColor") or _person_color(email, accounts)
            cal_fg = cal.get("foregroundColor") or DEFAULT_EVENT_TEXT

            try:
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

                        entry = palette.get(str(event.get("colorId") or ""), {})
                        event_bg = entry.get("background") or cal_bg
                        event_fg = entry.get("foreground") or cal_fg

                        uid = event.get("iCalUID", event["id"])
                        existing = events_by_uid.get(uid)
                        # Same event can arrive twice: once from its owner's
                        # calendar, once as a copy shared into another
                        # account. Keep the owner's copy.
                        if existing is not None and not (
                            is_owner and not existing["_is_owner_copy"]
                        ):
                            continue

                        start_date, end_date, is_all_day = _parse_event_range(event)
                        if is_all_day:
                            start_time = None
                            end_time = None
                            start_iso = None
                            end_iso = None
                            sort_minutes = -1  # all-day events always sort first
                        else:
                            start_dt = dt.datetime.fromisoformat(event["start"]["dateTime"])
                            end_dt = dt.datetime.fromisoformat(event["end"]["dateTime"])
                            start_time = start_dt.strftime("%-I:%M %p")
                            end_time = end_dt.strftime("%-I:%M %p")
                            # Offset-carrying ISO strings, handed to the time
                            # grid to position by. Kept as full timestamps
                            # (not minutes-from-midnight) because one event
                            # dict is shared across every day it spans, so
                            # per-day clamping has to happen per column on the
                            # client, not once here.
                            start_iso = start_dt.isoformat()
                            end_iso = end_dt.isoformat()
                            sort_minutes = start_dt.hour * 60 + start_dt.minute

                        events_by_uid[uid] = {
                            "uid": uid,
                            "event_id": event["id"],
                            "calendar_id": cal_id,
                            "access_role": cal.get("accessRole"),
                            "recurring_event_id": event.get("recurringEventId"),
                            "title": event.get("summary", "(no title)"),
                            "location": event.get("location"),
                            "start_date": start_date,
                            "end_date": end_date,
                            "all_day": is_all_day,
                            "start_time": start_time,
                            "end_time": end_time,
                            "start_iso": start_iso,
                            "end_iso": end_iso,
                            "account": email,
                            "owner_label": _owner_label(email),
                            "calendar_name": cal.get("summary"),
                            "color": event_bg,
                            "text_color": event_fg,
                            "sort_minutes": sort_minutes,
                            "_is_owner_copy": is_owner,
                        }

                    page_token = resp.get("nextPageToken")
                    if not page_token:
                        break
            except ACCOUNT_FETCH_ERRORS as exc:
                err = classify(email, exc).to_dict()
                err["calendar"] = cal.get("summary")
                errors.append(err)
                continue

    # Convert/clean each unique event once, before distributing it across
    # every day it spans - the same dict is shared across multiple days for
    # multi-day events, so converting per-day would double-convert it.
    for event in events_by_uid.values():
        event.pop("_is_owner_copy", None)
        event["start_date"] = event["start_date"].isoformat()
        event["end_date"] = event["end_date"].isoformat()

    return list(events_by_uid.values()), errors


def _fetch_month_grid(year: int, month: int) -> dict:
    grid_start, grid_end = _grid_bounds(year, month)
    events, errors = _fetch_events_for_range(grid_start, grid_end)

    days: dict[str, list[dict]] = {}
    d = grid_start
    while d <= grid_end:
        days[d.isoformat()] = []
        d += dt.timedelta(days=1)

    for event in events:
        d = max(dt.date.fromisoformat(event["start_date"]), grid_start)
        end = min(dt.date.fromisoformat(event["end_date"]), grid_end)
        while d <= end:
            days[d.isoformat()].append(event)
            d += dt.timedelta(days=1)

    # Sort by sort_minutes (a real minutes-since-midnight value), not the
    # formatted "9:00 AM" display string - lexicographic string sort would
    # put "10:00 AM" before "9:00 AM".
    for day_events in days.values():
        day_events.sort(key=lambda e: e["sort_minutes"])

    return {
        "year": year,
        "month": month,
        "grid_start": grid_start.isoformat(),
        "grid_end": grid_end.isoformat(),
        "days": days,
        "errors": errors,
    }


def get_month_grid(year: int, month: int) -> dict:
    return _cached(("month", year, month), lambda: _fetch_month_grid(year, month))


def _fetch_week_grid(anchor_date: dt.date) -> dict:
    week_start = _week_start(anchor_date)
    week_end = week_start + dt.timedelta(days=6)
    events, errors = _fetch_events_for_range(week_start, week_end)
    # Always all 7 days, even empty ones - a week should render complete.
    days = _group_events_by_day(events, week_start, week_end, skip_empty=False)
    return {
        "from": week_start.isoformat(),
        "to": week_end.isoformat(),
        "days": days,
        "errors": errors,
    }


def get_week_grid(year: int, month: int, day: int) -> dict:
    anchor = dt.date(year, month, day)
    week_start = _week_start(anchor)
    return _cached(("week", week_start.isoformat()), lambda: _fetch_week_grid(anchor))


def _fetch_day_grid(date: dt.date) -> dict:
    events, errors = _fetch_events_for_range(date, date)
    days = _group_events_by_day(events, date, date, skip_empty=False)
    return {
        "from": date.isoformat(),
        "to": date.isoformat(),
        "days": days,
        "errors": errors,
    }


def get_day_grid(year: int, month: int, day: int) -> dict:
    date = dt.date(year, month, day)
    return _cached(("day", date.isoformat()), lambda: _fetch_day_grid(date))


def _fetch_agenda(from_date: dt.date, num_days: int) -> dict:
    to_date = from_date + dt.timedelta(days=num_days - 1)
    events, errors = _fetch_events_for_range(from_date, to_date)
    # Skip empty days - agenda's whole value is "what's actually coming up".
    days = _group_events_by_day(events, from_date, to_date, skip_empty=True)
    return {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "days": days,
        "errors": errors,
    }


def get_agenda(from_date: dt.date, num_days: int = 30) -> dict:
    return _cached(
        ("agenda", from_date.isoformat(), num_days),
        lambda: _fetch_agenda(from_date, num_days),
    )


_FREQ_MAP = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY", "yearly": "YEARLY"}


def _build_rrule(
    freq: str, until: str | None, all_day: bool, time_zone: str
) -> str | None:
    if freq not in _FREQ_MAP:
        return None
    rule = f"FREQ={_FREQ_MAP[freq]}"
    if until:
        if all_day:
            # DTSTART is a DATE, so UNTIL must match value type - bare date,
            # no time/Z (RFC5545 3.3.10).
            rule += f";UNTIL={until.replace('-', '')}"
        else:
            # DTSTART is a DATE-TIME, so UNTIL must be UTC DATE-TIME. Use
            # end-of-day in the event's own tz, then convert - midnight would
            # exclude a same-day occurrence later than midnight.
            local_eod = dt.datetime.fromisoformat(f"{until}T23:59:59").replace(
                tzinfo=ZoneInfo(time_zone)
            )
            rule += f";UNTIL={local_eod.astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    return f"RRULE:{rule}"


def _rfc3339_local(value: str) -> str:
    """Turn the "YYYY-MM-DDTHH:MM" an <input type="datetime-local"> produces into
    the RFC3339 string Google's dateTime field requires.

    RFC3339 makes the seconds field mandatory, and datetime-local omits it, so
    posting the input's value straight through made Google reject every *timed*
    event with a bare 400 "Bad Request". All-day events were unaffected (they use
    the date field), which is why this looked like an intermittent fault rather
    than a broken code path.

    No offset is added on purpose: it is sent alongside an explicit timeZone, and
    Google reads the dateTime as wall-clock in that zone.
    """
    return dt.datetime.fromisoformat(value).isoformat(timespec="seconds")


def create_event(
    account: str,
    calendar_id: str,
    time_zone: str,
    *,
    title: str,
    location: str | None,
    description: str | None,
    all_day: bool,
    start: str,  # "YYYY-MM-DD" if all_day else "YYYY-MM-DDTHH:MM"
    end: str,
    recurrence_freq: str,  # "none"/"daily"/"weekly"/"monthly"/"yearly"
    recurrence_until: str | None,
    guests: list[str],
) -> dict:
    _require_live_mode()
    body = {"summary": title, "location": location, "description": description}

    if all_day:
        # Google's end.date is exclusive (same convention _parse_event_range
        # relies on when reading) - a one-day event's end.date must be
        # start + 1 day.
        end_exclusive = (dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat()
        body["start"] = {"date": start}
        body["end"] = {"date": end_exclusive}
    else:
        body["start"] = {"dateTime": _rfc3339_local(start), "timeZone": time_zone}
        body["end"] = {"dateTime": _rfc3339_local(end), "timeZone": time_zone}

    rrule = _build_rrule(recurrence_freq, recurrence_until, all_day, time_zone)
    if rrule:
        body["recurrence"] = [rrule]

    if guests:
        body["attendees"] = [{"email": g} for g in guests]

    creds = google_auth.get_credentials(account)
    service = build("calendar", "v3", credentials=creds)
    result = (
        service.events()
        .insert(
            calendarId=calendar_id,
            body=body,
            # Only email invitees when there are any, to avoid spamming
            # attendees on every plain personal event.
            sendUpdates="all" if guests else "none",
        )
        .execute()
    )
    invalidate_cache()
    return result


def _format_datetime_local(iso_datetime: str) -> str:
    # Google's dateTime strings carry the wall-clock time exactly as it was
    # entered (e.g. "2026-08-10T09:00:00-04:00") - the offset just labels
    # which zone that wall-clock reading is in, so dropping it after parsing
    # recovers the original "YYYY-MM-DDTHH:MM" the datetime-local input needs.
    return dt.datetime.fromisoformat(iso_datetime).strftime("%Y-%m-%dT%H:%M")


def get_event(account: str, calendar_id: str, event_id: str) -> dict:
    """Full editable shape for the Add Event form's edit mode. recurring_event_id
    is the gate for whether recurrence editing is offered at all - instance
    events fetched this way never carry their own `recurrence` (only the
    series' master event does), so recurrence_freq/recurrence_until are
    always returned as the "none" starting point, never reverse-parsed."""
    if DEMO_MODE:
        event = demo_data.find_event(event_id, _person_color)
        if event is None:
            raise ValueError(f"No demo event {event_id}")
        return {
            "title": event["title"],
            "location": event["location"],
            "description": None,
            "all_day": event["all_day"],
            "start": event["start_date"] if event["all_day"] else event["start_iso"][:16],
            "end": event["end_date"] if event["all_day"] else event["end_iso"][:16],
            "time_zone": "America/New_York",
            "recurring_event_id": None,
            "recurrence_freq": "none",
            "recurrence_until": None,
            "guests": [],
        }

    creds = google_auth.get_credentials(account)
    service = build("calendar", "v3", credentials=creds)
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    start_date, end_date, is_all_day = _parse_event_range(event)
    if is_all_day:
        start = start_date.isoformat()
        end = end_date.isoformat()
    else:
        start = _format_datetime_local(event["start"]["dateTime"])
        end = _format_datetime_local(event["end"]["dateTime"])

    # An all-day event has no start.timeZone - fall back to the calendar's
    # own default so toggling it to a timed event during edit still has a
    # valid IANA zone to construct dateTime values with.
    time_zone = event["start"].get("timeZone")
    if not time_zone:
        cal = service.calendarList().get(calendarId=calendar_id).execute()
        time_zone = cal.get("timeZone")

    return {
        "title": event.get("summary", ""),
        "location": event.get("location"),
        "description": event.get("description"),
        "all_day": is_all_day,
        "start": start,
        "end": end,
        "time_zone": time_zone,
        "recurring_event_id": event.get("recurringEventId"),
        "recurrence_freq": "none",
        "recurrence_until": None,
        "guests": [a["email"] for a in event.get("attendees", [])],
    }


def update_event(
    account: str,
    calendar_id: str,
    event_id: str,
    time_zone: str,
    *,
    title: str,
    location: str | None,
    description: str | None,
    all_day: bool,
    start: str,
    end: str,
    recurrence_freq: str,
    recurrence_until: str | None,
    guests: list[str],
) -> dict:
    """Sends a diff, not the full form state - Calendar API's attendees is a
    full-list-replace on any write that includes it (wiping RSVP status and
    re-notifying everyone if resent unchanged), so only fields that actually
    changed are included, via events().patch() rather than events().update()
    so omitted keys are left completely untouched regardless of what else
    changes."""
    _require_live_mode()
    creds = google_auth.get_credentials(account)
    service = build("calendar", "v3", credentials=creds)
    current = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    body: dict = {}

    if title != current.get("summary", ""):
        body["summary"] = title
    if (location or None) != (current.get("location") or None):
        body["location"] = location
    if (description or None) != (current.get("description") or None):
        body["description"] = description

    _, _, current_all_day = _parse_event_range(current)
    if all_day != current_all_day:
        # Shape change (date <-> dateTime), not a value change - must send
        # the whole start/end object as a unit, never a sub-key merge.
        if all_day:
            end_exclusive = (dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat()
            body["start"] = {"date": start}
            body["end"] = {"date": end_exclusive}
        else:
            body["start"] = {"dateTime": _rfc3339_local(start), "timeZone": time_zone}
            body["end"] = {"dateTime": _rfc3339_local(end), "timeZone": time_zone}
    elif all_day:
        end_exclusive = (dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat()
        if start != current["start"]["date"] or end_exclusive != current["end"]["date"]:
            body["start"] = {"date": start}
            body["end"] = {"date": end_exclusive}
    else:
        if start != _format_datetime_local(current["start"]["dateTime"]) or end != _format_datetime_local(
            current["end"]["dateTime"]
        ):
            body["start"] = {"dateTime": _rfc3339_local(start), "timeZone": time_zone}
            body["end"] = {"dateTime": _rfc3339_local(end), "timeZone": time_zone}

    # Recurrence is never touched for an event that's already part of a
    # series - only a previously non-recurring event can have one added.
    if current.get("recurringEventId") is None:
        rrule = _build_rrule(recurrence_freq, recurrence_until, all_day, time_zone)
        if rrule:
            body["recurrence"] = [rrule]

    current_guests = sorted(a["email"].lower() for a in current.get("attendees", []))
    new_guests = sorted(g.lower() for g in guests)
    had_or_has_guests = bool(current_guests or new_guests)
    if current_guests != new_guests:
        body["attendees"] = [{"email": g} for g in guests]

    if not body:
        return current

    result = (
        service.events()
        .patch(
            calendarId=calendar_id,
            eventId=event_id,
            body=body,
            # Notify on any edit to an event that has guests, matching
            # Google Calendar's own default behavior - not only when the
            # guest list itself changed.
            sendUpdates="all" if had_or_has_guests else "none",
        )
        .execute()
    )
    invalidate_cache()
    return result


def delete_event(account: str, calendar_id: str, event_id: str, notify_guests: bool) -> None:
    _require_live_mode()
    creds = google_auth.get_credentials(account)
    service = build("calendar", "v3", credentials=creds)
    service.events().delete(
        calendarId=calendar_id,
        eventId=event_id,
        sendUpdates="all" if notify_guests else "none",
    ).execute()
    invalidate_cache()
