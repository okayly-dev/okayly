"""The ad studio's two Muse jobs: Spark writes the words, Muse Image makes pictures, and Spark
vision reads each picture back. Muse has no write tool here either. What it returns is only
a proposal that code checks (policy.check_ad, policy.check_image) before a person sees it."""
import base64
import hashlib
import json
from dataclasses import dataclass, field

from ..verification import policy
from .fixture_image import make_png
from .loop import DraftError, run_tool_loop
from .prompts import load_prompt
from .tools import AD_TOOLS, definitions, run_tool

SYSTEM = load_prompt("ad")

AD_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["headline", "text", "image_prompts", "facts_used"],
    "properties": {
        "headline": {"type": "string"}, "text": {"type": "string"},
        "image_prompts": {"type": "array", "items": {"type": "string"}},
        "facts_used": {"type": "array", "items": {"type": "string"}},
    },
}
AD_FORMAT = {"format": {"type": "json_schema", "name": "ad_draft", "strict": True, "schema": AD_SCHEMA}}

TOOLS = definitions(AD_TOOLS)

REVIEW_SYSTEM = load_prompt("picture_check")
REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["has_people", "has_before_after", "has_health_claim", "text_hard_to_read", "notes"],
    "properties": {
        "has_people": {"type": "boolean"},
        "has_before_after": {"type": "boolean"},
        "has_health_claim": {"type": "boolean"},
        "text_hard_to_read": {"type": "boolean"},
        "notes": {"type": "string"},
    },
}
REVIEW_FORMAT = {"format": {"type": "json_schema", "name": "picture_check", "strict": True, "schema": REVIEW_SCHEMA}}
MAX_PICTURES = 3


@dataclass
class AdDraft:
    headline: str
    text: str
    image_prompts: list[str] = field(default_factory=list)
    facts_used: list[str] = field(default_factory=list)
    tools_used: list[dict] = field(default_factory=list)   # which read tools Muse called (names and answer sizes only)


def parse_ad_draft(text: str) -> AdDraft:
    try:
        draft_data = json.loads(text)
    except (TypeError, ValueError) as error:
        raise DraftError("Muse did not return JSON") from error
    valid = (isinstance(draft_data, dict) and set(draft_data) == {"headline", "text", "image_prompts", "facts_used"}
          and isinstance(draft_data["headline"], str) and isinstance(draft_data["text"], str)
          and isinstance(draft_data["image_prompts"], list) and all(isinstance(item, str) and item.strip() for item in draft_data["image_prompts"])
          and isinstance(draft_data["facts_used"], list) and all(isinstance(item, str) for item in draft_data["facts_used"]))
    if not valid or not draft_data["image_prompts"]:
        raise DraftError("Muse returned JSON that does not match the schema")
    return AdDraft(draft_data["headline"].strip(), draft_data["text"].strip(), [prompt_text.strip() for prompt_text in draft_data["image_prompts"]][:MAX_PICTURES], draft_data["facts_used"])


def parse_picture_check(text: str) -> dict:
    """Spark reports what it sees (has_*). Code turns that into the positive checks the policy needs."""
    try:
        check = json.loads(text)
    except (TypeError, ValueError) as error:
        raise DraftError("Muse did not return JSON") from error
    keys = ("has_people", "has_before_after", "has_health_claim", "text_hard_to_read")
    if not (isinstance(check, dict) and set(check) == {*keys, "notes"} and all(isinstance(check[k], bool) for k in keys) and isinstance(check["notes"], str)):
        raise DraftError("Muse returned JSON that does not match the schema")
    return {"no_people": not check["has_people"], "no_before_after": not check["has_before_after"],
            "no_health_claim": not check["has_health_claim"], "text_legible": not check["text_hard_to_read"], "notes": check["notes"].strip()}


class MuseAdStudio:
    """context must offer: facts() -> dict, ad_rules() -> str."""

    def __init__(self, muse, context):
        self.muse, self.ctx = muse, context

    def draft(self, name: str, feedback: dict | None = None) -> AdDraft:
        prompt = f"Write the ad for a draft named {json.dumps(name)}. Read the practice details and the ad rules with the tools first."
        if feedback:
            prompt += (f"\n\nYour previous ad was blocked by our checks.\nHeadline: {feedback['headline']}\nText: {feedback['text']}\n"
                       f"Reasons: {' '.join(feedback['issues'])}\nWrite a new ad that fixes every reason.")
        tool_log = []
        draft = run_tool_loop(self.muse, prompt=prompt, instructions=SYSTEM, tools=TOOLS, text_format=AD_FORMAT,
                              run_tool=lambda name, args: run_tool(AD_TOOLS, self.ctx, name, args), parse=parse_ad_draft,
                              purpose="ad_draft", tool_log=tool_log)
        draft.tools_used = tool_log
        return draft

    def image(self, prompt: str) -> bytes:
        return self.muse.generate_image(prompt)

    def review_image(self, data: bytes) -> dict:
        mime = policy.sniff_image(data) or "image/png"
        uri = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        response = self.muse.respond(
            input=[{"role": "user", "content": [{"type": "input_text", "text": "Check this ad picture."},
                                                {"type": "input_image", "image_url": uri}]}],
            instructions=REVIEW_SYSTEM, text_format=REVIEW_FORMAT, purpose="ad_picture_check")
        return parse_picture_check(response.output_text)


class FixtureAdStudio:
    """Offline studio for tests and the no-spend demo. Pictures are small generated placeholders,
    and a picture whose prompt mentions people is reported as showing people, so the picture
    check has something to stop."""
    PEOPLE = ("family", "smiling", "a person", "patient", "child")   # not "people": prompts say "no people"

    def __init__(self, fixture: dict):
        self.fx = fixture
        self._seen: dict[str, str] = {}

    def draft(self, name: str, feedback: dict | None = None) -> AdDraft:
        item = self.fx["rewrite"] if feedback and "rewrite" in self.fx else self.fx["first"]
        return AdDraft(item["headline"], item["text"], list(self.fx["image_prompts"]), item.get("facts_used", []))

    def image(self, prompt: str) -> bytes:
        seed = hashlib.sha256(prompt.encode()).digest()
        base = (60 + seed[0] % 40, 140 + seed[1] % 60, 190 + seed[2] % 50)
        rows = []
        for row_number in range(96):
            row = []
            for _ in range(96):
                for channel in base:
                    row.append(min(255, channel + (row_number * 40) // 96))
            rows.append(row)
        data = make_png(96, 96, rows)
        self._seen[hashlib.sha256(data).hexdigest()] = prompt
        return data

    def review_image(self, data: bytes) -> dict:
        prompt = self._seen.get(hashlib.sha256(data).hexdigest(), "")
        people = any(word in prompt.lower() for word in self.PEOPLE)
        return {"no_people": not people, "no_before_after": True, "no_health_claim": True, "text_legible": True,
                "notes": "People in the picture." if people else "Flat illustration, no people, no text."}
