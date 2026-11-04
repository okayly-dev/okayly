"""'Check for new reviews': one made-up review per call from a fixed pool, never more than the limit waiting,
the review and its audit entry saved together, and no Muse call inside the route."""
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.providers.seed import load_new_reviews
from app.wiring import build, load_fixture

POOL_IDS = [r["id"] for r in load_new_reviews()]


class CountingDrafter:
    """Stands in for Muse: any call is counted, and the test then checks the count is zero."""
    def __init__(self):
        self.calls = 0

    def draft(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("The check-new route must not draft anything")


def orch():
    return build(db_path=":memory:", drafter="fixture")


def client(o=None, demo=False):
    return TestClient(create_app(o or orch(), demo_controls=demo))


def answer(c, review_id):
    """Draft, approve and post the reply for one review, the normal way."""
    p = c.post(f"/api/reviews/{review_id}/propose").json()
    done = c.post(f"/api/proposals/{p['id']}/approve", json={"hash": p["hash"]}).json()
    assert done["state"] in ("VERIFIED", "APPROVED")   # APPROVED is the Yelp hand-off


def waiting(c):
    return [x["review"]["id"] for x in c.get("/api/reviews").json() if not x["review"]["reply"]]


def test_the_pool_is_six_made_up_reviews_with_new_ids():
    pool = load_new_reviews()
    sample_ids = {r["id"] for r in load_fixture()["reviews"]}
    assert len(pool) == 6 and not sample_ids & set(POOL_IDS)
    assert {r["platform"] for r in pool} == {"Google", "Yelp"}
    assert all(r["reply"] is None for r in pool)
    assert all(r["id"] in load_fixture()["fixture_drafts"] for r in pool)   # the offline drafter can answer each one


def test_the_route_needs_no_demo_flag_and_adds_the_pool_in_order_one_per_call():
    c = client(demo=False)
    for rid in ("g1", "g2", "y1"):   # leave only the review that needs a person (y3) waiting
        answer(c, rid)
    seen = []
    for expected in POOL_IDS[:2]:
        out = c.post("/api/reviews/check-new").json()
        assert out["status"] == "added" and out["review"]["id"] == expected and out["review"]["reply"] is None
        seen.append(expected)
    assert [x["review"]["id"] for x in c.get("/api/reviews").json()][:2] == seen[::-1]   # newest first
    assert len(c.get("/api/reviews").json()) == 7 + 2


def test_it_adds_none_when_three_or_more_are_waiting():
    o = orch()
    c = client(o)
    assert len(waiting(c)) == 4   # g1, g2, y1 and y3 have no reply yet
    out = c.post("/api/reviews/check-new").json()
    assert out == {"status": "waiting_first", "message": "Reply to the ones waiting first.", "review": None}
    assert len(c.get("/api/reviews").json()) == 7
    answer(c, "g1")
    answer(c, "g2")   # two waiting now: y1 and y3
    assert c.post("/api/reviews/check-new").json()["status"] == "added"
    assert len(waiting(c)) == 3
    assert c.post("/api/reviews/check-new").json()["status"] == "waiting_first"


def test_a_yelp_reply_the_person_approved_counts_as_answered():
    c = client()
    for rid in ("g1", "g2"):
        answer(c, rid)
    assert c.post("/api/reviews/check-new").json()["status"] == "added"    # y1, y3 and the new one wait: 3 waiting
    assert c.post("/api/reviews/check-new").json()["status"] == "waiting_first"
    answer(c, "y1")   # approved for hand-off: the reply is never posted by the app, but the person has dealt with it
    assert c.post("/api/reviews/check-new").json()["status"] == "added"


def test_it_says_none_when_the_pool_is_used_up():
    o = orch()
    c = client(o)
    for rid in ("g1", "g2", "y1"):
        answer(c, rid)
    for rid in POOL_IDS:
        out = c.post("/api/reviews/check-new").json()
        assert out["status"] == "added" and out["review"]["id"] == rid
        answer(c, rid)
    out = c.post("/api/reviews/check-new").json()
    assert out == {"status": "none_left", "message": "No new reviews right now.", "review": None}
    assert len(c.get("/api/reviews").json()) == 7 + 6


def test_every_pool_review_gets_a_reply_that_passes_the_rules():
    c = client()
    for rid in ("g1", "g2", "y1"):
        answer(c, rid)
    for rid in POOL_IDS:
        assert c.post("/api/reviews/check-new").json()["review"]["id"] == rid
        p = c.post(f"/api/reviews/{rid}/propose").json()
        assert p["state"] == "PROPOSED", p
        assert p["first_draft"] is None   # the offline drafter's first reply passes without a rewrite
        c.post(f"/api/proposals/{p['id']}/approve", json={"hash": p["hash"]})
    assert c.get("/api/audit/verify").json()["ok"] is True


def test_each_call_writes_one_audit_entry_and_the_chain_verifies():
    o = orch()
    c = client(o)
    c.post("/api/reviews/check-new")   # refused: four are waiting
    answer(c, "g1")
    answer(c, "g2")
    c.post("/api/reviews/check-new")   # adds n1
    entries = [e for e in o.audit.events(1000) if e["type"] == "reviews.checked"]
    assert len(entries) == 2
    assert "new review: none" in entries[1]["detail"] and "new review: n1" in entries[0]["detail"]
    assert o.audit.verify()["ok"] is True


def test_the_review_and_its_audit_entry_are_saved_together():
    o = orch()
    c = client(o)
    answer(c, "g1")
    answer(c, "g2")
    real = o.audit.append

    def failing(type, *args, **kwargs):
        if type == "reviews.checked":
            raise RuntimeError("audit write failed")
        return real(type, *args, **kwargs)
    o.audit.append = failing
    with pytest.raises(RuntimeError):
        o.check_new_reviews()
    assert o.rt.reader.read_review("n1") is None   # no audit entry, so no new review either
    o.audit.append = real
    assert o.check_new_reviews()["status"] == "added"
    assert o.audit.verify()["ok"] is True


def test_no_muse_call_happens_inside_the_route():
    o = orch()
    spy = CountingDrafter()
    o.drafter, o.ad_studio = spy, spy
    c = client(o)
    # answer three by hand first so the route has room, without using the spy
    for rid in ("g1", "g2", "y1"):
        o.rt.store.run("UPDATE reviews SET reply='Thanks.' WHERE id=?", (rid,))
    assert c.post("/api/reviews/check-new").json()["status"] == "added"
    assert spy.calls == 0
    usage = c.get("/api/usage").json()
    assert usage["calls"] == 0


def test_the_workflow_has_no_way_to_reach_a_model():
    """It imports only the sample-data loaders: no agents, no drafter, no Muse client."""
    import ast
    import app.workflows.new_reviews as w
    imported = [n.module for n in ast.walk(ast.parse(open(w.__file__, encoding="utf-8").read())) if isinstance(n, ast.ImportFrom)]
    assert imported == ["providers.seed"]


def test_demo_reset_puts_the_original_seven_back_and_the_pool_starts_again():
    o = orch()
    c = client(o, demo=True)
    for rid in ("g1", "g2", "y1"):
        answer(c, rid)
    assert c.post("/api/reviews/check-new").json()["review"]["id"] == POOL_IDS[0]
    assert len(c.get("/api/reviews").json()) == 8
    assert c.post("/api/demo/reset").json() == {"ok": True}
    assert len(c.get("/api/reviews").json()) == 7
    assert o.audit.verify()["ok"] is True
    answer(c, "g1")
    answer(c, "g2")
    assert c.post("/api/reviews/check-new").json()["review"]["id"] == POOL_IDS[0]   # the pool starts again


def test_a_custom_pool_can_be_passed_to_the_service():
    o = orch()
    for rid in ("g1", "g2", "y1"):
        o.rt.store.run("UPDATE reviews SET reply='Thanks.' WHERE id=?", (rid,))
    pool = [{"id": "z1", "platform": "Google", "stars": 5, "who": "Test T.", "date": "Oct 1", "text": "Fine.", "reply": None}]
    assert o.check_new_reviews(pool)["review"]["id"] == "z1"
    assert o.check_new_reviews(pool)["status"] == "none_left"
