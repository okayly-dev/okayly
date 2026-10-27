"""Builds an Orchestrator from settings. Default is the no-spend fixture drafter and an
in-memory database; set DRAFTER=muse (and MODEL_API_KEY) to use the real model."""
import json
import os
import time
from pathlib import Path

from .agents.ads import FixtureAdStudio, MuseAdStudio
from .agents.reviews import FixtureDrafter, MuseDrafter
from .providers.sandbox import ManualYelp, SandboxAdAccount, SandboxGoogle
from .service import Orchestrator
from .core.store import Store

FIXTURE = Path(__file__).parent / "fixtures" / "sample.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def build(db_path: str | None = None, drafter: str | None = None, clock=time.time, muse=None) -> Orchestrator:
    db_path = db_path or os.environ.get("DB_PATH", ":memory:")
    drafter = drafter or os.environ.get("DRAFTER", "fixture")
    fx = load_fixture()
    store = Store(db_path)
    providers = {"Google": SandboxGoogle(store), "Yelp": ManualYelp(store), "Ads": SandboxAdAccount(store)}
    providers["Google"].seed(fx["reviews"])
    providers["Ads"].seed(fx["ads"])
    orch = Orchestrator(store, providers, None, fx["facts"], fx["past_replies"], clock=clock)
    if drafter == "muse":
        from .agents.client import MuseClient
        muse = muse or MuseClient(store=store)
        orch.drafter = MuseDrafter(muse, orch.drafter_context())
        orch.ad_studio = MuseAdStudio(muse, orch.drafter_context())
    else:
        orch.drafter = FixtureDrafter(fx["fixture_drafts"])
        orch.ad_studio = FixtureAdStudio(fx["fixture_ad"])
    return orch
