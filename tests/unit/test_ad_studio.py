from app.agents.tools import AD_TOOLS, run_tool
import json

import pytest

from app.verification import policy
from app.agents.ads import MuseAdStudio, parse_ad_draft, parse_picture_check
from app.agents.loop import DraftError
from app.wiring import load_fixture


FACTS = load_fixture()["facts"]


PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20
GOOD = {"no_people": True, "no_before_after": True, "no_health_claim": True, "text_legible": True}


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
    assert "error" in run_tool(AD_TOOLS, _Ctx(), "ads.get_practice_facts", "not json")
    assert "error" in run_tool(AD_TOOLS, _Ctx(), "ads.get_practice_facts", '{"x":1}')
    assert "error" in run_tool(AD_TOOLS, _Ctx(), "ads.create_ad", "{}")
    assert "rules" in run_tool(AD_TOOLS, _Ctx(), "ads.get_ad_rules", "{}")


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
