"""Assemble the HTTP app, startup warmup, and shared error responses."""

from __future__ import annotations

import logging
import math
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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
from backend.app.core.persistence import EnvelopeConflictError, init_db

logger = logging.getLogger("careloop")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CareLoop backend starting (version=%s)", __version__)
    # Storage failures must prevent serving, not masquerade as a healthy startup.
    init_db()
    try:
        # Warm the KB only; BM25 is built on first retrieval. Log load failures
        # without blocking startup; lazy endpoint loading can retry them.
        from backend.app.core.kb_loader import get_kb

        stats = get_kb().stats()
        logger.info("knowledge base ready: %s nodes", sum(stats["node_counts"].values()))
    except Exception as exc:  # noqa: BLE001  # pragma: no cover - missing dataset
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
    """Render validation failures as the documented 422 body, JSON-safe.

    JSON parsers can accept nonfinite ``Infinity`` and ``NaN`` input literals.
    Response rendering rejects these values, turning the intended 422 into
    a 500 unless they are stringified. Drop ``ctx`` because it may carry
    non-serializable error objects.
    """
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": [
            _json_safe_error(error) for error in exc.errors()
        ]},
    )


def _json_safe(value: Any):
    """Recursively replace nonfinite floats with their string spelling."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _json_safe_error(error: dict) -> dict:
    return {
        key: _json_safe(value)
        for key, value in error.items()
        if key != "ctx"
    }


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


class CalendarResponse(BaseModel):
    """Server-local calendar metadata from one clock sample; no patient state."""

    today: date = Field(description="Server-local calendar date in YYYY-MM-DD format.")
    timezone: str = Field(description="System timezone name at the sampled instant, not necessarily an IANA ID.")
    utc_offset_minutes: float = Field(description="Server-local offset east of UTC in minutes at the sampled instant.")


def _server_local_now() -> datetime:
    """Sample the system clock once in the server's local timezone."""
    return datetime.now().astimezone()


@app.get("/calendar", tags=["meta"], response_model=CalendarResponse, summary="Server-local calendar")
def read_calendar() -> CalendarResponse:
    """Return today's date under the same server-local policy as adherence.

    The timezone label and UTC offset describe the same instant as the date.
    This endpoint reads no database and does not configure a timezone policy.
    """
    local_now = _server_local_now()
    utc_offset = local_now.utcoffset()
    assert utc_offset is not None  # astimezone() always returns an aware datetime.
    return CalendarResponse(
        today=local_now.date(),
        timezone=local_now.tzname() or "",
        utc_offset_minutes=utc_offset.total_seconds() / 60,
    )


@app.get("/", tags=["meta"], summary="Service banner")
def root() -> dict[str, str]:
    return {
        "service": "CareLoop API",
        "version": __version__,
        "docs": "/docs",
        "health": "/healthz",
    }
