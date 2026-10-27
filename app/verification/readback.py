"""Pure comparisons the executor relies on. They look at values the caller already read;
they never read or write anything themselves, so they are easy to test and cannot be
talked around by a model.

- approved_content_problem: is what is stored still exactly what the person approved?
- precondition_problem: is the world still as it was when the person approved?
- readback_matches: does an independent read show what was approved?"""
import hashlib

from ..core.payload import content_hash


def approved_content_problem(*, kind: str, provider: str, resource: str, before: dict, after: dict, attempt: int,
                             approved_hash: str, stored_hash: str) -> str | None:
    """Recompute the SHA-256 of the stored change. It must equal both the hash the person
    approved and the hash stored with the proposal. Returns a plain reason, or None."""
    now = content_hash(kind, provider, resource, before, after, attempt)
    if now != approved_hash:
        return f"approved {approved_hash[:12]}, stored content is now {now[:12]}"
    if now != stored_hash:
        return f"stored hash {stored_hash[:12]} does not match the stored content {now[:12]}"
    return None


def precondition_problem(kind: str, before: dict, after: dict, current, image: dict | None = None) -> str | None:
    """current is the freshly read review (reply) or the ad already saved under that name (ad),
    or None if there is none. image is the stored picture row (data, passed) for an ad."""
    if kind == "ad":
        if current is not None:
            return "an ad with this name already exists"
        if not image or not image["passed"] or hashlib.sha256(image["data"]).hexdigest() != after["image_sha"]:
            return "the picture is not the one that was checked"
        return None
    if current is None or current.reply is not None or current.text != before["text"]:
        return "the review changed"
    return None


def readback_matches(kind: str, after: dict, observed) -> bool:
    """observed is what an independent read returned: the ad, or the review. None means not found."""
    if observed is None:
        return False
    if kind == "ad":
        return (observed.status == "paused" and observed.headline == after["headline"] and observed.text == after["text"]
                and observed.image_sha == after["image_sha"] and observed.format == after["format"])
    return observed.reply == after["reply"]
