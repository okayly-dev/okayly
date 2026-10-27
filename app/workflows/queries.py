"""Read-only questions the interface asks: lists, one proposal, a picture, usage, and the
read-only context Muse is given."""
from ..agents.context import ReadContext
from ..core import proposals
from ..core.errors import NotFound


def get(rt, pid: str) -> dict:
    return proposals.view(proposals.row(rt.store, pid))


def list_reviews(rt) -> list[dict]:
    out = []
    for rv in rt.reader.list_reviews():
        p = rt.store.one("SELECT * FROM proposals WHERE review_id=? AND kind='reply' ORDER BY created_at DESC, attempt DESC LIMIT 1", (rv.id,))
        out.append({"review": rv.__dict__, "proposal": proposals.view(p) if p else None})
    return out


def list_ads(rt) -> dict:
    rows = rt.store.all("SELECT * FROM proposals WHERE kind='ad' ORDER BY created_at DESC, attempt DESC")
    return {"ads": [a.__dict__ for a in rt.reader.list_ads()], "proposals": [proposals.view(r) for r in rows]}


def image(rt, sha: str) -> tuple[str, bytes]:
    r = rt.store.one("SELECT mime, data FROM images WHERE sha=?", (sha,))
    if not r:
        raise NotFound("No such picture.")
    return r["mime"], r["data"]


def usage(rt) -> dict:
    r = rt.store.one("SELECT COUNT(*) n, COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(cached_tokens),0) c, COALESCE(SUM(output_tokens),0) o, COALESCE(SUM(cost_usd),0) usd FROM usage")
    return {"calls": r["n"], "input_tokens": r["i"], "cached_tokens": r["c"], "output_tokens": r["o"], "cost_usd": round(r["usd"], 6)}


def drafter_context(rt) -> ReadContext:
    """What Muse may reach: reads only. It holds no write handle."""
    return ReadContext(rt.reader, rt.facts, rt.past)
