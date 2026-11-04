"""'Check for new reviews': hand out the next made-up review from the pool, at most one per call.
No Muse call happens here. The reply is drafted later by the normal flow when the page asks for it,
and the new review text reaches Muse only through the labelled read tool, like every other review."""
from ..providers.seed import add_review, load_new_reviews

WAITING_LIMIT = 3   # at this many unanswered reviews, no new one is added

FOUND = "Found a new review."
WAIT_FIRST = "Reply to the ones waiting first."
NONE_LEFT = "No new reviews right now."


def waiting_count(rt) -> int:
    """Reviews with no reply yet. A Yelp reply the person approved (to paste into Yelp) counts as answered."""
    return rt.store.one(
        "SELECT COUNT(*) n FROM reviews r WHERE (r.reply IS NULL OR r.reply = '') AND NOT EXISTS "
        "(SELECT 1 FROM proposals p WHERE p.review_id = r.id AND p.kind = 'reply' AND p.handoff = 1 AND p.state = 'APPROVED')")["n"]


def check_new_reviews(rt, pool: list[dict] | None = None) -> dict:
    pool = load_new_reviews() if pool is None else pool
    with rt.store.tx():   # the new review and its audit entry land together, or not at all (invariant 8)
        waiting = waiting_count(rt)
        have = {r["id"] for r in rt.store.all("SELECT id FROM reviews")}
        nxt = next((r for r in pool if r["id"] not in have), None) if waiting < WAITING_LIMIT else None
        if waiting >= WAITING_LIMIT:
            status, msg, rid = "waiting_first", WAIT_FIRST, "none"
        elif nxt is None:
            status, msg, rid = "none_left", NONE_LEFT, "none"
        else:
            add_review(rt.store, nxt)
            status, msg, rid = "added", FOUND, nxt["id"]
        rt.audit.append("reviews.checked", f"Checked for new reviews. {msg}", f"new review: {rid}; waiting before: {waiting}", None)
    return {"status": status, "message": msg, "review": rt.reader.read_review(rid).__dict__ if status == "added" else None}
