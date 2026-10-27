"""Proposing a change: a review reply or a paused ad draft. Muse (through the drafters) only
proposes; code checks the draft against the rules before a person ever sees it."""
import hashlib
import json
import re
import secrets
from concurrent.futures import ThreadPoolExecutor

from ..core import proposals
from ..core.canonical import sha256
from ..core.domain import Issue, State
from ..core.errors import InvalidTransition, NotFound, PolicyViolation
from ..core.payload import content_hash
from ..verification import policy

AD_NAME_MAX = 60


def create(rt, *, kind, resource, provider, before, after, handoff, priority, first_blocked, extra, plain, detail, audits=()) -> dict:
    store = rt.store
    attempt = 1 + store.one("SELECT COALESCE(MAX(attempt),0) m FROM proposals WHERE review_id=? AND kind=?", (resource, kind))["m"]
    h = content_hash(kind, provider, resource, before, after, attempt)
    pid = "act_" + secrets.token_hex(4)
    now = rt.clock()
    with store.tx():
        store.run(
            "INSERT INTO proposals (id, review_id, kind, state, reason, attempt, before_json, after_json, hash, idem, provider, handoff, priority, first_draft_json, created_at, expires_at, extra_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, resource, kind, State.PROPOSED.value, "", attempt, json.dumps(before), json.dumps(after), h,
             "idem_" + sha256(h + str(attempt))[:12], provider, handoff, priority,
             json.dumps(first_blocked) if first_blocked else None, now, now + rt.ttl,
             json.dumps(extra) if extra else None))
        rt.audit.append("proposal.created", plain, f"hash {h[:12]}; attempt {attempt}; first draft blocked: {bool(first_blocked)}" + detail, pid)
        for a in audits:
            rt.audit.append(*a, pid)
    return proposals.view(proposals.row(store, pid))


def skip(rt, resource: str, reason: str, audit: bool = True, what: str = "reply") -> dict:
    detail = f"{resource}: {reason}"
    if audit and not rt.store.one("SELECT 1 FROM events WHERE type='proposal.skipped' AND detail=?", (detail,)):
        rt.audit.append("proposal.skipped", f"We wrote no {what} and left this for a person.", detail, None)
    return {"status": "needs_human", "review_id": resource, "reason": reason}


def propose_reply(rt, review_id: str) -> dict:
    rv = rt.reader.read_review(review_id)
    if rv is None:
        raise NotFound(f"No review {review_id}")
    live = proposals.live(rt.store, "reply", review_id)
    if live:
        return proposals.view(live)
    if rv.reply is not None:
        raise InvalidTransition("This review already has a reply.")

    why = policy.needs_human(rv)
    if why:
        return skip(rt, review_id, why)

    first_blocked = None
    d = rt.drafter.draft(review_id)
    if d.escalate:
        return skip(rt, review_id, d.escalate_reason or "A person should handle this one.")
    issues = policy.check_reply(d.reply, rv, rt.facts)
    if issues:
        first_blocked = {"reply": d.reply, "issues": [i.message for i in issues]}
        rt.audit.append("draft.blocked", "A first draft was stopped by the privacy and claims check.",
                        "; ".join(i.code for i in issues), None)
        d = rt.drafter.draft(review_id, feedback=first_blocked)
        if d.escalate:
            return skip(rt, review_id, d.escalate_reason or "A person should handle this one.")
        issues = policy.check_reply(d.reply, rv, rt.facts)
        if issues:
            rt.audit.append("draft.blocked_twice", "The rewrite was also stopped, so no reply was proposed.", "; ".join(i.code for i in issues), None)
            return skip(rt, review_id, "We could not write a reply that passes the checks.", audit=False)

    return create(
        rt, kind="reply", resource=review_id, provider=rt.reader.provider_name(rv.platform),
        before={"text": rv.text, "reply": None}, after={"review": review_id, "platform": rv.platform, "reply": d.reply},
        handoff=0, priority="personal_touch" if rv.stars <= 2 else "normal", first_blocked=first_blocked, extra=None,
        plain=f"We drafted a reply to a {rv.stars}-star {rv.platform} review.", detail="")


def propose_ad(rt, name: str, fmt: str = "wide") -> dict:
    name = (name or "").strip()
    if not 1 <= len(name) <= AD_NAME_MAX or not re.fullmatch(r"[\w .,'&()\-]+", name):
        raise PolicyViolation([Issue("bad_name", f"Give the ad a short name (up to {AD_NAME_MAX} letters, numbers and spaces).")])
    if fmt not in policy.AD_FORMATS:
        raise PolicyViolation([Issue("bad_format", "Pick wide, square or tall.")])
    live = proposals.live(rt.store, "ad", name)
    if live:
        return proposals.view(live)
    if rt.reader.read_ad(name) is not None:
        raise InvalidTransition("An ad with this name already exists.")

    first_blocked = None
    d = rt.ad_studio.draft(name)
    issues = policy.check_ad(d.headline, d.text, rt.facts)
    if issues:
        first_blocked = {"headline": d.headline, "text": d.text, "issues": [i.message for i in issues]}
        rt.audit.append("draft.blocked", "A first ad draft was stopped by the ad rules check.", "; ".join(i.code for i in issues), None)
        d = rt.ad_studio.draft(name, feedback=first_blocked)
        issues = policy.check_ad(d.headline, d.text, rt.facts)
        if issues:
            rt.audit.append("draft.blocked_twice", "The rewrite was also stopped, so no ad was proposed.", "; ".join(i.code for i in issues), None)
            return skip(rt, name, "We could not write an ad that passes the checks.", audit=False, what="ad")

    pictures = make_pictures(rt, d.image_prompts)
    passing = [p for p in pictures if p["passed"]]
    if not passing:
        rt.audit.append("ad.no_picture", "No picture passed the picture check, so no ad was proposed.",
                        "; ".join(f"{p['sha'][:12] if p['sha'] else 'none'}: {','.join(p['codes'])}" for p in pictures), None)
        return skip(rt, name, "None of the pictures passed the picture check.", audit=False, what="ad")

    with rt.store.tx():   # pictures and proposal land together, or not at all
        for p in pictures:
            if p["data"]:
                rt.store.run("INSERT OR IGNORE INTO images (sha, mime, data, prompt, review_json, passed) VALUES (?,?,?,?,?,?)",
                             (p["sha"], p["mime"], p["data"], p["prompt"], json.dumps(p["review"]), int(p["passed"])))
        cands = [{k: p[k] for k in ("sha", "mime", "prompt", "review", "passed", "issues")} for p in pictures]
        audits = [("image.checked", f"Picture {i + 1} passed the picture check." if p["passed"]
                   else f"Picture {i + 1} was stopped by the picture check: {' '.join(p['issues'])}",
                   (p["sha"] or "no picture")[:12] + "; " + (",".join(p["codes"]) or "all checks passed"))
                  for i, p in enumerate(pictures)]
        return create(
            rt, kind="ad", resource=name, provider=rt.reader.provider_name("Ads"), before={"exists": False},
            after={"name": name, "headline": d.headline, "text": d.text, "image_sha": passing[0]["sha"], "format": fmt, "status": "paused"},
            handoff=0, priority="normal", first_blocked=first_blocked, extra={"candidates": cands},
            plain=f"We drafted an ad called {name}. It will be saved paused, with no budget.",
            detail=f"; {len(passing)} of {len(pictures)} pictures passed", audits=audits)


def make_pictures(rt, prompts: list[str]) -> list[dict]:
    """Make and check each picture in parallel. One failed picture does not stop the others."""
    def one(prompt):
        p = {"prompt": prompt, "sha": None, "mime": None, "data": None, "review": None, "passed": False, "issues": [], "codes": []}
        try:
            data = rt.ad_studio.image(prompt)
            p.update(data=data, sha=hashlib.sha256(data).hexdigest(), mime=policy.sniff_image(data))
            p["review"] = rt.ad_studio.review_image(data) if p["mime"] else None
            found = policy.check_image(data, p["review"])
        except Exception as e:   # a network or model failure becomes "this picture is not usable"
            found = [Issue("picture_failed", "We could not make or check this picture.")]
            p["error"] = type(e).__name__
        p.update(passed=not found, issues=[i.message for i in found], codes=[i.code for i in found])
        return p
    with ThreadPoolExecutor(max_workers=max(1, len(prompts))) as ex:
        return list(ex.map(one, prompts))
