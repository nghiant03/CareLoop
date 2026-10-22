"""HTTP boundary; transaction completion precedes each successful response."""

from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from careloop.db import database_url
from careloop.evidence import service
from careloop.evidence.models import (
    BatchInput,
    DraftInput,
    PublicationInput,
    RetirementInput,
    RevisionInput,
    SourceInput,
)
from careloop.foods.routes import router as food_routes
from careloop.patients.routes import router as patient_routes
from careloop.planning.routes import router as planning_routes


def create_app(url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        pool = ConnectionPool(
            url or database_url(),
            open=False,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
            timeout=5,
        )
        try:
            pool.open()
            pool.wait(timeout=10)
            app.state.pool = pool
            yield
        finally:
            pool.close()

    app = FastAPI(title="CareLoop", version="0.1.0", lifespan=lifespan)
    app.include_router(patient_routes)
    app.include_router(food_routes)
    app.include_router(planning_routes)

    @app.exception_handler(service.WorkflowError)
    async def workflow_error(request: Request, exc: service.WorkflowError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.get("/api/health")
    def health():
        with app.state.pool.connection() as conn:
            conn.execute("SELECT generation FROM evidence_catalogue").fetchone()
        return {"status": "ok"}

    @app.get("/api/evidence/sources")
    def sources(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        with app.state.pool.connection() as conn:
            return conn.execute(
                """SELECT id, title, locator, edition, content_sha256, created_at
                   FROM evidence_sources ORDER BY created_at, id LIMIT %s OFFSET %s""",
                (limit, offset),
            ).fetchall()

    @app.post("/api/evidence/sources", status_code=201)
    def create_source(data: SourceInput):
        with app.state.pool.connection() as conn:
            result = service.create_source(conn, data)
        return result

    @app.get("/api/evidence/sources/{source_id}")
    def get_source(source_id: UUID):
        with app.state.pool.connection() as conn:
            return service.source(conn, source_id)

    @app.get("/api/evidence/catalogue")
    def catalogue():
        with app.state.pool.connection() as conn:
            return service.catalogue(conn)

    @app.post("/api/evidence/rules", status_code=201)
    def create_rule(data: DraftInput):
        with app.state.pool.connection() as conn:
            result = service.save_draft(conn, data)
        return result

    @app.get("/api/evidence/rules/{rule_id}")
    def get_rule(rule_id: UUID):
        with app.state.pool.connection() as conn:
            return service.get_rule(conn, rule_id)

    @app.post("/api/evidence/rules/{rule_id}/revisions", status_code=201)
    def revise(rule_id: UUID, data: RevisionInput):
        with app.state.pool.connection() as conn:
            result = service.save_draft(conn, data, rule_id)
        return result

    @app.post("/api/evidence/approvals")
    def approve(data: BatchInput):
        with app.state.pool.connection() as conn:
            result = service.approve(conn, data)
        return result

    @app.post("/api/evidence/publications", status_code=201)
    def publish(data: PublicationInput):
        with app.state.pool.connection() as conn:
            result = service.publish(conn, data)
        return result

    @app.post("/api/evidence/rules/{rule_id}/retirement")
    def retire(rule_id: UUID, data: RetirementInput):
        with app.state.pool.connection() as conn:
            result = service.retire(conn, rule_id, data)
        return result

    @app.get("/api/evidence/publications")
    def publications(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        with app.state.pool.connection() as conn:
            return conn.execute(
                """
                SELECT p.*, (SELECT jsonb_agg(jsonb_build_object(
                    'rule_id', r.rule_id, 'revision', r.revision) ORDER BY r.rule_id)
                    FROM evidence_publication_rules r WHERE r.publication_id = p.id) AS rules
                FROM evidence_publications p ORDER BY created_at, id LIMIT %s OFFSET %s
            """,
                (limit, offset),
            ).fetchall()

    @app.get("/api/audit")
    def audit(
        entity_id: UUID | None = None,
        after: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
    ):
        with app.state.pool.connection() as conn:
            return conn.execute(
                """
                SELECT * FROM audit_events WHERE sequence > %s
                AND (%s::uuid IS NULL OR entity_id = %s)
                ORDER BY sequence LIMIT %s
            """,
                (after, entity_id, entity_id, limit),
            ).fetchall()

    return app
