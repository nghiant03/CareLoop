"""Operator knowledge workspace."""

import base64
import binascii
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from urllib.parse import urlsplit

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.knowledge.discovery import (
    DiscoveryClient,
    discover_rules,
    load_discovery_prompt,
)
from backend.knowledge.store import KnowledgeStore, load_release
from backend.storage.postgres import database_url

MAX_REQUEST_BYTES = 32 * 1024 * 1024
logger = logging.getLogger("careloop.knowledge")


class OperatorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Authorship(OperatorRequest):
    actor: str = Field(min_length=1, max_length=200)


class CreateDraft(Authorship):
    draft_id: str = Field(min_length=1, max_length=100)
    rules: dict
    dishes: list[dict]


class RevisionAction(Authorship):
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=1, max_length=10000)


class EditDraft(RevisionAction):
    rules: dict
    dishes: list[dict]


class ReviewDecision(RevisionAction):
    decision: Literal["approve", "reject"]
    confirmed: Literal[True]


class PublishDraft(RevisionAction):
    release_id: str = Field(min_length=1, max_length=100)
    confirmed: Literal[True]


class CloneRelease(Authorship):
    release_id: str = Field(min_length=1, max_length=100)
    draft_id: str = Field(min_length=1, max_length=100)


class SourceUpload(OperatorRequest):
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=MAX_REQUEST_BYTES)
    encoding: Literal["text", "base64"] = "text"
    source_url: str | None = Field(default=None, max_length=2000)


class DiscoveryRequest(OperatorRequest):
    sources: list[SourceUpload] = Field(min_length=1, max_length=10)
    draft_id: str | None = None
    instructions: str | None = Field(default=None, min_length=1, max_length=100000)


def create_review_app(*, discovery_client: DiscoveryClient | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        if os.environ.get("CARELOOP_KNOWLEDGE_RELEASE"):
            raise ValueError("knowledge workspace cannot select a live release; use published mode for clinical workflows")
        url = database_url("knowledge")
        if not url:
            raise ValueError("knowledge workspace requires a knowledge PostgreSQL URL")
        store = KnowledgeStore(url)
        store.initialize()  # Deployment setup owns schema creation.
        app.state.store = store
        app.state.token = secrets.token_urlsafe(32)
        app.state.discovery_client = discovery_client
        yield

    app = FastAPI(title="CareLoop knowledge workspace — no clinical use", lifespan=lifespan,
                  root_path="/api", description=(
                      "Local operator discovery, draft authoring, revision-bound review and publication. "
                      "Publication never activates knowledge. Patient guidance and planning are unavailable."))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def restrict_surface(request: Request, call_next):
        path = request.scope.get("path", "")
        if path.startswith("/api/"):
            path = path[4:]
        if not (path == "/knowledge" or path.startswith("/knowledge/") or path in {
            "/", "/healthz", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json",
        }):
            return JSONResponse(status_code=503, content={
                "error": "review_only_deployment", "clinical_workflows_enabled": False,
                "detail": "Clinical workflows are disabled in the knowledge workspace.",
            }, headers={"Cache-Control": "no-store"})
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (request.url.scheme, request.url.netloc):
                return JSONResponse(status_code=403, content={"detail": "Cross-origin operator requests are not allowed"})
            # Bound streamed bodies as well as declared lengths.
            received = bytearray()
            async for chunk in request.stream():
                received.extend(chunk)
                if len(received) > MAX_REQUEST_BYTES:
                    return JSONResponse(status_code=413, content={"detail": "Request exceeds the 32 MiB upload limit"})
            request._body = bytes(received)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def require_token(request: Request):
        if not secrets.compare_digest(request.headers.get("x-review-token", ""), app.state.token):
            raise HTTPException(status_code=403, detail="Reload the workspace before submitting an operator action")

    @app.exception_handler(ValueError)
    async def invalid_operation(request: Request, error: ValueError):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(psycopg.IntegrityError)
    async def conflicting_operation(request: Request, error: psycopg.IntegrityError):
        return JSONResponse(status_code=409, content={"detail": "A draft, release or review with this identity already exists. Refresh before retrying."})

    @app.exception_handler(psycopg.Error)
    async def storage_failure(request: Request, error: psycopg.Error):
        return JSONResponse(status_code=503, content={"detail": "Knowledge storage is unavailable. No successful save is confirmed; refresh before retrying."})

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "service": "careloop-backend", "deployment_mode": "review",
                "clinical_workflows_enabled": False}

    @app.get("/")
    @app.get("/knowledge")
    def workspace_status():
        return {"deployment_mode": "review", "clinical_workflows_enabled": False,
                "csrf_token": app.state.token, "drafts": app.state.store.list_drafts(),
                "discovery_available": app.state.discovery_client is not None,
                "instructions": load_discovery_prompt()}

    @app.post("/knowledge/drafts", dependencies=[Depends(require_token)], status_code=201)
    def create_draft(payload: CreateDraft):
        return app.state.store.create_draft(**payload.model_dump())

    @app.get("/knowledge/drafts/{draft_id}")
    def draft_snapshot(draft_id: str, revision: int | None = None):
        state = app.state.store.show(draft_id)
        selected_revision = state["revision"] if revision is None else revision
        if selected_revision < 1 or selected_revision > state["revision"]:
            raise HTTPException(status_code=404, detail="Draft revision not found")
        rules, dishes = app.state.store.documents(draft_id, selected_revision)
        return {"draft": state, "revision": selected_revision,
                "documents": {"rules": rules, "dishes": dishes}, "events": app.state.store.history(draft_id)}

    @app.put("/knowledge/drafts/{draft_id}", dependencies=[Depends(require_token)])
    def edit_draft(draft_id: str, payload: EditDraft):
        return app.state.store.edit_draft(draft_id, **payload.model_dump())

    @app.post("/knowledge/drafts/{draft_id}/review", dependencies=[Depends(require_token)])
    def review_draft(draft_id: str, payload: ReviewDecision):
        return app.state.store.review(draft_id, **payload.model_dump(exclude={"confirmed"}))

    @app.post("/knowledge/drafts/{draft_id}/publish", dependencies=[Depends(require_token)])
    def publish_draft(draft_id: str, payload: PublishDraft):
        release = app.state.store.publish(draft_id, **payload.model_dump(exclude={"confirmed"}))
        return {"release_id": release.release_id, "published_at": release.published_at,
                "activated": False, "detail": "Select this release in published deployment mode and restart to activate it."}

    @app.get("/knowledge/releases/{release_id}")
    def release_documents(release_id: str):
        release = load_release(app.state.store.database, release_id)
        return {"release_id": release.release_id, "rules": release.rules_document(), "dishes": release.dishes()}

    @app.post("/knowledge/clone", dependencies=[Depends(require_token)], status_code=201)
    def clone_release(payload: CloneRelease):
        release = load_release(app.state.store.database, payload.release_id)
        return app.state.store.create_draft(payload.draft_id, release.rules_document(), release.dishes(),
                                           actor=payload.actor, parent_release=payload.release_id,
                                           provenance={"parent_release": payload.release_id})

    @app.post("/knowledge/discover", dependencies=[Depends(require_token)])
    def discover(payload: DiscoveryRequest):
        if app.state.discovery_client is None:
            raise HTTPException(status_code=503, detail="Discovery provider is not configured. No provider has been selected; no extraction was attempted.")
        rules = {"dsl_version": "1.0", "rules": []}
        if payload.draft_id:
            rules, _ = app.state.store.documents(payload.draft_id)
        with TemporaryDirectory(prefix="careloop-discovery-") as directory:
            paths = []
            names = set()
            for source in payload.sources:
                if (Path(source.name).name != source.name or source.name in {".", ".."}
                        or "\\" in source.name or source.name in names):
                    raise HTTPException(status_code=422, detail="Source filenames must be unique names, not filesystem paths")
                names.add(source.name)
                path = Path(directory) / source.name
                try:
                    content = (base64.b64decode(source.content, validate=True) if source.encoding == "base64"
                               else source.content.encode("utf-8"))
                except (ValueError, binascii.Error) as error:
                    raise HTTPException(status_code=422, detail="Source contains invalid base64 data") from error
                path.write_bytes(content)
                paths.append(path)
            try:
                return discover_rules(paths, rules, app.state.discovery_client,
                                      source_urls=[source.source_url for source in payload.sources],
                                      source_names=[source.name for source in payload.sources],
                                      instructions=payload.instructions)
            except (ValueError, TypeError) as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            except Exception as error:
                logger.warning("Knowledge extraction failed (%s)", type(error).__name__)
                raise HTTPException(status_code=502, detail="Discovery failed. Check source readability and the configured provider; no knowledge was changed.") from error

    return app
