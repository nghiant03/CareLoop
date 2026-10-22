"""Transaction-local plan flags shared by food and target workflows."""

from psycopg.types.json import Jsonb

from careloop.workflow import record_event


def flag_plans(conn, decision, reason, *, target_id=None, food_id=None, plan_id=None, facts=None):
    rows = conn.execute(
        """
        SELECT p.id, p.body FROM plans p JOIN plan_requests r ON r.id = p.request_id
        WHERE (%s::uuid IS NULL OR r.target_id = %s)
          AND (%s::uuid IS NULL OR p.id = %s)
          AND (%s::uuid IS NULL OR EXISTS (
              SELECT 1 FROM plan_foods f WHERE f.plan_id = p.id AND f.food_id = %s))
    """,
        (target_id, target_id, plan_id, plan_id, food_id, food_id),
    ).fetchall()
    for row in rows:
        alerts = []
        if facts is not None:
            for meal in row["body"]["meals"]:
                for allergy in facts.get("allergies") or []:
                    status = meal["food"]["allergen_status"].get(allergy)
                    if status != "absent":
                        alerts.append(
                            {
                                "day": meal["day"],
                                "slot": meal["slot"],
                                "allergen": allergy,
                                "status": status or "unknown",
                            }
                        )
        conn.execute(
            """UPDATE plans SET needs_review = true,
            review_reasons = review_reasons || %s::jsonb,
            allergy_alerts = allergy_alerts || %s::jsonb WHERE id = %s""",
            (Jsonb([reason]), Jsonb(alerts), row["id"]),
        )
        record_event(
            conn, decision, "plan.flagged", row["id"], {"reason": reason, "allergy_alerts": alerts}
        )
