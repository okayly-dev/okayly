"""Read-only questions the interface asks: lists, one proposal, a picture, usage, and the
read-only context Muse is given."""
from ..agents.context import ReadContext
from ..core import proposals
from ..core.errors import NotFound


def get(rt, pid: str) -> dict:
    return proposals.view(proposals.row(rt.store, pid))


def list_reviews(rt) -> list[dict]:
    out = []
    for review in rt.reader.list_reviews():
        latest = rt.store.one("SELECT * FROM proposals WHERE review_id=? AND kind='reply' ORDER BY created_at DESC, attempt DESC LIMIT 1", (review.id,))
        out.append({"review": review.__dict__, "proposal": proposals.view(latest) if latest else None})
    return out


def list_ads(rt) -> dict:
    rows = rt.store.all("SELECT * FROM proposals WHERE kind='ad' ORDER BY created_at DESC, attempt DESC")
    return {"ads": [ad.__dict__ for ad in rt.reader.list_ads()], "proposals": [proposals.view(row) for row in rows]}


def image(rt, sha: str) -> tuple[str, bytes]:
    row = rt.store.one("SELECT mime, data FROM images WHERE sha=?", (sha,))
    if not row:
        raise NotFound("No such picture.")
    return row["mime"], row["data"]


def usage(rt) -> dict:
    row = rt.store.one("SELECT COUNT(*) calls, COALESCE(SUM(input_tokens),0) input_tokens, COALESCE(SUM(cached_tokens),0) cached_tokens, "
                       "COALESCE(SUM(output_tokens),0) output_tokens, COALESCE(SUM(cost_usd),0) cost_usd FROM usage")
    return {"calls": row["calls"], "input_tokens": row["input_tokens"], "cached_tokens": row["cached_tokens"],
            "output_tokens": row["output_tokens"], "cost_usd": round(row["cost_usd"], 6)}


def usage_today(rt, daily_cap_usd: float) -> dict:
    """The usage totals plus what was spent today (the UTC day the clock is in) against the daily cap."""
    now = rt.clock()
    start_of_day = now - now % 86400
    row = rt.store.one("SELECT COALESCE(SUM(cost_usd), 0) spent FROM usage WHERE ts>=? AND ts<?",
                       (start_of_day, start_of_day + 86400))
    spent = round(float(row["spent"]), 6)
    return {**usage(rt), "cap_usd": daily_cap_usd, "spent_today_usd": spent,
            "remaining_usd": round(max(0.0, daily_cap_usd - spent), 6)}


def drafter_context(rt) -> ReadContext:
    """What Muse may reach: reads only. It holds no write handle."""
    return ReadContext(rt.reader, rt.facts, rt.past)
