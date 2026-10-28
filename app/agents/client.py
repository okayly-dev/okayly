"""Thin wrapper over the OpenAI SDK pointed at the Meta Model API (Responses API).
The key is read from the environment by the caller and never logged. Every call's token
usage is written to the usage table so cost is visible."""
import base64
import os
import time

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from ..core.errors import DraftError, MuseBudgetReached, MuseRateLimited, MuseRejected, MuseUnavailable
from ..core.messages import MUSE_BAD_OUTPUT, MUSE_BUDGET_REACHED, MUSE_RATE_LIMITED, MUSE_REJECTED, MUSE_UNAVAILABLE

BASE_URL = "https://api.meta.ai/v1"
MODEL = "muse-spark-1.3"
# $ per 1M tokens, from Meta's pricing page (checked 2026-10-26; recheck before relying on it)
PRICE_IN, PRICE_CACHED, PRICE_OUT = 1.25, 0.15, 4.25
IMAGE_MODEL = "muse-image-1.0"
IMAGE_PRICE = 0.01  # $ per picture (spike, 2026-10-26)
DEFAULT_DAILY_SPEND_CAP_USD = 2.00


def cost_usd(input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    fresh = max(0, input_tokens - cached_tokens)
    return (fresh * PRICE_IN + cached_tokens * PRICE_CACHED + output_tokens * PRICE_OUT) / 1e6


class MuseClient:
    def __init__(self, store=None, api_key: str | None = None, base_url: str = BASE_URL, model: str = MODEL,
                 client=None, daily_spend_cap_usd: float = DEFAULT_DAILY_SPEND_CAP_USD, clock=time.time):
        key = api_key or os.environ.get("MODEL_API_KEY")
        if client is None:
            if not key:
                raise RuntimeError("MODEL_API_KEY is not set")
            # the SDK does not read MODEL_API_KEY by itself, so it is passed explicitly
            client = OpenAI(api_key=key, base_url=base_url, max_retries=3, timeout=90)
        self.client = client
        self.model = model
        self.store = store
        self.daily_spend_cap_usd = daily_spend_cap_usd
        self.clock = clock

    def spent_today_usd(self) -> float:
        if self.store is None:
            return 0.0
        now = self.clock()
        start = now - now % 86400
        row = self.store.one("SELECT COALESCE(SUM(cost_usd), 0) usd FROM usage WHERE ts>=? AND ts<?",
                             (start, start + 86400))
        return float(row["usd"])

    def _check_budget(self) -> None:
        if self.spent_today_usd() >= self.daily_spend_cap_usd:
            raise MuseBudgetReached(MUSE_BUDGET_REACHED)

    @staticmethod
    def _raise_plain(exc: Exception) -> None:
        status = getattr(exc, "status_code", None)
        if isinstance(exc, RateLimitError) or status == 429:
            raise MuseRateLimited(MUSE_RATE_LIMITED) from None
        if isinstance(exc, (APITimeoutError, APIConnectionError)) or (isinstance(status, int) and status >= 500):
            raise MuseUnavailable(MUSE_UNAVAILABLE) from None
        if isinstance(exc, APIStatusError) or (isinstance(status, int) and 400 <= status < 500):
            raise MuseRejected(MUSE_REJECTED) from None
        raise MuseUnavailable(MUSE_UNAVAILABLE) from None

    def respond(self, *, input, instructions=None, tools=None, text_format=None, previous_response_id=None,
                purpose: str = "", max_output_tokens: int = 4000):
        self._check_budget()
        kw = {"model": self.model, "input": input, "max_output_tokens": max_output_tokens}
        if instructions:
            kw["instructions"] = instructions
        if tools:
            kw["tools"] = tools
            kw["parallel_tool_calls"] = False  # one call per turn keeps the loop easy to audit
        if text_format:
            kw["text"] = text_format
        if previous_response_id:
            kw["previous_response_id"] = previous_response_id
        try:
            r = self.client.responses.create(**kw)
        except Exception as exc:
            self._raise_plain(exc)
        self._record(r, purpose)
        return r

    def _record(self, r, purpose: str) -> None:
        if self.store is None or getattr(r, "usage", None) is None:
            return
        u = r.usage
        cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
        self.store.run(
            "INSERT INTO usage (ts, model, purpose, input_tokens, cached_tokens, output_tokens, cost_usd) VALUES (?,?,?,?,?,?,?)",
            (self.clock(), self.model, purpose, u.input_tokens, cached, u.output_tokens, cost_usd(u.input_tokens, cached, u.output_tokens)),
        )

    def generate_image(self, prompt: str, purpose: str = "ad_picture") -> bytes:
        """One picture from Muse Image. The API returns base64, not a link."""
        self._check_budget()
        try:
            r = self.client.images.generate(model=IMAGE_MODEL, prompt=prompt, n=1)
        except Exception as exc:
            self._raise_plain(exc)
        b64 = (r.data[0].b64_json if getattr(r, "data", None) else None)
        if not b64:
            raise DraftError(MUSE_BAD_OUTPUT)
        if self.store is not None:
            self.store.run(
                "INSERT INTO usage (ts, model, purpose, input_tokens, cached_tokens, output_tokens, cost_usd) VALUES (?,?,?,?,?,?,?)",
                (self.clock(), IMAGE_MODEL, purpose, 0, 0, 0, IMAGE_PRICE))
        return base64.b64decode(b64)
