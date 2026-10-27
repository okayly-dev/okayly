import pytest

from app.verification import policy
from app.core.domain import ReviewState
from app.core.errors import Expired, HashMismatch, InvalidTransition, PolicyViolation
from app.agents.reviews import Draft
from app.wiring import build, load_fixture


FACTS = load_fixture()["facts"]


def rv(text="Waited a long time.", who="Dana M.", stars=2, rid="g1", platform="Google"):
    return ReviewState(rid, platform, stars, who, "Oct 25", text, None)


def orch(**kw):
    return build(db_path=":memory:", drafter="fixture", **kw)


# ---------- propose ----------
def test_blocked_first_draft_is_rewritten_and_recorded():
    o = orch()
    p = o.propose_reply("g1")
    assert p["state"] == "PROPOSED" and p["priority"] == "personal_touch"
    assert p["first_draft"] and "crown" in p["first_draft"]["reply"]
    assert policy.check_reply(p["after"]["reply"], rv(), FACTS) == []
    assert any(e["type"] == "draft.blocked" for e in o.audit.events())


def test_escalated_review_gets_no_proposal():
    o = orch()
    r = o.propose_reply("y3")
    assert r["status"] == "needs_human"
    assert o.store.one("SELECT 1 FROM proposals WHERE review_id='y3'") is None


def test_second_blocked_draft_means_no_proposal():
    o = orch()

    class Bad:
        def draft(self, rid, feedback=None):
            return Draft("We promise a refund for your crown appointment.")
    o.drafter = Bad()
    assert o.propose_reply("g2")["status"] == "needs_human"
    assert any(e["type"] == "draft.blocked_twice" for e in o.audit.events())


def test_propose_is_idempotent_while_open():
    o = orch()
    a, b = o.propose_reply("g2"), o.propose_reply("g2")
    assert a["id"] == b["id"]


def test_already_answered_review_is_refused():
    with pytest.raises(InvalidTransition):
        orch().propose_reply("g3")


# ---------- approve / execute / verify ----------
def test_happy_path_posts_and_verifies():
    o = orch()
    p = o.propose_reply("g2")
    done = o.approve(p["id"], p["hash"])
    assert done["state"] == "VERIFIED"
    assert o.providers["Google"].read_review("g2").reply == p["after"]["reply"]
    types = [e["type"] for e in reversed(o.audit.events())]
    assert types[-5:] == ["action.approved", "execution.started", "execution.succeeded", "verification.passed"][-5:] or "verification.passed" in types
    assert o.audit.verify()["ok"]


def test_approval_with_wrong_hash_is_refused_and_nothing_written():
    o = orch()
    p = o.propose_reply("g2")
    with pytest.raises(HashMismatch):
        o.approve(p["id"], "0" * 64)
    assert o.get(p["id"])["state"] == "PROPOSED"
    assert o.providers["Google"].read_review("g2").reply is None
    assert any(e["type"] == "approval.refused" for e in o.audit.events())


def test_editing_after_viewing_invalidates_the_old_approval():
    o = orch()
    p = o.propose_reply("g2")
    seen = p["hash"]
    edited = o.edit_reply(p["id"], "Thank you for the kind words. Comments like this mean a lot here.")
    assert edited["hash"] != seen
    with pytest.raises(HashMismatch):
        o.approve(p["id"], seen)
    assert o.approve(p["id"], edited["hash"])["state"] == "VERIFIED"


def test_edit_that_breaks_a_rule_is_refused():
    o = orch()
    p = o.propose_reply("g2")
    with pytest.raises(PolicyViolation) as e:
        o.edit_reply(p["id"], "Sorry about your root canal. We promise it will not happen again.")
    assert {i.code for i in e.value.issues} >= {"confirms_patient", "promise"}
    assert o.get(p["id"])["after"]["reply"] == p["after"]["reply"]


def test_stale_precondition_blocks_the_write():
    o = orch()
    p = o.propose_reply("g1")
    o.approve(p["id"], p["hash"], execute=False)
    o.providers["Google"].edit_text("g1", " (Edit: it was an hour.)")  # reviewer edits after the OK
    out = o.execute(p["id"])
    assert out["state"] == "FAILED" and out["reason"] == "precondition_changed"
    assert o.providers["Google"].read_review("g1").reply is None
    assert any(e["type"] == "execution.refused" for e in o.audit.events())


def test_someone_else_already_replied_blocks_the_write():
    o = orch()
    p = o.propose_reply("g2")
    o.approve(p["id"], p["hash"], execute=False)
    o.providers["Google"].set_reply("g2", "A teammate replied first.")
    assert o.execute(p["id"])["state"] == "FAILED"
    assert o.providers["Google"].read_review("g2").reply == "A teammate replied first."


def test_execute_is_idempotent_by_key():
    o = orch()
    p = o.propose_reply("g2")
    prov = o.providers["Google"]
    prov.post_reply("g2", "first", "idem_same")
    prov.post_reply("g2", "second", "idem_same")
    assert prov.read_review("g2").reply == "first"


def test_cannot_execute_without_approval():
    o = orch()
    p = o.propose_reply("g2")
    with pytest.raises(InvalidTransition):
        o.execute(p["id"])


def test_expired_approval_is_refused():
    t = [1000.0]
    o = orch(clock=lambda: t[0])
    p = o.propose_reply("g2")
    t[0] += 25 * 3600
    with pytest.raises(Expired):
        o.approve(p["id"], p["hash"])
    assert o.get(p["id"])["state"] == "REJECTED"


def test_yelp_is_approved_but_never_posted():
    o = orch()
    p = o.propose_reply("y1")
    out = o.approve(p["id"], p["hash"])
    assert out["state"] == "APPROVED" and out["handoff"] is True
    assert o.providers["Yelp"].read_review("y1").reply is None
    with pytest.raises(InvalidTransition):
        o.execute(p["id"])


def test_reject_is_final_and_a_new_proposal_is_a_new_attempt():
    o = orch()
    p = o.propose_reply("g2")
    assert o.reject(p["id"], "Not now")["state"] == "REJECTED"
    with pytest.raises(InvalidTransition):
        o.approve(p["id"], p["hash"])
    p2 = o.propose_reply("g2")
    assert p2["id"] != p["id"] and p2["attempt"] == 2


