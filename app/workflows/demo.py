"""Demo controls (only reachable when DEMO_CONTROLS=1)."""
from ..providers.seed import seed_ads, seed_reviews


def demo_reset(rt, reviews: list[dict], ads: list[dict] = ()) -> None:
    with rt.store.tx():
        for t in ("proposals", "events", "writes", "reviews", "ads", "images"):
            rt.store.run(f"DELETE FROM {t}")
        rt.store.run("DELETE FROM sqlite_sequence WHERE name='events'")
    seed_reviews(rt.store, reviews)
    seed_ads(rt.store, list(ads))


def demo_tamper(rt, on: bool) -> dict:
    """Edit the text of audit entry 2 behind the app's back, to show the chain check catching it."""
    suffix = " (edited)"
    if on:
        rt.store.run("UPDATE events SET plain = plain || ? WHERE seq=2 AND plain NOT LIKE ?", (suffix, "%" + suffix))
    else:
        rt.store.run("UPDATE events SET plain = substr(plain, 1, length(plain) - ?) WHERE seq=2 AND plain LIKE ?", (len(suffix), "%" + suffix))
    return {"tampered": bool(rt.store.one("SELECT 1 FROM events WHERE seq=2 AND plain LIKE ?", ("%" + suffix,)))}
