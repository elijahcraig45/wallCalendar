"""Synthetic calendar fixtures for demo mode (WALLCAL_DEMO=1).

Exists so the wall layout can be built and screenshot-verified without
signing in to anyone's real calendar - and so the dense/overlapping/multi-day
cases the layout has to survive are actually present, which a real calendar on
any given day may not be.

Events are emitted in the same shape `_fetch_events_for_range` returns *after*
its final conversion pass: `start_date`/`end_date` are ISO strings and there's
no internal `_is_owner_copy` key. Anything reading events can't tell the
difference.

Everything is anchored to today, so the fixtures are always in view no matter
when they're rendered, and deterministic for a given date.
"""

import datetime as dt

from app.config import DEMO_ACCOUNT_COUNT

# (email, display label, calendar summary, background, foreground)
# Colours are taken from Google's real palette, because that's where live colours
# come from now - an event inherits its calendar's colour unless it overrides it.
# Light chip + dark text is Google's own scheme, not an invention here.
_PEOPLE = [
    ("henry.demo@example.com", "Henry", "Family", "#ffad46", "#000000"),
    ("avery.demo@example.com", "Avery", "Avery", "#9fe1e7", "#000000"),
    ("robin.demo@example.com", "Robin", "Robin", "#a47ae2", "#000000"),
]

# Weekly rhythm, keyed by Python weekday (Mon=0 .. Sun=6). Each entry is
# (person_index, weekdays, start_hhmm, end_hhmm, title, location).
_WEEKLY = [
    (0, {0, 1, 2, 3, 4}, "09:00", "09:20", "Standup", None),
    (0, {0, 2, 4}, "06:30", "07:30", "Gym", "YMCA"),
    (0, {1}, "13:00", "14:00", "1:1 with Dana", None),
    (0, {2}, "11:30", "12:30", "Design review", None),
    (0, {3}, "15:00", "16:30", "Sprint planning", None),
    (0, {5}, "10:00", "11:00", "Farmers market", "Downtown"),
    (1, {0, 1, 2, 3, 4}, "08:45", "09:00", "School dropoff", None),
    (1, {1, 3}, "18:00", "19:15", "Pottery class", "Clay Studio"),
    (1, {2}, "09:30", "10:30", "Client call", None),
    (1, {4}, "17:00", "18:00", "Happy hour", "The Porch"),
    (1, {6}, "09:00", "10:00", "Long run", None),
    (2, {0}, "12:00", "13:00", "Lunch with Sam", None),
    (2, {3}, "20:00", "21:30", "Trivia night", "Brewery"),
]

# One-offs at fixed offsets from today. Timed entries deliberately pile up on
# today to exercise the overlap layout, and the long title is there to keep an
# ellipsis case permanently in the fixtures.
# (person_index, day_offset, start_hhmm, end_hhmm, title, location)
_TIMED_ONE_OFFS = [
    (0, -1, "07:00", "07:45", "Car inspection", "Firestone"),
    (0, 0, "14:00", "15:00", "Dentist", "Dr. Alvarez"),
    (1, 0, "14:30", "15:30", "Plumber window", None),
    (0, 0, "14:45", "16:00", "Pickup order ready", "Ace Hardware"),
    (0, 1, "10:00", "16:00", "Quarterly planning offsite — bring laptop and charger", "Midtown"),
    (1, 3, "19:30", "20:30", "Parent-teacher conference", None),
    (0, 4, "22:30", "23:45", "Red-eye to Denver", "ATL Terminal S"),
    (1, 6, "16:00", "17:00", "Soccer practice", "Field 4"),
]

# (person_index, start_day_offset, end_day_offset_inclusive, title)
_ALL_DAY_ONE_OFFS = [
    (0, 0, 0, "Trash night"),
    # Long enough to have to ellipsise inside a month cell. Kept in the fixtures
    # because a real calendar had one and the layout clipped it mid-word.
    (0, 0, 0, "Stay at Hilton Garden Inn Nashville Downtown — conference rate"),
    (0, 1, 1, "Mom's birthday"),
    (1, 2, 5, "Asheville trip"),
    # Deliberately crosses a Saturday->Sunday boundary: a multi-day bar has to
    # split across week rows and square off its cut ends.
    (0, 4, 9, "Grandma visiting"),
    (0, 9, 9, "Registration deadline"),
]


def accounts() -> list[str]:
    return [p[0] for p in _PEOPLE[:DEMO_ACCOUNT_COUNT]]


def labels() -> dict[str, str]:
    return {p[0]: p[1] for p in _PEOPLE[:DEMO_ACCOUNT_COUNT]}


def calendars(writable_only: bool = False) -> list[dict]:
    return [
        {
            "account": email,
            "calendar_id": f"{email}-primary",
            "summary": summary,
            "access_role": "owner",
            "time_zone": "America/New_York",
        }
        for email, _label, summary, _bg, _fg in _PEOPLE[:DEMO_ACCOUNT_COUNT]
    ]


def _timed(
    uid: str,
    person_index: int,
    date: dt.date,
    start_hhmm: str,
    end_hhmm: str,
    title: str,
    location: str | None,
    color_for,
) -> dict:
    email, label, summary, bg, fg = _PEOPLE[person_index]
    start = dt.datetime.combine(date, dt.time.fromisoformat(start_hhmm))
    end = dt.datetime.combine(date, dt.time.fromisoformat(end_hhmm))
    return {
        "uid": uid,
        "event_id": uid,
        "calendar_id": f"{email}-primary",
        "access_role": "owner",
        "recurring_event_id": None,
        "title": title,
        "location": location,
        "start_date": date.isoformat(),
        "end_date": date.isoformat(),
        "all_day": False,
        "start_time": start.strftime("%-I:%M %p"),
        "end_time": end.strftime("%-I:%M %p"),
        "start_iso": start.isoformat(),
        "end_iso": end.isoformat(),
        "account": email,
        "owner_label": label,
        "calendar_name": summary,
        "color": bg,
        "text_color": fg,
        "sort_minutes": start.hour * 60 + start.minute,
    }


def _all_day(
    uid: str,
    person_index: int,
    start_date: dt.date,
    end_date: dt.date,
    title: str,
    color_for,
) -> dict:
    email, label, summary, bg, fg = _PEOPLE[person_index]
    return {
        "uid": uid,
        "event_id": uid,
        "calendar_id": f"{email}-primary",
        "access_role": "owner",
        "recurring_event_id": None,
        "title": title,
        "location": None,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "all_day": True,
        "start_time": None,
        "end_time": None,
        "start_iso": None,
        "end_iso": None,
        "account": email,
        "owner_label": label,
        "calendar_name": summary,
        "color": bg,
        "text_color": fg,
        "sort_minutes": -1,
    }


def find_event(event_id: str, color_for) -> dict | None:
    """Backs demo mode's `get_event` so tapping an event still opens a populated
    edit sheet. Scans a wide window around today rather than keeping an index -
    the fixtures are a few dozen events, generated deterministically."""
    today = dt.date.today()
    events, _ = events_for_range(
        today - dt.timedelta(days=45), today + dt.timedelta(days=90), color_for
    )
    for event in events:
        if event["event_id"] == event_id:
            return event
    return None


def events_for_range(
    range_start: dt.date, range_end: dt.date, color_for
) -> tuple[list[dict], list[dict]]:
    """Mirrors `_fetch_events_for_range`'s (events, errors) contract. `color_for`
    is passed in rather than imported to keep calendar_service the single owner
    of the person-color palette (and to avoid a circular import)."""
    today = dt.date.today()
    events: list[dict] = []

    def in_range(start: dt.date, end: dt.date) -> bool:
        return start <= range_end and end >= range_start

    day = range_start
    while day <= range_end:
        for idx, (person, weekdays, start, end, title, location) in enumerate(_WEEKLY):
            if person >= DEMO_ACCOUNT_COUNT or day.weekday() not in weekdays:
                continue
            events.append(
                _timed(
                    f"demo-weekly-{idx}-{day.isoformat()}",
                    person, day, start, end, title, location, color_for,
                )
            )
        day += dt.timedelta(days=1)

    for idx, (person, offset, start, end, title, location) in enumerate(_TIMED_ONE_OFFS):
        date = today + dt.timedelta(days=offset)
        if person >= DEMO_ACCOUNT_COUNT or not in_range(date, date):
            continue
        events.append(
            _timed(
                f"demo-oneoff-{idx}", person, date, start, end, title, location, color_for
            )
        )

    for idx, (person, start_offset, end_offset, title) in enumerate(_ALL_DAY_ONE_OFFS):
        start_date = today + dt.timedelta(days=start_offset)
        end_date = today + dt.timedelta(days=end_offset)
        if person >= DEMO_ACCOUNT_COUNT or not in_range(start_date, end_date):
            continue
        events.append(
            _all_day(f"demo-allday-{idx}", person, start_date, end_date, title, color_for)
        )

    return events, []
