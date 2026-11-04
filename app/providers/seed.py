"""Sample-data loaders for the sandbox. They fill an empty store with the fictional reviews and
ads. They take the store, not a provider, so the demo reset needs no provider handle."""
import json
from pathlib import Path

NEW_REVIEWS = Path(__file__).resolve().parent.parent / "fixtures" / "new_reviews.json"


def load_new_reviews() -> list[dict]:
    """The made-up pool that 'Check for new reviews' draws from, in the order it is handed out."""
    return json.loads(NEW_REVIEWS.read_text(encoding="utf-8"))["reviews"]


def add_review(store, r: dict) -> None:
    """Add one review the same way seeding does. It goes to the top of the list (newest first).
    The caller wraps this and its audit entry in one transaction."""
    with store.tx():
        top = store.one("SELECT COALESCE(MIN(ord), 0) m FROM reviews")["m"]
        store.run(
            "INSERT INTO reviews (id, ord, platform, stars, who, date, text, reply) VALUES (?,?,?,?,?,?,?,?)",
            (r["id"], top - 1, r["platform"], r["stars"], r["who"], r["date"], r["text"], r.get("reply")),
        )


def seed_reviews(store, reviews: list[dict]) -> None:
    with store.tx():
        if store.one("SELECT 1 FROM reviews LIMIT 1"):
            return
        for i, r in enumerate(reviews):
            store.run(
                "INSERT INTO reviews (id, ord, platform, stars, who, date, text, reply) VALUES (?,?,?,?,?,?,?,?)",
                (r["id"], i, r["platform"], r["stars"], r["who"], r["date"], r["text"], r.get("reply")),
            )


def seed_ads(store, ads: list[dict]) -> None:
    with store.tx():
        if store.one("SELECT 1 FROM ads LIMIT 1"):
            return
        for a in ads:
            store.run("INSERT INTO ads (name, status, headline, text, image_sha, format) VALUES (?,?,?,?,?,?)",
                      (a["name"], "paused", a["headline"], a["text"], None, a.get("format", "wide")))
