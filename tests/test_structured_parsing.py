import json
import sys
from types import SimpleNamespace

import pytest
from test_documents import pdf

from careloop.evidence import documents, pdf_worker
from careloop.evidence.structure import html_sections, ocr_sections


def test_html_keeps_parent_units_and_table_headers_without_navigation():
    raw = b"""<nav>Navigation</nav><main><h1>Nutrition</h1><h2>Energy</h2>
    <p>Requirements (kcal/day)</p><h3>Adults</h3>
    <table><tr><th>Age</th><th>Male</th><th>Female</th></tr>
    <tr><td>18-29</td><td>2280</td><td>1745</td></tr>
    <tr><td>30-59</td><td>2185</td><td>1720</td></tr></table>
    <footer>Subscribe</footer></main>"""
    sections = html_sections(raw)
    tables = [value for _, value in sections if "<table>" in value]
    assert len(tables) == 1
    assert all("kcal/day" in t and "<th>Female</th>" in t and "Energy" in t for t in tables)
    content, chunks = documents.passages(sections)
    assert "Subscribe" not in content and "Navigation" not in content
    assert all(content[c["start_offset"] : c["end_offset"]] == c["content"] for c in chunks)


def test_merged_cells_are_not_detached_from_their_rows():
    sections = html_sections(b"""<main><h1>Requirements</h1><table>
    <tr><th rowspan="2">Age</th><th colspan="2">Energy</th></tr>
    <tr><th>Male</th><th>Female</th></tr>
    <tr><td>Adult</td><td>2000</td><td>1800</td></tr></table></main>""")
    assert len(sections) == 1
    assert 'rowspan="2"' in sections[0][1] and "1800" in sections[0][1]


def test_streamed_content_outside_main_and_td_units_survive():
    sections = html_sections(b"""<body><main><article>Loading</article></main>
    <div hidden id="S:1"><h1>Guidance</h1><table>
    <tr><th>Nutrient</th><th>Requirement</th></tr>
    <tr><th>Units</th><td>mg/day</td></tr>
    <tr><td>Sodium</td><td>2000</td></tr></table></div></body>""")
    content, _ = documents.passages(sections)
    assert "mg/day" in content and "2000" in content
    assert content.count("2000") == 1


def test_sentence_boundaries_and_large_documents():
    paragraph = "A complete recommendation sentence. " * 400
    content, chunks = documents.passages([("Section", paragraph)])
    assert all(c["content"].endswith(".") for c in chunks)
    assert all(len(c["content"]) <= 9000 for c in chunks)
    assert len(documents.passages([(f"Page {n}", "x " * 3000) for n in range(200)])[0]) > 1_000_000
    assert content


def test_ocr_page_cache_preserves_blocks_and_skips_second_inference(tmp_path, monkeypatch):
    monkeypatch.setenv("CARELOOP_DATA_DIR", str(tmp_path))
    calls = []
    blocks = [
        {"block_label": "header", "block_content": "Journal navigation"},
        {"block_label": "paragraph_title", "block_content": "Protein (g/day)"},
        {
            "block_label": "table",
            "block_content": "<table><tr><th>Age</th><th>Intake</th></tr>"
            "<tr><td>Adult</td><td>50</td></tr></table>",
        },
    ]

    class Engine:
        def predict(self, input):
            calls.append(input)
            return [SimpleNamespace(json={"res": {"parsing_res_list": blocks}})]

    raw = pdf()
    first = pdf_worker.parse_pdf(raw, factory=Engine)
    monkeypatch.setenv("CARELOOP_OCR_DEVICE", "gpu:0")
    second = pdf_worker.parse_pdf(raw, factory=Engine)
    assert first == second and len(calls) == 1
    assert second["pages"][0]["device"] == "cpu"
    content, _ = documents.passages(ocr_sections(first["pages"]))
    assert "Journal navigation" not in content
    assert "Protein (g/day)" in content and "<td>50</td>" in content
    assert list(tmp_path.rglob("1.json"))
    assert json.loads(list(tmp_path.rglob("1.json"))[0].read_text())["blocks"] == blocks


def test_invalid_ocr_shape_does_not_cache_success(tmp_path, monkeypatch):
    monkeypatch.setenv("CARELOOP_DATA_DIR", str(tmp_path))

    class Engine:
        def predict(self, input):
            return [SimpleNamespace(json={"res": {}})]

    with pytest.raises(ValueError, match="missing layout blocks"):
        pdf_worker.parse_pdf(pdf(), factory=Engine)
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("available", [True, False])
def test_cuda_selection_never_silently_falls_back_to_cpu(tmp_path, monkeypatch, available):
    monkeypatch.setenv("CARELOOP_OCR_DEVICE", "gpu:0")
    for variable in ("PADDLE_PDX_CACHE_HOME", "HF_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(variable, str(tmp_path))
    monkeypatch.setitem(
        sys.modules,
        "paddle",
        SimpleNamespace(
            is_compiled_with_cuda=lambda: available,
            device=SimpleNamespace(cuda=SimpleNamespace(device_count=lambda: int(available))),
        ),
    )
    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(PPStructureV3=lambda **kw: kw))
    if available:
        assert pdf_worker.pipeline()["device"] == "gpu:0"
    else:
        with pytest.raises(ValueError, match="no GPU is available"):
            pdf_worker.pipeline()
