"""Editing a waiting proposal. Every edit is checked again by the rules and gets a new hash,
so an approval given for the old wording no longer applies."""
import json

from ..core import proposals
from ..core.canonical import sha256
from ..core.domain import Issue, State
from ..core.errors import InvalidTransition, NotFound, PolicyViolation
from ..core.messages import MSG
from ..core.payload import content_hash
from ..verification import policy


def _need(rt, pid: str, kind: str):
    r = proposals.row(rt.store, pid)
    if r["kind"] != kind:
        raise InvalidTransition(f"{pid} is not a {MSG[kind]['noun']}.")
    if r["state"] != State.PROPOSED.value:
        raise InvalidTransition(f"Only a waiting {MSG[kind]['noun']} can be edited.")
    return r


def _rehash(rt, r, after: dict, type: str, plain: str) -> dict:
    h = content_hash(r["kind"], r["provider"], r["review_id"], json.loads(r["before_json"]), after, r["attempt"])
    with rt.store.tx():
        rt.store.run("UPDATE proposals SET after_json=?, hash=?, idem=? WHERE id=?",
                     (json.dumps(after), h, "idem_" + sha256(h + str(r["attempt"]))[:12], r["id"]))
        rt.audit.append(type, plain, f"hash {h[:12]}", r["id"])
    return proposals.view(proposals.row(rt.store, r["id"]))


def edit_reply(rt, pid: str, text: str) -> dict:
    r = _need(rt, pid, "reply")
    rv = rt.reader.read_review(r["review_id"])
    issues = policy.check_reply(text, rv, rt.facts)
    if issues:
        raise PolicyViolation(issues)
    after = json.loads(r["after_json"])
    after["reply"] = text.strip()
    return _rehash(rt, r, after, "draft.edited", "You changed the wording of a reply. We checked it again and it passed.")


def edit_ad(rt, pid: str, headline: str | None = None, text: str | None = None, fmt: str | None = None) -> dict:
    r = _need(rt, pid, "ad")
    after = json.loads(r["after_json"])
    after["headline"] = (headline if headline is not None else after["headline"]).strip()
    after["text"] = (text if text is not None else after["text"]).strip()
    if fmt is not None:
        if fmt not in policy.AD_FORMATS:
            raise PolicyViolation([Issue("bad_format", "Pick wide, square or tall.")])
        after["format"] = fmt
    issues = policy.check_ad(after["headline"], after["text"], rt.facts)
    if issues:
        raise PolicyViolation(issues)
    return _rehash(rt, r, after, "draft.edited", "You changed the wording of an ad. We checked it again and it passed.")


def choose_picture(rt, pid: str, sha: str) -> dict:
    r = _need(rt, pid, "ad")
    cands = (json.loads(r["extra_json"]) or {}).get("candidates", [])
    pick = next((c for c in cands if c["sha"] == sha), None)
    if pick is None:
        raise NotFound("That picture is not one of this ad's pictures.")
    if not pick["passed"]:
        raise PolicyViolation([Issue("picture_blocked", "That picture did not pass the picture check, so it cannot be used.")])
    after = json.loads(r["after_json"])
    after["image_sha"] = sha
    return _rehash(rt, r, after, "picture.chosen", "You picked a different picture for the ad.")
