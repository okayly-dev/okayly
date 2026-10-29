"""Drafting a review reply with Muse Spark.

Data and instructions stay apart: the review text never appears in the prompt. Muse reads it
only through a read tool, which labels it as untrusted customer text. Muse has no write tool;
its only output is a structured draft that code checks before a person sees it."""
import json
from dataclasses import dataclass, field

from .loop import DraftError, run_tool_loop
from .prompts import load_prompt
from .tools import REVIEW_TOOLS, definitions, run_tool

SYSTEM = load_prompt("reply")

DRAFT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["reply", "facts_used", "escalate", "escalate_reason"],
    "properties": {
        "reply": {"type": "string"},
        "facts_used": {"type": "array", "items": {"type": "string"}},
        "escalate": {"type": "boolean"},
        "escalate_reason": {"type": "string"},
    },
}
DRAFT_FORMAT = {"format": {"type": "json_schema", "name": "review_reply", "strict": True, "schema": DRAFT_SCHEMA}}

TOOLS = definitions(REVIEW_TOOLS)


@dataclass
class Draft:
    reply: str
    facts_used: list[str] = field(default_factory=list)
    escalate: bool = False
    escalate_reason: str = ""
    tools_used: list[dict] = field(default_factory=list)   # which read tools Muse called (names and answer sizes only)


def parse_draft(text: str) -> Draft:
    try:
        draft_data = json.loads(text)
    except (TypeError, ValueError) as error:
        raise DraftError("Muse did not return JSON") from error
    valid = (isinstance(draft_data, dict) and set(draft_data) == {"reply", "facts_used", "escalate", "escalate_reason"}
          and isinstance(draft_data["reply"], str) and isinstance(draft_data["escalate"], bool) and isinstance(draft_data["escalate_reason"], str)
          and isinstance(draft_data["facts_used"], list) and all(isinstance(fact, str) for fact in draft_data["facts_used"]))
    if not valid:
        raise DraftError("Muse returned JSON that does not match the schema")
    return Draft(draft_data["reply"].strip(), draft_data["facts_used"], draft_data["escalate"], draft_data["escalate_reason"].strip())


class MuseDrafter:
    """context must offer: review(id) -> ReviewState, facts() -> dict, past_replies(n) -> list[str]."""

    def __init__(self, muse, context):
        self.muse = muse
        self.ctx = context

    def draft(self, review_id: str, feedback: dict | None = None) -> Draft:
        prompt = f"Draft a reply for review id {review_id}. Read everything you need with the tools."
        if feedback:
            prompt += (f"\n\nYour previous draft was blocked by our checks.\nPrevious draft: {feedback['reply']}\n"
                       f"Reasons: {' '.join(feedback['issues'])}\nWrite a new draft that fixes every reason.")
        tool_log = []
        draft = run_tool_loop(self.muse, prompt=prompt, instructions=SYSTEM, tools=TOOLS, text_format=DRAFT_FORMAT,
                              run_tool=lambda name, args: run_tool(REVIEW_TOOLS, self.ctx, name, args), parse=parse_draft,
                              purpose="review_reply_draft", tool_log=tool_log)
        draft.tools_used = tool_log
        return draft


class FixtureDrafter:
    """Offline drafter for tests and the no-spend demo. fixture_drafts maps review id to
    [first draft, rewrite]; the rewrite is used when the first draft was blocked."""

    def __init__(self, fixture_drafts: dict):
        self.fx = fixture_drafts

    def draft(self, review_id: str, feedback: dict | None = None) -> Draft:
        draft_data = self.fx.get(review_id)
        if draft_data is None:
            return Draft("", [], True, "No draft available for this review.")
        item = draft_data["rewrite"] if feedback and "rewrite" in draft_data else draft_data["first"]
        return Draft(item.get("reply", ""), item.get("facts_used", []), item.get("escalate", False), item.get("escalate_reason", ""))
