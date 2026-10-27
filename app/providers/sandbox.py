"""The write side of the sandbox providers. Only the executors hold these objects. They
also keep the read methods (inherited from SandboxReader) so tests and demo controls can look
at the result, but Muse and the workflows only ever get a plain SandboxReader.
Google is writable; Yelp is read-only because no way for an app to post a Yelp reply was found."""
import time

from .read import PLATFORMS, SandboxReader
from .seed import seed_ads, seed_reviews


class ManualHandoff(Exception):
    """The platform cannot be written to by this app; a person posts the approved text."""


class _Base(SandboxReader):
    name = ""
    can_post = False

    def __init__(self, store):
        super().__init__(store)
        self.store = store

    def seed(self, reviews: list[dict]) -> None:
        seed_reviews(self.store, reviews)

    # demo and test control: someone changes the review outside this app
    def edit_text(self, review_id: str, suffix: str) -> None:
        self.store.run("UPDATE reviews SET text = text || ? WHERE id=?", (suffix, review_id))

    def set_reply(self, review_id: str, reply: str | None) -> None:
        self.store.run("UPDATE reviews SET reply=? WHERE id=?", (reply, review_id))


class SandboxGoogle(_Base):
    name, can_post = PLATFORMS["Google"]

    def post_reply(self, review_id: str, reply: str, idem: str) -> None:
        """Idempotent: the same key never writes twice."""
        with self.store.tx():
            if self.store.one("SELECT 1 FROM writes WHERE idem=?", (idem,)):
                return
            self.store.run("UPDATE reviews SET reply=? WHERE id=?", (reply, review_id))
            self.store.run("INSERT INTO writes (idem, review_id, applied_at) VALUES (?,?,?)", (idem, review_id, time.time()))


class ManualYelp(_Base):
    name, can_post = PLATFORMS["Yelp"]

    def post_reply(self, review_id: str, reply: str, idem: str) -> None:
        raise ManualHandoff("Yelp does not let this app post replies.")


class NameTaken(Exception):
    """An ad with this name already exists in the account."""


class SandboxAdAccount(SandboxReader):
    """A practice ad account in miniature. It can read ads and create paused drafts. There is no
    method to switch an ad on and no budget field anywhere, so this app cannot spend money."""
    name, can_post = PLATFORMS["Ads"]

    def __init__(self, store):
        super().__init__(store)
        self.store = store

    def seed(self, ads: list[dict]) -> None:
        seed_ads(self.store, ads)

    def create_paused_draft(self, name: str, headline: str, text: str, image_sha: str, fmt: str, idem: str) -> None:
        """Idempotent: the same key never writes twice."""
        with self.store.tx():
            if self.store.one("SELECT 1 FROM writes WHERE idem=?", (idem,)):
                return
            if self.read_ad(name) is not None:
                raise NameTaken(name)
            self.store.run("INSERT INTO ads (name, status, headline, text, image_sha, format) VALUES (?,?,?,?,?,?)",
                           (name, "paused", headline, text, image_sha, fmt))
            self.store.run("INSERT INTO writes (idem, review_id, applied_at) VALUES (?,?,?)", (idem, name, time.time()))

    # demo and test control: a teammate saves an ad with the same name outside this app
    def demo_create(self, name: str, headline: str = "Teammate draft", text: str = "Saved by a teammate.") -> None:
        self.store.run("INSERT OR IGNORE INTO ads (name, status, headline, text, image_sha, format) VALUES (?,?,?,?,?,?)",
                       (name, "paused", headline, text, None, "wide"))
