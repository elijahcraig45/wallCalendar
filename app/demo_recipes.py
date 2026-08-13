"""Synthetic recipes for demo mode.

Shaped through `recipes_service._shape` from Firestore-style documents rather than
hand-written output, so the fixtures exercise the same type-unwrapping the live
path uses. One fixture deliberately carries `timerSeconds` on a step - the real
data has none yet, and the cooking view's one-tap timer needs the case covered.
"""


def _doc(recipe_id, fields):
    """Wraps plain Python back into Firestore's typed representation."""
    def wrap(value):
        if value is None:
            return {"nullValue": None}
        if isinstance(value, bool):
            return {"booleanValue": value}
        if isinstance(value, int):
            return {"integerValue": str(value)}
        if isinstance(value, float):
            return {"doubleValue": value}
        if isinstance(value, str):
            return {"stringValue": value}
        if isinstance(value, list):
            return {"arrayValue": {"values": [wrap(item) for item in value]}}
        if isinstance(value, dict):
            return {"mapValue": {"fields": {k: wrap(v) for k, v in value.items()}}}
        raise TypeError(type(value))

    return {
        "name": f"projects/demo/databases/(default)/documents/recipes/{recipe_id}",
        "fields": {key: wrap(value) for key, value in fields.items()},
    }


def _ingredient(name, amount, unit=""):
    return {"name": name, "amount": amount, "unit": unit, "section": None}


def _step(number, instruction, title=None, timer_seconds=None, timer_label=None):
    return {
        "stepNumber": number,
        "title": title,
        "instruction": instruction,
        "timerSeconds": timer_seconds,
        "timerLabel": timer_label,
        "ingredientsForStep": None,
    }


_DOCS = [
    _doc("demo-carbonara", {
        "title": "Weeknight Carbonara",
        "description": "Five ingredients, one pan, fifteen minutes.",
        "imageUrl": "",
        "servings": 4,
        "prepTimeMinutes": 5,
        "cookTimeMinutes": 15,
        "category": "Main Course",
        "cuisine": "Italian",
        "difficulty": 0,
        "tags": ["fast", "pantry"],
        "notes": "Pull the pan off the heat before the eggs go in or you get scrambled eggs.",
        "ingredients": [
            _ingredient("Spaghetti", "1", "lb"),
            _ingredient("Guanciale or pancetta", "6", "oz"),
            _ingredient("Egg yolks", "4"),
            _ingredient("Pecorino Romano, grated", "1", "cup"),
            _ingredient("Black pepper", "lots"),
        ],
        "steps": [
            _step(1, "Boil the pasta in well-salted water until just shy of al dente.",
                  title="Pasta", timer_seconds=540, timer_label="Pasta"),
            _step(2, "Render the guanciale in a cold pan over medium heat until crisp."),
            _step(3, "Whisk yolks with the cheese and a great deal of pepper."),
            _step(4, "Off the heat, toss pasta with the fat, then the egg mixture, "
                     "loosening with pasta water until glossy."),
        ],
    }),
    _doc("demo-sheetpan", {
        "title": "Sheet Pan Chicken and Broccoli",
        "description": "The one that happens on Tuesdays.",
        "imageUrl": "",
        "servings": 4,
        "prepTimeMinutes": 10,
        "cookTimeMinutes": 25,
        "category": "Main Course",
        "difficulty": 0,
        "tags": ["one pan"],
        "ingredients": [
            _ingredient("Chicken thighs", "2", "lb"),
            _ingredient("Broccoli, in florets", "1", "head"),
            _ingredient("Olive oil", "3", "tbsp"),
            _ingredient("Lemon", "1"),
        ],
        "steps": [
            _step(1, "Heat the oven to 425°F."),
            _step(2, "Toss everything with oil, salt and pepper on a sheet pan.",
                  timer_seconds=1500, timer_label="Roast"),
            _step(3, "Roast until the chicken reads 175°F and the broccoli has char."),
        ],
    }),
    _doc("demo-cookies", {
        "title": "Brown Butter Chocolate Chip Cookies",
        "description": "Worth browning the butter for.",
        "imageUrl": "",
        "servings": 24,
        "prepTimeMinutes": 30,
        "cookTimeMinutes": 12,
        "category": "Dessert",
        "difficulty": 1,
        "tags": ["baking"],
        "ingredients": [
            _ingredient("Butter", "1", "cup"),
            _ingredient("Brown sugar", "1 1/4", "cups"),
            _ingredient("Bread flour", "2 1/4", "cups"),
            _ingredient("Dark chocolate, chopped", "8", "oz"),
            _ingredient("Flaky salt", "for finishing"),
        ],
        "steps": [
            _step(1, "Brown the butter until it smells like toffee, then cool it."),
            _step(2, "Cream with sugars, add eggs, then dry ingredients."),
            _step(3, "Rest the dough overnight if you can bear to."),
            _step(4, "Bake at 375°F until the edges set but the middles look underdone.",
                  timer_seconds=720, timer_label="Bake"),
        ],
    }),
    _doc("demo-soup", {
        "title": "Lentil Soup with Lemon",
        "description": "Cheap, fast, and better the next day.",
        "imageUrl": "",
        "servings": 6,
        "prepTimeMinutes": 10,
        "cookTimeMinutes": 35,
        "category": "Soup",
        "difficulty": 0,
        "tags": ["vegetarian", "make ahead"],
        "ingredients": [
            _ingredient("Brown lentils", "2", "cups"),
            _ingredient("Onion, diced", "1"),
            _ingredient("Carrots, diced", "2"),
            _ingredient("Cumin", "2", "tsp"),
            _ingredient("Lemon", "1"),
        ],
        "steps": [
            _step(1, "Sweat the onion and carrot until soft."),
            _step(2, "Add lentils, cumin and 8 cups water; simmer until tender.",
                  timer_seconds=2100, timer_label="Simmer"),
            _step(3, "Finish with lemon juice, and more salt than you think."),
        ],
    }),
]


def get_recipes() -> dict:
    from app import recipes_service

    recipes = [recipes_service._shape(doc) for doc in _DOCS]
    recipes.sort(key=lambda recipe: recipe["title"].lower())
    return {
        "recipes": recipes,
        "categories": sorted({r["category"] for r in recipes if r["category"]}),
        "stale": False,
        "errors": [],
    }
