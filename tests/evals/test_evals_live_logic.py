"""The live eval runner's scoring, tested with a scripted drafter: no Muse call, no cost."""
import app.wiring as wiring
from app.agents.reviews import Draft
from app.core.errors import MuseUnavailable
from evals.run import run_live


class ScriptedDrafter:
    """reply-001 breaks a rule first and then behaves; reply-002 is always clean; reply-003 always fails;
    reply-004 breaks a rule twice; everything else is clean."""

    def draft(self, review_id, feedback=None):
        if review_id == "reply-001":
            return Draft("Thank you." if feedback else "We guarantee your next visit will be perfect.")
        if review_id == "reply-003":
            raise MuseUnavailable("busy")
        if review_id == "reply-004":
            return Draft("We guarantee a free implant.")
        return Draft("Thank you for the kind words.")


def test_live_scoring_counts_clean_fixed_blocked_twice_and_errors(monkeypatch):
    real_build = wiring.build

    def build(db_path=None, drafter=None, **kw):
        orch = real_build(db_path=db_path, drafter="fixture")
        orch.drafter = ScriptedDrafter()
        return orch

    monkeypatch.setattr(wiring, "build", build)
    ids = ["reply-001", "reply-002", "reply-003", "reply-004"]
    cases = [{"id": i, "group": "reply_bait", "input": {"review": "Fine.", "draft": "x"}, "expected": {"outcome": "passes"}} for i in ids]
    out = run_live(cases)
    by_id = {r["id"]: r for r in out["cases"]}
    assert by_id["reply-001"]["outcome"] == "proposed" and by_id["reply-001"]["first_draft_clean"] is False
    assert by_id["reply-002"]["outcome"] == "proposed" and by_id["reply-002"]["first_draft_clean"] is True
    assert by_id["reply-003"]["outcome"] == "error" and by_id["reply-003"]["error"] == "MuseUnavailable"
    assert by_id["reply-004"]["outcome"] == "blocked_twice"
    g = out["groups"]["reply_bait"]
    assert (g["cases"], g["drafted_by_muse"], g["first_draft_clean"], g["fixed_after_block"], g["blocked_twice"], g["errors"]) == (4, 3, 1, 1, 1, 1)
    assert out["final_violations"] == 0
