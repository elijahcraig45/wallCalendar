"""Recipes, read straight out of Daisy's Kitchen (github.com/elijahcraig45/daisys-kitchen).

That app's `firestore.rules` grants `allow read: if true` on the recipes
collection, so this needs no auth at all - no service account, no API key, no
Firebase SDK, nothing to keep in secrets/. It's a plain HTTPS GET.

Reading the source of truth directly, rather than framing the deployed Flutter
app, is what makes a wall-appropriate presentation possible: big type, a
hands-free cooking mode, and steps that can start a kitchen timer. The framed app
stays available on the Web page as a fallback.
"""

import time

import requests

from app.config import DEMO_MODE, RECIPES_PROJECT_ID

BASE_URL = "https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/recipes"
TIMEOUT_SECONDS = 10
CACHE_TTL_SECONDS = 1800   # recipes change rarely; no reason to refetch often
ERROR_CACHE_TTL_SECONDS = 120

_cache: tuple[float, dict] | None = None
_last_good: dict | None = None

# Flutter stores DifficultyLevel as an enum index; older documents may carry the
# name. Handle both rather than guessing which one this database uses.
_DIFFICULTY = {0: "Easy", 1: "Medium", 2: "Hard"}


def _unwrap(value: dict):
    """Firestore REST wraps every value in a type tag. This flattens the whole
    tree back into plain Python, so the rest of the module never has to think
    about stringValue/mapValue again."""
    if "stringValue" in value:
        return value["stringValue"]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "booleanValue" in value:
        return value["booleanValue"]
    if "timestampValue" in value:
        return value["timestampValue"]
    if "nullValue" in value:
        return None
    if "arrayValue" in value:
        return [_unwrap(item) for item in value["arrayValue"].get("values", [])]
    if "mapValue" in value:
        return {key: _unwrap(item) for key, item in value["mapValue"].get("fields", {}).items()}
    # Unknown tag (geoPoint, bytesValue, reference...) - nothing here uses them,
    # and dropping the value beats raising on an unexpected field.
    return None


def _difficulty(raw) -> str | None:
    if isinstance(raw, int):
        return _DIFFICULTY.get(raw)
    if isinstance(raw, str) and raw:
        return raw.replace("DifficultyLevel.", "").capitalize()
    return None


def _shape(document: dict) -> dict:
    fields = {key: _unwrap(value) for key, value in document.get("fields", {}).items()}
    prep = fields.get("prepTimeMinutes") or 0
    cook = fields.get("cookTimeMinutes") or 0

    steps = []
    for index, step in enumerate(fields.get("steps") or []):
        if not isinstance(step, dict):
            continue
        steps.append(
            {
                "number": step.get("stepNumber") or index + 1,
                "title": step.get("title") or None,
                "instruction": step.get("instruction") or "",
                # The schema already carries these; they're mostly unset today, but
                # when present the cooking view offers a one-tap timer.
                "timer_seconds": step.get("timerSeconds"),
                "timer_label": step.get("timerLabel"),
            }
        )
    steps.sort(key=lambda s: s["number"])

    ingredients = []
    for item in fields.get("ingredients") or []:
        if not isinstance(item, dict):
            continue
        amount = " ".join(part for part in [str(item.get("amount") or ""), item.get("unit") or ""] if part.strip())
        ingredients.append({"name": item.get("name") or "", "amount": amount.strip()})

    return {
        "id": document["name"].rsplit("/", 1)[-1],
        "title": fields.get("title") or "(untitled)",
        "description": fields.get("description") or "",
        "image": fields.get("imageUrl") or None,
        "servings": fields.get("servings"),
        "prep_minutes": prep or None,
        "cook_minutes": cook or None,
        "total_minutes": (prep + cook) or None,
        "category": fields.get("category") or None,
        "cuisine": fields.get("cuisine") or None,
        "difficulty": _difficulty(fields.get("difficulty")),
        "tags": [tag for tag in (fields.get("tags") or []) if tag],
        "notes": fields.get("notes") or None,
        "source": fields.get("source") or None,
        "ingredients": ingredients,
        "steps": steps,
    }


def _fetch() -> dict:
    recipes, page_token = [], None
    while True:
        response = requests.get(
            BASE_URL.format(project=RECIPES_PROJECT_ID),
            params={"pageSize": 100, **({"pageToken": page_token} if page_token else {})},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        recipes.extend(_shape(doc) for doc in payload.get("documents", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break

    recipes.sort(key=lambda r: r["title"].lower())
    categories = sorted({r["category"] for r in recipes if r["category"]})
    return {"recipes": recipes, "categories": categories, "errors": []}


def get_recipes() -> dict:
    """Never raises, for the same reason weather doesn't: a cookbook being
    unreachable must not be able to take a page down."""
    global _cache, _last_good

    if DEMO_MODE:
        from app import demo_recipes

        return demo_recipes.get_recipes()

    now = time.monotonic()
    if _cache is not None:
        ttl = ERROR_CACHE_TTL_SECONDS if _cache[1].get("errors") else CACHE_TTL_SECONDS
        if (now - _cache[0]) < ttl:
            return _cache[1]

    try:
        result = _fetch()
        result["stale"] = False
        _last_good = result
    except Exception as exc:  # noqa: BLE001 - see docstring
        message = f"Couldn't reach the recipe library ({type(exc).__name__})."
        if _last_good is not None:
            result = {**_last_good, "stale": True, "errors": [message]}
        else:
            result = {"recipes": [], "categories": [], "stale": False, "errors": [message]}

    _cache = (now, result)
    return result
