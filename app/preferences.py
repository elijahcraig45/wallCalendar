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


# Rail destinations that can be switched off from the System page. Kept to an
# explicit set so a typo in a POST can't hide a section nothing can turn back on,
# and so the Calendar (the reason the thing is on the wall) is not in the list.
HIDEABLE_SECTIONS = ("groceries", "recipes", "weather", "spotify", "browser", "today")


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
