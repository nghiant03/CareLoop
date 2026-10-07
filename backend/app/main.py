"""CareLoop FastAPI application entrypoint.

Run locally::

    uvicorn backend.app.main:app --reload --port 8000

Responsibilities:
- lifespan startup/shutdown logging (graph DB readiness is a Week 2 concern)
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
from backend.app.api import chat, envelopes, patients, plans, rules
from backend.app.core.approval_gate import EnvelopeNotApprovedError

logger = logging.getLogger("careloop")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CareLoop backend starting (version=%s)", __version__)
    # Week 2: initialise the versioned graph store / KB connections here.
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
        content={"error": "validation_error", "detail": exc.errors()},
    )


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
app.include_router(rules.router)
app.include_router(envelopes.router)
app.include_router(plans.router)
app.include_router(chat.router)


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
