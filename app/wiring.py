"""Builds an Orchestrator from settings. Default is the no-spend fixture drafter and an
in-memory database; set DRAFTER=muse (and MODEL_API_KEY) to use the real model."""
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .agents.ads import FixtureAdStudio, MuseAdStudio
from .agents.reviews import FixtureDrafter, MuseDrafter
from .agents.news import FixtureNews, MuseNews
from .providers.feeds import FeedItem, fetch_feed
from .providers.sandbox import ManualYelp, SandboxAdAccount, SandboxGoogle
from .service import Orchestrator
from .workflows.news import NewsCheck
from .core.store import Store

FIXTURE = Path(__file__).parent / "fixtures" / "sample.json"
NEWS_SOURCES = Path(__file__).parent / "fixtures" / "news_sources.json"
NEWS_SAMPLE = Path(__file__).parent / "fixtures" / "news_sample.json"
DEFAULT_DAILY_SPEND_CAP_USD = 2.00


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def sample_news_fetch(clock):
    """The no-spend demo's news: made-up items dated a few days back, labelled as samples."""
    def fetch(source):
        rows = json.loads(NEWS_SAMPLE.read_text(encoding="utf-8"))["items"]
        now = datetime.fromtimestamp(clock(), timezone.utc)
        return [FeedItem(r["title"], r["link"], now - timedelta(days=r["days_ago"]), r["text"]) for r in rows]
    return fetch


def build(db_path: str | None = None, drafter: str | None = None, clock=time.time, muse=None) -> Orchestrator:
    db_path = db_path or os.environ.get("DB_PATH", ":memory:")
    drafter = drafter or os.environ.get("DRAFTER", "fixture")
    fx = load_fixture()
    store = Store(db_path)
    providers = {"Google": SandboxGoogle(store), "Yelp": ManualYelp(store), "Ads": SandboxAdAccount(store)}
    providers["Google"].seed(fx["reviews"])
    providers["Ads"].seed(fx["ads"])
    orch = Orchestrator(store, providers, None, fx["facts"], fx["past_replies"], clock=clock)
    orch.daily_spend_cap_usd = float(os.environ.get("DAILY_SPEND_CAP_USD", DEFAULT_DAILY_SPEND_CAP_USD))
    if drafter == "muse":
        from .agents.client import MuseClient
        muse = muse or MuseClient(store=store, daily_spend_cap_usd=orch.daily_spend_cap_usd, clock=clock)
        orch.drafter = MuseDrafter(muse, orch.drafter_context())
        orch.ad_studio = MuseAdStudio(muse, orch.drafter_context())
        sources = json.loads(NEWS_SOURCES.read_text(encoding="utf-8"))["sources"]
        orch.news = NewsCheck(sources, lambda source: fetch_feed(source["url"]), MuseNews(muse), clock, "live")
    else:
        orch.drafter = FixtureDrafter(fx["fixture_drafts"])
        orch.ad_studio = FixtureAdStudio(fx["fixture_ad"])
        sample_source = [{"name": "Sample feed", "url": "", "kind": "Sample", "host": "example.invalid"}]
        orch.news = NewsCheck(sample_source, sample_news_fetch(clock), FixtureNews(), clock, "sample")
    return orch
