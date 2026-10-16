"""Read-only draft inspection, deliberately separate from the clinical application.

No patient, planner, chat, approval or publication handlers are imported here.
The explicit draft revision is pinned at startup and is never a runtime release.
"""

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.knowledge.store import KnowledgeStore
from backend.knowledge.validation import content_hash
from backend.storage.postgres import database_url


def create_review_app() -> FastAPI:
    """Start only with an explicit, existing draft revision and a read-only snapshot.

    Missing or mismatched configuration fails startup. Draft edits require restart
    with a new revision, just as published knowledge uses a controlled restart.
    No application database initialization or source-fixture fallback occurs.
    """
    @asynccontextmanager
    async def lifespan(app):
        draft_id = os.environ.get("CARELOOP_REVIEW_DRAFT", "")
        revision_text = os.environ.get("CARELOOP_REVIEW_REVISION", "")
        if not draft_id or not revision_text.isdecimal() or int(revision_text) < 1:
            raise ValueError("review deployment requires CARELOOP_REVIEW_DRAFT and a positive CARELOOP_REVIEW_REVISION")
        url = database_url("knowledge")
        if not url:
            raise ValueError("review deployment requires a knowledge PostgreSQL URL")
        if os.environ.get("CARELOOP_KNOWLEDGE_RELEASE"):
            raise ValueError("review deployment cannot select a published release simultaneously")
        store = KnowledgeStore(url)
        rules, dishes = store.documents(draft_id, int(revision_text))
        state = store.show(draft_id)
        if (state["revision"] != int(revision_text) or state["rules_hash"] != content_hash(rules)
                or state["dishes_hash"] != content_hash(dishes)):
            raise ValueError("draft changed during review startup or selected revision is not current")
        app.state.snapshot = {"deployment_mode": "review", "clinical_workflows_enabled": False,
                              "draft": state, "technical_review": rules.get("authoring_review"),
                              "rules": rules, "dishes": dishes}
        yield

    app = FastAPI(title="CareLoop knowledge review — no clinical use", lifespan=lifespan,
                  root_path="/api", description=(
                      "Read-only inspection of an unpublished draft. Technical review is not clinical approval. "
                      "Patient guidance, meal planning, mutations, approval and publication are unavailable."))

    @app.middleware("http")
    async def restrict_surface(request: Request, call_next):
        path = request.scope.get("path", "")
        if path.startswith("/api/"):
            path = path[4:]
        allowed = {"/", "/healthz", "/knowledge-review", "/knowledge-review/documents",
                   "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
        if request.method not in {"GET", "HEAD"} or path not in allowed:
            return JSONResponse(status_code=503, content={
                "error": "review_only_deployment", "clinical_workflows_enabled": False,
                "detail": "This deployment only inspects draft knowledge. No clinical workflows or writes are enabled.",
            })
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "service": "careloop-backend", "deployment_mode": "review",
                "clinical_workflows_enabled": False}

    @app.get("/")
    @app.get("/knowledge-review", summary="Inspect review status, provenance and blockers")
    def review_status():
        snapshot = app.state.snapshot
        return {key: snapshot[key] for key in ("deployment_mode", "clinical_workflows_enabled", "draft", "technical_review")}

    @app.get("/knowledge-review/documents", summary="Inspect the pinned rules and catalogue, not a live release")
    def documents():
        snapshot = app.state.snapshot
        return {"clinical_workflows_enabled": False, "rules": snapshot["rules"], "dishes": snapshot["dishes"]}

    return app
