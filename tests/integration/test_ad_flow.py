import pytest

from app import policy
from app.errors import HashMismatch, InvalidTransition, NotFound, PolicyViolation
from app.wiring import build, load_fixture


FACTS = load_fixture()["facts"]


def orch():
    return build(db_path=":memory:", drafter="fixture")


def types(o):
    return [e["type"] for e in o.audit.events(1000)][::-1]


# ---------- propose ----------
def test_blocked_first_ad_is_rewritten_and_pictures_are_checked():
    o = orch()
    p = o.propose_ad("Spring new patients")
    assert p["state"] == "PROPOSED" and p["kind"] == "ad" and p["after"]["status"] == "paused"
    assert p["first_draft"] and "guaranteed" in p["first_draft"]["headline"]
    assert policy.check_ad(p["after"]["headline"], p["after"]["text"], FACTS) == []
    cands = p["extra"]["candidates"]
    assert [c["passed"] for c in cands] == [True, False, True]
    assert "people" in cands[1]["issues"][0]
    assert p["after"]["image_sha"] == cands[0]["sha"]
    t = types(o)
    assert t.count("image.checked") == 3 and "draft.blocked" in t and t[-1] != "execution.started"


def test_ad_happy_path_saves_a_paused_draft_and_verifies():
    o = orch()
    p = o.propose_ad("Spring new patients")
    done = o.approve(p["id"], p["hash"])
    assert done["state"] == "VERIFIED"
    ad = o.providers["Ads"].read_ad("Spring new patients")
    assert ad.status == "paused" and ad.image_sha == p["after"]["image_sha"] and ad.headline == p["after"]["headline"]
    assert o.audit.verify()["ok"] is True
    assert {"proposal.created", "action.approved", "execution.succeeded", "verification.passed"} <= set(types(o))


def test_propose_is_idempotent_and_an_existing_name_is_refused():
    o = orch()
    assert o.propose_ad("A")["id"] == o.propose_ad("A")["id"]
    with pytest.raises(InvalidTransition):
        o.propose_ad("Welcome new patients (sample)")


@pytest.mark.parametrize("name", ["", "x" * 61, "<script>", "a/b"])
def test_bad_ad_names_are_refused(name):
    with pytest.raises(PolicyViolation):
        orch().propose_ad(name)


def test_second_blocked_ad_means_no_proposal():
    o = orch()

    class Bad:
        def draft(self, name, feedback=None):
            from app.muse.ads import AdDraft
            return AdDraft("Guaranteed results", "Free whitening", ["x"])
    o.ad_studio = Bad()
    assert o.propose_ad("B")["status"] == "needs_human"
    assert o.store.one("SELECT 1 FROM proposals WHERE kind='ad'") is None


def test_no_passing_picture_means_no_proposal():
    o = orch()
    o.ad_studio.fx["image_prompts"] = ["a smiling family", "a person with a toothbrush"]
    r = o.propose_ad("C")
    assert r["status"] == "needs_human" and "picture" in r["reason"]
    assert o.store.one("SELECT 1 FROM proposals WHERE kind='ad'") is None
    assert "ad.no_picture" in types(o)


def test_one_picture_failing_does_not_stop_the_others():
    o = orch()
    real = o.ad_studio.image

    def flaky(prompt):
        if "chair" in prompt:
            raise TimeoutError("slow")
        return real(prompt)
    o.ad_studio.image = flaky
    p = o.propose_ad("D")
    assert [c["passed"] for c in p["extra"]["candidates"]] == [False, False, True]
    assert p["extra"]["candidates"][0]["sha"] is None and p["after"]["image_sha"] == p["extra"]["candidates"][2]["sha"]


# ---------- the approval is bound to the exact ad ----------
def test_changing_the_picture_changes_the_hash_and_voids_the_old_approval():
    o = orch()
    p = o.propose_ad("E")
    other = p["extra"]["candidates"][2]["sha"]
    p2 = o.choose_picture(p["id"], other)
    assert p2["hash"] != p["hash"] and p2["after"]["image_sha"] == other
    with pytest.raises(HashMismatch):
        o.approve(p["id"], p["hash"])
    assert o.providers["Ads"].read_ad("E") is None
    assert o.approve(p["id"], p2["hash"])["state"] == "VERIFIED"


def test_a_picture_that_failed_its_check_cannot_be_chosen():
    o = orch()
    p = o.propose_ad("F")
    with pytest.raises(PolicyViolation):
        o.choose_picture(p["id"], p["extra"]["candidates"][1]["sha"])
    with pytest.raises(NotFound):
        o.choose_picture(p["id"], "f" * 64)


def test_editing_the_words_is_checked_and_rehashed():
    o = orch()
    p = o.propose_ad("G")
    with pytest.raises(PolicyViolation) as e:
        o.edit_ad(p["id"], headline="Best dentist, guaranteed")
    assert "results_claim" in {i.code for i in e.value.issues}
    q = o.edit_ad(p["id"], headline="Taking new patients", fmt="square")
    assert q["hash"] != p["hash"] and q["after"]["format"] == "square"
    with pytest.raises(HashMismatch):
        o.approve(p["id"], p["hash"])


def test_reply_endpoints_do_not_touch_ads():
    o = orch()
    p = o.propose_ad("H")
    with pytest.raises(InvalidTransition):
        o.edit_reply(p["id"], "Thank you.")
    r = o.propose_reply("g2")
    with pytest.raises(InvalidTransition):
        o.edit_ad(r["id"], headline="x")


# ---------- the executor re-reads before writing ----------
def test_name_taken_after_approval_blocks_the_write():
    o = orch()
    p = o.propose_ad("I")
    o.providers["Ads"].demo_create("I")                      # a teammate saves the same name
    out = o.approve(p["id"], p["hash"])
    assert out["state"] == "FAILED" and out["reason"] == "precondition_changed"
    assert o.providers["Ads"].read_ad("I").headline == "Teammate draft"
    assert o.audit.verify()["ok"] is True
    assert any("already exists" in e["detail"] for e in o.audit.events() if e["type"] == "execution.refused")


def test_picture_swapped_behind_the_apps_back_blocks_the_write():
    o = orch()
    p = o.propose_ad("J")
    sha = p["after"]["image_sha"]
    o.store.run("UPDATE images SET data=? WHERE sha=?", (o.image(sha)[1] + b"\x00", sha))
    out = o.approve(p["id"], p["hash"])
    assert out["state"] == "FAILED" and out["reason"] == "precondition_changed"
    assert o.providers["Ads"].read_ad("J") is None


def test_readback_mismatch_is_reported_not_hidden():
    o = orch()
    p = o.propose_ad("K")
    real = o.providers["Ads"].create_paused_draft

    def sloppy(name, headline, text, sha, fmt, idem):
        real(name, headline + "!", text, sha, fmt, idem)      # the account stored something different
    o.providers["Ads"].create_paused_draft = sloppy
    out = o.approve(p["id"], p["hash"])
    assert out["state"] == "FAILED" and out["reason"] == "verification_mismatch"


def test_ad_execute_is_idempotent_by_key():
    o = orch()
    p = o.propose_ad("L")
    o.approve(p["id"], p["hash"])
    a = p["after"]
    o.providers["Ads"].create_paused_draft(a["name"], "other", "other", a["image_sha"], "wide", o.get(p["id"])["idem"])
    assert o.providers["Ads"].read_ad("L").headline == p["after"]["headline"]


def test_reject_is_final_for_ads():
    o = orch()
    p = o.propose_ad("M")
    assert o.reject(p["id"], "not now")["state"] == "REJECTED"
    with pytest.raises(InvalidTransition):
        o.approve(p["id"], p["hash"])
    assert o.propose_ad("M")["attempt"] == 2


def test_replies_and_ads_share_one_audit_chain():
    o = orch()
    r = o.propose_reply("g2")
    a = o.propose_ad("N")
    o.approve(r["id"], r["hash"])
    o.approve(a["id"], a["hash"])
    assert o.audit.verify()["ok"] is True
    assert {e["proposal_id"] for e in o.audit.events(1000)} >= {r["id"], a["id"]}


