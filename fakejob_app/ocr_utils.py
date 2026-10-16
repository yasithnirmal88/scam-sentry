"""
ocr_utils.py
------------
Extracts text from uploaded PDF and image files.

- Images (JPG/JPEG/PNG) -> Tesseract OCR (pytesseract).
- PDFs -> try direct text extraction first (pdfplumber); if the PDF is a
  scanned document with no extractable text layer, rasterize a bounded
  number of pages and run OCR on them (pdf2image + pytesseract).

Tesseract and Poppler are **system** binaries (Debian: ``tesseract-ocr``,
``poppler-utils``) — ``pip install`` never provides them. On real deployments
install them in the image (see the Dockerfile); the native Render runtime cannot,
so OCR there is unavailable by design. Point ``TESSERACT_CMD`` at the binary
when it is not on ``PATH`` (e.g. a custom Windows install). When the engine is
missing the affected request fails with a clean, actionable ``ValueError``
(the API turns it into a 400 JSON response) instead of a stack trace.

Hardening: uploaded files are untrusted, so processing is bounded to protect
the worker from memory/CPU exhaustion:

- at most ``config.MAX_PDF_PAGES`` pages are read or rasterized per PDF;
- rasterized pages never exceed ``config.PDF_OCR_DPI`` DPI;
- any single decoded image is limited to ``config.MAX_IMAGE_PIXELS`` pixels.

Files that exceed these limits fail with a clear ``ValueError`` (the API
turns that into a 400 JSON response) instead of crashing the worker.
"""

import io
import os
import shutil

import pytesseract
import pdfplumber
from PIL import Image

import config

try:
    from pdf2image import convert_from_bytes
    PDF2IMAGE_AVAILABLE = True
except Exception:
    PDF2IMAGE_AVAILABLE = False


# Common Windows install location, used only when no explicit override and no
# PATH entry are found. Tesseract is a system binary (apt: tesseract-ocr), not a
# pip package, so it may legitimately be absent.
_DEFAULT_WIN_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _configure_tesseract():
    """Point pytesseract at the Tesseract binary.

    Resolution order: explicit ``TESSERACT_CMD`` env override, then ``PATH``,
    then the common Windows install location. Returns the command in use; when
    nothing is found it keeps pytesseract's default so a missing binary surfaces
    as a clean ``TesseractNotFoundError`` instead of an import-time crash.
    """
    configured = getattr(config, "TESSERACT_CMD", "") or ""
    if configured:
        pytesseract.pytesseract.tesseract_cmd = configured
        return configured
    if not shutil.which("tesseract") and os.path.exists(_DEFAULT_WIN_TESSERACT):
        pytesseract.pytesseract.tesseract_cmd = _DEFAULT_WIN_TESSERACT
        return _DEFAULT_WIN_TESSERACT
    return getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")


TESSERACT_CMD = _configure_tesseract()


def tesseract_available():
    """True when a usable Tesseract binary can be located. Never raises.

    Used for diagnostics (health/readiness); the extraction paths still rely on
    catching ``TesseractNotFoundError`` so a mocked/edge environment behaves
    predictably.
    """
    cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract") or "tesseract"
    if os.path.isabs(cmd) or os.sep in cmd:
        return os.path.exists(cmd)
    return shutil.which(cmd) is not None


# A PDF whose extracted text layer is at least this long is treated as a real
# text layer, and OCR is skipped.
_TEXT_LAYER_MIN_CHARS = 30


# User-facing messages for the "server is missing the OCR toolchain" case. Kept
# free of raw exception text so nothing leaks into the API response.
_IMAGE_OCR_UNAVAILABLE = (
    "Text extraction from images is unavailable on this server (the OCR "
    "engine, Tesseract, is not installed). You can still paste the job text "
    "directly, or upload a text-based PDF."
)
_PDF_OCR_UNAVAILABLE = (
    "This PDF has no extractable text layer and image OCR is unavailable on "
    "this server (the OCR engine, Tesseract, is not installed). Try a "
    "text-based PDF or paste the job text directly."
)
_PDF_RENDER_UNAVAILABLE = (
    "This PDF has no extractable text layer and could not be rendered for OCR "
    "on this server. Try a text-based PDF or paste the job text directly."
)


def _enforce_pixel_budget(width, height, what="image"):
    """Reject any raster whose pixel count would blow the memory budget."""
    if width * height > config.MAX_IMAGE_PIXELS:
        raise ValueError(
            f"The {what} is too large to process ({width}x{height} pixels; "
            f"limit is {config.MAX_IMAGE_PIXELS}). Please upload a smaller "
            f"or lower-resolution file."
        )


def extract_text_from_image(file_bytes):
    try:
        image = Image.open(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError(f"Could not read the image: {exc}") from exc

    # Dimensions are known from the header, so this rejects an over-budget
    # image before any pixels are decoded.
    _enforce_pixel_budget(image.width, image.height, "image")

    if image.mode != "RGB":
        image = image.convert("RGB")
    try:
        text = pytesseract.image_to_string(image)
    except pytesseract.TesseractNotFoundError as exc:
        # The OCR engine itself is missing (common on hosted/native runtimes
        # where the system package is not installed). Give an actionable message.
        raise ValueError(_IMAGE_OCR_UNAVAILABLE) from exc
    except Exception as exc:
        raise ValueError(f"OCR could not be completed: {exc}") from exc
    return text.strip()


def extract_text_from_pdf(file_bytes):
    try:
        pdf = pdfplumber.open(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError(f"Could not read the PDF: {exc}") from exc

    with pdf:
        total_pages = len(pdf.pages)
        if total_pages == 0:
            raise ValueError("The PDF contains no pages.")
        # Cap the number of pages we read to bound time and memory.
        pages = pdf.pages[: config.MAX_PDF_PAGES]
        text_parts = [page.extract_text() or "" for page in pages]
        combined = "\n".join(text_parts).strip()

    if len(combined) >= _TEXT_LAYER_MIN_CHARS:
        return combined, "text-layer"

    # Fallback: scanned PDF with no text layer -> OCR a bounded number of
    # pages at a bounded DPI.
    if PDF2IMAGE_AVAILABLE:
        last_page = min(total_pages, config.MAX_PDF_PAGES)
        try:
            images = convert_from_bytes(
                file_bytes,
                dpi=config.PDF_OCR_DPI,
                first_page=1,
                last_page=last_page,
            )
        except Exception as exc:
            if combined:
                return combined, "text-layer"
            # Poppler (pdf2image's backend) is a system dependency too; keep the
            # raw error out of the response.
            raise ValueError(_PDF_RENDER_UNAVAILABLE) from exc

        ocr_parts = []
        for img in images:
            _enforce_pixel_budget(img.width, img.height, "PDF page")
            try:
                ocr_parts.append(pytesseract.image_to_string(img))
            except pytesseract.TesseractNotFoundError as exc:
                if combined:
                    return combined, "text-layer"
                raise ValueError(_PDF_OCR_UNAVAILABLE) from exc
            except Exception as exc:
                if combined:
                    return combined, "text-layer"
                raise ValueError(f"OCR could not be completed: {exc}") from exc
        ocr_text = "\n".join(ocr_parts).strip()
        if ocr_text:
            return ocr_text, "ocr"

    return combined, "text-layer"


def extract_text(filename, file_bytes):
    lower = filename.lower()
    if lower.endswith((".png", ".jpg", ".jpeg")):
        return extract_text_from_image(file_bytes), "image-ocr"
    if lower.endswith(".pdf"):
        return extract_text_from_pdf(file_bytes)
    raise ValueError("Unsupported file type. Please upload a PDF, JPG, JPEG, or PNG file.")
