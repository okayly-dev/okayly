"""/api/usage: lifetime totals plus today's spend against the daily cap. "Today" is the UTC day
that the app's clock is in: from midnight (included) to the next midnight (not included)."""
from fastapi.testclient import TestClient

from app.api import create_app
from app.wiring import build

DAY = 86400
MIDNIGHT = 5 * DAY            # the start of "today" in the test
NOW = MIDNIGHT + 12 * 3600    # noon


def make_client(monkeypatch, cap="2.00"):
    monkeypatch.setenv("DAILY_SPEND_CAP_USD", cap)
    orch = build(db_path=":memory:", drafter="fixture", clock=lambda: NOW)
    return orch, TestClient(create_app(orch, demo_controls=False))


def add_usage(orch, ts, cost, purpose="test", input_tokens=0, cached_tokens=0, output_tokens=0):
    orch.store.run("INSERT INTO usage (ts, model, purpose, input_tokens, cached_tokens, output_tokens, cost_usd) VALUES (?,?,?,?,?,?,?)",
                   (ts, "m", purpose, input_tokens, cached_tokens, output_tokens, cost))


def test_empty_usage_table(monkeypatch):
    _, client = make_client(monkeypatch)
    assert client.get("/api/usage").json() == {
        "calls": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "cost_usd": 0,
        "cap_usd": 2.0, "spent_today_usd": 0, "remaining_usd": 2.0}


def test_only_rows_inside_today_count_towards_today(monkeypatch):
    orch, client = make_client(monkeypatch)
    add_usage(orch, MIDNIGHT - 1, 10.0, "one second before midnight, yesterday", 1, 0, 1)
    add_usage(orch, MIDNIGHT, 0.25, "exactly midnight, today", 100, 10, 20)
    add_usage(orch, NOW, 0.5, "noon, today", 200, 20, 40)
    add_usage(orch, MIDNIGHT + DAY - 1, 0.125, "last second of today", 300, 30, 60)
    add_usage(orch, MIDNIGHT + DAY, 20.0, "exactly tomorrow's midnight", 2, 0, 2)
    add_usage(orch, MIDNIGHT + DAY + 5, 30.0, "tomorrow", 3, 0, 3)
    body = client.get("/api/usage").json()
    assert body == {
        "calls": 6, "input_tokens": 606, "cached_tokens": 60, "output_tokens": 126, "cost_usd": 60.875,
        "cap_usd": 2.0, "spent_today_usd": 0.875, "remaining_usd": 1.125}
    assert list(body) == ["calls", "input_tokens", "cached_tokens", "output_tokens", "cost_usd",
                          "cap_usd", "spent_today_usd", "remaining_usd"]


def test_remaining_never_goes_below_zero(monkeypatch):
    orch, client = make_client(monkeypatch, cap="1.00")
    add_usage(orch, NOW, 1.5)
    body = client.get("/api/usage").json()
    assert body["spent_today_usd"] == 1.5
    assert body["remaining_usd"] == 0.0


def test_amounts_are_rounded_to_six_places(monkeypatch):
    orch, client = make_client(monkeypatch)
    add_usage(orch, NOW, 0.1234567891)
    add_usage(orch, NOW, 0.0000001)
    body = client.get("/api/usage").json()
    assert body["spent_today_usd"] == round(0.1234567891 + 0.0000001, 6)
    assert body["cost_usd"] == body["spent_today_usd"]
    assert body["remaining_usd"] == round(2.0 - (0.1234567891 + 0.0000001), 6)


def test_the_window_follows_the_clock(monkeypatch):
    monkeypatch.setenv("DAILY_SPEND_CAP_USD", "2.00")
    now = [NOW]
    orch = build(db_path=":memory:", drafter="fixture", clock=lambda: now[0])
    client = TestClient(create_app(orch, demo_controls=False))
    add_usage(orch, NOW, 0.75)
    assert client.get("/api/usage").json()["spent_today_usd"] == 0.75
    now[0] = MIDNIGHT + DAY          # the next UTC day starts: yesterday's spend no longer counts
    body = client.get("/api/usage").json()
    assert body["spent_today_usd"] == 0
    assert body["remaining_usd"] == 2.0
    assert body["cost_usd"] == 0.75
