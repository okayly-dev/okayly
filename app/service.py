"""A thin facade over the layers, so the HTTP interface and the tests have one object to talk to.
It holds no logic of its own: every method hands off to a workflow (propose, edit, approve,
reject, reads) or to the executor (the only code that writes).

Muse proposes, code validates, a person approves the exact content hash, a separate executor
recomputes that hash and writes, and an independent read confirms. Every step is recorded in
the audit chain in the same transaction as the state change."""
import time

from .executors.executor import Executor
from .providers.read import SandboxReader
from .workflows import approval_gate, demo, edit, propose, queries, reject
from .workflows.runtime import TTL_SECONDS, Runtime


class Orchestrator:
    def __init__(self, store, providers: dict, drafter, facts: dict, past_replies: list[str], clock=time.time, ttl: int = TTL_SECONDS,
                 ad_studio=None):
        self.store, self.providers = store, providers
        self.news = None   # a workflows.news.NewsCheck, set by wiring
        reader = SandboxReader(store)
        self.rt = Runtime(store, reader, drafter, ad_studio, facts, past_replies, clock, ttl)
        self.audit = self.rt.audit
        self.executor = Executor(store, self.audit, providers, reader)

    @property
    def drafter(self):
        return self.rt.drafter

    @drafter.setter
    def drafter(self, value):
        self.rt.drafter = value

    @property
    def ad_studio(self):
        return self.rt.ad_studio

    @ad_studio.setter
    def ad_studio(self, value):
        self.rt.ad_studio = value

    def check_news(self) -> dict:
        return self.news.run()

    def drafter_context(self):
        return queries.drafter_context(self.rt)

    # propose / edit / decide
    def propose_reply(self, review_id: str) -> dict:
        return propose.propose_reply(self.rt, review_id)

    def propose_ad(self, name: str, fmt: str = "wide") -> dict:
        return propose.propose_ad(self.rt, name, fmt)

    def edit_reply(self, pid: str, text: str) -> dict:
        return edit.edit_reply(self.rt, pid, text)

    def edit_ad(self, pid: str, headline: str | None = None, text: str | None = None, fmt: str | None = None) -> dict:
        return edit.edit_ad(self.rt, pid, headline, text, fmt)

    def choose_picture(self, pid: str, sha: str) -> dict:
        return edit.choose_picture(self.rt, pid, sha)

    def approve(self, pid: str, seen_hash: str, execute: bool = True) -> dict:
        return approval_gate.approve(self.rt, pid, seen_hash, run=self.executor.execute if execute else None)

    def reject(self, pid: str, reason: str) -> dict:
        return reject.reject(self.rt, pid, reason)

    def execute(self, pid: str) -> dict:
        return self.executor.execute(approval_gate.approved_action_for(self.rt, pid))

    # reads
    def get(self, pid: str) -> dict:
        return queries.get(self.rt, pid)

    def list_reviews(self) -> list[dict]:
        return queries.list_reviews(self.rt)

    def list_ads(self) -> dict:
        return queries.list_ads(self.rt)

    def image(self, sha: str) -> tuple[str, bytes]:
        return queries.image(self.rt, sha)

    def usage(self) -> dict:
        return queries.usage(self.rt)

    # demo controls (only reachable when DEMO_CONTROLS=1)
    def demo_reset(self, reviews: list[dict], ads: list[dict] = ()) -> None:
        demo.demo_reset(self.rt, reviews, ads)

    def demo_tamper(self, on: bool) -> dict:
        return demo.demo_tamper(self.rt, on)
