import json

from app.config import PROJECT_ROOT

PREFS_FILE = PROJECT_ROOT / "data" / "calendar_prefs.json"
PREFS_FILE.parent.mkdir(exist_ok=True)

LABELS_FILE = PROJECT_ROOT / "data" / "account_labels.json"


def load_prefs() -> dict:
    if not PREFS_FILE.exists():
        return {"excluded_calendar_ids": []}
    return json.loads(PREFS_FILE.read_text())


def save_prefs(prefs: dict) -> None:
    PREFS_FILE.write_text(json.dumps(prefs, indent=2))


def update_prefs(**changes) -> dict:
    """Merge changes into the stored prefs rather than replacing the file.

    Every setter has to go through this. set_calendar_excluded() used to call
    save_prefs({"excluded_calendar_ids": ...}) with a freshly built one-key dict,
    which silently dropped every other key - so the moment a second setting lived
    in this file, toggling a calendar's visibility would wipe it.
    """
    prefs = load_prefs()
    prefs.update(changes)
    save_prefs(prefs)
    return prefs


def set_calendar_excluded(calendar_id: str, excluded: bool) -> None:
    excluded_ids = set(load_prefs().get("excluded_calendar_ids", []))
    if excluded:
        excluded_ids.add(calendar_id)
    else:
        excluded_ids.discard(calendar_id)
    update_prefs(excluded_calendar_ids=sorted(excluded_ids))


# ---------- display ----------
#
# This panel has no software backlight: it reports no DDC/CI (checked with ddcutil -
# "I2C slave address x37 is unresponsive") and HDMI outputs get no
# /sys/class/backlight entry. So "brightness" here darkens the image rather than the
# lamp, and there is a floor below which a lit backlight reads as grey haze instead
# of dark. Anything genuinely dark has to power the panel off, which is what the
# sleep stages below are for.

# Below about 0.2 the picture is mostly gone but the backlight still glows, so
# lower values buy nothing and only make the wall look broken.
MIN_BRIGHTNESS = 0.2

# Minutes of no interaction before the faint-clock stage. Night-gated by default -
# see SLEEP_AT_NIGHT_ONLY - because a kitchen calendar that hides itself at 2pm has
# stopped doing its job.
DEFAULT_SLEEP_AFTER_MINUTES = 10

# Minutes before the panel is powered off outright, handled by swayidle rather than
# by the page. 0 means never.
DEFAULT_DISPLAY_OFF_MINUTES = 40
ALLOWED_DISPLAY_OFF_MINUTES = (0, 30, 40, 60, 120)


def display_settings() -> dict:
    prefs = load_prefs()
    brightness = float(prefs.get("brightness", 1.0))
    off_after = int(prefs.get("display_off_minutes", DEFAULT_DISPLAY_OFF_MINUTES))
    return {
        "brightness": min(1.0, max(MIN_BRIGHTNESS, brightness)),
        "min_brightness": MIN_BRIGHTNESS,
        "sleep_enabled": bool(prefs.get("sleep_enabled", True)),
        "sleep_after_minutes": int(
            prefs.get("sleep_after_minutes", DEFAULT_SLEEP_AFTER_MINUTES)
        ),
        "sleep_at_night_only": bool(prefs.get("sleep_at_night_only", True)),
        "display_off_minutes": off_after
        if off_after in ALLOWED_DISPLAY_OFF_MINUTES
        else DEFAULT_DISPLAY_OFF_MINUTES,
        "allowed_display_off_minutes": list(ALLOWED_DISPLAY_OFF_MINUTES),
    }


def set_display_settings(**changes) -> dict:
    """Validate and store display settings. Unknown keys are ignored rather than
    stored, so a typo can't leave dead state in the prefs file."""
    updates = {}

    if "brightness" in changes:
        try:
            value = float(changes["brightness"])
        except (TypeError, ValueError):
            raise ValueError("brightness must be a number between 0 and 1")
        updates["brightness"] = min(1.0, max(MIN_BRIGHTNESS, value))

    if "sleep_enabled" in changes:
        updates["sleep_enabled"] = bool(changes["sleep_enabled"])

    if "sleep_at_night_only" in changes:
        updates["sleep_at_night_only"] = bool(changes["sleep_at_night_only"])

    if "sleep_after_minutes" in changes:
        try:
            minutes = int(changes["sleep_after_minutes"])
        except (TypeError, ValueError):
            raise ValueError("sleep_after_minutes must be a whole number of minutes")
        # Below a couple of minutes the wall would blank itself while someone is
        # still reading it.
        updates["sleep_after_minutes"] = min(120, max(2, minutes))

    if "display_off_minutes" in changes:
        try:
            minutes = int(changes["display_off_minutes"])
        except (TypeError, ValueError):
            raise ValueError("display_off_minutes must be a whole number of minutes")
        if minutes not in ALLOWED_DISPLAY_OFF_MINUTES:
            raise ValueError(
                "display_off_minutes must be one of "
                + ", ".join(str(m) for m in ALLOWED_DISPLAY_OFF_MINUTES)
            )
        updates["display_off_minutes"] = minutes

    if updates:
        update_prefs(**updates)
    return display_settings()


# Rail destinations that can be switched off from the System page. Kept to an
# explicit set so a typo in a POST can't hide a section nothing can turn back on,
# and so the Calendar (the reason the thing is on the wall) is not in the list.
HIDEABLE_SECTIONS = (
    "groceries", "recipes", "weather", "spotify", "browser", "today", "sports",
)


def hidden_sections() -> set[str]:
    stored = load_prefs().get("hidden_sections", [])
    return {name for name in stored if name in HIDEABLE_SECTIONS}


def set_section_hidden(section: str, hidden: bool) -> set[str]:
    if section not in HIDEABLE_SECTIONS:
        raise ValueError(f"{section!r} is not a hideable section")
    current = hidden_sections()
    if hidden:
        current.add(section)
    else:
        current.discard(section)
    update_prefs(hidden_sections=sorted(current))
    return current


def load_labels() -> dict:
    if not LABELS_FILE.exists():
        return {}
    return json.loads(LABELS_FILE.read_text())


def save_labels(labels: dict) -> None:
    LABELS_FILE.write_text(json.dumps(labels, indent=2))


def set_account_label(email: str, label: str) -> None:
    labels = load_labels()
    labels[email] = label
    save_labels(labels)
