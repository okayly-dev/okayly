"""Writes the one-line summaries for the News card. Muse gets the feed text as untrusted data,
has no tools, and can only return a summary for each item. It cannot change a link, date or source."""
import json
import re

from ..core.errors import DraftError
from ..core.messages import MUSE_BAD_OUTPUT
from .prompts import load_prompt

SYSTEM = load_prompt("news")

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["summaries"],
    "properties": {"summaries": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "summary"],
        "properties": {"id": {"type": "integer"}, "summary": {"type": "string"}}}}},
}
FORMAT = {"format": {"type": "json_schema", "name": "news_summaries", "strict": True, "schema": SCHEMA}}


def parse_summaries(text: str, count: int) -> list[str]:
    """One summary per item, in order. A missing or odd answer becomes an empty string; the caller
    then shows the item's own title instead."""
    try:
        data = json.loads(text)
        rows = data["summaries"]
    except (TypeError, ValueError, KeyError) as error:
        raise DraftError(MUSE_BAD_OUTPUT) from error
    summaries = [""] * count
    if not isinstance(rows, list):
        rows = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), int) and isinstance(row.get("summary"), str) \
                and 0 <= row["id"] < count:
            summaries[row["id"]] = row["summary"].strip()
    return summaries


class MuseNews:
    def __init__(self, muse):
        self.muse = muse

    def summarise(self, items) -> list[str]:
        data = [{"id": index, "untrusted_title": item.title, "untrusted_text": item.text[:1500]} for index, item in enumerate(items)]
        # Muse spends part of this budget thinking before it answers, so it is generous.
        response = self.muse.respond(input=[{"role": "user", "content": json.dumps(data)}], instructions=SYSTEM,
                              text_format=FORMAT, purpose="news_summary", max_output_tokens=8000)
        try:
            return parse_summaries(response.output_text, len(items))
        except DraftError:
            return [""] * len(items)   # a summary is optional: the card then shows each item's own title


class FixtureNews:
    """No-spend summariser for tests and the sample demo: the first sentence of the item's own text."""

    def summarise(self, items) -> list[str]:
        summaries = []
        for item in items:
            text = item.text.removeprefix("Sample text. ")
            # A sentence-ending mark followed by whitespace separates the first sentence.
            sentences = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
            summaries.append(sentences[0])
        return summaries
