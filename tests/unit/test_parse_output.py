"""Characterization tests for the three parsers that screen Muse's JSON (reply draft, ad draft,
picture check). Each table lists inputs that must be accepted (with the exact result) and inputs
that must be refused (with the exact message). The tables were written against the code before
it was tidied and must keep passing unchanged."""
import json

import pytest

from app.agents.ads import MAX_PICTURES, parse_ad_draft, parse_picture_check
from app.agents.loop import DraftError
from app.agents.reviews import parse_draft

NOT_JSON = "Muse did not return JSON"
BAD_SCHEMA = "Muse returned JSON that does not match the schema"


def changed(base: dict, **changes) -> dict:
    """A copy of base with some fields replaced."""
    return {**base, **changes}


def without(base: dict, key: str) -> dict:
    return {name: value for name, value in base.items() if name != key}


def as_text(value) -> str:
    return json.dumps(value)


def assert_refused(parser, text, message):
    with pytest.raises(DraftError) as caught:
        parser(text)
    assert str(caught.value) == message


# ---------------------------------------------------------------- reply draft
REPLY = {"reply": "Thank you.", "facts_used": ["hours"], "escalate": False, "escalate_reason": ""}


def reply_values(draft):
    return draft.reply, draft.facts_used, draft.escalate, draft.escalate_reason, draft.tools_used


REPLY_ACCEPTED = [
    ("minimal", as_text(REPLY), ("Thank you.", ["hours"], False, "", [])),
    ("empty facts list", as_text(changed(REPLY, facts_used=[])), ("Thank you.", [], False, "", [])),
    ("escalate true with reason", as_text(changed(REPLY, escalate=True, escalate_reason="legal threat")),
     ("Thank you.", ["hours"], True, "legal threat", [])),
    ("extra whitespace around the JSON", "  \n" + json.dumps(REPLY, indent=4) + "\n  ", ("Thank you.", ["hours"], False, "", [])),
    ("reply is stripped", as_text(changed(REPLY, reply="  \n Thanks! \t")), ("Thanks!", ["hours"], False, "", [])),
    ("escalate_reason is stripped", as_text(changed(REPLY, escalate_reason="  why  ")), ("Thank you.", ["hours"], False, "why", [])),
    ("facts are kept as they are (not stripped)", as_text(changed(REPLY, facts_used=[" a ", ""])), ("Thank you.", [" a ", ""], False, "", [])),
    ("empty reply is accepted here", as_text(changed(REPLY, reply="")), ("", ["hours"], False, "", [])),
    ("blank reply becomes empty", as_text(changed(REPLY, reply="   ")), ("", ["hours"], False, "", [])),
    ("key order does not matter", '{"escalate_reason":"","escalate":false,"facts_used":[],"reply":"x"}', ("x", [], False, "", [])),
]


@pytest.mark.parametrize("name, text, expected", REPLY_ACCEPTED, ids=[row[0] for row in REPLY_ACCEPTED])
def test_reply_draft_accepted(name, text, expected):
    assert reply_values(parse_draft(text)) == expected


REPLY_REFUSED = [
    ("extra key", as_text(changed(REPLY, mood="happy")), BAD_SCHEMA),
    ("missing reply", as_text(without(REPLY, "reply")), BAD_SCHEMA),
    ("missing facts_used", as_text(without(REPLY, "facts_used")), BAD_SCHEMA),
    ("missing escalate", as_text(without(REPLY, "escalate")), BAD_SCHEMA),
    ("missing escalate_reason", as_text(without(REPLY, "escalate_reason")), BAD_SCHEMA),
    ("reply is a number", as_text(changed(REPLY, reply=1)), BAD_SCHEMA),
    ("reply is a bool", as_text(changed(REPLY, reply=True)), BAD_SCHEMA),
    ("reply is null", as_text(changed(REPLY, reply=None)), BAD_SCHEMA),
    ("reply is a list", as_text(changed(REPLY, reply=["hi"])), BAD_SCHEMA),
    ("escalate is a string", as_text(changed(REPLY, escalate="no")), BAD_SCHEMA),
    ("escalate is the string false", as_text(changed(REPLY, escalate="false")), BAD_SCHEMA),
    ("escalate is the number 0", as_text(changed(REPLY, escalate=0)), BAD_SCHEMA),
    ("escalate is the number 1", as_text(changed(REPLY, escalate=1)), BAD_SCHEMA),
    ("escalate is null", as_text(changed(REPLY, escalate=None)), BAD_SCHEMA),
    ("escalate_reason is a bool", as_text(changed(REPLY, escalate_reason=False)), BAD_SCHEMA),
    ("escalate_reason is a number", as_text(changed(REPLY, escalate_reason=5)), BAD_SCHEMA),
    ("escalate_reason is null", as_text(changed(REPLY, escalate_reason=None)), BAD_SCHEMA),
    ("facts_used is a string", as_text(changed(REPLY, facts_used="hours")), BAD_SCHEMA),
    ("facts_used is null", as_text(changed(REPLY, facts_used=None)), BAD_SCHEMA),
    ("facts_used is an object", as_text(changed(REPLY, facts_used={"a": "b"})), BAD_SCHEMA),
    ("facts_used holds a number", as_text(changed(REPLY, facts_used=["a", 2])), BAD_SCHEMA),
    ("facts_used holds a bool", as_text(changed(REPLY, facts_used=[True])), BAD_SCHEMA),
    ("facts_used holds null", as_text(changed(REPLY, facts_used=[None])), BAD_SCHEMA),
    ("facts_used holds a list", as_text(changed(REPLY, facts_used=[["a"]])), BAD_SCHEMA),
    ("top level is a list", as_text([REPLY]), BAD_SCHEMA),
    ("top level is a number", "7", BAD_SCHEMA),
    ("top level is a string", '"hello"', BAD_SCHEMA),
    ("top level is true", "true", BAD_SCHEMA),
    ("top level is null", "null", BAD_SCHEMA),
    ("empty object", "{}", BAD_SCHEMA),
    ("empty list", "[]", BAD_SCHEMA),
    ("not JSON", "not json", NOT_JSON),
    ("empty text", "", NOT_JSON),
    ("JSON cut off", '{"reply": "hi"', NOT_JSON),
    ("single quotes", "{'reply': 'hi'}", NOT_JSON),
    ("None instead of text", None, NOT_JSON),
]


@pytest.mark.parametrize("name, text, message", REPLY_REFUSED, ids=[row[0] for row in REPLY_REFUSED])
def test_reply_draft_refused(name, text, message):
    assert_refused(parse_draft, text, message)


# ------------------------------------------------------------------ ad draft
AD = {"headline": "Check-ups", "text": "Book a visit.", "image_prompts": ["a clean waiting room"], "facts_used": ["hours"]}


def ad_values(draft):
    return draft.headline, draft.text, draft.image_prompts, draft.facts_used, draft.tools_used


AD_ACCEPTED = [
    ("minimal", as_text(AD), ("Check-ups", "Book a visit.", ["a clean waiting room"], ["hours"], [])),
    ("empty facts list", as_text(changed(AD, facts_used=[])), ("Check-ups", "Book a visit.", ["a clean waiting room"], [], [])),
    ("extra whitespace around the JSON", "\n  " + json.dumps(AD, indent=2) + "  \n", ("Check-ups", "Book a visit.", ["a clean waiting room"], ["hours"], [])),
    ("headline is stripped", as_text(changed(AD, headline="  Hi \n")), ("Hi", "Book a visit.", ["a clean waiting room"], ["hours"], [])),
    ("text is stripped", as_text(changed(AD, text="\t Come in ")), ("Check-ups", "Come in", ["a clean waiting room"], ["hours"], [])),
    ("picture prompts are stripped", as_text(changed(AD, image_prompts=["  one ", "\ttwo\n"])), ("Check-ups", "Book a visit.", ["one", "two"], ["hours"], [])),
    ("facts are kept as they are (not stripped)", as_text(changed(AD, facts_used=[" a ", ""])), ("Check-ups", "Book a visit.", ["a clean waiting room"], [" a ", ""], [])),
    ("empty headline and text are accepted here", as_text(changed(AD, headline="", text="")), ("", "", ["a clean waiting room"], ["hours"], [])),
    ("exactly MAX_PICTURES prompts all kept", as_text(changed(AD, image_prompts=["p"] * MAX_PICTURES)), ("Check-ups", "Book a visit.", ["p"] * MAX_PICTURES, ["hours"], [])),
    ("more than MAX_PICTURES prompts are cut", as_text(changed(AD, image_prompts=[f"p{n}" for n in range(MAX_PICTURES + 2)])),
     ("Check-ups", "Book a visit.", [f"p{n}" for n in range(MAX_PICTURES)], ["hours"], [])),
]


@pytest.mark.parametrize("name, text, expected", AD_ACCEPTED, ids=[row[0] for row in AD_ACCEPTED])
def test_ad_draft_accepted(name, text, expected):
    assert ad_values(parse_ad_draft(text)) == expected


AD_REFUSED = [
    ("extra key", as_text(changed(AD, budget=5)), BAD_SCHEMA),
    ("missing headline", as_text(without(AD, "headline")), BAD_SCHEMA),
    ("missing text", as_text(without(AD, "text")), BAD_SCHEMA),
    ("missing image_prompts", as_text(without(AD, "image_prompts")), BAD_SCHEMA),
    ("missing facts_used", as_text(without(AD, "facts_used")), BAD_SCHEMA),
    ("headline is a number", as_text(changed(AD, headline=3)), BAD_SCHEMA),
    ("headline is a bool", as_text(changed(AD, headline=True)), BAD_SCHEMA),
    ("headline is null", as_text(changed(AD, headline=None)), BAD_SCHEMA),
    ("text is a bool", as_text(changed(AD, text=False)), BAD_SCHEMA),
    ("text is a list", as_text(changed(AD, text=["a"])), BAD_SCHEMA),
    ("image_prompts is a string", as_text(changed(AD, image_prompts="a picture")), BAD_SCHEMA),
    ("image_prompts is null", as_text(changed(AD, image_prompts=None)), BAD_SCHEMA),
    ("image_prompts is empty", as_text(changed(AD, image_prompts=[])), BAD_SCHEMA),
    ("image_prompts has an empty item", as_text(changed(AD, image_prompts=["fine", ""])), BAD_SCHEMA),
    ("image_prompts has a blank item", as_text(changed(AD, image_prompts=["fine", "  \n\t"])), BAD_SCHEMA),
    ("image_prompts only has a blank item", as_text(changed(AD, image_prompts=[" "])), BAD_SCHEMA),
    ("image_prompts holds a number", as_text(changed(AD, image_prompts=["fine", 4])), BAD_SCHEMA),
    ("image_prompts holds a bool", as_text(changed(AD, image_prompts=[True])), BAD_SCHEMA),
    ("image_prompts holds null", as_text(changed(AD, image_prompts=[None])), BAD_SCHEMA),
    ("a blank prompt beyond the cut is still refused", as_text(changed(AD, image_prompts=["a"] * MAX_PICTURES + [" "])), BAD_SCHEMA),
    ("facts_used is a string", as_text(changed(AD, facts_used="hours")), BAD_SCHEMA),
    ("facts_used is null", as_text(changed(AD, facts_used=None)), BAD_SCHEMA),
    ("facts_used holds a number", as_text(changed(AD, facts_used=[1])), BAD_SCHEMA),
    ("facts_used holds a bool", as_text(changed(AD, facts_used=[False])), BAD_SCHEMA),
    ("facts_used holds null", as_text(changed(AD, facts_used=[None])), BAD_SCHEMA),
    ("top level is a list", as_text([AD]), BAD_SCHEMA),
    ("top level is a number", "12", BAD_SCHEMA),
    ("top level is a string", '"ad"', BAD_SCHEMA),
    ("top level is null", "null", BAD_SCHEMA),
    ("empty object", "{}", BAD_SCHEMA),
    ("not JSON", "an ad", NOT_JSON),
    ("empty text", "", NOT_JSON),
    ("JSON cut off", '{"headline": "x", ', NOT_JSON),
    ("None instead of text", None, NOT_JSON),
]


@pytest.mark.parametrize("name, text, message", AD_REFUSED, ids=[row[0] for row in AD_REFUSED])
def test_ad_draft_refused(name, text, message):
    assert_refused(parse_ad_draft, text, message)


# -------------------------------------------------------------- picture check
CHECK = {"has_people": False, "has_before_after": False, "has_health_claim": False, "text_hard_to_read": False, "notes": "ok"}
ALL_PASS = {"no_people": True, "no_before_after": True, "no_health_claim": True, "text_legible": True}

CHECK_ACCEPTED = [
    ("all clear", as_text(CHECK), {**ALL_PASS, "notes": "ok"}),
    ("people seen", as_text(changed(CHECK, has_people=True)), {**ALL_PASS, "no_people": False, "notes": "ok"}),
    ("before and after seen", as_text(changed(CHECK, has_before_after=True)), {**ALL_PASS, "no_before_after": False, "notes": "ok"}),
    ("health claim seen", as_text(changed(CHECK, has_health_claim=True)), {**ALL_PASS, "no_health_claim": False, "notes": "ok"}),
    ("text hard to read", as_text(changed(CHECK, text_hard_to_read=True)), {**ALL_PASS, "text_legible": False, "notes": "ok"}),
    ("everything wrong", as_text(changed(CHECK, has_people=True, has_before_after=True, has_health_claim=True, text_hard_to_read=True)),
     {"no_people": False, "no_before_after": False, "no_health_claim": False, "text_legible": False, "notes": "ok"}),
    ("extra whitespace around the JSON", "\n " + json.dumps(CHECK, indent=3) + " \n", {**ALL_PASS, "notes": "ok"}),
    ("notes are stripped", as_text(changed(CHECK, notes="  seen \n")), {**ALL_PASS, "notes": "seen"}),
    ("empty notes are accepted", as_text(changed(CHECK, notes="")), {**ALL_PASS, "notes": ""}),
    ("key order does not matter", '{"notes":"n","text_hard_to_read":false,"has_health_claim":false,"has_before_after":false,"has_people":false}', {**ALL_PASS, "notes": "n"}),
]


@pytest.mark.parametrize("name, text, expected", CHECK_ACCEPTED, ids=[row[0] for row in CHECK_ACCEPTED])
def test_picture_check_accepted(name, text, expected):
    assert parse_picture_check(text) == expected


CHECK_FIELDS = ["has_people", "has_before_after", "has_health_claim", "text_hard_to_read"]
CHECK_REFUSED = [
    ("extra key", as_text(changed(CHECK, verdict="fine")), BAD_SCHEMA),
    ("missing notes", as_text(without(CHECK, "notes")), BAD_SCHEMA),
    *[(f"missing {key}", as_text(without(CHECK, key)), BAD_SCHEMA) for key in CHECK_FIELDS],
    *[(f"{key} is a string", as_text(changed(CHECK, **{key: "false"})), BAD_SCHEMA) for key in CHECK_FIELDS],
    *[(f"{key} is the number 0", as_text(changed(CHECK, **{key: 0})), BAD_SCHEMA) for key in CHECK_FIELDS],
    *[(f"{key} is the number 1", as_text(changed(CHECK, **{key: 1})), BAD_SCHEMA) for key in CHECK_FIELDS],
    *[(f"{key} is null", as_text(changed(CHECK, **{key: None})), BAD_SCHEMA) for key in CHECK_FIELDS],
    ("notes is a bool", as_text(changed(CHECK, notes=True)), BAD_SCHEMA),
    ("notes is a number", as_text(changed(CHECK, notes=3)), BAD_SCHEMA),
    ("notes is null", as_text(changed(CHECK, notes=None)), BAD_SCHEMA),
    ("notes is a list", as_text(changed(CHECK, notes=["ok"])), BAD_SCHEMA),
    ("top level is a list", as_text([CHECK]), BAD_SCHEMA),
    ("top level is a number", "1", BAD_SCHEMA),
    ("top level is a string", '"fine"', BAD_SCHEMA),
    ("top level is true", "true", BAD_SCHEMA),
    ("top level is null", "null", BAD_SCHEMA),
    ("empty object", "{}", BAD_SCHEMA),
    ("not JSON", "looks fine", NOT_JSON),
    ("empty text", "", NOT_JSON),
    ("JSON cut off", '{"has_people": false', NOT_JSON),
    ("None instead of text", None, NOT_JSON),
]


@pytest.mark.parametrize("name, text, message", CHECK_REFUSED, ids=[f"{row[0]} #{n}" for n, row in enumerate(CHECK_REFUSED)])
def test_picture_check_refused(name, text, message):
    assert_refused(parse_picture_check, text, message)
