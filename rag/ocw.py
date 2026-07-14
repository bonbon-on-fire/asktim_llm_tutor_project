"""OCW source reader for RAG ingestion (best-effort crawler).

Reads a course's ``online_link.txt`` (its MIT OpenCourseWare URL), crawls pages
under the same ``/courses/<slug>/`` path, strips boilerplate, and returns each
page as a labeled ``(source, text)`` document. **Linked PDFs are also fetched and
their text extracted** (via ``pypdf``) — that's where OCW keeps the substantive
content (lecture notes, problem sets), which isn't in the HTML. Best-effort: OCW
structure varies, so this is defensive (timeouts, per-item try/except, doc cap,
size cap, polite delay) and the local reader remains the reliable fallback.

``requests``, ``beautifulsoup4``, and ``pypdf`` are imported lazily so that
``--source local`` ingestion works even if they aren't installed.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CURRICULUM_ROOT = _REPO_ROOT / "curriculum"

Doc = tuple[str, str]

_USER_AGENT = "AskTIM-RAG/1.0 (+educational tutor; contact course staff)"
# Skipped link types. PDFs are NOT skipped — they're fetched and text-extracted.
_SKIP_EXT = (".zip", ".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mov", ".srt", ".vtt")


def read_online_link(course: str, curriculum_root: Path | str | None = None) -> str | None:
    """Return the first non-empty URL in the course's ``online_link.txt``, or None."""
    root = Path(curriculum_root) if curriculum_root is not None else _DEFAULT_CURRICULUM_ROOT
    path = root / course / "online_link.txt"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return None


def _course_prefix(url: str) -> str:
    """The ``/courses/<slug>/`` path prefix that in-scope pages must share."""
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    # .../courses/<slug>/...  ->  /courses/<slug>/
    if "courses" in parts:
        i = parts.index("courses")
        slug = parts[i : i + 2]
        return "/" + "/".join(slug) + "/"
    return parsed.path if parsed.path.endswith("/") else parsed.path + "/"


def _extract_text(html: str) -> str:
    """Extract readable body text from an HTML page, stripping chrome and blank runs."""
    from bs4 import BeautifulSoup  # lazy

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "form"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text(separator="\n")
    # Collapse runs of blank lines / trailing whitespace.
    lines = [ln.strip() for ln in text.splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract_pdf_text(data: bytes) -> str:
    """Extract text from a PDF's bytes via ``pypdf`` (best-effort, per-page)."""
    import io

    from pypdf import PdfReader  # lazy

    try:
        reader = PdfReader(io.BytesIO(data))
        pages: list[str] = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(pages)
    except Exception:
        return ""
    lines = [ln.strip() for ln in text.splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def load_ocw_docs(
    course: str,
    *,
    curriculum_root: Path | str | None = None,
    max_pages: int = 80,
    delay_seconds: float = 0.5,
    min_chars: int = 200,
    max_pdf_bytes: int = 25 * 1024 * 1024,
) -> list[Doc]:
    """Crawl the course's OCW site (HTML pages + linked PDFs) into labeled docs.

    HTML pages are text-extracted and their in-scope links enqueued; linked PDFs
    are downloaded and text-extracted (this is where OCW's lecture notes /
    problem sets live). Returns ``[]`` if there's no ``online_link.txt`` —
    callers treat OCW as best-effort.
    """
    import time

    import requests  # lazy

    base = read_online_link(course, curriculum_root)
    if not base:
        return []

    prefix = _course_prefix(base)
    host = urlparse(base).netloc
    session = requests.Session()
    session.headers["User-Agent"] = _USER_AGENT

    seen: set[str] = set()
    queue: list[str] = [base]
    docs: list[Doc] = []

    while queue and len(docs) < max_pages:
        url = queue.pop(0)
        norm = url.split("#")[0].rstrip("/")
        if norm in seen:
            continue
        seen.add(norm)
        try:
            resp = session.get(url, timeout=30)
        except Exception:
            continue
        if resp.status_code != 200:
            continue

        ctype = resp.headers.get("content-type", "").lower()
        label_tail = urlparse(url).path.split("/courses/")[-1].strip("/")
        is_pdf = url.lower().endswith(".pdf") or "application/pdf" in ctype

        if is_pdf:
            # Extract text from the PDF; PDFs have no in-scope links to crawl.
            if len(resp.content) <= max_pdf_bytes:
                text = _extract_pdf_text(resp.content)
                if len(text) >= min_chars:
                    docs.append((f"ocw:{label_tail}", text))
            time.sleep(delay_seconds)
            continue

        if "text/html" not in ctype:
            continue
        html = resp.text

        text = _extract_text(html)
        if len(text) >= min_chars:
            docs.append((f"ocw:{label_tail}", text))

        # Enqueue same-course in-scope links (HTML pages and PDFs).
        from bs4 import BeautifulSoup  # lazy

        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            link = urljoin(url, a["href"]).split("#")[0]
            parsed = urlparse(link)
            if parsed.netloc != host:
                continue
            if not parsed.path.startswith(prefix):
                continue
            if parsed.path.lower().endswith(_SKIP_EXT):
                continue
            if link.split("#")[0].rstrip("/") not in seen:
                queue.append(link)

        time.sleep(delay_seconds)

    return docs
