"""Resumable first-boot imports; clinical decisions remain in the review workflow."""

import logging
from functools import partial
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from psycopg.types.json import Jsonb

from careloop import ingestion
from careloop.evidence import acquisition, documents, extraction, imports
from careloop.evidence.models import Actor
from careloop.evidence.structure import PARSER_VERSION
from careloop.inference import InferenceClient, Settings
from careloop.workflow import WorkflowError, lock_catalogue

LOG = logging.getLogger(__name__)
ACTOR = Actor(name="CareLoop first-boot import", role="reviewer")
REASON = "Default public-source initialization; requires explicit clinical review"
LOCK = 81723009


class BootstrapError(Exception):
    """Public initialization guidance, without upstream response or credential text."""


def status(pool):
    with pool.connection() as conn:
        return conn.execute("SELECT * FROM bootstrap_jobs ORDER BY key").fetchall()


def save_status(conn, key, state, detail=None, error=None):
    conn.execute(
        """INSERT INTO bootstrap_jobs (key,state,detail,error) VALUES (%s,%s,%s,%s)
        ON CONFLICT (key) DO UPDATE SET state=excluded.state, detail=excluded.detail,
        error=excluded.error, updated_at=now()""",
        (key, state, Jsonb(detail or {}), error),
    )


def job(pool, key, work):
    with pool.connection() as conn:
        previous = conn.execute("SELECT * FROM bootstrap_jobs WHERE key=%s", (key,)).fetchone()
        if previous and previous["state"] == "completed":
            return previous["detail"]
        save_status(conn, key, "running")
    LOG.info("First-boot processing: %s", key)
    try:
        # Import functions atomically persist their own completion markers.
        detail = work()
        with pool.connection() as conn:
            save_status(conn, key, "completed", detail)
        return detail
    except Exception as exc:
        # Do not persist exception messages that could contain provider credentials.
        error = (
            f"{type(exc).__name__}: initialization failed; inspect source/provider configuration"
        )
        if isinstance(exc, BootstrapError):
            error = str(exc)
        elif isinstance(exc, WorkflowError):
            error = exc.message
        with pool.connection() as conn:
            save_status(conn, key, "failed", error=error)
        LOG.warning("First-boot failure: %s (%s)", key, type(exc).__name__)
        return None


def load_foods(pool, directory):
    records, _, _ = ingestion.acquire("sgfoodid", Path(directory) / "sgfoodid", 0)
    with pool.connection() as conn:
        lock_catalogue(conn)
        existing = {
            r["external_id"]
            for r in conn.execute(
                "SELECT external_id FROM foods WHERE namespace=%s",
                (ingestion.ADAPTERS["sgfoodid"].NAMESPACE,),
            ).fetchall()
        }
        missing = [(code, body) for code, body in records if code not in existing]
        ingestion.import_records(conn, "sgfoodid", missing, ACTOR, REASON)
        detail = {"imported": len(missing), "source_records": len(records)}
        save_status(conn, "foods:sgfoodid:v1", "completed", detail)
    return detail


def load_source(pool, seed, key):
    data = imports.DocumentInput(
        actor=ACTOR,
        reason=REASON,
        title=seed["title"],
        url=seed["url"],
        edition="Default source acquired at first boot",
    )
    with pool.connection() as conn:
        previous = conn.execute(
            """SELECT s.id, d.original, d.metadata FROM evidence_sources s
            JOIN evidence_documents d ON d.source_id=s.id WHERE s.locator=%s
            ORDER BY s.created_at DESC LIMIT 1""",
            (seed["url"],),
        ).fetchone()
    if previous:
        data = data.model_copy(update={"refresh_of": previous["id"]})
        raw, metadata = bytes(previous["original"]), dict(previous["metadata"])
        content, chunks, parsing = documents.extract(raw, metadata["content_type"])
        metadata.update(parsing, reparsed_from=str(previous["id"]))
        prepared = raw, metadata, content, chunks
    else:
        prepared = imports.prepare(data)
    with pool.connection() as conn:
        source = imports.save(conn, data, prepared)
        detail = {"source_id": str(source["id"])}
        save_status(conn, key, "completed", detail)
    return detail


def process_passage(pool, source_id, ordinal, key):
    data = extraction.ExtractionInput(
        actor=ACTOR,
        reason=REASON,
        request_id=uuid5(NAMESPACE_URL, key),
        passage_ordinal=ordinal,
    )
    try:
        settings = Settings.load()
    except Exception:
        raise BootstrapError(
            "Configure LLM_BASE_URL and LLM_API_KEY, then restart the API"
        ) from None
    with InferenceClient(settings) as client:
        run = extraction.extract(pool, client, source_id, data)
    if run["state"] != "completed":
        # Stable request IDs preserve failed/uncertain calls rather than billing twice.
        raise BootstrapError(
            f"Extraction {data.request_id} is {run['state']}; inspect its evidence history "
            "and retry explicitly from evidence review"
        )
    return {
        "source_id": source_id,
        "passage_ordinal": ordinal,
        "request_id": str(data.request_id),
        "rule_ids": run["rule_ids"],
    }


def run(pool, directory, stop):
    # Session lock excludes other API workers; PostgreSQL releases it after a crash.
    with pool.connection() as guard:
        if not guard.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (LOCK,)).fetchone()[
            "acquired"
        ]:
            return
        guard.commit()
        try:
            job(pool, "foods:sgfoodid:v1", lambda: load_foods(pool, directory))
            sources = []
            for seed in acquisition.SEEDS:
                if stop.is_set():
                    return
                key = f"source:{PARSER_VERSION}:" + seed["url"]
                detail = job(pool, key, partial(load_source, pool, seed, key))
                if detail:
                    sources.append(detail["source_id"])
            # Acquire all documents before starting slower hosted extraction.
            for source_id in sources:
                with pool.connection() as conn:
                    passages = conn.execute(
                        "SELECT ordinal FROM evidence_passages WHERE source_id=%s ORDER BY ordinal",
                        (source_id,),
                    ).fetchall()
                    for passage in passages:
                        key = (
                            f"extract:{source_id}:{passage['ordinal']}:{extraction.PROMPT_VERSION}"
                        )
                        conn.execute(
                            "INSERT INTO bootstrap_jobs (key,state) VALUES (%s,'pending') "
                            "ON CONFLICT DO NOTHING",
                            (key,),
                        )
                for passage in passages:
                    if stop.is_set():
                        return
                    ordinal = passage["ordinal"]
                    key = f"extract:{source_id}:{ordinal}:{extraction.PROMPT_VERSION}"
                    job(pool, key, partial(process_passage, pool, source_id, ordinal, key))
        finally:
            guard.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
