"""Tests for the OCR / file-extraction path.

Fully offline and deterministic: OCR (pytesseract) and PDF rasterization
(pdf2image/poppler) are monkeypatched, and PDF/image fixtures are built
in-memory. No external binaries or network are required.
"""

import io

import pytest
from PIL import Image

import config
import ocr_utils
from models.job import init_db


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _png_bytes(size=(60, 30), color=(255, 255, 255)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _build_pdf(page_texts):
    """Build a minimal, valid, text-layer PDF from a list of page strings.

    Object layout: 1=font, 2=catalog, 3=pages, then for each page a content
    stream and a page object. Offsets are computed so the xref is correct.
    """
    n = len(page_texts)
    # Object numbers: 1=font, 2=catalog, 3=pages, then page/content pairs.
    page_nums = [4 + 2 * i for i in range(n)]
    content_nums = [5 + 2 * i for i in range(n)]

    objects = [(1, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")]
    objects.append((2, b"<< /Type /Catalog /Pages %d 0 R >>" % 3))
    kids = b" ".join(b"%d 0 R" % pn for pn in page_nums)
    objects.append(
        (3, b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(len(page_texts)).encode() + b" >>")
    )
    for i, text in enumerate(page_texts):
        content = ("BT /F1 12 Tf 72 720 Td (%s) Tj ET" % text).encode("latin-1")
        stream = b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream"
        objects.append((content_nums[i], stream))
        objects.append((page_nums[i],
                        b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] "
                        b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                        % (3, 1, content_nums[i])))

    objects.sort(key=lambda t: t[0])
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num, body in objects:
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    xref_pos = len(out)
    max_num = max(offsets)
    out += b"xref\n0 %d\n" % (max_num + 1)
    out += b"0000000000 65535 f \n"
    for num in range(1, max_num + 1):
        out += b"%010d 00000 n \n" % offsets.get(num, 0)
    out += (b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (max_num + 1, 2, xref_pos))
    return bytes(out)


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

def test_config_has_sane_ocr_limits():
    assert config.MAX_PDF_PAGES >= 1
    assert config.PDF_OCR_DPI >= 72
    assert config.MAX_IMAGE_PIXELS > 0
    # Optional explicit path override; empty means "resolve from PATH".
    assert isinstance(config.TESSERACT_CMD, str)


# ---------------------------------------------------------------------------
# Tesseract path resolution
# ---------------------------------------------------------------------------

def test_tesseract_cmd_env_override(monkeypatch):
    """TESSERACT_CMD wins and is applied to pytesseract."""
    monkeypatch.setattr(config, "TESSERACT_CMD", r"C:\custom\tesseract.exe")
    monkeypatch.setattr(ocr_utils.pytesseract.pytesseract, "tesseract_cmd",
                        "tesseract")
    assert ocr_utils._configure_tesseract() == r"C:\custom\tesseract.exe"
    assert (ocr_utils.pytesseract.pytesseract.tesseract_cmd
            == r"C:\custom\tesseract.exe")


def test_tesseract_available_detects_missing_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_utils.pytesseract.pytesseract, "tesseract_cmd",
                        str(tmp_path / "nope"))
    assert ocr_utils.tesseract_available() is False


def test_tesseract_available_detects_present_binary(tmp_path, monkeypatch):
    exe = tmp_path / "tesseract"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(ocr_utils.pytesseract.pytesseract, "tesseract_cmd",
                        str(exe))
    assert ocr_utils.tesseract_available() is True


# ---------------------------------------------------------------------------
# Image extraction
# ---------------------------------------------------------------------------

def test_image_extraction_runs_ocr(monkeypatch):
    monkeypatch.setattr(ocr_utils.pytesseract, "image_to_string",
                        lambda img, **k: "HELLO WORLD")
    text, method = ocr_utils.extract_text("poster.png", _png_bytes())
    assert text == "HELLO WORLD"
    assert method == "image-ocr"


def test_jpeg_extension_is_accepted(monkeypatch):
    monkeypatch.setattr(ocr_utils.pytesseract, "image_to_string",
                        lambda img, **k: "JPEG TEXT")
    buf = io.BytesIO()
    Image.new("RGB", (40, 20)).save(buf, format="JPEG")
    text, method = ocr_utils.extract_text("flyer.JPG", buf.getvalue())
    assert text == "JPEG TEXT"
    assert method == "image-ocr"


def test_oversized_image_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "MAX_IMAGE_PIXELS", 100)  # 60x30 = 1800 > 100
    with pytest.raises(ValueError):
        ocr_utils.extract_text("big.png", _png_bytes())


def test_image_ocr_failure_is_clean(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("tesseract not found")
    monkeypatch.setattr(ocr_utils.pytesseract, "image_to_string", boom)
    with pytest.raises(ValueError):
        ocr_utils.extract_text("x.png", _png_bytes())


def test_missing_tesseract_binary_gives_actionable_error(monkeypatch):
    """A missing OCR engine yields a clean, user-actionable message (no raw exc)."""
    def boom(*a, **k):
        raise ocr_utils.pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(ocr_utils.pytesseract, "image_to_string", boom)
    with pytest.raises(ValueError) as exc:
        ocr_utils.extract_text("x.png", _png_bytes())
    msg = str(exc.value).lower()
    assert "tesseract" in msg and "paste" in msg


def test_corrupt_image_is_clean():
    with pytest.raises(ValueError):
        ocr_utils.extract_text("broken.png", b"not really an image")


# ---------------------------------------------------------------------------
# PDF text-layer extraction
# ---------------------------------------------------------------------------

def test_pdf_text_layer_is_extracted():
    pdf = _build_pdf(["Senior Engineer at Acme Corp building APIs with Python and SQL."])
    text, method = ocr_utils.extract_text("job.pdf", pdf)
    assert method == "text-layer"
    assert "Senior Engineer" in text


def test_pdf_text_layer_succeeds_without_ocr(monkeypatch):
    """A text-layer PDF must not touch Tesseract at all."""
    def boom(*a, **k):
        raise ocr_utils.pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(ocr_utils.pytesseract, "image_to_string", boom)
    pdf = _build_pdf(["Senior Engineer at Acme Corp building APIs with Python."])
    text, method = ocr_utils.extract_text("job.pdf", pdf)
    assert method == "text-layer"
    assert "Senior Engineer" in text


def test_pdf_only_reads_capped_pages(monkeypatch):
    monkeypatch.setattr(config, "MAX_PDF_PAGES", 2)
    filler = "lorem ipsum dolor sit amet " * 3
    pdf = _build_pdf([f"PAGE-{i} {filler}" for i in range(1, 5)])
    text, method = ocr_utils.extract_text("job.pdf", pdf)
    assert method == "text-layer"
    assert "PAGE-1" in text and "PAGE-2" in text
    assert "PAGE-3" not in text and "PAGE-4" not in text


def test_pdf_without_pages_is_rejected():
    with pytest.raises(ValueError):
        ocr_utils.extract_text("empty.pdf", _build_pdf([]))


def test_corrupt_pdf_is_clean():
    with pytest.raises(ValueError):
        ocr_utils.extract_text("broken.pdf", b"%PDF-1.4 this is not a real pdf")


def test_unsupported_file_type_is_rejected():
    with pytest.raises(ValueError):
        ocr_utils.extract_text("notes.txt", b"hello")


# ---------------------------------------------------------------------------
# PDF OCR fallback
# ---------------------------------------------------------------------------

def _patch_rasterizer(monkeypatch, images):
    monkeypatch.setattr(ocr_utils, "PDF2IMAGE_AVAILABLE", True)
    monkeypatch.setattr(ocr_utils, "convert_from_bytes", lambda *a, **k: images)


def test_scanned_pdf_falls_back_to_ocr(monkeypatch):
    _patch_rasterizer(monkeypatch, [Image.new("RGB", (40, 20))])
    monkeypatch.setattr(ocr_utils.pytesseract, "image_to_string",
                        lambda img, **k: "SCANNED SCAM TEXT " * 3)
    text, method = ocr_utils.extract_text("scan.pdf", _build_pdf([""]))
    assert method == "ocr"
    assert "SCANNED" in text


def test_ocr_respects_page_and_dpi_caps(monkeypatch):
    monkeypatch.setattr(config, "MAX_PDF_PAGES", 3)
    captured = {}

    def fake_convert(data, dpi=None, first_page=None, last_page=None):
        captured["dpi"] = dpi
        captured["last_page"] = last_page
        return [Image.new("RGB", (40, 20))]

    monkeypatch.setattr(ocr_utils, "PDF2IMAGE_AVAILABLE", True)
    monkeypatch.setattr(ocr_utils, "convert_from_bytes", fake_convert)
    monkeypatch.setattr(ocr_utils.pytesseract, "image_to_string",
                        lambda img, **k: "x" * 40)
    ocr_utils.extract_text("scan.pdf", _build_pdf([""] * 7))
    assert captured["last_page"] == 3
    assert captured["dpi"] == config.PDF_OCR_DPI


def test_rasterized_page_over_pixel_budget_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "MAX_IMAGE_PIXELS", 100)  # 40x20 = 800 > 100
    _patch_rasterizer(monkeypatch, [Image.new("RGB", (40, 20))])
    monkeypatch.setattr(ocr_utils.pytesseract, "image_to_string",
                        lambda img, **k: "x" * 40)
    with pytest.raises(ValueError):
        ocr_utils.extract_text("scan.pdf", _build_pdf([""]))


def test_render_failure_is_clean_when_no_text(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("poppler not installed")

    monkeypatch.setattr(ocr_utils, "PDF2IMAGE_AVAILABLE", True)
    monkeypatch.setattr(ocr_utils, "convert_from_bytes", boom)
    with pytest.raises(ValueError):
        ocr_utils.extract_text("scan.pdf", _build_pdf([""]))


def test_render_failure_keeps_short_text_layer(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("poppler not installed")

    monkeypatch.setattr(ocr_utils, "PDF2IMAGE_AVAILABLE", True)
    monkeypatch.setattr(ocr_utils, "convert_from_bytes", boom)
    text, method = ocr_utils.extract_text("scan.pdf", _build_pdf(["short txt"]))
    assert method == "text-layer"
    assert "short txt" in text


def test_scanned_pdf_without_tesseract_gives_actionable_error(monkeypatch):
    _patch_rasterizer(monkeypatch, [Image.new("RGB", (40, 20))])

    def boom(*a, **k):
        raise ocr_utils.pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(ocr_utils.pytesseract, "image_to_string", boom)
    with pytest.raises(ValueError) as exc:
        ocr_utils.extract_text("scan.pdf", _build_pdf([""]))
    assert "paste" in str(exc.value).lower()


def test_missing_pdf2image_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(ocr_utils, "PDF2IMAGE_AVAILABLE", False)
    text, method = ocr_utils.extract_text("scan.pdf", _build_pdf([""]))
    assert method == "text-layer"


# ---------------------------------------------------------------------------
# API behaviour when extraction runs / fails
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "ocr.db"))
    init_db(config.DATABASE_PATH)
    import app as app_module
    app_module.app.config["TESTING"] = True
    app_module.limiter.enabled = False
    with app_module.app.test_client() as c:
        yield c


def _post_file(client, data, filename):
    return client.post("/api/analyze/file",
                       data={"file": (io.BytesIO(data), filename)},
                       content_type="multipart/form-data")


def test_upload_unsupported_type_returns_json_error(client):
    res = _post_file(client, b"hello", "notes.txt")
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_upload_corrupt_pdf_returns_json_error(client):
    res = _post_file(client, b"%PDF-1.4 broken", "bad.pdf")
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_upload_empty_file_returns_json_error(client):
    res = _post_file(client, b"", "empty.png")
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_upload_valid_image_is_analyzed(client, monkeypatch):
    scam = ("Pay a refundable registration fee of $50 before the interview. "
            "Apply immediately and send your bank account number and NIC copy.")
    monkeypatch.setattr(ocr_utils.pytesseract, "image_to_string",
                        lambda img, **k: scam)
    res = _post_file(client, _png_bytes(), "poster.png")
    assert res.status_code == 200
    body = res.get_json()
    assert body["source"].startswith("file-upload")
    assert body["overall_risk_level"] == "Critical"


def test_upload_ocr_failure_returns_clean_error(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("tesseract missing")
    monkeypatch.setattr(ocr_utils.pytesseract, "image_to_string", boom)
    res = _post_file(client, _png_bytes(), "poster.png")
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_upload_missing_ocr_returns_actionable_error(client, monkeypatch):
    """Hosted runtime without the OCR binary: 400 + guidance, no stack trace."""
    def boom(*a, **k):
        raise ocr_utils.pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(ocr_utils.pytesseract, "image_to_string", boom)
    res = _post_file(client, _png_bytes(), "poster.png")
    assert res.status_code == 400
    body = res.get_json()
    assert "paste" in body["error"].lower()
    assert "tesseract" in body["error"].lower()


def test_upload_text_pdf_succeeds_without_ocr(client, monkeypatch):
    def boom(*a, **k):
        raise ocr_utils.pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(ocr_utils.pytesseract, "image_to_string", boom)
    pdf = _build_pdf(["Senior Engineer at Acme Corp, Remote. Build APIs with "
                      "Python and SQL. Salary 100000 USD."])
    res = _post_file(client, pdf, "job.pdf")
    assert res.status_code == 200
    assert res.get_json()["source"].startswith("file-upload")


def test_health_reports_ocr_diagnostics(client):
    ocr = client.get("/api/health").get_json()["ocr"]
    assert set(ocr) == {"tesseract", "pdf_render"}
    assert isinstance(ocr["tesseract"], bool)
    assert isinstance(ocr["pdf_render"], bool)


def test_upload_over_size_limit_returns_413(client, monkeypatch):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, "MAX_CONTENT_LENGTH", 100)
    res = _post_file(client, b"x" * 5000, "big.png")
    assert res.status_code == 413
    assert "error" in res.get_json()


def test_text_analysis_still_works(client):
    res = client.post("/api/analyze/text", json={
        "text": "Senior Engineer at Acme Corp, Remote. Build APIs. "
                "Requirements: 3 years Python. Salary 100000 USD."})
    assert res.status_code == 200
    assert res.get_json()["overall_risk_level"] in ("Low", "Medium", "High", "Critical")
