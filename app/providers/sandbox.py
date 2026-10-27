"""Sandbox providers. They implement the same small interface a real provider would:
read the current state, write (executor only), and read back through the same read path.
Google is writable; Yelp is read-only because no way for an app to post a Yelp reply was found."""
import time

from ..domain import ReviewState


class ManualHandoff(Exception):
    """The platform cannot be written to by this app; a person posts the approved text."""


class _Base:
    name = ""
    can_post = False

    def __init__(self, store):
        self.store = store

    @staticmethod
    def _row(r) -> ReviewState:
        return ReviewState(r["id"], r["platform"], r["stars"], r["who"], r["date"], r["text"], r["reply"])

    def read_review(self, review_id: str) -> ReviewState | None:
        r = self.store.one("SELECT * FROM reviews WHERE id=?", (review_id,))
        return self._row(r) if r else None

    def list_reviews(self) -> list[ReviewState]:
        return [self._row(r) for r in self.store.all("SELECT * FROM reviews ORDER BY ord")]

    def seed(self, reviews: list[dict]) -> None:
        with self.store.tx():
            if self.store.one("SELECT 1 FROM reviews LIMIT 1"):
                return
            for i, r in enumerate(reviews):
                self.store.run(
                    "INSERT INTO reviews (id, ord, platform, stars, who, date, text, reply) VALUES (?,?,?,?,?,?,?,?)",
                    (r["id"], i, r["platform"], r["stars"], r["who"], r["date"], r["text"], r.get("reply")),
                )

    # demo and test control: someone changes the review outside this app
    def edit_text(self, review_id: str, suffix: str) -> None:
        self.store.run("UPDATE reviews SET text = text || ? WHERE id=?", (suffix, review_id))

    def set_reply(self, review_id: str, reply: str | None) -> None:
        self.store.run("UPDATE reviews SET reply=? WHERE id=?", (reply, review_id))


class SandboxGoogle(_Base):
    name = "sandbox_google_profile"
    can_post = True

    def post_reply(self, review_id: str, reply: str, idem: str) -> None:
        """Idempotent: the same key never writes twice."""
        with self.store.tx():
            if self.store.one("SELECT 1 FROM writes WHERE idem=?", (idem,)):
                return
            self.store.run("UPDATE reviews SET reply=? WHERE id=?", (reply, review_id))
            self.store.run("INSERT INTO writes (idem, review_id, applied_at) VALUES (?,?,?)", (idem, review_id, time.time()))


class ManualYelp(_Base):
    name = "manual_handoff_yelp"
    can_post = False

    def post_reply(self, review_id: str, reply: str, idem: str) -> None:
        raise ManualHandoff("Yelp does not let this app post replies.")
