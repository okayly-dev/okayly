"""Thin wrapper over the OpenAI SDK pointed at the Meta Model API (Responses API).
The key is read from the environment by the caller and never logged. Every call's token
usage is written to the usage table so cost is visible."""
import os
import time

from openai import OpenAI

BASE_URL = "https://api.meta.ai/v1"
MODEL = "muse-spark-1.3"
# $ per 1M tokens, from Meta's pricing page (checked 2026-10-26; recheck before relying on it)
PRICE_IN, PRICE_CACHED, PRICE_OUT = 1.25, 0.15, 4.25


def cost_usd(input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    fresh = max(0, input_tokens - cached_tokens)
    return (fresh * PRICE_IN + cached_tokens * PRICE_CACHED + output_tokens * PRICE_OUT) / 1e6


class MuseClient:
    def __init__(self, store=None, api_key: str | None = None, base_url: str = BASE_URL, model: str = MODEL, client=None):
        key = api_key or os.environ.get("MODEL_API_KEY")
        if client is None:
            if not key:
                raise RuntimeError("MODEL_API_KEY is not set")
            # the SDK does not read MODEL_API_KEY by itself, so it is passed explicitly
            client = OpenAI(api_key=key, base_url=base_url, max_retries=3, timeout=90)
        self.client = client
        self.model = model
        self.store = store

    def respond(self, *, input, instructions=None, tools=None, text_format=None, previous_response_id=None,
                purpose: str = "", max_output_tokens: int = 4000):
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
        r = self.client.responses.create(**kw)
        self._record(r, purpose)
        return r

    def _record(self, r, purpose: str) -> None:
        if self.store is None or getattr(r, "usage", None) is None:
            return
        u = r.usage
        cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
        self.store.run(
            "INSERT INTO usage (ts, model, purpose, input_tokens, cached_tokens, output_tokens, cost_usd) VALUES (?,?,?,?,?,?,?)",
            (time.time(), self.model, purpose, u.input_tokens, cached, u.output_tokens, cost_usd(u.input_tokens, cached, u.output_tokens)),
        )
