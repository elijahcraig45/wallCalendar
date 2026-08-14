"""The household grocery list, read and written straight out of Daisy's Kitchen.

Same database as recipes_service, and deliberately nothing like it in how it
authenticates. Recipes are `allow read: if true`, so that module is a keyless
HTTPS GET. Grocery lists are not: their rules are

    allow read, write: if signedIn() && sharesHousehold(listHousehold());

so an unauthenticated request is refused outright. This module therefore uses a
**service account** on the recipes project, whose token is admin access - Firestore
rules do not apply to it at all, which is why no household membership, user
document or Firebase Auth user has to be created for the wall.

Setup (one time, as elijahcraig45@gmail.com):

    gcloud iam service-accounts create wall-calendar \\
        --project recipe-f644f --display-name "Wall calendar"
    gcloud projects add-iam-policy-binding recipe-f644f \\
        --member serviceAccount:wall-calendar@recipe-f644f.iam.gserviceaccount.com \\
        --role roles/datastore.user
    gcloud iam service-accounts keys create \\
        secrets/recipes_service_account.json \\
        --iam-account wall-calendar@recipe-f644f.iam.gserviceaccount.com \\
        --project recipe-f644f

Then back the key up to the private wallCalendar-secrets repo. Until it exists the
page renders an explained "not set up" state rather than an error, so the wall is
never worse off for the feature being half-configured.

Reads need no ingredient parsing: the app stores `aisle` and a pre-rendered
`quantityLabel` on every item specifically so other clients - this one - can show
the list without porting the Dart parser. Adding an item by hand is the one path
that does need it; see `_canonical_name` and the drift test in tests/api_checks.py.
"""

import datetime as dt
import re
import time

import requests

from app.config import DEMO_MODE, GROCERY_HOUSEHOLD_ID, GROCERY_SA_FILE, RECIPES_PROJECT_ID

# Admin access to Firestore. `datastore` is the scope Firestore uses; there is no
# separate firestore one.
SCOPES = ["https://www.googleapis.com/auth/datastore"]
BASE = (
    f"https://firestore.googleapis.com/v1/projects/{RECIPES_PROJECT_ID}"
    "/databases/(default)/documents"
)
TIMEOUT_SECONDS = 10
PAGE_SIZE = 300

# The app's own aisle order, so the wall walks the shop in the same direction the
# phone does. Mirrored from IngredientParser.aisleOrder.
AISLE_ORDER = [
    "produce", "bakery", "meat", "seafood", "dairy", "frozen",
    "pantry", "spices", "drinks", "household", "other",
]
AISLE_LABELS = {
    "produce": "Produce",
    "bakery": "Bakery",
    "meat": "Meat",
    "seafood": "Seafood",
    "dairy": "Dairy",
    "frozen": "Frozen",
    "pantry": "Pantry",
    "spices": "Spices",
    "drinks": "Drinks",
    "household": "Household",
    "other": "Other",
}


class GroceriesNotConfigured(RuntimeError):
    """No service-account key yet. Carries the setup instruction rather than
    surfacing as a generic failure, because this is the expected state on a fresh
    install and the fix is a documented command, not debugging."""


class GroceriesUnavailable(RuntimeError):
    """Something transient - network, Firestore refusing, no list to read."""


_credentials = None
_household_cache: tuple[float, str] | None = None
HOUSEHOLD_CACHE_TTL_SECONDS = 600


def _token() -> str:
    global _credentials

    if not GROCERY_SA_FILE.exists():
        raise GroceriesNotConfigured(
            "The grocery list needs a service-account key for the recipes project. "
            "See app/groceries_service.py for the three gcloud commands that create it."
        )

    if _credentials is None:
        # Imported here rather than at module scope: without a key file this module
        # still has to import cleanly so /today and the API can report the state.
        from google.oauth2 import service_account

        try:
            _credentials = service_account.Credentials.from_service_account_file(
                str(GROCERY_SA_FILE), scopes=SCOPES
            )
        except (ValueError, KeyError) as exc:
            raise GroceriesNotConfigured(
                f"The service-account key at {GROCERY_SA_FILE.name} is not readable "
                f"as one ({type(exc).__name__})."
            ) from exc

    if not _credentials.valid:
        from google.auth.transport.requests import Request

        try:
            _credentials.refresh(Request())
        except Exception as exc:  # noqa: BLE001 - google.auth raises broadly
            raise GroceriesUnavailable(
                f"Couldn't get a Firestore token ({type(exc).__name__})."
            ) from exc
    return _credentials.token


def _call(method: str, path: str, **kwargs) -> dict:
    try:
        response = requests.request(
            method,
            f"{BASE}/{path}",
            headers={"Authorization": f"Bearer {_token()}"},
            timeout=TIMEOUT_SECONDS,
            **kwargs,
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        if status in (401, 403):
            raise GroceriesUnavailable(
                "Firestore refused the wall's credential. Check the service account "
                "still has roles/datastore.user on the recipes project."
            ) from exc
        raise GroceriesUnavailable(f"Firestore returned {status}.") from exc
    except requests.exceptions.RequestException as exc:
        raise GroceriesUnavailable(f"Couldn't reach Firestore ({type(exc).__name__}).") from exc
    return response.json() if response.content else {}


def _unwrap(value: dict):
    """Firestore REST type tags, flattened. Same job as recipes_service._unwrap;
    kept separate rather than shared because the two modules have no other reason
    to depend on each other and this one handles timestamps it actually reads."""
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
        return {k: _unwrap(v) for k, v in value["mapValue"].get("fields", {}).items()}
    return None


def _household_id() -> str:
    """Which list to read.

    Configured explicitly when set, otherwise discovered - a project with exactly
    one grocery list needs no configuration, and that is the shape of this
    household. Two or more and it refuses to guess, because silently showing the
    wrong family's list is worse than asking for a config value.
    """
    global _household_cache

    if GROCERY_HOUSEHOLD_ID:
        return GROCERY_HOUSEHOLD_ID

    now = time.monotonic()
    if _household_cache and (now - _household_cache[0]) < HOUSEHOLD_CACHE_TTL_SECONDS:
        return _household_cache[1]

    payload = _call("GET", "groceryLists", params={"pageSize": 10})
    lists = payload.get("documents", [])
    if not lists:
        raise GroceriesUnavailable(
            "No grocery list exists yet. Add something to the list in Daisy's Kitchen "
            "first and it will appear here."
        )
    if len(lists) > 1:
        raise GroceriesUnavailable(
            "This project has more than one household list, so the wall can't tell "
            "which is yours. Set WALLCAL_HOUSEHOLD_ID in .env."
        )

    household = lists[0]["name"].rsplit("/", 1)[-1]
    _household_cache = (now, household)
    return household


def _shape(document: dict) -> dict:
    fields = {key: _unwrap(value) for key, value in document.get("fields", {}).items()}
    aisle = fields.get("aisle") or "other"
    return {
        "id": document["name"].rsplit("/", 1)[-1],
        "display": fields.get("display") or "",
        "canonical_name": fields.get("canonicalName") or "",
        # An aisle this wall doesn't know about must still be groupable rather than
        # vanishing, so an unrecognised value falls into Other.
        "aisle": aisle if aisle in AISLE_LABELS else "other",
        "aisle_label": AISLE_LABELS.get(aisle, AISLE_LABELS["other"]),
        "quantity_label": fields.get("quantityLabel") or "",
        "source_titles": fields.get("sourceTitles") or [],
        "done": bool(fields.get("done")),
    }


def _sort_key(item: dict) -> tuple:
    # Exactly GroceryService.watchItems' ordering: unticked first, then store order,
    # then alphabetical. Done items sink rather than disappear - "did I get that?"
    # is a question people ask a list.
    return (item["done"], AISLE_ORDER.index(item["aisle"]), item["display"].lower())


def _fetch_items(household: str) -> list[dict]:
    items, page_token = [], None
    while True:
        params = {"pageSize": PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token
        payload = _call("GET", f"groceryLists/{household}/items", params=params)
        items.extend(_shape(doc) for doc in payload.get("documents", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return items


def get_groceries() -> dict:
    """Never raises. A shopping list being unreachable must not take the Today page
    down, so failures come back in the payload for the UI to explain in place."""
    if DEMO_MODE:
        from app import demo_groceries

        return demo_groceries.get_groceries()

    try:
        household = _household_id()
        items = sorted(_fetch_items(household), key=_sort_key)
    except (GroceriesNotConfigured, GroceriesUnavailable) as exc:
        return {
            "items": [],
            "groups": [],
            "available": False,
            "configured": not isinstance(exc, GroceriesNotConfigured),
            "open_count": 0,
            "done_count": 0,
            "errors": [str(exc)],
        }

    return {
        "items": items,
        "groups": _group(items),
        "available": True,
        "configured": True,
        "open_count": sum(1 for item in items if not item["done"]),
        "done_count": sum(1 for item in items if item["done"]),
        "errors": [],
    }


def _group(items: list[dict]) -> list[dict]:
    """Aisle groups in store order, built server-side so every client that reads
    this endpoint groups identically. Only aisles with something in them appear."""
    groups = []
    for aisle in AISLE_ORDER:
        members = [item for item in items if item["aisle"] == aisle and not item["done"]]
        if members:
            groups.append({"aisle": aisle, "label": AISLE_LABELS[aisle], "items": members})
    return groups


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def set_done(item_id: str, done: bool) -> dict:
    """Ticks an item off, and records the purchase.

    The history write mirrors GroceryService.setDone rather than being optional:
    that collection is what a "you usually buy this weekly" suggestion gets built
    from later, and it can only ever be collected forwards. A wall that ticked
    items off without recording them would punch holes in it.
    """
    if DEMO_MODE:
        from app import demo_groceries

        return demo_groceries.set_done(item_id, done)

    household = _household_id()
    path = f"groceryLists/{household}/items/{item_id}"
    updated = _call(
        "PATCH",
        path,
        params=[
            ("updateMask.fieldPaths", "done"),
            ("updateMask.fieldPaths", "doneAt"),
        ],
        json={
            "fields": {
                "done": {"booleanValue": done},
                "doneAt": {"timestampValue": _now()} if done else {"nullValue": None},
            }
        },
    )

    item = _shape(updated)

    # Guarded on a non-empty canonical name rather than just on `done`.
    #
    # This reads the name out of the PATCH response, which assumes Firestore echoes
    # the whole document back and not only the updateMask paths. It should - no
    # `mask` parameter is sent - but an empty name here would write a history row
    # keyed on "", and that collection is the one thing in this module that can be
    # silently CORRUPTED rather than merely fail: the spec collects it forward for a
    # later "you usually buy this weekly" suggestion, so it can never be
    # backfilled. Skipping one row is recoverable; a collection of empty keys is not.
    if done and item["canonical_name"]:
        try:
            _call(
                "POST",
                f"groceryHistory/{household}/purchases",
                json={
                    "fields": {
                        "canonicalName": {"stringValue": item["canonical_name"]},
                        "doneAt": {"timestampValue": _now()},
                    }
                },
            )
        except GroceriesUnavailable:
            # The tick is what the person asked for and it already succeeded.
            # Losing one history row is not worth failing that back to them.
            pass

    return item


def remove(item_id: str) -> None:
    if DEMO_MODE:
        from app import demo_groceries

        return demo_groceries.remove(item_id)

    _call("DELETE", f"groceryLists/{_household_id()}/items/{item_id}")


def clear_done() -> int:
    """Clears everything already ticked off, in one commit - a half-cleared list
    after a dropped connection would be confusing. Mirrors GroceryService.clearDone."""
    if DEMO_MODE:
        from app import demo_groceries

        return demo_groceries.clear_done()

    household = _household_id()
    done = [item for item in _fetch_items(household) if item["done"]]
    if not done:
        return 0

    prefix = (
        f"projects/{RECIPES_PROJECT_ID}/databases/(default)/documents"
        f"/groceryLists/{household}/items"
    )
    # :commit sits on the database, not on a document path, so it can't go through
    # _call's documents-rooted URL.
    try:
        response = requests.post(
            f"https://firestore.googleapis.com/v1/projects/{RECIPES_PROJECT_ID}"
            "/databases/(default)/documents:commit",
            headers={"Authorization": f"Bearer {_token()}"},
            json={"writes": [{"delete": f"{prefix}/{item['id']}"} for item in done]},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise GroceriesUnavailable(
            f"Couldn't clear the finished items ({type(exc).__name__})."
        ) from exc
    return len(done)


# ---------- adding an item by hand ----------
#
# The one path that needs the Dart parser's logic. Ported rather than approximated,
# because the canonical name is the key `GroceryService.addRecipe` merges on: a
# Python answer that disagreed with Dart's would put a second "tomato" row on the
# list instead of merging into the existing one. tests/api_checks.py pins this port
# against the Dart source when the recipes repo is checked out beside this one.

NEVER_SINGULARISE = {
    "molasses", "couscous", "hummus", "asparagus", "greens", "oats", "chives",
    "grits", "sprouts", "brussels", "peas", "lentils", "capers", "noodles",
}

AISLE_KEYWORDS = {
    "produce": ["lettuce", "spinach", "kale", "tomato", "onion", "garlic", "potato",
                "carrot", "celery", "cucumber", "apple", "banana", "lemon", "lime",
                "orange", "berry", "berries", "avocado", "mushroom", "broccoli", "zucchini",
                "squash", "herb", "parsley", "cilantro", "basil", "ginger", "scallion",
                "shallot", "corn", "bean sprout", "cabbage", "peach", "pear", "grape",
                "bell pepper"],
    "bakery": ["bread", "bun", "roll", "tortilla", "pita", "bagel", "baguette",
               "breadcrumb", "panko", "croissant"],
    "meat": ["chicken", "beef", "pork", "lamb", "turkey", "bacon", "sausage", "ham",
             "mince", "steak", "ground beef", "ground chicken", "ground pork",
             "ground turkey", "ground lamb"],
    "seafood": ["salmon", "tuna", "shrimp", "prawn", "cod", "tilapia", "fish", "scallop",
                "crab", "lobster", "anchovy"],
    "dairy": ["milk", "butter", "cheese", "yogurt", "yoghurt", "cream", "egg",
              "parmesan", "pecorino", "mozzarella", "cheddar", "feta", "ricotta",
              "mascarpone"],
    "frozen": ["frozen", "ice cream", "puff pastry"],
    "pantry": ["flour", "sugar", "rice", "pasta", "orzo", "oat", "oil", "vinegar",
               "stock", "broth", "sauce", "tomato paste", "bean", "lentil", "chickpea",
               "honey", "syrup", "chocolate", "cocoa", "vanilla", "yeast",
               "baking powder", "baking soda", "cornstarch", "nut", "almond", "walnut",
               "pecan", "peanut", "raisin", "coconut", "noodle", "quinoa", "couscous",
               "molasses", "jam", "mustard", "mayonnaise", "ketchup", "soy sauce",
               "canned", "tuna can"],
    "spices": ["salt", "pepper", "cinnamon", "cumin", "paprika", "oregano", "thyme",
               "rosemary", "chili", "chilli", "curry", "turmeric", "nutmeg", "clove",
               "bay leaf", "seasoning", "spice"],
    "drinks": ["water", "juice", "wine", "beer", "coffee", "tea", "soda"],
    "household": ["foil", "parchment", "wrap", "bag", "towel"],
}

# "2 lb", "1 1/2 cups", "3/4 tsp" - enough to split a quantity off the front of
# something typed by a person. Anything it can't read is treated as all name,
# which lists the item unquantified rather than mangling it.
_AMOUNT = re.compile(
    r"^\s*(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*"
    r"([a-zA-Z]+\.?)?\s+(.*)$"
)
_UNITS = {
    "cup", "cups", "c", "tbsp", "tbsps", "tablespoon", "tablespoons", "tsp", "tsps",
    "teaspoon", "teaspoons", "oz", "ounce", "ounces", "lb", "lbs", "pound", "pounds",
    "g", "gram", "grams", "kg", "ml", "l", "liter", "liters", "litre", "litres",
    "clove", "cloves", "can", "cans", "pinch", "slice", "slices", "bunch", "bunches",
    "package", "packages", "pkg", "stick", "sticks", "head", "heads", "sprig", "sprigs",
}


def _singularise(text: str) -> str:
    words = text.split(" ")
    if not words:
        return text
    last = words[-1]
    if last in NEVER_SINGULARISE or len(last) <= 3:
        return text
    if last.endswith("ies"):
        words[-1] = last[:-3] + "y"
    elif last.endswith("es") and not last.endswith("ses"):
        words[-1] = last[:-2]
    elif last.endswith("s") and not last.endswith("ss"):
        words[-1] = last[:-1]
    return " ".join(words)


def _canonical_name(name: str) -> str:
    text = name.lower().strip()
    text = re.sub(r"\([^)]*\)", " ", text)
    # Everything after a comma is preparation, not identity: "onion, finely chopped".
    comma = text.find(",")
    if comma > 0:
        text = text[:comma]
    text = re.sub(r"\b(for|to)\s+(the\s+)?\w+$", " ", text)
    text = re.sub(r"[*†]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return _singularise(text)


def _aisle_for(canonical: str) -> str:
    for aisle in AISLE_ORDER:
        for keyword in AISLE_KEYWORDS.get(aisle, []):
            if keyword in canonical:
                return aisle
    return "other"


def _split_amount(text: str) -> tuple[str, str]:
    """(quantity_label, name). Only treats the leading word as a unit if it looks
    like one - "2 lemons" must keep "lemons" as the name, not read it as a unit."""
    match = _AMOUNT.match(text)
    if not match:
        return "", text.strip()

    number, unit, rest = match.group(1), match.group(2), match.group(3)
    if unit and unit.lower().rstrip(".") in _UNITS:
        return f"{number} {unit.lower().rstrip('.')}".strip(), rest.strip()
    # No unit: the second token was part of the name.
    name = f"{unit} {rest}".strip() if unit else rest.strip()
    return number, name


def add_item(text: str) -> dict:
    """Adds a typed line, e.g. "2 lemons" or just "milk"."""
    text = (text or "").strip()
    if not text:
        raise GroceriesUnavailable("An item needs some text.")

    if DEMO_MODE:
        from app import demo_groceries

        return demo_groceries.add_item(text)

    quantity, name = _split_amount(text)
    canonical = _canonical_name(name)
    if not canonical:
        raise GroceriesUnavailable("An item needs some text.")

    household = _household_id()
    created = _call(
        "POST",
        f"groceryLists/{household}/items",
        json={
            "fields": {
                "display": {"stringValue": name},
                "canonicalName": {"stringValue": canonical},
                "quantityLabel": {"stringValue": quantity},
                "aisle": {"stringValue": _aisle_for(canonical)},
                "sourceTitles": {"arrayValue": {"values": []}},
                # The app re-combines quantities from `raw` rather than from the
                # rendered label, so a wall-added item has to carry it too or a
                # later recipe add would drop this amount.
                "raw": {"arrayValue": {"values": [{"stringValue": text}]}},
                "done": {"booleanValue": False},
                "addedAt": {"timestampValue": _now()},
            }
        },
    )
    return _shape(created)
