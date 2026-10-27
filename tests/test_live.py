"""Calls the real Muse API. Costs a few cents. Run: RUN_LIVE=1 .venv/bin/python -m pytest -m live -s"""
import os

import pytest

from app import policy
from app.wiring import build

pytestmark = [pytest.mark.live, pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to call the real API")]


@pytest.fixture(scope="module")
def orch():
    return build(db_path=":memory:", drafter="muse")


@pytest.mark.parametrize("rid", ["g1", "g2", "y1"])
def test_real_muse_reply_passes_the_checks_and_posts(orch, rid):
    p = orch.propose_reply(rid)
    assert p["state"] == "PROPOSED", p
    review = orch.providers["Google"].read_review(rid)
    assert policy.check_reply(p["after"]["reply"], review, orch.facts) == []
    print(f"\n{rid}: first draft blocked={bool(p['first_draft'])}\n  {p['after']['reply']}")
    if review.platform == "Google":
        assert orch.approve(p["id"], p["hash"])["state"] == "VERIFIED"


def test_real_muse_escalates_the_legal_review(orch):
    r = orch.propose_reply("y3")
    assert r["status"] == "needs_human"


def test_usage_was_recorded(orch):
    u = orch.usage()
    print("\nusage:", u)
    assert u["calls"] >= 1 and u["cost_usd"] > 0
