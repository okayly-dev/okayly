import pytest

from app.verification import policy
from app.core.domain import ReviewState
from app.wiring import load_fixture

FACTS = load_fixture()["facts"]


def rv(text="Waited a long time.", who="Dana M.", stars=2, rid="g1", platform="Google"):
    return ReviewState(rid, platform, stars, who, "Oct 25", text, None)


# ---------- policy ----------
@pytest.mark.parametrize("text,code", [
    ("We are sorry your crown appointment ran late.", "confirms_patient"),
    ("As our patient you matter to us.", "confirms_patient"),
    ("We promise your next visit will be on time.", "promise"),
    ("We will give you a full refund.", "promise"),
    ("You should take an antibiotic for the swelling.", "health_advice"),
    ("Hi Dana, thank you for telling us.", "uses_name"),
    ("Please call (555) 999-1234.", "unknown_phone"),
    ("x" * 601, "too_long"),
    ("", "empty"),
])
def test_policy_blocks(text, code):
    assert code in {i.code for i in policy.check_reply(text, rv(), FACTS)}


def test_policy_allows_good_replies():
    fx = load_fixture()
    for did in ("g1", "g2", "y1"):
        text = (fx["fixture_drafts"][did].get("rewrite") or fx["fixture_drafts"][did]["first"])["reply"]
        review = next(r for r in fx["reviews"] if r["id"] == did)
        r = ReviewState(did, review["platform"], review["stars"], review["who"], review["date"], review["text"], None)
        assert policy.check_reply(text, r, FACTS) == [], did


def test_needs_human_for_legal_and_billing():
    assert policy.needs_human(rv("I was billed twice and I am talking to a lawyer.")) is not None
    assert policy.needs_human(rv("Great team.")) is None


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




# ---------- T2b: closed gaps (each pairs a blocked input with a near-miss that must stay clean) ----------
@pytest.mark.parametrize("blocked,allowed", [
    ("As one of our patients, your comments matter.", "As one of our neighbors, your comments matter."),
    ("See you at your next routine cleaning.", "We hope your next week goes smoothly."),
    ("We guarantee your next visit will be perfect.", "We hope your next visitor finds this useful."),
])
def test_patient_confirmation_variants_are_narrow(blocked, allowed):
    assert "confirms_patient" in {i.code for i in policy.check_reply(blocked, rv(), FACTS)}
    assert "confirms_patient" not in {i.code for i in policy.check_reply(allowed, rv(), FACTS)}


@pytest.mark.parametrize("blocked,allowed", [
    ("Visit hтtps://example.invalid/help for details.", "The hтtps protocol was mentioned."),
    ("Visit www . example . invalid for details.", "The abbreviation www was discussed."),
])
def test_disguised_links_are_blocked_without_blocking_plain_text(blocked, allowed):
    empty_facts = {"phones": [], "urls": []}
    assert "unknown_link" in {i.code for i in policy.check_reply(blocked, rv(), empty_facts)}
    assert "unknown_link" not in {i.code for i in policy.check_reply(allowed, rv(), empty_facts)}


def test_free_treatment_is_a_promise_but_free_to_contact_is_not():
    assert "promise" in {i.code for i in policy.check_reply("We offer a free implant.", rv(), FACTS)}
    assert "promise" not in {i.code for i in policy.check_reply("Feel free to contact the office.", rv(), FACTS)}


@pytest.mark.parametrize("text", [
    "I am going to the police about this.", "I will start a lawsuit.", "A class action lawsuit is coming.",
    "They submitted a fraudulent insurance claim in my name.", "You will hear from my lawyer.",
])
def test_serious_legal_and_fraud_reviews_still_need_a_person(text):
    assert policy.needs_human(rv(text)) is not None


def test_hyphenated_before_and_after_is_blocked_but_timing_is_not():
    assert "before_after" in {i.code for i in policy.check_ad("Welcome", "See our before-and-after gallery.", FACTS)}
    assert "before_after" not in {i.code for i in policy.check_ad("Welcome", "Call before or after work.", FACTS)}


def test_spelled_out_star_rating_is_blocked_but_plain_star_word_is_not():
    assert "results_claim" in {i.code for i in policy.check_ad("Five-Star Team", "A friendly local office.", FACTS)}
    assert "results_claim" not in {i.code for i in policy.check_ad("Star Team", "A friendly local office.", FACTS)}
