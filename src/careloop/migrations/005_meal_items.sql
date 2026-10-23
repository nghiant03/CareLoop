ALTER TABLE meal_logs ADD COLUMN item integer NOT NULL DEFAULT 1 CHECK (item BETWEEN 1 AND 5);
ALTER TABLE meal_logs DROP CONSTRAINT meal_logs_patient_id_plan_id_logged_on_slot_key;
ALTER TABLE meal_logs ADD UNIQUE (patient_id, plan_id, logged_on, slot, item);
