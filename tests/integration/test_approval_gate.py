"""Writes happen only through the approval gate: the executor recomputes the content hash
and refuses on any difference."""
import json

import pytest

from app.core.errors import InvalidTransition
from app.providers.read import SandboxReader
from app.wiring import build
from app.workflows import approval_gate
from app.workflows.approval_gate import ApprovedAction

WRITE_METHODS = ("post_reply", "create_paused_draft")


def orch():
    return build(db_path=":memory:", drafter="fixture")


def refusals(o):
    return [e for e in o.audit.events(1000) if e["type"] == "execution.refused"]


def test_reply_changed_after_approval_is_refused_and_nothing_is_posted():
    o = orch()
    p = o.propose_reply("g2")
    o.approve(p["id"], p["hash"], execute=False)
    after = dict(p["after"], reply="Something nobody approved.")
    o.store.run("UPDATE proposals SET after_json=? WHERE id=?", (json.dumps(after), p["id"]))
    out = o.execute(p["id"])
    assert out["state"] == "FAILED" and out["reason"] == "approved_content_changed"
    assert o.providers["Google"].read_review("g2").reply is None
    assert o.store.one("SELECT 1 FROM writes") is None
    r = refusals(o)
    assert len(r) == 1 and "approved_content_changed" in r[0]["detail"] and "nothing written" in r[0]["detail"]
    assert r[0]["plain"].startswith("We stopped.") and "nothing was posted" in r[0]["plain"]
    assert not any(e["type"] == "execution.started" for e in o.audit.events(1000))
    assert o.audit.verify()["ok"] is True


def test_ad_changed_after_approval_is_refused_and_nothing_is_saved():
    o = orch()
    p = o.propose_ad("Gate ad")
    o.approve(p["id"], p["hash"], execute=False)
    after = dict(p["after"], headline="Free implants today")
    o.store.run("UPDATE proposals SET after_json=? WHERE id=?", (json.dumps(after), p["id"]))
    out = o.execute(p["id"])
    assert out["state"] == "FAILED" and out["reason"] == "approved_content_changed"
    assert o.providers["Ads"].read_ad("Gate ad") is None
    assert o.store.one("SELECT 1 FROM writes") is None
    assert "nothing was saved" in refusals(o)[0]["plain"]
    assert o.audit.verify()["ok"] is True


def test_a_stored_hash_that_does_not_match_the_content_is_refused():
    o = orch()
    p = o.propose_reply("g2")
    o.approve(p["id"], p["hash"], execute=False)
    o.store.run("UPDATE proposals SET hash=? WHERE id=?", ("0" * 64, p["id"]))
    out = o.execute(p["id"])
    assert out["state"] == "FAILED" and out["reason"] == "approved_content_changed"
    assert o.providers["Google"].read_review("g2").reply is None


def test_an_approval_for_different_content_is_refused():
    o = orch()
    p = o.propose_reply("g2")
    o.approve(p["id"], p["hash"], execute=False)
    stale = ApprovedAction(p["id"], "reply", "f" * 64, approval_gate._SEAL)   # white-box: a hash that is not the content's
    out = o.executor.execute(stale)
    assert out["state"] == "FAILED" and out["reason"] == "approved_content_changed"
    assert o.providers["Google"].read_review("g2").reply is None


def test_untouched_content_still_posts_and_verifies():
    o = orch()
    p = o.propose_reply("g2")
    o.approve(p["id"], p["hash"], execute=False)
    assert o.execute(p["id"])["state"] == "VERIFIED"
    assert not refusals(o)


def test_an_approved_action_cannot_be_made_outside_the_gate():
    with pytest.raises(TypeError):
        ApprovedAction("act_1", "reply", "a" * 64)
    with pytest.raises(TypeError):
        ApprovedAction("act_1", "reply", "a" * 64, object())


def test_the_executor_refuses_anything_that_is_not_an_approved_action():
    o = orch()
    p = o.propose_reply("g2")
    o.approve(p["id"], p["hash"], execute=False)
    for not_approved in (p["id"], p, None, ("act", "reply", p["hash"])):
        with pytest.raises(TypeError):
            o.executor.execute(not_approved)
    assert o.get(p["id"])["state"] == "APPROVED"
    assert o.providers["Google"].read_review("g2").reply is None


def test_a_waiting_proposal_cannot_be_executed():
    o = orch()
    p = o.propose_reply("g2")
    forged = ApprovedAction(p["id"], "reply", p["hash"], approval_gate._SEAL)   # white-box
    with pytest.raises(InvalidTransition):
        o.executor.execute(forged)
    assert o.get(p["id"])["state"] == "PROPOSED"


def test_the_context_given_to_muse_has_no_write_handle():
    o = orch()
    ctx = o.drafter_context()
    for name in WRITE_METHODS + ("seed", "edit_text", "set_reply", "demo_create"):
        assert not hasattr(ctx, name)
        assert not hasattr(ctx._reader, name)
    assert type(ctx._reader) is SandboxReader
    assert all(ctx._reader is not w for w in o.providers.values())
    held = [v for v in vars(ctx).values()]
    assert not any(hasattr(v, n) for v in held for n in WRITE_METHODS)


def test_the_workflows_hold_no_write_handle():
    o = orch()
    assert type(o.rt.reader) is SandboxReader
    held = list(vars(o.rt).values())
    assert not any(hasattr(v, n) for v in held for n in WRITE_METHODS)
    assert not any(getattr(v, "__self__", None) in o.providers.values() for v in held)   # no bound method of a provider
