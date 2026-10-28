import base64
from types import SimpleNamespace

import pytest

from app.agents.client import MuseClient
from app.core.errors import MuseBudgetReached, MuseRateLimited, MuseRejected, MuseUnavailable
from app.core.store import Store


class FakeFailure(Exception):
    def __init__(self, status_code, detail=""):
        super().__init__(detail)
        self.status_code = status_code


class FakeEndpoint:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    def create(self, **_):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result

    generate = create


class FakeSDK:
    def __init__(self, *, response=None, image=None, error=None):
        self.responses = FakeEndpoint(response, error)
        self.images = FakeEndpoint(image, error)


@pytest.mark.parametrize(("status", "expected"), [
    (429, MuseRateLimited),
    (400, MuseRejected),
    (401, MuseRejected),
    (500, MuseUnavailable),
    (503, MuseUnavailable),
])
def test_status_failures_are_classified_with_plain_sanitized_messages(status, expected):
    secret = "fake-key-never-show"
    url = "https://secret.invalid/path"
    muse = MuseClient(client=FakeSDK(error=FakeFailure(status, f"{secret} {url}")))
    with pytest.raises(expected) as caught:
        muse.respond(input=[])
    assert secret not in str(caught.value)
    assert url not in str(caught.value)
    assert "Nothing was changed" in str(caught.value)


def test_connection_failure_is_unavailable_and_image_failure_is_classified():
    muse = MuseClient(client=FakeSDK(error=TimeoutError("private network detail")))
    with pytest.raises(MuseUnavailable):
        muse.respond(input=[])
    with pytest.raises(MuseUnavailable):
        muse.generate_image("sample prompt")


def test_budget_blocks_before_call_and_utc_day_rollover_resets_it():
    now = [2 * 86400 + 60]
    store = Store()
    store.run("INSERT INTO usage (ts, model, purpose, input_tokens, cached_tokens, output_tokens, cost_usd) VALUES (?,?,?,?,?,?,?)",
              (now[0], "m", "test", 0, 0, 0, 2.0))
    response = SimpleNamespace(usage=None)
    sdk = FakeSDK(response=response)
    muse = MuseClient(store=store, client=sdk, daily_spend_cap_usd=2.0, clock=lambda: now[0])

    with pytest.raises(MuseBudgetReached):
        muse.respond(input=[])
    assert sdk.responses.calls == 0

    now[0] += 86400
    assert muse.respond(input=[]) is response
    assert sdk.responses.calls == 1


def test_image_call_records_cost():
    raw = b"image bytes"
    image = SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(raw).decode())])
    store = Store()
    muse = MuseClient(store=store, client=FakeSDK(image=image), clock=lambda: 123.0)
    assert muse.generate_image("sample") == raw
    assert store.one("SELECT cost_usd FROM usage")["cost_usd"] == 0.01
