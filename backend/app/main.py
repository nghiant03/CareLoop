"""CareLoop FastAPI application entrypoint.

Run locally::

    uvicorn backend.app.main:app --reload --port 8000

Responsibilities:
- lifespan logging and knowledge-base warmup
- dev-permissive CORS for the React UI
- exception handlers that keep error bodies stable for the frontend
- mounting of the patient / rules / envelope / plan / chat routers
- the ``/healthz`` liveness probe
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app import __version__
from backend.app.api import (
    adherence,
    chat,
    dishes,
    envelopes,
    kb,
    mining,
    observations,
    patients,
    plans,
    review,
    rules,
    simulations,
)
from backend.app.core.approval_gate import EnvelopeNotApprovedError
from backend.app.core.envelope_lifecycle import EnvelopeScopeError
from backend.app.core.persistence import EnvelopeConflictError

logger = logging.getLogger("careloop")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CareLoop backend starting (version=%s)", __version__)
    try:
        # Warm the versioned knowledge base + BM25 index once per process
        # (in-memory SQLite per rules/SCHEMA_DECISION.md). Failure to load must
        # not take the API down; endpoints fall back to lazy loading.
        from backend.app.core.kb_loader import get_kb

        stats = get_kb().stats()
        logger.info("knowledge base ready: %s nodes", sum(stats["node_counts"].values()))
    except Exception as exc:  # pragma: no cover - missing dataset
        logger.warning("knowledge base not loaded at startup: %s", exc)
    yield
    logger.info("CareLoop backend shutting down")


app = FastAPI(
    title="CareLoop API",
    version=__version__,
    description=(
        "Explainable decision support: approved nutrient envelopes -> Singapore "
        "meal plans, with traceability from guideline to plated meal."
    ),
    lifespan=lifespan,
)

# Dev-permissive CORS. Tighten allow_origins before any deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(EnvelopeNotApprovedError)
async def _envelope_not_approved_handler(
    request: Request, exc: EnvelopeNotApprovedError
) -> JSONResponse:
    """Render the approval-gate violation as the documented 409 body."""
    return JSONResponse(
        status_code=409,
        content={"error": "envelope_not_approved", "status": exc.status},
    )


@app.exception_handler(RequestValidationError)
async def _validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": [
            {k: v for k, v in error.items() if k != "ctx"} for error in exc.errors()
        ]},
    )


@app.exception_handler(EnvelopeConflictError)
async def _envelope_conflict_handler(request: Request, exc: EnvelopeConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={
        "error": "envelope_conflict", "envelope_id": exc.envelope_id, "message": str(exc),
    })


@app.exception_handler(EnvelopeScopeError)
async def _envelope_scope_handler(request: Request, exc: EnvelopeScopeError) -> JSONResponse:
    return JSONResponse(status_code=422, content={
        "error": "out_of_scope_envelope", "envelope_id": exc.envelope.envelope_id,
        "status": exc.envelope.status.value,
    })


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": str(exc)},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(patients.router)
app.include_router(adherence.router)
app.include_router(dishes.router)
app.include_router(rules.router)
app.include_router(envelopes.router)
app.include_router(plans.router)
app.include_router(observations.router)
app.include_router(review.router)
app.include_router(simulations.router)
app.include_router(chat.router)
app.include_router(mining.router)
app.include_router(kb.router)


@app.get("/healthz", tags=["meta"], summary="Liveness probe")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "careloop-backend", "version": __version__}


@app.get("/", tags=["meta"], summary="Service banner")
def root() -> dict[str, str]:
    return {
        "service": "CareLoop API",
        "version": __version__,
        "docs": "/docs",
        "health": "/healthz",
    }
