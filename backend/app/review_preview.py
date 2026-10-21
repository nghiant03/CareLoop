"""Draft inspection and opt-in review decisions, separate from clinical workflows.

No patient, planner, chat, envelope approval or publication handlers are imported here.
The explicit draft revision is pinned at startup and is never a runtime release.
"""

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.knowledge.store import KnowledgeStore
from backend.knowledge.validation import content_hash
from backend.storage.postgres import database_url


class ReviewDecision(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    decision: Literal["approve", "reject"]
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=1, max_length=10000)


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
        operator_file = os.environ.get("CARELOOP_REVIEW_OPERATOR_URL_FILE")
        app.state.operator = KnowledgeStore(Path(operator_file).read_text().strip()) if operator_file else None
        app.state.store = store
        app.state.token = secrets.token_urlsafe(32)
        app.state.snapshot = {"deployment_mode": "review", "clinical_workflows_enabled": False,
                              "draft": state, "technical_review": rules.get("authoring_review"),
                              "rules": rules, "dishes": dishes}
        yield

    app = FastAPI(title="CareLoop knowledge review — no clinical use", lifespan=lifespan,
                  root_path="/api", description=(
                      "Inspect an unpublished draft and optionally record revision-bound review decisions. "
                      "Patient guidance, meal planning, document editing and publication are unavailable."))

    @app.middleware("http")
    async def restrict_surface(request: Request, call_next):
        path = request.scope.get("path", "")
        if path.startswith("/api/"):
            path = path[4:]
        allowed = {"/", "/healthz", "/knowledge-review", "/knowledge-review/documents",
                   "/knowledge-review/history", "/knowledge-review/revision",
                   "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
        decision_request = path == "/knowledge-review/decision" and request.method == "POST"
        if not decision_request and (request.method not in {"GET", "HEAD"} or path not in allowed):
            return JSONResponse(status_code=503, content={
                "error": "review_only_deployment", "clinical_workflows_enabled": False,
                "detail": "Only draft inspection and explicitly enabled review decisions are available. Clinical workflows are disabled.",
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
        result = {key: snapshot[key] for key in ("deployment_mode", "clinical_workflows_enabled", "draft", "technical_review")}
        result["review_enabled"] = app.state.operator is not None
        result["csrf_token"] = app.state.token
        result["current_draft"] = app.state.store.show(snapshot["draft"]["draft_id"])
        return result

    @app.get("/knowledge-review/documents", summary="Inspect the pinned rules and catalogue, not a live release")
    def documents():
        snapshot = app.state.snapshot
        return {"clinical_workflows_enabled": False, "rules": snapshot["rules"], "dishes": snapshot["dishes"]}

    @app.get("/knowledge-review/history")
    def history():
        return app.state.store.history(app.state.snapshot["draft"]["draft_id"])

    @app.get("/knowledge-review/revision")
    def revision(revision: int):
        if revision < 1 or revision > app.state.snapshot["draft"]["revision"]:
            return JSONResponse(status_code=404, content={"detail": "Revision outside pinned snapshot"})
        rules, dishes = app.state.store.documents(app.state.snapshot["draft"]["draft_id"], revision)
        return {"rules": rules, "dishes": dishes}

    @app.post("/knowledge-review/decision")
    def decide(payload: ReviewDecision, request: Request):
        if not secrets.compare_digest(request.headers.get("x-review-token", ""), app.state.token):
            return JSONResponse(status_code=403, content={"detail": "Reload the workspace before submitting a review"})
        if app.state.operator is None:
            return JSONResponse(status_code=403, content={"detail": "Review recording is not enabled by the operator"})
        draft = app.state.snapshot["draft"]
        if payload.expected_revision != draft["revision"]:
            return JSONResponse(status_code=409, content={"detail": "Decision must match the displayed pinned revision"})
        try:
            current = app.state.operator.show(draft["draft_id"])
            if (current["rules_hash"], current["dishes_hash"]) != (draft["rules_hash"], draft["dishes_hash"]):
                raise ValueError("stale draft revision; restart review deployment")
            result = app.state.operator.review(draft["draft_id"], **payload.model_dump())
        except ValueError as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})
        except psycopg.IntegrityError:
            return JSONResponse(status_code=409, content={"detail": "A decision already exists for this revision"})
        return result

    return app
