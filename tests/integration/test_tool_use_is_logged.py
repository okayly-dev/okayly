"""Each draft from Muse leaves one audit entry naming the read tools it used and how big each answer was.
The customer's words are never copied into that entry."""
import json
from types import SimpleNamespace as NS

from app.agents.ads import AdDraft
from app.agents.reviews import MuseDrafter
from app.wiring import build

GOOD_REPLY = json.dumps({"reply": "Thank you for taking the time to share this.", "facts_used": [],
                         "escalate": False, "escalate_reason": ""})


class ScriptedMuse:
    """Plays a fixed conversation: ask for the review, ask for the practice facts, then answer."""
    def __init__(self):
        self.steps = [
            ("reviews.get_review", json.dumps({"review_id": "g2"})),
            ("reviews.get_practice_facts", "{}"),
            ("exec.post_reply", json.dumps({"review_id": "g2"})),     # a write tool Muse should not have
        ]

    def respond(self, **_):
        if self.steps:
            name, args = self.steps.pop(0)
            return NS(id=f"r{len(self.steps)}", output_text="", output=[NS(type="function_call", name=name, arguments=args, call_id="c")])
        return NS(id="last", output_text=GOOD_REPLY, output=[])


def tool_events(o):
    return [e for e in o.audit.events(1000) if e["type"] == "draft.tools_used"]


def test_a_muse_draft_logs_the_tools_it_used_and_no_customer_text():
    o = build(db_path=":memory:", drafter="fixture")
    o.drafter = MuseDrafter(ScriptedMuse(), o.drafter_context())
    p = o.propose_reply("g2")
    assert p["state"] == "PROPOSED"
    (event,) = tool_events(o)
    assert event["proposal_id"] == p["id"]
    assert "reviews.get_review" in event["detail"] and "reviews.get_practice_facts" in event["detail"]
    assert "exec.post_reply" in event["detail"] and "(error)" in event["detail"]     # the refused write attempt is on record
    assert "3" in event["plain"]
    review_text = o.providers["Google"].read_review("g2").text
    assert not any(review_text in e["plain"] + e["detail"] for e in o.audit.events(1000))
    assert o.audit.verify()["ok"] is True


def test_a_draft_that_used_no_tools_writes_no_tool_entry():
    o = build(db_path=":memory:", drafter="fixture")
    o.propose_reply("g2")
    assert tool_events(o) == []


def test_an_ad_draft_logs_its_tools_too():
    o = build(db_path=":memory:", drafter="fixture")
    real = o.ad_studio.draft

    def draft(name, feedback=None):
        d = real(name, feedback)
        d.tools_used = [{"tool": "ads.get_ad_rules", "chars": 120, "error": False}]
        return d
    o.ad_studio.draft = draft
    p = o.propose_ad("Tool log ad")
    (event,) = tool_events(o)
    assert event["proposal_id"] == p["id"] and "ads.get_ad_rules 120 chars" in event["detail"]
