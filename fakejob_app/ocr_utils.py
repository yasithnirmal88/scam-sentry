"""
ocr_utils.py
------------
Extracts text from uploaded PDF and image files.

- Images (JPG/JPEG/PNG) -> Tesseract OCR (pytesseract).
- PDFs -> try direct text extraction first (pdfplumber); if the PDF is a
  scanned document with no extractable text layer, rasterize a bounded
  number of pages and run OCR on them (pdf2image + pytesseract).

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

# On Windows, locate tesseract executable if not in system PATH
if not shutil.which("tesseract"):
    default_win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(default_win_path):
        pytesseract.pytesseract.tesseract_cmd = default_win_path

try:
    from pdf2image import convert_from_bytes
    PDF2IMAGE_AVAILABLE = True
except Exception:
    PDF2IMAGE_AVAILABLE = False


# A PDF whose extracted text layer is at least this long is treated as a real
# text layer, and OCR is skipped.
_TEXT_LAYER_MIN_CHARS = 30


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
            raise ValueError(f"Could not render the PDF for OCR: {exc}") from exc

        ocr_parts = []
        for img in images:
            _enforce_pixel_budget(img.width, img.height, "PDF page")
            try:
                ocr_parts.append(pytesseract.image_to_string(img))
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
