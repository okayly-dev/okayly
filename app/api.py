"""HTTP interface. Every button in the interface maps to one endpoint here. The browser holds
no model key and no provider credentials."""
import os
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from typing import Any

from pydantic import BaseModel, Field

from .core.errors import DraftError, OrchestratorError, PolicyViolation
from .core.messages import MUSE_BAD_OUTPUT
from .wiring import build, load_fixture


class ApproveBody(BaseModel):
    hash: str = Field(min_length=8, max_length=128)


class EditBody(BaseModel):
    reply: str = Field(max_length=2000)


class ProposeAdBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    format: str = Field(default="wide", max_length=10)
    # Optional brief. Checked in code (verification.policy.read_ad_brief) so a bad value gets the app's plain error, not a framework one.
    headline_wish: Any = None
    picture_request: Any = None
    picture_count: Any = None


class EditAdBody(BaseModel):
    headline: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=1000)
    format: str | None = Field(default=None, max_length=10)


class PictureBody(BaseModel):
    sha: str = Field(pattern=r"^[0-9a-f]{64}$")


class CollideBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class RejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


class TamperBody(BaseModel):
    on: bool


class SuffixBody(BaseModel):
    suffix: str = Field(default=" (Edit: the wait was closer to an hour.)", max_length=300)


def create_app(orchestrator=None, demo_controls: bool | None = None) -> FastAPI:
    orch = orchestrator or build()
    demo = demo_controls if demo_controls is not None else os.environ.get("DEMO_CONTROLS") == "1"
    app = FastAPI(title="Review-reply orchestrator", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.exception_handler(OrchestratorError)
    async def handle(_: Request, e: OrchestratorError):
        body = {"error": MUSE_BAD_OUTPUT if isinstance(e, DraftError) else str(e)}
        if isinstance(e, PolicyViolation):
            body["issues"] = [{"code": i.code, "message": i.message} for i in e.issues]
        return JSONResponse(body, status_code=e.status)

    @app.get("/api/health")
    def health():
        return {"ok": True, "drafter": type(orch.drafter).__name__}

    @app.get("/api/reviews")
    def reviews():
        return orch.list_reviews()

    @app.post("/api/reviews/{review_id}/propose")
    def propose(review_id: str):
        return orch.propose_reply(review_id)

    @app.get("/api/ads")
    def ads():
        return orch.list_ads()

    @app.post("/api/ads/propose")
    def propose_ad(b: ProposeAdBody):
        return orch.propose_ad(b.name, b.format, b.headline_wish, b.picture_request, b.picture_count)

    @app.get("/api/images/{sha}")
    def image(sha: str):
        mime, data = orch.image(sha)
        return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})

    @app.post("/api/proposals/{pid}/edit-ad")
    def edit_ad(pid: str, b: EditAdBody):
        return orch.edit_ad(pid, b.headline, b.text, b.format)

    @app.post("/api/proposals/{pid}/picture")
    def picture(pid: str, b: PictureBody):
        return orch.choose_picture(pid, b.sha)

    @app.get("/api/proposals/{pid}")
    def proposal(pid: str):
        return orch.get(pid)

    @app.post("/api/proposals/{pid}/edit")
    def edit(pid: str, b: EditBody):
        return orch.edit_reply(pid, b.reply)

    @app.post("/api/proposals/{pid}/approve")
    def approve(pid: str, b: ApproveBody):
        return orch.approve(pid, b.hash)

    @app.post("/api/proposals/{pid}/reject")
    def reject(pid: str, b: RejectBody):
        return orch.reject(pid, b.reason)

    @app.post("/api/news/check")
    def news_check():
        return orch.check_news()

    @app.get("/api/audit")
    def audit(limit: int = 200):
        return orch.audit.events(min(max(limit, 1), 1000))

    @app.get("/api/audit/verify")
    def verify():
        return orch.audit.verify()

    @app.get("/api/usage")
    def usage():
        return orch.usage_today()

    if demo:
        @app.post("/api/demo/reviews/{review_id}/edit")
        def demo_edit(review_id: str, b: SuffixBody):
            orch.providers["Google"].edit_text(review_id, b.suffix)
            return {"ok": True}

        @app.post("/api/demo/reset")
        def demo_reset():
            fx = load_fixture()
            orch.demo_reset(fx["reviews"], fx["ads"])
            return {"ok": True}

        @app.post("/api/demo/ads/collide")
        def demo_collide(b: CollideBody):
            orch.providers["Ads"].demo_create(b.name)
            return {"ok": True}

        @app.post("/api/demo/audit/tamper")
        def demo_tamper(b: TamperBody):
            return orch.demo_tamper(b.on)

    web = Path(__file__).resolve().parent.parent / "web"
    if web.is_dir():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")

    return app
