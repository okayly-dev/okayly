import json

import pytest

from app import policy
from app.domain import State
from app.errors import HashMismatch, InvalidTransition, NotFound, PolicyViolation
from app.muse.ads import MuseAdStudio, parse_ad_draft, parse_picture_check
from app.muse.loop import DraftError
from app.providers.sandbox import SandboxAdAccount
from app.wiring import build, load_fixture

FACTS = load_fixture()["facts"]


def orch():
    return build(db_path=":memory:", drafter="fixture")


def types(o):
    return [e["type"] for e in o.audit.events(1000)][::-1]


# ---------- ad rules ----------
@pytest.mark.parametrize("headline,text,code", [
    ("Smile before and after", "Come see.", "before_after"),
    ("Best dentist in town", "Call us.", "results_claim"),
    ("Painless care", "Call us.", "results_claim"),
    ("Welcome", "Results guaranteed.", "results_claim"),
    ("Free whitening", "Today only.", "price_claim"),
    ("Welcome", "Only $99 for a cleaning.", "price_claim"),
    ("Welcome", "Our patients love us.", "patient_proof"),
    ("Welcome", "We fix your pain fast.", "health_claim"),
    ("Welcome", "Call (555) 999-1234.", "unknown_phone"),
    ("x" * 41, "Hello there.", "headline_too_long"),
    ("Welcome", "x" * 126, "text_too_long"),
    ("", "Hello", "empty"),
])
def test_check_ad_blocks(headline, text, code):
    assert code in {i.code for i in policy.check_ad(headline, text, FACTS)}


def test_check_ad_allows_the_plain_version():
    assert policy.check_ad("Now welcoming new patients", "Brightwood Family Dental is taking new patients. Call (555) 010-0142 to book a time.", FACTS) == []


def test_a_price_is_allowed_only_when_the_practice_lists_it():
    facts = {**FACTS, "offers": ["$99 new patient exam"]}
    assert policy.check_ad("New patients", "A $99 new patient exam.", facts) == []
    assert policy.check_ad("New patients", "A $49 exam.", facts)[0].code == "price_claim"


PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20
GOOD = {"no_people": True, "no_before_after": True, "no_health_claim": True, "text_legible": True}


def test_image_gate_needs_every_check_to_be_exactly_true():
    assert policy.check_image(PNG, GOOD) == []
    for k in GOOD:
        assert {i.code for i in policy.check_image(PNG, {**GOOD, k: False})} == {k}
    assert policy.check_image(PNG, {**GOOD, "no_people": "true"})            # a string is not True
    assert policy.check_image(PNG, None)[0].code == "not_reviewed"
    assert policy.check_image(b"<svg onload=alert(1)>", GOOD)[0].code == "not_an_image"
    assert policy.check_image(PNG + b"x" * policy.MAX_IMAGE_BYTES, GOOD)[0].code == "image_too_big"


def test_image_type_comes_from_the_bytes():
    assert policy.sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8X") == "image/webp"
    assert policy.sniff_image(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert policy.sniff_image(b"GIF89a") is None


# ---------- the sandbox ad account ----------
def test_ad_account_cannot_activate_or_spend():
    assert not any(hasattr(SandboxAdAccount, n) for n in ("activate", "publish", "set_budget", "enable", "resume"))
    cols = {r["name"] for r in orch().store.all("PRAGMA table_info(ads)")}
    assert not cols & {"budget", "spend", "daily_budget"} and "status" in cols


def test_ad_status_can_only_be_paused():
    o = orch()
    with pytest.raises(Exception):
        o.store.run("UPDATE ads SET status='active'")


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


# ---------- Muse ad studio, with a scripted fake ----------
class _Item:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, output, text="", rid="r"):
        self.output, self.output_text, self.id = output, text, rid


class _FakeMuse:
    def __init__(self, script):
        self.script, self.sent = list(script), []

    def respond(self, **kw):
        self.sent.append(kw)
        return self.script.pop(0)


class _Ctx:
    def facts(self):
        return FACTS

    def ad_rules(self):
        return policy.AD_RULES_TEXT


def test_ad_studio_runs_the_tool_loop():
    call = lambda n, i: _Item(type="function_call", name=n, arguments="{}", call_id=f"c{i}")
    final = json.dumps({"headline": "Hi", "text": "There", "image_prompts": ["a", "b", "c", "d"], "facts_used": []})
    m = _FakeMuse([_Resp([call("ads.get_practice_facts", 1)], rid="r1"), _Resp([call("ads.get_ad_rules", 2)], rid="r2"),
                   _Resp([_Item(type="message")], text=final, rid="r3")])
    d = MuseAdStudio(m, _Ctx()).draft("Spring")
    assert d.headline == "Hi" and len(d.image_prompts) == 3        # capped at three pictures
    assert m.sent[2]["previous_response_id"] == "r2" and all(s["tools"] for s in m.sent)


def test_ad_studio_tools_reject_bad_arguments_and_have_no_write_tool():
    s = MuseAdStudio(None, _Ctx())
    assert "error" in s._run_tool("ads.get_practice_facts", "not json")
    assert "error" in s._run_tool("ads.get_practice_facts", '{"x":1}')
    assert "error" in s._run_tool("ads.create_ad", "{}")
    assert "rules" in s._run_tool("ads.get_ad_rules", "{}")


def test_picture_check_is_translated_by_code():
    raw = json.dumps({"has_people": True, "has_before_after": False, "has_health_claim": False, "text_hard_to_read": False, "notes": " a person "})
    r = parse_picture_check(raw)
    assert r["no_people"] is False and r["no_before_after"] is True and r["notes"] == "a person"
    for bad in ["nope", "{}", json.dumps({"has_people": "no", "has_before_after": False, "has_health_claim": False, "text_hard_to_read": False, "notes": ""})]:
        with pytest.raises(DraftError):
            parse_picture_check(bad)


def test_picture_check_sends_the_picture_as_an_image_input():
    ok = json.dumps({"has_people": False, "has_before_after": False, "has_health_claim": False, "text_hard_to_read": False, "notes": ""})
    m = _FakeMuse([_Resp([], text=ok)])
    out = MuseAdStudio(m, _Ctx()).review_image(PNG)
    assert out["no_people"] is True
    part = m.sent[0]["input"][0]["content"][1]
    assert part["type"] == "input_image" and part["image_url"].startswith("data:image/png;base64,")


def test_parse_ad_draft_validates_shape():
    ok = {"headline": "h", "text": "t", "image_prompts": ["p"], "facts_used": []}
    assert parse_ad_draft(json.dumps(ok)).headline == "h"
    for bad in [{}, {**ok, "image_prompts": []}, {**ok, "headline": 1}, {**ok, "image_prompts": [3]}, {**ok, "extra": 1}]:
        with pytest.raises(DraftError):
            parse_ad_draft(json.dumps(bad))
    with pytest.raises(DraftError):
        parse_ad_draft("not json")
