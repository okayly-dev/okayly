"""Each draft from Muse leaves one audit entry naming the read tools it used and how big each answer was.
The customer's words are never copied into that entry."""
import json
from types import SimpleNamespace as NS

from app.agents.ads import AdDraft
from app.agents.loop import REFUSED_NAME
from app.agents.reviews import MuseDrafter
from app.wiring import build
from app.workflows.propose import tools_entry

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
    assert "exec.post_reply" not in event["detail"]          # a name Muse was never offered is not copied into the record
    assert REFUSED_NAME in event["detail"] and "(refused)" in event["detail"]
    assert event["plain"] == ("Before writing, Muse looked up 2 things (read-only). "
                              "It also asked for 1 thing it is not allowed to use; that was refused.")
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


HOSTILE_NAMES = ["Jane Doe had a root canal on Tuesday", "<script>alert(1)</script>", "reviews.get_review\nfake line",
                 "Reviews.Get_Review", "reviews.get_review ", "x" * 500, ""]


def test_hostile_tool_names_never_reach_the_audit_log_or_the_page_text():
    class HostileMuse(ScriptedMuse):
        def __init__(self, names):
            self.steps = [(name, "{}") for name in names] + [("reviews.get_review", json.dumps({"review_id": "g2"}))]
    for names in (HOSTILE_NAMES[:3], HOSTILE_NAMES[3:6], HOSTILE_NAMES[6:]):      # the loop allows only a few rounds per draft
        o = build(db_path=":memory:", drafter="fixture")
        o.drafter = MuseDrafter(HostileMuse(names), o.drafter_context())
        assert o.propose_reply("g2")["state"] == "PROPOSED"
        (event,) = tool_events(o)
        everything = " ".join(e["plain"] + " " + e["detail"] for e in o.audit.events(1000))
        for name in names:
            if name and "reviews.get_review" not in name:      # a near-copy of the real name is a prefix of the honest entry
                assert name not in everything
        assert event["detail"].count("reviews.get_review") == 1     # only the one real lookup is named
        assert "<" not in event["detail"] and "\n" not in event["detail"] and "x" * 20 not in event["detail"]
        assert event["plain"].startswith("Before writing, Muse looked up 1 thing (read-only).")
        assert o.audit.verify()["ok"] is True


def test_the_sentence_counts_failed_and_refused_requests_separately():
    entry = {"tool": "reviews.get_review", "chars": 40, "error": True, "refused": False}
    plain, detail = tools_entry([entry, {"tool": "reviews.get_practice_facts", "chars": 90, "error": False, "refused": False}])
    assert plain == "Before writing, Muse looked up 1 thing (read-only). 1 lookup returned an error."
    assert detail == "reviews.get_review 40 chars (error); reviews.get_practice_facts 90 chars"
    plain, _ = tools_entry([{"tool": REFUSED_NAME, "chars": 20, "error": True, "refused": True}])
    assert plain == "Before writing, Muse looked nothing up. It asked for 1 thing it is not allowed to use; that was refused."
