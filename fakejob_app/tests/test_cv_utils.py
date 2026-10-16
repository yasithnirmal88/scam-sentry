"""Tests for cv_utils.extract_cv_text (TXT / DOCX / PDF delegation + safety)."""

import io
import zipfile

import pytest

import cv_utils
import ocr_utils


def _docx_bytes(text: str) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
        + text +
        "</w:t></w:r></w:p></w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buf.getvalue()


def test_txt_extraction():
    text, method = cv_utils.extract_cv_text("resume.txt", b"Python developer CV")
    assert "Python developer CV" in text
    assert method == "text"


def test_txt_utf16_fallback():
    text, method = cv_utils.extract_cv_text(
        "resume.txt", "Café manager".encode("utf-16"))
    assert method == "text"
    assert "manager" in text


def test_docx_extraction():
    data = _docx_bytes("Senior Data Analyst with SQL skills")
    text, method = cv_utils.extract_cv_text("cv.docx", data)
    assert "Senior Data Analyst" in text and "SQL" in text
    assert method == "docx"


def test_docx_corrupt_raises_value_error():
    with pytest.raises(ValueError):
        cv_utils.extract_cv_text("cv.docx", b"definitely not a zip")


def test_pdf_delegates_to_ocr_utils(monkeypatch):
    calls = {}

    def fake_pdf(file_bytes):
        calls["bytes"] = file_bytes
        return "Extracted PDF text", "text-layer"

    monkeypatch.setattr(ocr_utils, "extract_text_from_pdf", fake_pdf)
    text, method = cv_utils.extract_cv_text("cv.pdf", b"%PDF-1.4 fake")
    assert text == "Extracted PDF text"
    assert method == "pdf-text-layer"
    assert calls["bytes"] == b"%PDF-1.4 fake"


def test_unsupported_extension_raises():
    with pytest.raises(ValueError):
        cv_utils.extract_cv_text("cv.doc", b"legacy word")
    with pytest.raises(ValueError):
        cv_utils.extract_cv_text("photo.png", b"\x89PNG")


def test_empty_file_raises():
    with pytest.raises(ValueError):
        cv_utils.extract_cv_text("cv.txt", b"")
