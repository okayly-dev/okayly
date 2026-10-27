"""The only data Muse can reach: a read-only context. It is built from a reader object (anything
with read_review) plus the approved practice facts. It has no method that writes, and the
agents package never imports the write side of the providers."""
from ..verification import policy


class ReadContext:
    def __init__(self, reader, facts: dict, past_replies: list[str]):
        self._reader, self._facts, self._past = reader, facts, past_replies

    def review(self, rid):
        return self._reader.read_review(rid)

    def facts(self):
        return self._facts

    def past_replies(self, n):
        return self._past[:n]

    def ad_rules(self):
        return policy.AD_RULES_TEXT
