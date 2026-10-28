"""Invariant 8: a state change and its audit entry are saved together, or neither is.
Each test makes one audit write fail and checks that the proposal's state did not move."""
import pytest

from app.wiring import build


def orch(clock=None):
    return build(db_path=":memory:", drafter="fixture", **({"clock": clock} if clock else {}))


def fail_audit(o, audit_type):
    """Make the audit write for one entry type raise, as a full disk or a locked database would."""
    real = o.audit.append

    def append(type, *args, **kwargs):
        if type == audit_type:
            raise RuntimeError("audit write failed")
        return real(type, *args, **kwargs)
    o.audit.append = append


def state(o, pid):
    return o.store.one("SELECT state FROM proposals WHERE id=?", (pid,))["state"]


def logged(o, audit_type):
    return any(e["type"] == audit_type for e in o.audit.events(1000))


def test_reject_without_its_audit_entry_leaves_the_proposal_waiting():
    o = orch()
    p = o.propose_reply("g2")
    fail_audit(o, "action.rejected")
    with pytest.raises(RuntimeError):
        o.reject(p["id"], "not now")
    assert state(o, p["id"]) == "PROPOSED" and not logged(o, "action.rejected")


def test_expiry_without_its_audit_entry_leaves_the_proposal_waiting():
    now = [1_000_000.0]
    o = orch(clock=lambda: now[0])
    p = o.propose_reply("g2")
    now[0] += 10 * 24 * 3600                                   # long after the approval request expired
    fail_audit(o, "approval.expired")
    with pytest.raises(RuntimeError):
        o.approve(p["id"], p["hash"], execute=False)
    assert state(o, p["id"]) == "PROPOSED" and not logged(o, "approval.expired")


def test_refusal_before_writing_needs_its_audit_entry_to_move_to_failed():
    o = orch()
    p = o.propose_ad("Atomic ad")
    o.providers["Ads"].demo_create("Atomic ad")                # a teammate saves the same name
    fail_audit(o, "execution.refused")
    with pytest.raises(RuntimeError):
        o.approve(p["id"], p["hash"])
    assert state(o, p["id"]) != "FAILED" and not logged(o, "execution.refused")


def test_executed_state_needs_its_audit_entry():
    o = orch()
    p = o.propose_reply("g2")
    o.approve(p["id"], p["hash"], execute=False)
    fail_audit(o, "execution.succeeded")
    with pytest.raises(RuntimeError):
        o.execute(p["id"])
    assert state(o, p["id"]) == "EXECUTING" and not logged(o, "execution.succeeded")


def test_verified_state_needs_its_audit_entry():
    o = orch()
    p = o.propose_reply("g2")
    o.approve(p["id"], p["hash"], execute=False)
    fail_audit(o, "verification.passed")
    with pytest.raises(RuntimeError):
        o.execute(p["id"])
    assert state(o, p["id"]) == "EXECUTED" and not logged(o, "verification.passed")


def test_a_failed_demo_reset_keeps_the_old_data(monkeypatch):
    o = orch()
    p = o.propose_reply("g2")
    reviews_before = o.store.one("SELECT COUNT(*) n FROM reviews")["n"]
    monkeypatch.setattr("app.workflows.demo.seed_ads", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("seed failed")))
    with pytest.raises(RuntimeError):
        o.demo_reset([{"id": "x1", "platform": "Google", "stars": 5, "who": "A", "date": "today", "text": "Great"}], [])
    assert o.store.one("SELECT COUNT(*) n FROM reviews")["n"] == reviews_before
    assert state(o, p["id"]) == "PROPOSED"
