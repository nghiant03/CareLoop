from uuid import UUID

from fastapi import APIRouter, Query, Request

from careloop.patients import service
from careloop.patients.csv_import import parse_csv
from careloop.patients.models import (
    CSVInput,
    PatientEdit,
    PatientInput,
    ProposalInput,
    TargetApproval,
    TargetEdit,
)
from careloop.workflow import require_role

router = APIRouter(prefix="/api", tags=["Patients and targets"])


@router.get("/patients")
def patients(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    with request.app.state.pool.connection() as conn:
        return conn.execute(
            """SELECT p.*, r.body, r.created_at FROM patients p
            JOIN patient_revisions r ON (r.patient_id, r.revision) = (p.id, p.latest_revision)
            ORDER BY r.created_at, p.id LIMIT %s OFFSET %s""",
            (limit, offset),
        ).fetchall()


@router.post("/patients", status_code=201)
def create_patient(data: PatientInput, request: Request):
    with request.app.state.pool.connection() as conn:
        result = service.save_patient(conn, data)
    return result


@router.post("/patients/import-csv", status_code=201)
def import_patients(data: CSVInput, request: Request):
    require_role(data, "clinician")
    records = parse_csv(data)
    with request.app.state.pool.connection() as conn:
        imported = [service.save_patient(conn, record)["id"] for record in records]
    return {"patient_ids": imported, "count": len(imported)}


@router.get("/patients/{patient_id}")
def patient(patient_id: UUID, request: Request):
    with request.app.state.pool.connection() as conn:
        return service.get_patient(conn, patient_id)


@router.post("/patients/{patient_id}/revisions", status_code=201)
def edit_patient(patient_id: UUID, data: PatientEdit, request: Request):
    with request.app.state.pool.connection() as conn:
        result = service.save_patient(conn, data, patient_id)
    return result


@router.post("/patients/{patient_id}/targets", status_code=201)
def propose(patient_id: UUID, data: ProposalInput, request: Request):
    with request.app.state.pool.connection() as conn:
        result = service.propose(conn, patient_id, data)
    return result


@router.get("/patients/{patient_id}/targets")
def targets(patient_id: UUID, request: Request):
    with request.app.state.pool.connection() as conn:
        service.get_patient(conn, patient_id)
        return conn.execute(
            """SELECT id, patient_revision, latest_revision, approved_revision,
            needs_review, review_reasons, created_at FROM target_sets WHERE patient_id = %s
            ORDER BY created_at, id""",
            (patient_id,),
        ).fetchall()


@router.get("/patients/{patient_id}/target-readiness")
def readiness(patient_id: UUID, request: Request):
    with request.app.state.pool.connection() as conn:
        return service.target_readiness(conn, patient_id)


@router.get("/targets/{target_id}")
def target(target_id: UUID, request: Request):
    with request.app.state.pool.connection() as conn:
        return service.get_target(conn, target_id)


@router.post("/targets/{target_id}/revisions", status_code=201)
def edit_target(target_id: UUID, data: TargetEdit, request: Request):
    with request.app.state.pool.connection() as conn:
        result = service.edit_target(conn, target_id, data)
    return result


@router.post("/targets/{target_id}/approval")
def approve_target(target_id: UUID, data: TargetApproval, request: Request):
    with request.app.state.pool.connection() as conn:
        result = service.approve_target(conn, target_id, data)
    return result
