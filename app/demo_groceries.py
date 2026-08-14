"""Synthetic grocery list for demo mode.

Writes are faked rather than refused, matching demo_spotify's reasoning: there is
no real list to corrupt, and a shopping list is only testable if ticking an item
actually ticks it. State lives in the process and resets with the server.

The fixture deliberately spans several aisles and carries one already-ticked item,
because the two things most worth checking on this page are that it groups in store
order and that done items sink rather than disappear.
"""

import itertools

from app.groceries_service import (
    _aisle_for,
    _canonical_name,
    _group,
    _split_amount,
    _sort_key,
    AISLE_LABELS,
)

_counter = itertools.count(100)


def _item(item_id, display, aisle, quantity="", done=False, sources=()):
    return {
        "id": item_id,
        "display": display,
        "canonical_name": _canonical_name(display),
        "aisle": aisle,
        "aisle_label": AISLE_LABELS[aisle],
        "quantity_label": quantity,
        "source_titles": list(sources),
        "done": done,
    }


# Sized and shaped like a real weekly shop - around thirty lines spread over most
# of the aisles - rather than the handful it takes to prove the code works. A
# twelve-item fixture made the page look two-thirds empty at 1920x1080 and invited
# tuning the layout to fill space it would not have in real use. Deliberately
# contains no "cucumbers": the add-an-item test types those, and it can only assert
# what add did if the fixture doesn't already supply them.
_items = [
    _item("demo-1", "lemons", "produce", "4"),
    _item("demo-2", "baby spinach", "produce", "1 bunch", sources=["Lemon Orzo"]),
    _item("demo-3", "garlic", "produce", "3 cloves", sources=["Lemon Orzo"]),
    _item("demo-4", "yellow onions", "produce", "3"),
    _item("demo-5", "roma tomatoes", "produce", "6"),
    _item("demo-6", "avocados", "produce", "2"),
    _item("demo-7", "bananas", "produce", "1 bunch"),
    _item("demo-8", "sourdough loaf", "bakery"),
    _item("demo-9", "flour tortillas", "bakery", "1 package"),
    _item("demo-10", "chicken thighs", "meat", "2 lb", sources=["Weeknight Traybake"]),
    _item("demo-11", "bacon", "meat", "1 package"),
    _item("demo-12", "salmon fillets", "seafood", "2", sources=["Friday Salmon"]),
    _item("demo-13", "whole milk", "dairy", "1 gal"),
    _item("demo-14", "parmesan", "dairy", "200 g", sources=["Lemon Orzo"]),
    _item("demo-15", "greek yogurt", "dairy", "32 oz"),
    _item("demo-16", "butter", "dairy", "1 lb"),
    _item("demo-17", "frozen peas", "frozen", "1 bag"),
    _item("demo-18", "ice cream", "frozen"),
    _item("demo-19", "orzo", "pantry", "1 lb", sources=["Lemon Orzo"]),
    _item("demo-20", "olive oil", "pantry"),
    _item("demo-21", "chicken stock", "pantry", "2 cartons", sources=["Weeknight Traybake"]),
    _item("demo-22", "black beans", "pantry", "2 cans"),
    _item("demo-23", "smoked paprika", "spices", sources=["Weeknight Traybake"]),
    _item("demo-24", "bay leaves", "spices"),
    _item("demo-25", "coffee beans", "drinks", "12 oz"),
    _item("demo-26", "sparkling water", "drinks", "1 case"),
    _item("demo-27", "paper towels", "household"),
    _item("demo-28", "parchment paper", "household"),
    # Already in the trolley: these have to sink to the bottom, not vanish.
    _item("demo-29", "eggs", "dairy", "1 dozen", done=True),
    _item("demo-30", "russet potatoes", "produce", "5 lb", done=True),
]


def get_groceries() -> dict:
    items = sorted((dict(item) for item in _items), key=_sort_key)
    return {
        "items": items,
        "groups": _group(items),
        "available": True,
        "configured": True,
        "open_count": sum(1 for item in items if not item["done"]),
        "done_count": sum(1 for item in items if item["done"]),
        "errors": [],
    }


def add_item(text: str) -> dict:
    quantity, name = _split_amount(text)
    canonical = _canonical_name(name)
    aisle = _aisle_for(canonical)
    item = {
        "id": f"demo-{next(_counter)}",
        "display": name,
        "canonical_name": canonical,
        "aisle": aisle,
        "aisle_label": AISLE_LABELS[aisle],
        "quantity_label": quantity,
        "source_titles": [],
        "done": False,
    }
    _items.append(item)
    return dict(item)


def set_done(item_id: str, done: bool) -> dict:
    for item in _items:
        if item["id"] == item_id:
            item["done"] = done
            return dict(item)
    raise ValueError(f"No demo item {item_id}")


def remove(item_id: str) -> None:
    global _items
    _items = [item for item in _items if item["id"] != item_id]


def clear_done() -> int:
    global _items
    before = len(_items)
    _items = [item for item in _items if not item["done"]]
    return before - len(_items)
