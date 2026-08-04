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


def set_calendar_excluded(calendar_id: str, excluded: bool) -> None:
    prefs = load_prefs()
    excluded_ids = set(prefs.get("excluded_calendar_ids", []))
    if excluded:
        excluded_ids.add(calendar_id)
    else:
        excluded_ids.discard(calendar_id)
    save_prefs({"excluded_calendar_ids": sorted(excluded_ids)})


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
