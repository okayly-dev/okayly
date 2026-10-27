"""The read side of the providers. Everything that only needs to look at reviews or ads
(workflows, the read-back, and the context Muse reads through) uses this class. It has no
method that changes anything outside the app."""
from ..core.domain import AdState, ReviewState

# platform -> (provider name, whether this app is allowed to post to it)
PLATFORMS = {
    "Google": ("sandbox_google_profile", True),
    "Yelp": ("manual_handoff_yelp", False),
    "Ads": ("sandbox_ad_account", True),
}


class SandboxReader:
    def __init__(self, store):
        self._store = store

    @staticmethod
    def provider_name(platform: str) -> str:
        return PLATFORMS[platform][0]

    @staticmethod
    def platform_can_post(platform: str) -> bool:
        return PLATFORMS[platform][1]

    @staticmethod
    def _review(r) -> ReviewState:
        return ReviewState(r["id"], r["platform"], r["stars"], r["who"], r["date"], r["text"], r["reply"])

    @staticmethod
    def _ad(r) -> AdState:
        return AdState(r["name"], r["status"], r["headline"], r["text"], r["image_sha"], r["format"])

    def read_review(self, review_id: str) -> ReviewState | None:
        r = self._store.one("SELECT * FROM reviews WHERE id=?", (review_id,))
        return self._review(r) if r else None

    def list_reviews(self) -> list[ReviewState]:
        return [self._review(r) for r in self._store.all("SELECT * FROM reviews ORDER BY ord")]

    def read_ad(self, name: str) -> AdState | None:
        r = self._store.one("SELECT * FROM ads WHERE name=?", (name,))
        return self._ad(r) if r else None

    def list_ads(self) -> list[AdState]:
        return [self._ad(r) for r in self._store.all("SELECT * FROM ads ORDER BY rowid")]
