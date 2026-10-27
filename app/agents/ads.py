"""The ad studio's two Muse jobs: Spark writes the words, Muse Image makes pictures, and Spark
vision reads each picture back. Muse has no write tool here either. What it returns is only
a proposal that code checks (policy.check_ad, policy.check_image) before a person sees it."""
import base64
import hashlib
import json
import struct
import zlib
from dataclasses import dataclass, field

from ..verification import policy
from .loop import DraftError, load_args, run_tool_loop

SYSTEM = """You write one short Facebook and Instagram ad for a dental practice. A person approves it before it is saved, and it is saved paused.
Rules:
- Read the practice details with ads.get_practice_facts and the ad rules with ads.get_ad_rules first.
- Headline up to 40 characters, text up to 125. Plain words, warm, no jargon.
- No before-and-after, no results, guarantees or health claims, no ratings, awards or "best" claims, no talk of patients or reviews.
- No prices, discounts or free offers unless the practice details list them. Use only facts from the practice details.
- Give exactly 3 picture prompts. Each describes a flat, calm illustration or object. No people, no faces, no teeth close-ups, no text in the picture.
Answer in the required JSON."""

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

TOOLS = [
    {"type": "function", "name": "ads.get_practice_facts", "strict": True,
     "description": "Read the practice's approved details: name, phone, hours, voice and tone.",
     "parameters": {"type": "object", "additionalProperties": False, "required": [], "properties": {}}},
    {"type": "function", "name": "ads.get_ad_rules", "strict": True,
     "description": "Read the rules every ad and picture must follow.",
     "parameters": {"type": "object", "additionalProperties": False, "required": [], "properties": {}}},
]

REVIEW_SYSTEM = """You check one ad picture for a dental practice. Report only what you can see. Do not judge quality or style.
- has_people: any person, face, body part, or hand
- has_before_after: two states shown side by side, or a comparison of teeth
- has_health_claim: anything that suggests a treatment result, a health condition, or a medical symbol used as a promise
- text_hard_to_read: there is text and it would be small or unclear on a phone. False if there is no text.
Answer in the required JSON."""
REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["has_people", "has_before_after", "has_health_claim", "text_hard_to_read", "notes"],
    "properties": {k: {"type": "boolean"} for k in ("has_people", "has_before_after", "has_health_claim", "text_hard_to_read")}
    | {"notes": {"type": "string"}},
}
REVIEW_FORMAT = {"format": {"type": "json_schema", "name": "picture_check", "strict": True, "schema": REVIEW_SCHEMA}}
MAX_PICTURES = 3


@dataclass
class AdDraft:
    headline: str
    text: str
    image_prompts: list[str] = field(default_factory=list)
    facts_used: list[str] = field(default_factory=list)


def parse_ad_draft(text: str) -> AdDraft:
    try:
        d = json.loads(text)
    except (TypeError, ValueError) as e:
        raise DraftError("Muse did not return JSON") from e
    ok = (isinstance(d, dict) and set(d) == {"headline", "text", "image_prompts", "facts_used"}
          and isinstance(d["headline"], str) and isinstance(d["text"], str)
          and isinstance(d["image_prompts"], list) and all(isinstance(x, str) and x.strip() for x in d["image_prompts"])
          and isinstance(d["facts_used"], list) and all(isinstance(x, str) for x in d["facts_used"]))
    if not ok or not d["image_prompts"]:
        raise DraftError("Muse returned JSON that does not match the schema")
    return AdDraft(d["headline"].strip(), d["text"].strip(), [p.strip() for p in d["image_prompts"]][:MAX_PICTURES], d["facts_used"])


def parse_picture_check(text: str) -> dict:
    """Spark reports what it sees (has_*). Code turns that into the positive checks the policy needs."""
    try:
        d = json.loads(text)
    except (TypeError, ValueError) as e:
        raise DraftError("Muse did not return JSON") from e
    keys = ("has_people", "has_before_after", "has_health_claim", "text_hard_to_read")
    if not (isinstance(d, dict) and set(d) == {*keys, "notes"} and all(isinstance(d[k], bool) for k in keys) and isinstance(d["notes"], str)):
        raise DraftError("Muse returned JSON that does not match the schema")
    return {"no_people": not d["has_people"], "no_before_after": not d["has_before_after"],
            "no_health_claim": not d["has_health_claim"], "text_legible": not d["text_hard_to_read"], "notes": d["notes"].strip()}


class MuseAdStudio:
    """context must offer: facts() -> dict, ad_rules() -> str."""

    def __init__(self, muse, context):
        self.muse, self.ctx = muse, context

    def _run_tool(self, name: str, raw_args: str) -> dict:
        args = load_args(raw_args)
        if args is None or args:
            return {"error": "this tool takes no arguments; send {}"}
        if name == "ads.get_practice_facts":
            return self.ctx.facts()
        if name == "ads.get_ad_rules":
            return {"rules": self.ctx.ad_rules()}
        return {"error": f"unknown tool {name}"}

    def draft(self, name: str, feedback: dict | None = None) -> AdDraft:
        prompt = f"Write the ad for a draft named {json.dumps(name)}. Read the practice details and the ad rules with the tools first."
        if feedback:
            prompt += (f"\n\nYour previous ad was blocked by our checks.\nHeadline: {feedback['headline']}\nText: {feedback['text']}\n"
                       f"Reasons: {' '.join(feedback['issues'])}\nWrite a new ad that fixes every reason.")
        return run_tool_loop(self.muse, prompt=prompt, instructions=SYSTEM, tools=TOOLS, text_format=AD_FORMAT,
                             run_tool=self._run_tool, parse=parse_ad_draft, purpose="ad_draft")

    def image(self, prompt: str) -> bytes:
        return self.muse.generate_image(prompt)

    def review_image(self, data: bytes) -> dict:
        mime = policy.sniff_image(data) or "image/png"
        uri = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        r = self.muse.respond(
            input=[{"role": "user", "content": [{"type": "input_text", "text": "Check this ad picture."},
                                                {"type": "input_image", "image_url": uri}]}],
            instructions=REVIEW_SYSTEM, text_format=REVIEW_FORMAT, purpose="ad_picture_check")
        return parse_picture_check(r.output_text)


def _png(w: int, h: int, rgb_rows) -> bytes:
    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(row) for row in rgb_rows)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


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
        rows = [[min(255, c + (y * 40) // 96) for _ in range(96) for c in base] for y in range(96)]
        data = _png(96, 96, rows)
        self._seen[hashlib.sha256(data).hexdigest()] = prompt
        return data

    def review_image(self, data: bytes) -> dict:
        prompt = self._seen.get(hashlib.sha256(data).hexdigest(), "")
        people = any(w in prompt.lower() for w in self.PEOPLE)
        return {"no_people": not people, "no_before_after": True, "no_health_claim": True, "text_legible": True,
                "notes": "People in the picture." if people else "Flat illustration, no people, no text."}
