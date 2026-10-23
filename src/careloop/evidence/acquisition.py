"""Bounded HTTPS acquisition from the project's authoritative source domains."""

import http.client
import ipaddress
import socket
import ssl
from time import monotonic
from urllib.parse import urljoin, urlsplit

from careloop.workflow import WorkflowError

DOMAINS = {
    "healthhub.sg",
    "www.healthhub.sg",
    "who.int",
    "www.who.int",
    "iris.who.int",
    "primarycarepages.sg",
    "www.primarycarepages.sg",
    "ace-hta.gov.sg",
    "www.ace-hta.gov.sg",
    "kdigo.org",
}
MAX_BYTES = 10_000_000
SEEDS = [
    {
        "title": "Singapore dietary allowances",
        "url": "https://www.healthhub.sg/well-being-and-lifestyle/food-diet-and-nutrition/recommended_dietary_allowances",
    },
    {
        "title": "WHO healthy diet",
        "url": "https://www.who.int/news-room/fact-sheets/detail/healthy-diet",
    },
    {
        "title": "HPB lifestyle prescriptions",
        "url": "https://www.primarycarepages.sg/healthier-sg/lifestyle-prescriptions",
    },
    {
        "title": "KDIGO 2024 CKD guideline",
        "url": "https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf",
    },
]


def validate_url(url):
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in DOMAINS
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ValueError
        if any(ord(c) < 33 or ord(c) > 126 for c in url):
            raise ValueError
    except ValueError as exc:
        raise WorkflowError(422, "Use an HTTPS URL on an approved evidence domain") from exc
    return parsed


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=15, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # Connect to the validated address, retaining hostname verification and SNI.
        raw = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def download(url):
    original = url
    deadline = monotonic() + 60
    for _ in range(6):
        parsed = validate_url(url)
        try:
            addresses = sorted(
                {
                    row[4][0]
                    for row in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
                }
            )
            if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
                raise WorkflowError(422, "Evidence host must resolve only to public addresses")
            conn = PinnedHTTPS(parsed.hostname, addresses[0])
            try:
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                conn.request(
                    "GET",
                    path,
                    headers={"User-Agent": "CareLoop-academic/0.1", "Accept-Encoding": "identity"},
                )
                response = conn.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    if not location:
                        raise WorkflowError(422, "Source redirect has no destination")
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise WorkflowError(422, f"Source server returned HTTP {response.status}")
                if response.getheader("Content-Encoding", "identity") != "identity":
                    raise WorkflowError(422, "Compressed HTTP responses are unsupported")
                parts, size = [], 0
                while size <= MAX_BYTES:
                    if monotonic() > deadline:
                        raise WorkflowError(422, "Source download exceeded its time limit")
                    part = response.read(min(65536, MAX_BYTES + 1 - size))
                    if not part:
                        break
                    parts.append(part)
                    size += len(part)
                payload = b"".join(parts)
                if len(payload) > MAX_BYTES:
                    raise WorkflowError(422, "Source exceeds the 10 MB acquisition limit")
                return payload, {
                    "requested_url": original,
                    "final_url": url,
                    "content_type": response.getheader("Content-Type", ""),
                    "etag": response.getheader("ETag"),
                    "last_modified": response.getheader("Last-Modified"),
                }
            finally:
                conn.close()
        except (OSError, http.client.HTTPException) as exc:
            raise WorkflowError(422, "Source download failed; submit a PDF or pasted text") from exc
    raise WorkflowError(422, "Source exceeded the redirect limit")
