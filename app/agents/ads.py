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
MAX_PICTURES = policy.AD_MAX_PICTURES   # 3: the most pictures any ad gets; a brief can ask for fewer


@dataclass
class AdDraft:
    headline: str
    text: str
    image_prompts: list[str] = field(default_factory=list)
    facts_used: list[str] = field(default_factory=list)
    tools_used: list[dict] = field(default_factory=list)   # which read tools Muse called (names and answer sizes only)


AD_KEYS = {"headline", "text", "image_prompts", "facts_used"}
PICTURE_FLAGS = ("has_people", "has_before_after", "has_health_claim", "text_hard_to_read")


def _is_list_of_strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _are_usable_picture_prompts(value) -> bool:
    """At least one prompt, and every prompt is text with something in it. How many we keep is decided by parse_ad_draft."""
    if not isinstance(value, list) or not value:
        return False
    return all(isinstance(prompt, str) and prompt.strip() for prompt in value)


def _ad_matches_schema(data) -> bool:
    """True only for an object with exactly the four keys, each of the right type."""
    if not isinstance(data, dict) or set(data) != AD_KEYS:
        return False
    if not isinstance(data["headline"], str) or not isinstance(data["text"], str):
        return False
    if not _are_usable_picture_prompts(data["image_prompts"]):
        return False
    return _is_list_of_strings(data["facts_used"])


def parse_ad_draft(text: str, count: int = MAX_PICTURES) -> AdDraft:
    """count is how many pictures the person asked for (1 to MAX_PICTURES). Extra prompts are cut; fewer are kept as sent."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as error:
        raise DraftError("Muse did not return JSON") from error
    if not _ad_matches_schema(data):
        raise DraftError("Muse returned JSON that does not match the schema")
    prompts = [prompt.strip() for prompt in data["image_prompts"]][:min(count, MAX_PICTURES)]
    return AdDraft(data["headline"].strip(), data["text"].strip(), prompts, data["facts_used"])


def _picture_check_matches_schema(data) -> bool:
    """True only for an object with the four yes/no flags (real true/false) and a notes string."""
    if not isinstance(data, dict) or set(data) != {*PICTURE_FLAGS, "notes"}:
        return False
    if not all(isinstance(data[flag], bool) for flag in PICTURE_FLAGS):   # 0 and 1 are refused
        return False
    return isinstance(data["notes"], str)


def parse_picture_check(text: str) -> dict:
    """Spark reports what it sees (has_*). Code turns that into the positive checks the policy needs."""
    try:
        check = json.loads(text)
    except (TypeError, ValueError) as error:
        raise DraftError("Muse did not return JSON") from error
    if not _picture_check_matches_schema(check):
        raise DraftError("Muse returned JSON that does not match the schema")
    return {"no_people": not check["has_people"], "no_before_after": not check["has_before_after"],
            "no_health_claim": not check["has_health_claim"], "text_legible": not check["text_hard_to_read"], "notes": check["notes"].strip()}


class _BriefContext:
    """The read-only context plus this one request's brief, so a tool can answer with it. The brief is never put in a prompt."""

    def __init__(self, context, brief):
        self._context, self._brief = context, brief

    def ad_brief(self):
        return self._brief

    def __getattr__(self, name):
        return getattr(self._context, name)


class MuseAdStudio:
    """context must offer: facts() -> dict, ad_rules() -> str."""

    def __init__(self, muse, context):
        self.muse, self.ctx = muse, context

    def draft(self, name: str, feedback: dict | None = None, brief: policy.AdBrief | None = None) -> AdDraft:
        prompt = f"Write the ad for a draft named {json.dumps(name)}. Read the practice details and the ad rules with the tools first."
        if brief is not None and brief.active:
            prompt += " The person left a brief: read it with the ads.get_ad_brief tool too."   # the words themselves only come back as that tool's answer
        context = _BriefContext(self.ctx, brief)
        count = brief.picture_count if brief is not None else MAX_PICTURES
        if feedback:
            prompt += (f"\n\nYour previous ad was blocked by our checks.\nHeadline: {feedback['headline']}\nText: {feedback['text']}\n"
                       f"Reasons: {' '.join(feedback['issues'])}\nWrite a new ad that fixes every reason.")
        tool_log = []
        draft = run_tool_loop(self.muse, prompt=prompt, instructions=SYSTEM, tools=TOOLS, text_format=AD_FORMAT,
                              run_tool=lambda name, args: run_tool(AD_TOOLS, context, name, args), parse=lambda text: parse_ad_draft(text, count),
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

    def draft(self, name: str, feedback: dict | None = None, brief: policy.AdBrief | None = None) -> AdDraft:
        item = self.fx["rewrite"] if feedback and "rewrite" in self.fx else self.fx["first"]
        count = brief.picture_count if brief is not None else MAX_PICTURES
        headline = (brief.headline_wish if brief is not None else "") or item["headline"]   # a headline idea already passed the ad rules
        return AdDraft(headline, item["text"], list(self.fx["image_prompts"])[:count], item.get("facts_used", []))

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
