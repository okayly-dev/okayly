"""Reads a public news feed (RSS, Atom or RDF) and returns plain items. It only reads: it never
logs in, never posts, and gives back text that must be treated as untrusted."""
import html
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

MAX_BYTES = 1_500_000   # a feed bigger than this is refused
TIMEOUT_SECONDS = 15
USER_AGENT = "okayly-news/0.1 (reads public feeds)"


@dataclass
class FeedItem:
    title: str
    link: str
    published: datetime
    text: str


class FeedError(Exception):
    """The feed could not be read. The message is plain enough to show."""


def _child_text(node, name: str) -> str:
    for child in node:
        if child.tag.split("}")[-1] == name:
            return (child.text or child.attrib.get("href") or "").strip()
    return ""


def _plain(text: str) -> str:
    """Feed descriptions often hold web markup. Keep only the words."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def _parse_date(raw: str) -> datetime | None:
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def parse_feed(xml_text: str) -> list[FeedItem]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as e:
        raise FeedError("The feed is not readable.") from e
    items = []
    for node in root.iter():
        if node.tag.split("}")[-1] not in ("item", "entry"):
            continue
        published = _parse_date(_child_text(node, "pubDate") or _child_text(node, "date")
                                or _child_text(node, "published") or _child_text(node, "updated"))
        link, title = _child_text(node, "link"), _child_text(node, "title")
        if published and link and title:
            text = _child_text(node, "description") or _child_text(node, "summary")
            items.append(FeedItem(_plain(title), link, published, _plain(text)))
    return items


def fetch_feed(url: str) -> list[FeedItem]:
    if not url.startswith("https://"):
        raise FeedError("Only secure feed addresses are read.")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_BYTES + 1)
    except Exception as e:
        raise FeedError("The feed could not be reached.") from e
    if len(body) > MAX_BYTES:
        raise FeedError("The feed is too large.")
    return parse_feed(body.decode("utf-8", errors="replace"))
