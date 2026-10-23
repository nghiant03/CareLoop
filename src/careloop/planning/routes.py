from uuid import UUID

from fastapi import APIRouter, Query, Request

from careloop.planning import service
from careloop.planning.models import PlanApproval, PlanInput, RecommendationInput, SubstitutionInput
from careloop.planning.recommendations import recommend

router = APIRouter(prefix="/api", tags=["Meal plans"])


@router.post("/plan-requests", status_code=201)
def generate(data: PlanInput, request: Request):
    with request.app.state.pool.connection() as conn:
        result = service.request_plans(conn, data)
    return result


@router.get("/patients/{patient_id}/plans")
def plans(
    patient_id: UUID,
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    with request.app.state.pool.connection() as conn:
        return conn.execute(
            """SELECT p.id, p.objective, p.needs_review, p.approved_at,
            p.request_id, r.target_id, r.target_revision, r.body->>'start_date' AS start_date
            FROM plans p JOIN plan_requests r ON r.id = p.request_id WHERE r.patient_id = %s
            ORDER BY p.created_at, p.id LIMIT %s OFFSET %s""",
            (patient_id, limit, offset),
        ).fetchall()


@router.get("/plans/{plan_id}")
def plan(plan_id: UUID, request: Request):
    with request.app.state.pool.connection() as conn:
        return service.get_plan(conn, plan_id)


@router.post("/plans/{plan_id}/approval")
def approve(plan_id: UUID, data: PlanApproval, request: Request):
    with request.app.state.pool.connection() as conn:
        result = service.approve_plan(conn, plan_id, data)
    return result


@router.post("/plans/{plan_id}/substitutions", status_code=201)
def substitute(plan_id: UUID, data: SubstitutionInput, request: Request):
    with request.app.state.pool.connection() as conn:
        result = service.substitute(conn, plan_id, data)
    return result


@router.post("/plans/{plan_id}/substitution-recommendations")
def recommendations(plan_id: UUID, data: RecommendationInput, request: Request):
    with request.app.state.pool.connection() as conn:
        result = recommend(conn, plan_id, data)
    return result
