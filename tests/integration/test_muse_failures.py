from fastapi.testclient import TestClient

from app.agents.client import MuseClient
from app.agents.reviews import MuseDrafter
from app.api import create_app
from app.wiring import build


class FakeFailure(Exception):
    def __init__(self, status_code):
        super().__init__("fake-key https://private.invalid")
        self.status_code = status_code


class FailingResponses:
    def __init__(self, error):
        self.error = error

    def create(self, **_):
        raise self.error


class FakeSDK:
    def __init__(self, error):
        self.responses = FailingResponses(error)


def test_timeout_and_rate_limit_return_plain_status_and_leave_no_proposal():
    cases = [
        (TimeoutError("fake-key https://private.invalid"), 503),
        (FakeFailure(429), 429),
    ]
    for error, status in cases:
        orch = build(db_path=":memory:", drafter="fixture")
        muse = MuseClient(store=orch.store, client=FakeSDK(error))
        orch.drafter = MuseDrafter(muse, orch.drafter_context())
        response = TestClient(create_app(orch, demo_controls=False)).post("/api/reviews/g2/propose")
        assert response.status_code == status
        assert "Nothing was changed" in response.json()["error"]
        assert "fake-key" not in response.text and "private.invalid" not in response.text
        assert orch.store.one("SELECT COUNT(*) n FROM proposals")["n"] == 0


def test_usage_returns_daily_cap_spend_and_remaining(monkeypatch):
    monkeypatch.setenv("DAILY_SPEND_CAP_USD", "2.00")
    now = 3 * 86400 + 100
    orch = build(db_path=":memory:", drafter="fixture", clock=lambda: now)
    orch.store.run("INSERT INTO usage (ts, model, purpose, input_tokens, cached_tokens, output_tokens, cost_usd) VALUES (?,?,?,?,?,?,?)",
                   (now, "m", "today", 0, 0, 0, 0.75))
    orch.store.run("INSERT INTO usage (ts, model, purpose, input_tokens, cached_tokens, output_tokens, cost_usd) VALUES (?,?,?,?,?,?,?)",
                   (now - 86400, "m", "yesterday", 0, 0, 0, 1.00))
    body = TestClient(create_app(orch, demo_controls=False)).get("/api/usage").json()
    assert body["cap_usd"] == 2.0
    assert body["spent_today_usd"] == 0.75
    assert body["remaining_usd"] == 1.25
