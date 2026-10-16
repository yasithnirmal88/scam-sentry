"""
cv_utils.py
-----------
Text extraction for uploaded CVs (resumes).

Supported inputs:

- ``.pdf``  -> reuse :mod:`ocr_utils` (text-layer first, OCR fallback for
  scanned PDFs). This keeps one hardened PDF pipeline for the whole app.
- ``.txt``  -> direct decode (UTF-8, then a lenient fallback).
- ``.docx`` -> parsed with the standard library (``zipfile`` + a tiny tag
  strip over ``word/document.xml``). No extra dependency is added; ``.doc``
  (the legacy binary format) is intentionally NOT supported.

This module only extracts text. It never classifies a job, never touches the
Risk Engine, and never sends anything to an LLM. Uploads are untrusted, so the
caller is expected to have enforced the size limit (Flask's
``MAX_CONTENT_LENGTH``) and the extension allowlist
(``config.CV_ALLOWED_EXTENSIONS``) before calling in.
"""

from __future__ import annotations

import io
import re
import zipfile

import config
import ocr_utils

CV_ALLOWED_EXTENSIONS = config.CV_ALLOWED_EXTENSIONS

_DOCX_TAG_RE = re.compile(rb"<[^>]+>")
_DOCX_PARAGRAPH_RE = re.compile(rb"</w:p>")
_WS_RE = re.compile(r"[ \t]+")


def _extract_txt(file_bytes: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    # latin-1 never raises; this is just a defensive fallback.
    return file_bytes.decode("latin-1", errors="ignore")


def _extract_docx(file_bytes: bytes) -> str:
    """Pull plain text out of a .docx with the standard library only.

    A .docx is a zip containing ``word/document.xml``. Paragraph tags are
    turned into newlines, then all tags are stripped. Deliberately simple: it
    does not reconstruct tables/lists perfectly, which is fine for matching.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            xml = archive.read("word/document.xml")
    except zipfile.BadZipFile as exc:
        raise ValueError("Could not read the Word document (.docx). The file "
                         "looks corrupt or is not a real .docx file.") from exc
    except KeyError as exc:
        raise ValueError("Could not read the Word document (.docx): the "
                         "expected content is missing.") from exc

    xml = _DOCX_PARAGRAPH_RE.sub(b"\n", xml)
    text = _DOCX_TAG_RE.sub(b" ", xml).decode("utf-8", errors="ignore")
    text = _WS_RE.sub(" ", text)
    # Collapse the runs of blank lines the tag strip leaves behind.
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def extract_cv_text(filename: str, file_bytes: bytes) -> tuple[str, str]:
    """Extract CV text. Returns ``(text, method)``.

    Raises ``ValueError`` with a clean, user-facing message for unsupported
    types, empty input, or unreadable files (the API turns it into a 400).
    """
    lower = (filename or "").lower()
    ext = "." + lower.rsplit(".", 1)[-1] if "." in lower else ""
    if ext not in CV_ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported CV file type. Please upload a PDF, TXT, "
                         "or DOCX file.")
    if not file_bytes:
        raise ValueError("The uploaded CV file is empty.")

    if ext == ".txt":
        return _extract_txt(file_bytes).strip(), "text"
    if ext == ".docx":
        return _extract_docx(file_bytes), "docx"
    # .pdf: reuse the shared, hardened PDF pipeline (text layer + OCR fallback).
    text, method = ocr_utils.extract_text_from_pdf(file_bytes)
    return text, "pdf-" + method
