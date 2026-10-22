from uuid import UUID

from fastapi import APIRouter, Query, Request

from careloop.foods.models import FoodEdit, FoodInput
from careloop.foods.service import get_food, save_food

router = APIRouter(prefix="/api/foods", tags=["Food catalogue"])


@router.get("")
def foods(
    request: Request,
    q: str = "",
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    with request.app.state.pool.connection() as conn:
        return conn.execute(
            """SELECT f.*, r.body FROM foods f JOIN food_revisions r
            ON (r.food_id, r.revision) = (f.id, f.latest_revision)
            WHERE strpos(lower(r.body->>'name'), lower(%s)) > 0
            ORDER BY r.body->>'name', f.id LIMIT %s OFFSET %s""",
            (q, limit, offset),
        ).fetchall()


@router.get("/{food_id}")
def food(food_id: UUID, request: Request):
    with request.app.state.pool.connection() as conn:
        return get_food(conn, food_id)


@router.post("", status_code=201)
def create_food(data: FoodInput, request: Request):
    with request.app.state.pool.connection() as conn:
        result = save_food(conn, data)
    return result


@router.post("/{food_id}/revisions", status_code=201)
def revise(food_id: UUID, data: FoodEdit, request: Request):
    with request.app.state.pool.connection() as conn:
        result = save_food(conn, data, food_id)
    return result
