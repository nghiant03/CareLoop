import base64
import binascii
import hashlib
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from psycopg.types.json import Jsonb
from pydantic import Field, model_validator

from careloop.evidence import acquisition, documents, service
from careloop.evidence.models import Decision, SourceInput, Text
from careloop.workflow import WorkflowError, record_event, require_role


class DocumentInput(Decision):
    title: Text
    edition: Text
    url: Annotated[str, Field(min_length=1, max_length=4000)] | None = None
    pdf_base64: Annotated[str, Field(min_length=1, max_length=13_333_336)] | None = None
    locator: Text | None = None
    refresh_of: UUID | None = None
    first_page: Annotated[int, Field(ge=1, le=500)] = 1
    last_page: Annotated[int, Field(ge=1, le=500)] | None = None

    @model_validator(mode="after")
    def one_input(self):
        if self.last_page is not None and self.last_page < self.first_page:
            raise ValueError("Last page must not precede first page")
        if (self.url is None) == (self.pdf_base64 is None):
            raise ValueError("Supply exactly one URL or base64 PDF")
        if self.pdf_base64 and not self.locator:
            raise ValueError("Uploaded PDFs require a source locator")
        return self


class DiscoveryInput(Decision):
    url: Annotated[str, Field(min_length=1, max_length=4000)]
    query: Annotated[str, Field(max_length=200)] = ""


def prepare(data):
    require_role(data, "reviewer")
    if data.url:
        raw, metadata = acquisition.download(data.url)
    else:
        try:
            raw = base64.b64decode(data.pdf_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise WorkflowError(422, "PDF upload is not valid base64") from exc
        if len(raw) > acquisition.MAX_BYTES or not raw.startswith(b"%PDF-"):
            raise WorkflowError(422, "Upload a PDF no larger than 10 MB")
        metadata = {"content_type": "application/pdf", "upload": True}
    content, chunks, parsing = documents.extract(
        raw, metadata["content_type"], data.first_page, data.last_page
    )
    metadata.update(parsing, retrieved_at=datetime.now(UTC).isoformat())
    return raw, metadata, content, chunks


def save(conn, data, prepared):
    raw, metadata, content, chunks = prepared
    previous = service.source(conn, data.refresh_of) if data.refresh_of else None
    source_data = SourceInput(
        actor=data.actor,
        reason=data.reason,
        title=data.title,
        edition=data.edition,
        locator=data.url or data.locator,
        content=content,
    )
    created = service.create_source(conn, source_data, chunks)
    if previous:
        before, after = set(previous["content"].splitlines()), set(content.splitlines())
        metadata["comparison"] = {
            "content_changed": previous["content_sha256"] != created["content_sha256"],
            "added_line_count": len(after - before),
            "removed_line_count": len(before - after),
            "added_lines_preview": sorted(after - before)[:20],
            "removed_lines_preview": sorted(before - after)[:20],
        }
    checksum = hashlib.sha256(raw).hexdigest()
    conn.execute(
        "INSERT INTO evidence_documents VALUES (%s,%s,%s,%s,%s)",
        (created["id"], raw, checksum, Jsonb(metadata), data.refresh_of),
    )
    record_event(
        conn,
        data,
        "source.acquired",
        created["id"],
        {
            "original_sha256": checksum,
            "parser": metadata["parser"],
            "refresh_of": str(data.refresh_of) if data.refresh_of else None,
        },
    )
    return service.source(conn, created["id"])
