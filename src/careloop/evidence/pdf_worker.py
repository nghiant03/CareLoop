"""Isolated, bounded PDF parser subprocess (Linux deployment)."""

import io
import json
import resource
import sys


def main():
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(sys.stdin.buffer.read(10_000_001)))
    if reader.is_encrypted or len(reader.pages) > 500:
        raise ValueError("Encrypted or oversized document")
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    last = (int(sys.argv[2]) if len(sys.argv) > 2 else 0) or len(reader.pages)
    if not 1 <= first <= last <= len(reader.pages):
        raise ValueError("Page range falls outside the document")
    pages, empty, length = [], [], 0
    for number in range(first, last + 1):
        page = reader.pages[number - 1]
        text = page.extract_text(extraction_mode="layout", layout_mode_space_vertically=False)
        length += len(text)
        if length > 1_000_000:
            raise ValueError("PDF text exceeds one million characters; select a smaller page range")
        if not text.strip():
            empty.append(number)
        pages.append({"page": number, "text": text})
    print(
        json.dumps(
            {
                "pages": pages,
                "empty_pages": empty,
                "total_pages": len(reader.pages),
                "selected_pages": [first, last],
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
