"""The rules for the News card, in code. Muse only writes a one-line summary; these rules decide
which items are shown and whether a summary is usable. The link, date and source always come from
the feed, never from Muse."""
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

MAX_AGE_DAYS = 14
MAX_NOTES = 3
KIND_ORDER = {"Official": 0}   # official sources are shown before other kinds, then newest first
MAX_SUMMARY_CHARS = 240
# An item must mention one of these to be shown. Edit this list to tune what counts as relevant.
TOPICS = ("dental", "dentist", "healthcare", "health ad", "review", "business profile", "local search",
          "local business", "local results", "local service", "advertis", "google ads", "privacy", "ranking",
          "spam", "policy", "ads", "ai mode", "search", "maps")


def is_recent(published: datetime, now: datetime) -> bool:
    return timedelta(0) <= now - published <= timedelta(days=MAX_AGE_DAYS)


def link_matches_source(link: str, host: str) -> bool:
    """The link must be a secure address on the source's own site."""
    parts = urlparse(link)
    name = (parts.hostname or "").lower()
    return parts.scheme == "https" and (name == host or name.endswith("." + host))


def is_relevant(title: str, text: str) -> bool:
    words = f"{title} {text}".lower()
    # a topic must start a word, so "ads" does not match "downloads" or "leads"
    return any(re.search(r"\b" + re.escape(topic), words) for topic in TOPICS)


def keep_item(item, source: dict, now: datetime) -> bool:
    return (is_recent(item.published, now) and link_matches_source(item.link, source["host"])
            and is_relevant(item.title, item.text))


def summary_ok(summary: str) -> bool:
    """One short plain sentence: no links, not empty, not long."""
    s = summary.strip()
    return bool(s) and len(s) <= MAX_SUMMARY_CHARS and not re.search(r"https?://|www\.|\b[\w-]+\.(com|org|net|io|co|gov|edu|info|dev|app|ai|us)\b", s, re.I)


def show_order(pair) -> tuple:
    """Sort key for (source, item) pairs: official sources first, then newest."""
    source, item = pair
    return (KIND_ORDER.get(source["kind"], 1), -item.published.timestamp())
