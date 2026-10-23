from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from careloop.evidence import acquisition, documents, extraction, imports, service
from careloop.evidence.models import BatchInput
from careloop.inference import InferenceClient, configured_client
from careloop.workflow import WorkflowError, require_role

router = APIRouter(prefix="/api/evidence", tags=["Evidence acquisition"])


@router.post("/sources/{source_id}/extractions", status_code=201)
def extract_rules(
    source_id: UUID,
    data: extraction.ExtractionInput,
    request: Request,
    client: Annotated[InferenceClient, Depends(configured_client)],
):
    return extraction.extract(request.app.state.pool, client, source_id, data)


@router.get("/sources/{source_id}/extractions/{request_id}")
def extraction_run(source_id: UUID, request_id: UUID, request: Request):
    with request.app.state.pool.connection() as conn:
        return extraction.get_run(conn, source_id, request_id)


@router.get("/sources/{source_id}/extractions")
def extraction_history(
    source_id: UUID,
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    with request.app.state.pool.connection() as conn:
        service.source(conn, source_id)
        return conn.execute(
            """SELECT id, source_id, state, result, error, rule_ids, created_at, finished_at,
            jsonb_build_object('model', request->>'model',
                'decision', request->'decision') AS request
            FROM evidence_extractions WHERE source_id=%s
            ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s""",
            (source_id, limit, offset),
        ).fetchall()


@router.post("/conflict-check")
def conflicts(data: BatchInput, request: Request):
    with request.app.state.pool.connection() as conn:
        return service.conflict_report(conn, data)


@router.get("/discovery-seeds")
def seeds():
    return {"approved_domains": sorted(acquisition.DOMAINS), "seeds": acquisition.SEEDS}


@router.post("/discover")
def discover(data: imports.DiscoveryInput):
    require_role(data, "reviewer")
    payload, metadata = acquisition.download(data.url)
    if "text/html" not in metadata["content_type"].lower():
        raise WorkflowError(422, "Discovery requires an HTML page; import PDFs directly")
    return {
        "source": metadata,
        "candidates": documents.discover(payload, metadata["final_url"], data.query),
        "limit": 100,
        "scope": "Approved-domain links on this page only",
    }


@router.post("/source-imports", status_code=201)
def import_document(data: imports.DocumentInput, request: Request):
    prepared = imports.prepare(data)
    with request.app.state.pool.connection() as conn:
        result = imports.save(conn, data, prepared)
    return result


@router.get("/sources/{source_id}/document")
def original(source_id: UUID, request: Request):
    with request.app.state.pool.connection() as conn:
        row = conn.execute(
            "SELECT original, metadata FROM evidence_documents WHERE source_id=%s", (source_id,)
        ).fetchone()
        if row is None:
            raise WorkflowError(404, "No acquired document for this source")
    suffix = "pdf" if row["metadata"]["media_type"] == "application/pdf" else "html"
    return Response(
        bytes(row["original"]),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="source.{suffix}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/sources/{source_id}/passages")
def source_passages(
    source_id: UUID,
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    with request.app.state.pool.connection() as conn:
        service.source(conn, source_id)
        return conn.execute(
            """SELECT * FROM evidence_passages WHERE source_id=%s
            ORDER BY ordinal LIMIT %s OFFSET %s""",
            (source_id, limit, offset),
        ).fetchall()


@router.get("/passages")
def search(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    published_only: bool = True,
    limit: int = Query(20, ge=1, le=100),
):
    with request.app.state.pool.connection() as conn:
        return conn.execute(
            """SELECT p.*, s.title, s.locator, s.edition,
            ts_rank(to_tsvector('english', p.content), plainto_tsquery('english', %s)) AS score
            FROM evidence_passages p JOIN evidence_sources s ON s.id=p.source_id
            WHERE to_tsvector('english', p.content) @@ plainto_tsquery('english', %s)
            AND (NOT %s OR EXISTS (SELECT 1 FROM evidence_rules r JOIN evidence_revisions v
                ON (v.rule_id,v.revision)=(r.id,r.active_revision)
                WHERE v.source_id=p.source_id AND NOT r.retired))
            ORDER BY score DESC, p.source_id, p.ordinal LIMIT %s""",
            (q, q, published_only, limit),
        ).fetchall()
