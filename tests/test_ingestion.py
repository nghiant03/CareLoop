import psycopg
import pytest
from psycopg.rows import dict_row
from test_sgfoodid import source_row

from careloop.adapters import nhanes, sgfoodid
from careloop.ingestion import import_records
from careloop.workflow import WorkflowError


@pytest.mark.parametrize(
    "source,role,table",
    [
        ("nhanes", "clinician", "patients"),
        ("sgfoodid", "reviewer", "foods"),
    ],
)
def test_import_functions_preserve_roles_and_caller_transaction(
    client, database, source, role, table
):
    records, _ = (
        nhanes.normalize([{"SEQN": 123, "RIDAGEYR": 40}], "a" * 64, 1)
        if source == "nhanes"
        else sgfoodid.normalize([source_row()], "a" * 64, 0)
    )
    with psycopg.connect(database, row_factory=dict_row) as conn:
        with pytest.raises(WorkflowError, match="role"):
            import_records(
                conn, source, records, {"name": "Test", "role": "patient"}, "Test import"
            )
        saved = import_records(conn, source, records, {"name": "Test", "role": role}, "Test import")
        assert len(saved) == 1
        conn.rollback()
    assert client.get(f"/api/{table}").json() == []
    with psycopg.connect(database, row_factory=dict_row) as conn:
        import_records(conn, source, records, {"name": "Test", "role": role}, "Test import")
    assert len(client.get(f"/api/{table}").json()) == 1
