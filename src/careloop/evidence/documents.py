"""Text/HTML/PDF passages with explicit extraction limits and source locations."""

import json
import subprocess
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin

from careloop.evidence.acquisition import validate_url
from careloop.workflow import WorkflowError

MAX_TEXT = 1_000_000


class DocumentHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []
        self.links = []
        self.anchor = None
        self.section_parts = []
        self.sections = []
        self.section_name = "HTML preamble"
        self.heading = None

    def push(self, text):
        self.parts.append(text)
        self.section_parts.append(text)

    def flush_section(self):
        text = "\n".join(
            line.strip() for line in "".join(self.section_parts).splitlines() if line.strip()
        )
        if text:
            self.sections.append((self.section_name, text))
        self.section_parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.flush_section()
            self.heading = ""
        if tag in {"p", "div", "section", "h1", "h2", "h3", "h4", "li", "tr", "br"}:
            self.push("\n")
        if tag in {"td", "th"}:
            self.push("\t")
        if tag == "a":
            self.anchor = {"url": dict(attrs).get("href", ""), "title": ""}

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden = max(0, self.hidden - 1)
        if self.hidden:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self.heading is not None:
            self.section_name = "Heading: " + " ".join(self.heading.split())[:300]
            self.heading = None
        if tag == "a" and self.anchor:
            self.links.append(self.anchor)
            self.anchor = None
        if tag in {"p", "div", "section", "h1", "h2", "h3", "h4", "li", "tr"}:
            self.push("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.push(data)
            if self.heading is not None:
                self.heading += data
            if self.anchor:
                self.anchor["title"] += data


def html_document(payload):
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise WorkflowError(422, "HTML must be UTF-8; submit decoded text instead") from exc
    parser = DocumentHTML()
    parser.feed(text)
    parser.flush_section()
    content = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
    return content, parser.links, parser.sections


def passages(sections):
    result, content = [], ""
    for location, text in sections:
        # Fixed-size bounded passages preserve every character and exact citation offsets.
        text = text.strip()
        if "\x00" in text:
            raise WorkflowError(422, "Extracted text contains unsupported null characters")
        for start in range(0, len(text), 1800):
            chunk = text[start : start + 1800]
            if not chunk.strip():
                continue
            if content:
                content += "\n\n"
            offset = len(content)
            content += chunk
            result.append(
                {
                    "ordinal": len(result) + 1,
                    "location": location,
                    "content": chunk,
                    "start_offset": offset,
                    "end_offset": len(content),
                }
            )
            if len(content) > MAX_TEXT:
                raise WorkflowError(422, "Extracted text exceeds one million characters")
    if not result:
        raise WorkflowError(
            422, "No extractable text; scanned documents require OCR or pasted text"
        )
    return content, result


def extract(payload, content_type, first_page=1, last_page=None):
    if payload.startswith(b"%PDF-"):
        try:
            worker = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "careloop.evidence.pdf_worker",
                    str(first_page),
                    str(last_page or 0),
                ],
                input=payload,
                capture_output=True,
                timeout=20,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkflowError(422, "PDF text extraction exceeded its time limit") from exc
        if worker.returncode:
            if worker.returncode == 2 and worker.stdout:
                raise WorkflowError(422, json.loads(worker.stdout)["error"])
            raise WorkflowError(422, "PDF unreadable, encrypted, or exceeds extraction limits")
        parsed = json.loads(worker.stdout)
        sections = [(f"Page {page['page']}", page["text"]) for page in parsed["pages"]]
        content, chunks = passages(sections)
        warnings = ["PDF reading order and tables need reviewer verification; no OCR performed"]
        if parsed["empty_pages"]:
            warnings.append(f"Pages without extractable text: {parsed['empty_pages']}")
        return (
            content,
            chunks,
            {
                "parser": "pypdf-6-layout-v1",
                "media_type": "application/pdf",
                "warnings": warnings,
                "total_pages": parsed["total_pages"],
                "selected_pages": parsed["selected_pages"],
            },
        )
    if first_page != 1 or last_page is not None:
        raise WorkflowError(422, "Page selection applies only to PDFs")
    if "text/html" not in content_type.lower():
        raise WorkflowError(422, "Expected an HTML page or PDF document")
    _, _, sections = html_document(payload)
    content, chunks = passages(sections)
    return (
        content,
        chunks,
        {
            "parser": "html-text-v1",
            "media_type": "text/html",
            "warnings": ["HTML navigation may remain; verify headings, tables and footnotes"],
        },
    )


def discover(payload, base_url, query):
    _, links, _ = html_document(payload)
    selected = {}
    for link in links:
        url = urljoin(base_url, link["url"]).split("#")[0]
        try:
            validate_url(url)
        except WorkflowError:
            continue
        title = " ".join(link["title"].split())
        if all(term in (title + " " + url).casefold() for term in query.casefold().split()):
            selected.setdefault(url, {"url": url, "title": title or url})
    return list(selected.values())[:100]
