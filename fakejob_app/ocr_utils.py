"""
ocr_utils.py
------------
Extracts text from uploaded PDF and image files.

- Images (JPG/JPEG/PNG) -> Tesseract OCR (pytesseract).
- PDFs -> try direct text extraction first (pdfplumber); if the PDF is a
  scanned document with no extractable text layer, rasterize each page
  and run OCR on it (pdf2image + pytesseract).
"""

import io
import pytesseract
import pdfplumber
from PIL import Image

import os
import shutil

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


def extract_text_from_image(file_bytes):
    image = Image.open(io.BytesIO(file_bytes))
    if image.mode != "RGB":
        image = image.convert("RGB")
    text = pytesseract.image_to_string(image)
    return text.strip()


def extract_text_from_pdf(file_bytes):
    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    combined = "\n".join(text_parts).strip()

    if len(combined) >= 30:
        return combined, "text-layer"

    # Fallback: scanned PDF with no text layer -> OCR each page image.
    if PDF2IMAGE_AVAILABLE:
        ocr_parts = []
        images = convert_from_bytes(file_bytes, dpi=200)
        for img in images:
            ocr_parts.append(pytesseract.image_to_string(img))
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
