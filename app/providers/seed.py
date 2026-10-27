"""Sample-data loaders for the sandbox. They fill an empty store with the fictional reviews and
ads. They take the store, not a provider, so the demo reset needs no provider handle."""


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
