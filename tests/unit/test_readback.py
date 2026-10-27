import hashlib

from app.core.domain import AdState, ReviewState
from app.core.payload import content_hash
from app.verification import readback


def args(after=None):
    return dict(kind="reply", provider="p", resource="g1", before={"text": "t", "reply": None},
                after=after or {"reply": "hi"}, attempt=1)


def test_approved_content_must_match_both_hashes():
    a = args()
    h = content_hash(**a)
    assert readback.approved_content_problem(**a, approved_hash=h, stored_hash=h) is None
    assert readback.approved_content_problem(**a, approved_hash="0" * 64, stored_hash=h)
    assert readback.approved_content_problem(**a, approved_hash=h, stored_hash="0" * 64)
    assert readback.approved_content_problem(**args({"reply": "other"}), approved_hash=h, stored_hash=h)


def test_precondition_for_a_reply():
    rv = ReviewState("g1", "Google", 5, "A B.", "d", "t", None)
    before = {"text": "t", "reply": None}
    assert readback.precondition_problem("reply", before, {}, rv) is None
    assert readback.precondition_problem("reply", before, {}, None)
    assert readback.precondition_problem("reply", before, {}, ReviewState("g1", "Google", 5, "A B.", "d", "t2", None))
    assert readback.precondition_problem("reply", before, {}, ReviewState("g1", "Google", 5, "A B.", "d", "t", "taken"))


def test_precondition_for_an_ad_checks_name_and_picture_bytes():
    data = b"picture"
    after = {"image_sha": hashlib.sha256(data).hexdigest()}
    assert readback.precondition_problem("ad", {}, after, None, {"data": data, "passed": 1}) is None
    assert readback.precondition_problem("ad", {}, after, AdState("n", "paused", "h", "t", None, "wide"), {"data": data, "passed": 1})
    assert readback.precondition_problem("ad", {}, after, None, {"data": data + b"x", "passed": 1})
    assert readback.precondition_problem("ad", {}, after, None, {"data": data, "passed": 0})
    assert readback.precondition_problem("ad", {}, after, None, None)


def test_readback_matches():
    assert readback.readback_matches("reply", {"reply": "hi"}, ReviewState("g1", "Google", 5, "A", "d", "t", "hi"))
    assert not readback.readback_matches("reply", {"reply": "hi"}, ReviewState("g1", "Google", 5, "A", "d", "t", "hi!"))
    assert not readback.readback_matches("reply", {"reply": "hi"}, None)
    after = {"headline": "h", "text": "t", "image_sha": "s", "format": "wide"}
    assert readback.readback_matches("ad", after, AdState("n", "paused", "h", "t", "s", "wide"))
    assert not readback.readback_matches("ad", after, AdState("n", "paused", "h!", "t", "s", "wide"))
