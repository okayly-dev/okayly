"""Builds an Orchestrator from settings. Default is the no-spend fixture drafter and an
in-memory database; set DRAFTER=muse (and MODEL_API_KEY) to use the real model."""
import json
import os
import time
from pathlib import Path

from .muse.reviews import FixtureDrafter, MuseDrafter
from .providers.sandbox import ManualYelp, SandboxGoogle
from .service import Orchestrator
from .store import Store

FIXTURE = Path(__file__).parent / "fixtures" / "sample.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def build(db_path: str | None = None, drafter: str | None = None, clock=time.time, muse=None) -> Orchestrator:
    db_path = db_path or os.environ.get("DB_PATH", ":memory:")
    drafter = drafter or os.environ.get("DRAFTER", "fixture")
    fx = load_fixture()
    store = Store(db_path)
    providers = {"Google": SandboxGoogle(store), "Yelp": ManualYelp(store)}
    providers["Google"].seed(fx["reviews"])
    orch = Orchestrator(store, providers, None, fx["facts"], fx["past_replies"], clock=clock)
    if drafter == "muse":
        from .muse.client import MuseClient
        orch.drafter = MuseDrafter(muse or MuseClient(store=store), orch.drafter_context())
    else:
        orch.drafter = FixtureDrafter(fx["fixture_drafts"])
    return orch
