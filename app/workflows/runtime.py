"""The shared state the workflows run on. It holds a read-only view of the providers
(never a write handle), the drafters, and the audit log."""
import time

from ..core.audit import Audit

TTL_SECONDS = 24 * 3600


class Runtime:
    def __init__(self, store, reader, drafter, ad_studio, facts: dict, past_replies: list[str],
                 clock=time.time, ttl: int = TTL_SECONDS, seed_reviews=None, seed_ads=None):
        self.store, self.reader = store, reader
        self.drafter, self.ad_studio = drafter, ad_studio
        self.facts, self.past, self.clock, self.ttl = facts, past_replies, clock, ttl
        self.audit = Audit(store, clock)
        # demo reset only: callables that put the sample data back; they are not write-to-provider calls
        self.seed_reviews, self.seed_ads = seed_reviews, seed_ads
