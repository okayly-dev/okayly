"""The News check: read the approved feeds, keep what the rules allow, ask for short summaries,
and return at most three notes. Nothing here writes to any account."""
from datetime import datetime, timezone

from ..providers.feeds import FeedError
from ..verification import news as rules


class NewsCheck:
    def __init__(self, sources: list[dict], fetch, summariser, clock, mode: str):
        """fetch(source) -> list of feed items; summariser.summarise(items) -> list of sentences."""
        self.sources, self.fetch, self.summariser, self.clock, self.mode = sources, fetch, summariser, clock, mode

    def run(self) -> dict:
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        found, failed = {}, []
        for source in self.sources:
            try:
                items = self.fetch(source)
            except FeedError:
                failed.append(source["name"])
                continue
            for item in items:
                if rules.keep_item(item, source, now):
                    found.setdefault(item.link, (source, item))   # the same article in two feeds counts once
        top = sorted(found.values(), key=rules.show_order)[:rules.MAX_NOTES]
        summaries = self.summariser.summarise([item for _, item in top]) if top else []
        notes = []
        for (source, item), summary in zip(top, summaries):
            notes.append({"title": item.title, "link": item.link, "date": item.published.date().isoformat(),
                          "source": source["name"], "kind": source["kind"],
                          "summary": summary if rules.summary_ok(summary) else item.title})
        return {"mode": self.mode, "notes": notes, "sources_checked": len(self.sources), "sources_failed": failed}
