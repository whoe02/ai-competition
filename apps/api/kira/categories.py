"""The vocabulary a transaction's category is drawn from.

One list, read by the API, the ledger's filter chips and — later — whatever
reads a receipt. Free text would let the same spending land under "Food",
"food" and "Makan", which no filter can put back together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

UNCATEGORISED = "uncategorised"


@dataclass(frozen=True, slots=True)
class Category:
    slug: str
    label: str


CATEGORIES: tuple[Category, ...] = (
    Category("food", "Food & drink"),
    Category("groceries", "Groceries"),
    Category("transport", "Transport"),
    Category("bills", "Bills & utilities"),
    Category("home", "Home"),
    Category("health", "Health"),
    Category("shopping", "Shopping"),
    Category("fun", "Fun"),
    Category("family", "Family & gifts"),
    Category("education", "Education"),
    Category("charity", "Charity"),
    Category("fees", "Fees & charges"),
    Category(UNCATEGORISED, "Uncategorised"),
)

_BY_SLUG = {category.slug: category for category in CATEGORIES}


def slugs() -> tuple[str, ...]:
    return tuple(_BY_SLUG)


def label_for(slug: str) -> str:
    """The human label, or a readable fallback for a slug written before this list."""
    known = _BY_SLUG.get(slug)
    if known is not None:
        return known.label
    return slug.replace("-", " ").replace("_", " ").capitalize()


# What the words people actually use point at. Ordered by category, matched on
# whole words only: "refunded" must not read as a fee, and "grabbed" must not
# read as a Grab ride.
_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("food", ("lunch", "dinner", "breakfast", "supper", "makan", "mamak", "kopitiam",
              "cafe", "coffee", "kopi", "teh", "nasi", "roti", "mee", "restaurant",
              "food", "snack", "bubble tea", "starbucks", "mcd", "kfc")),
    ("groceries", ("groceries", "grocery", "tesco", "lotus", "jaya grocer", "aeon",
                   "giant", "mydin", "village grocer", "market", "pasar")),
    ("transport", ("grab", "petrol", "fuel", "toll", "touch n go", "tng", "parking",
                   "taxi", "mrt", "lrt", "ktm", "bus", "train", "flight")),
    ("bills", ("bill", "astro", "unifi", "maxis", "celcom", "digi", "tnb", "electric",
               "water", "internet", "subscription", "netflix", "spotify", "insurance")),
    ("home", ("rent", "furniture", "ikea", "repair", "plumber", "cleaning")),
    ("health", ("clinic", "doctor", "dentist", "pharmacy", "panadol", "medicine",
                "hospital", "guardian", "watsons")),
    ("shopping", ("shopee", "lazada", "shirt", "shoes", "clothes", "uniqlo", "zalora")),
    ("fun", ("cinema", "movie", "gsc", "tgv", "concert", "game", "karaoke", "gym")),
    ("family", ("gift", "present", "angpow", "birthday", "wedding")),
    ("education", ("course", "tuition", "book", "class")),
    ("charity", ("donation", "donate", "zakat", "sedekah")),
    ("fees", ("fee", "charge", "interest", "stamp duty")),
)

_HINT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (slug, re.compile(r"\b(?:" + "|".join(re.escape(word) for word in words) + r")\b", re.I))
    for slug, words in _HINTS
)


def infer(text: str) -> str:
    """The category the words point at, or `uncategorised` when they point nowhere.

    A guess the user can see and correct beats a hardcoded slug they cannot.
    """
    for slug, pattern in _HINT_PATTERNS:
        if pattern.search(text):
            return slug
    return UNCATEGORISED
