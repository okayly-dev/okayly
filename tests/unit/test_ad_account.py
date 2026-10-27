import pytest

from app.providers.sandbox import SandboxAdAccount
from app.wiring import build


def orch():
    return build(db_path=":memory:", drafter="fixture")


# ---------- the sandbox ad account ----------
def test_ad_account_cannot_activate_or_spend():
    assert not any(hasattr(SandboxAdAccount, n) for n in ("activate", "publish", "set_budget", "enable", "resume"))
    cols = {r["name"] for r in orch().store.all("PRAGMA table_info(ads)")}
    assert not cols & {"budget", "spend", "daily_budget"} and "status" in cols


def test_ad_status_can_only_be_paused():
    o = orch()
    with pytest.raises(Exception):
        o.store.run("UPDATE ads SET status='active'")


