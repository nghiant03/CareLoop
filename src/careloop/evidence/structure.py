"""Context-preserving text units for HTML tables and OCR layout blocks."""

import re

from bs4 import BeautifulSoup

PARSER_VERSION = "structured-paddleocr-3.7-v1"
MAX_PASSAGE = 9000
MAX_TEXT = 10_000_000


def text(node):
    return " ".join(node.stripped_strings)


def table_units(table, context):
    summary = table.get("summary", "")
    for node in [table, *table.find_all(True)]:
        node.attrs = {
            key: value
            for key, value in node.attrs.items()
            if key in {"rowspan", "colspan", "scope", "headers", "id"}
        }
    for cell in table.find_all(["td", "th"]):
        value = text(cell)
        cell.clear()
        cell.append(value)
    # Unit rows and merged cells may use <td>; preserve the complete table semantics.
    caption = table.find("caption")
    prefix = "\n".join(filter(None, [context, summary, text(caption) if caption else ""]))
    return [prefix + "\n" + str(table)]


def html_sections(payload):
    soup = BeautifulSoup(payload.decode("utf-8-sig"), "html.parser")
    for node in soup.select(
        'script, style, noscript, svg, nav, header, footer, aside, [role="navigation"]'
    ):
        node.decompose()
    body = soup.body or soup
    # Some publishers place the substantive tables outside their small <main> wrapper.
    candidates = [
        node
        for node in soup.find_all(["main", "article"])
        if len(text(node)) >= len(text(body)) * 0.5
    ]
    root = max(candidates, key=lambda node: len(text(node))) if candidates else body
    headings, context_notes = {}, {}
    sections = []
    # Leaf blocks avoid repeating paragraphs inside lists/table cells.
    nodes = [
        node
        for node in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"])
        if not node.find_parent("table") and not node.find_parent("li")
    ]
    for node in nodes:
        if node.name.startswith("h") and len(node.name) == 2:
            level = int(node.name[1])
            headings = {k: v for k, v in headings.items() if k < level}
            context_notes = {k: v for k, v in context_notes.items() if k < level}
            headings[level] = text(node)
            continue
        context = " > ".join(headings.values())
        location = ("Heading: " + context) if context else "HTML content"
        if node.name == "table":
            table_context = "\n".join([context, *context_notes.values()])
            sections.extend((location, unit) for unit in table_units(node, table_context))
        else:
            value = text(node)
            if value:
                sections.append((location, "\n".join(filter(None, [context, value]))))
                if node.name == "p" and len(value) <= 1000:
                    context_notes[max(headings, default=0)] = value
    if not sections and text(root):
        sections = [("HTML content", text(root))]
    return sections


def split_text(value):
    if len(value) <= MAX_PASSAGE:
        return [value]
    if "<table" in value:
        raise ValueError("Table exceeds passage limit; select a smaller table for review")
    # Keep complete sentences/paragraphs; never split a number, word, or table cell.
    units = re.split(r"(?<=[.!?])\s+|\n\s*\n", value)
    chunks, current = [], ""
    for unit in units:
        if len(unit) > MAX_PASSAGE:
            raise ValueError("Unbroken text block exceeds passage limit")
        if current and len(current) + len(unit) + 2 > MAX_PASSAGE:
            chunks.append(current)
            current = ""
        current = (current + "\n\n" + unit).strip()
    if current:
        chunks.append(current)
    return chunks


def ocr_sections(pages):
    sections, heading = [], ""
    for page in pages:
        for index, block in enumerate(page["blocks"], 1):
            label = block["block_label"]
            value = block["block_content"].strip()
            if not value or label in {"header", "footer", "number", "header_image", "footer_image"}:
                continue
            location = f"Page {page['page']}, block {index} ({label})"
            if label in {"doc_title", "paragraph_title", "figure_title", "table_title"}:
                heading = value
            if label == "table":
                table = BeautifulSoup(value, "html.parser").find("table")
                units = table_units(table, heading) if table else [value]
                sections.extend((location, unit) for unit in units)
            else:
                sections.append(
                    (location, "\n".join(dict.fromkeys(filter(None, [heading, value]))))
                )
    return sections
