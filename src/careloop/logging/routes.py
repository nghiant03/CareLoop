from datetime import date
from uuid import UUID

from fastapi import APIRouter, Request

from careloop.logging import service
from careloop.logging.models import DayInput, LogEdit, LogInput, MealConfirmation

router = APIRouter(prefix="/api/patients/{patient_id}", tags=["Meal logging"])


@router.post("/meal-log-confirmations", status_code=201)
def confirm(patient_id: UUID, data: MealConfirmation, request: Request):
    with request.app.state.pool.connection() as conn:
        result = service.confirm_meal(conn, patient_id, data)
    return result


@router.post("/meal-logs", status_code=201)
def create(patient_id: UUID, data: LogInput, request: Request):
    with request.app.state.pool.connection() as conn:
        result = service.save_log(conn, patient_id, data)
    return result


@router.post("/meal-logs/{log_id}/revisions", status_code=201)
def correct(patient_id: UUID, log_id: UUID, data: LogEdit, request: Request):
    with request.app.state.pool.connection() as conn:
        result = service.save_log(conn, patient_id, data, log_id)
    return result


@router.get("/meal-logs/{log_id}")
def history(patient_id: UUID, log_id: UUID, request: Request):
    with request.app.state.pool.connection() as conn:
        result = service.get_log(conn, patient_id, log_id)
        result["history"] = conn.execute(
            "SELECT * FROM meal_log_revisions WHERE log_id=%s ORDER BY revision", (log_id,)
        ).fetchall()
    return result


@router.get("/meal-log-days/{logged_on}")
def summary(patient_id: UUID, logged_on: date, request: Request, plan_id: UUID | None = None):
    with request.app.state.pool.connection() as conn:
        return service.day_summary(conn, patient_id, logged_on, plan_id)


@router.post("/meal-log-days/{logged_on}")
def completion(patient_id: UUID, logged_on: date, data: DayInput, request: Request):
    with request.app.state.pool.connection() as conn:
        result = service.complete_day(conn, patient_id, logged_on, data)
    return result


@router.get("/meal-log-days/{logged_on}/target-comparison")
def compare(patient_id: UUID, logged_on: date, target_id: UUID, request: Request):
    with request.app.state.pool.connection() as conn:
        return service.compare_targets(conn, patient_id, logged_on, target_id)
