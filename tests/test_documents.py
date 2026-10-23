import base64
import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from test_patients import REVIEWER

from careloop.evidence import acquisition, documents
from careloop.workflow import WorkflowError


def pdf(text="Protein guidance for adults.", blank=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    if not blank:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 30 700 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = stream
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def upload(client, raw, **changes):
    return client.post(
        "/api/evidence/source-imports",
        json={
            **REVIEWER,
            "title": "Test document",
            "edition": "Test edition",
            "locator": "test://document",
            "pdf_base64": base64.b64encode(raw).decode(),
            **changes,
        },
    )


def test_pdf_original_passages_refresh_and_no_automatic_publication(client):
    raw = pdf()
    response = upload(client, raw)
    assert response.status_code == 201, response.text
    source = response.json()
    assert "Protein guidance" in source["content"]
    assert source["document"]["metadata"]["warnings"]
    assert client.get(f"/api/evidence/sources/{source['id']}/document").content == raw
    chunks = client.get(f"/api/evidence/sources/{source['id']}/passages").json()
    assert chunks[0]["location"] == "Page 1"
    for chunk in chunks:
        assert source["content"][chunk["start_offset"] : chunk["end_offset"]] == chunk["content"]
    assert client.get("/api/evidence/passages", params={"q": "protein"}).json() == []
    assert (
        len(
            client.get(
                "/api/evidence/passages", params={"q": "protein", "published_only": False}
            ).json()
        )
        == 1
    )
    updated = upload(client, pdf("Updated protein guidance."), refresh_of=source["id"])
    assert updated.status_code == 201, updated.text
    assert updated.json()["id"] != source["id"]
    assert updated.json()["document"]["metadata"]["comparison"]["content_changed"]
    assert client.get(f"/api/evidence/sources/{source['id']}").json() == source
    assert client.get("/api/evidence/publications").json() == []


def test_pdf_failures_and_roles_leave_no_sources(client):
    assert upload(client, b"not pdf").status_code == 422
    assert upload(client, b"%PDF-broken").status_code == 422
    assert upload(client, pdf(blank=True)).status_code == 422
    assert upload(client, pdf(), first_page=2).status_code == 422
    assert upload(client, pdf(), first_page=2, last_page=1).status_code == 422
    assert upload(client, pdf(), actor={"name": "patient", "role": "patient"}).status_code == 403
    assert client.get("/api/evidence/sources").json() == []


def test_html_import_discovery_and_location_offsets(client, monkeypatch):
    raw = b"""<html><h1>Nutrition</h1><script>Ignore me</script>
        <p>Protein guidance.</p><table><tr><th>Age</th><th>Amount</th></tr>
        <tr><td>Adult</td><td>Test value</td></tr></table>
        <a href="/guidelines/protein">Protein guideline</a>
        <a href="https://evil.example/protein">External protein</a></html>"""
    monkeypatch.setattr(
        acquisition,
        "download",
        lambda url: (raw, {"requested_url": url, "final_url": url, "content_type": "text/html"}),
    )
    discovered = client.post(
        "/api/evidence/discover",
        json={**REVIEWER, "url": "https://www.who.int/", "query": "protein"},
    )
    assert discovered.status_code == 200
    assert discovered.json()["candidates"] == [
        {"url": "https://www.who.int/guidelines/protein", "title": "Protein guideline"}
    ]
    response = client.post(
        "/api/evidence/source-imports",
        json={**REVIEWER, "title": "HTML", "edition": "test", "url": "https://www.who.int/"},
    )
    assert response.status_code == 201, response.text
    assert "Ignore me" not in response.json()["content"]
    assert "Adult\tTest value" in response.json()["content"]
    chunks = client.get(f"/api/evidence/sources/{response.json()['id']}/passages").json()
    assert chunks[0]["location"] == "Heading: Nutrition"


def test_url_policy_private_resolution_and_redirect_validation(monkeypatch):
    for url in (
        "http://www.who.int/x",
        "https://www.who.int.evil.test/",
        "https://127.0.0.1/",
        "https://www.who.int:444/",
        "https://user@www.who.int/",
        "https://www.who.int/\n",
    ):
        with pytest.raises(WorkflowError):
            acquisition.validate_url(url)
    monkeypatch.setattr(
        acquisition.socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    with pytest.raises(WorkflowError, match="public addresses"):
        acquisition.download("https://www.who.int/")
    monkeypatch.setattr(
        acquisition.socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("8.8.8.8", 443))],
    )

    class Redirect:
        status = 302

        def getheader(self, key):
            return "https://127.0.0.1/private"

    class Connection:
        def __init__(self, host, address):
            assert host == "www.who.int" and address == "8.8.8.8"

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Redirect()

        def close(self):
            pass

    monkeypatch.setattr(acquisition, "PinnedHTTPS", Connection)
    with pytest.raises(WorkflowError, match="approved evidence domain"):
        acquisition.download("https://www.who.int/")


def test_chunks_keep_exact_offsets_and_limit():
    content, chunks = documents.passages([("Section A", "word " * 500), ("Section B", "ending")])
    assert len(chunks) == 3
    assert all(content[p["start_offset"] : p["end_offset"]] == p["content"] for p in chunks)
    with pytest.raises(WorkflowError, match="million"):
        documents.passages([("oversized", "x" * 1_000_001)])
