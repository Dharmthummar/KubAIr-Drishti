import fitz
import re
import os
from core.gemini_config import gemini_api_key, gemini_ocr_model_name

STAMP_KEYWORDS = re.compile(
    r"\bdue\s*(date|dt)\b|\bdue\s*dt\.?\b|\bdebit\s+note\b|\bd\.?\s*n\.?\s*(no|number)?\.?\b|\bdn\s*(no|number)\b",
    re.IGNORECASE,
)

def env_enabled(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def extract_text_from_pdf(filepath: str, allow_ocr=None, max_pages=None) -> str:
    """
    Smart dual-mode PDF extractor.
    1. Try native text extraction (fast, 100% accurate for digital PDFs).
    2. Optional OCR for scanned pages. Disabled by default for low-memory PCs.
    """
    if allow_ocr is None:
        allow_ocr = env_enabled("ENABLE_PDF_OCR", "0")

    try:
        doc = fitz.open(filepath)
        pages_text = []
        scanned_pages = []
        page_limit = len(doc) if max_pages is None else min(len(doc), max_pages)

        for i in range(page_limit):
            page = doc[i]
            native_text = page.get_text().strip()
            # Heuristic: if native text is too short, page is likely a scanned image
            if len(native_text) > 50:
                if allow_ocr and not STAMP_KEYWORDS.search(native_text):
                    mat = fitz.Matrix(1.5, 1.5)
                    pix = page.get_pixmap(matrix=mat)
                    img_bytes = pix.tobytes("png")
                    scanned_pages.append((i, img_bytes))
                    pages_text.append(native_text)
                else:
                    pages_text.append(native_text)
            elif allow_ocr:
                mat = fitz.Matrix(1.5, 1.5)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                scanned_pages.append((i, img_bytes))
                pages_text.append(None)
            else:
                pages_text.append("")

        if scanned_pages:
            gemini_results = _ocr_with_gemini(scanned_pages)
            for idx, text in gemini_results:
                existing_text = pages_text[idx]
                pages_text[idx] = "\n".join(part for part in [existing_text, text] if part)

        doc.close()
        return "\n\n".join(text for text in pages_text if text)
    except Exception as e:
        return ""


def _ocr_with_gemini(scanned_pages: list) -> list:
    """
    Sends scanned page images to Gemini Vision for accurate OCR.
    Returns a list of (page_index, extracted_text) tuples.
    """
    api_key = gemini_api_key()
    if not api_key:
        return [(idx, "") for idx, _ in scanned_pages]

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(gemini_ocr_model_name())

        results = []
        for page_idx, img_bytes in scanned_pages:
            prompt = """You are a precise financial document OCR system.
Extract ALL text from this document image exactly as it appears.
Pay special attention to:
- Invoice numbers, PO numbers, MRN/GRN numbers
- Party/vendor names
- Dates (in any format)
- All monetary amounts, totals, and tax values (GST, TDS, etc.)
- Any instructions like 'Hold Payment', 'Debit Note', 'Urgent'
Output the raw extracted text only. No commentary."""

            import PIL.Image
            import io
            pil_img = PIL.Image.open(io.BytesIO(img_bytes))
            response = model.generate_content([prompt, pil_img])
            results.append((page_idx, response.text))

        return results
    except Exception as e:
        return [(idx, "") for idx, _ in scanned_pages]


def extract_structured_data(text: str) -> dict:
    """
    Uses multiple regex patterns to robustly extract key financial fields.
    Handles common Indian invoice formats.
    """
    data = {"invoice_no": None, "date": None, "amount": None}
    if not text:
        return data

    # Invoice Number — handles formats like INV/26-27/001, OG/26-27/012, Bill No. 123
    inv_patterns = [
        r'(?:Invoice|Inv|Bill|Tax Invoice)\s*(?:No|#|Number|\.)[:\s]*([A-Z0-9/\-]+)',
        r'(?:Invoice No|Inv No|Bill No)\s*[:\-]?\s*([A-Z0-9/\-]+)',
    ]
    for p in inv_patterns:
        m = re.search(p, text, re.I)
        if m:
            data["invoice_no"] = m.group(1).strip()
            break

    # Amount — handles ₹, commas, decimals, and labels like Net Amount, Grand Total
    amt_patterns = [
        r'(?:Grand\s+Total|Net\s+Amount|Total\s+Amount|Bill\s+Amount|Amount\s+Payable|Balance\s+Due)[:\s₹Rs.]*([0-9,]+(?:\.[0-9]{1,2})?)',
        r'(?:Total|Amount|Balance|Net)[:\s₹Rs.]*([0-9]{1,3}(?:,[0-9]{2,3})+(?:\.[0-9]{1,2})?)',
    ]
    for p in amt_patterns:
        m = re.search(p, text, re.I)
        if m:
            data["amount"] = m.group(1).replace(",", "").strip()
            break

    # Date — handles DD/MM/YYYY, DD-MM-YYYY, DD MMM YYYY
    date_patterns = [
        r'(?:Invoice\s+Date|Bill\s+Date|Date)[:\s]*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
        r'(?:Date)[:\s]*(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{2,4})',
        r'(\d{2}[\/\-]\d{2}[\/\-]\d{4})',
    ]
    for p in date_patterns:
        m = re.search(p, text, re.I)
        if m:
            data["date"] = m.group(1).strip()
            break

    return data


def extract_text_from_pdf_bytes(pdf_bytes: bytes, allow_ocr=None, max_pages=None) -> str:
    """Extracts text from a PDF given as raw bytes."""
    if allow_ocr is None:
        allow_ocr = env_enabled("ENABLE_PDF_OCR", "0")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages_text = []
        scanned_pages = []
        page_limit = len(doc) if max_pages is None else min(len(doc), max_pages)

        for i in range(page_limit):
            page = doc[i]
            native_text = page.get_text().strip()
            if len(native_text) > 50:
                if allow_ocr and not STAMP_KEYWORDS.search(native_text):
                    mat = fitz.Matrix(1.5, 1.5)
                    pix = page.get_pixmap(matrix=mat)
                    img_bytes = pix.tobytes("png")
                    scanned_pages.append((i, img_bytes))
                    pages_text.append(native_text)
                else:
                    pages_text.append(native_text)
            elif allow_ocr:
                mat = fitz.Matrix(1.5, 1.5)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                scanned_pages.append((i, img_bytes))
                pages_text.append(None)
            else:
                pages_text.append("")

        if scanned_pages:
            gemini_results = _ocr_with_gemini(scanned_pages)
            for idx, text in gemini_results:
                existing_text = pages_text[idx]
                pages_text[idx] = "\n".join(part for part in [existing_text, text] if part)

        doc.close()
        return "\n\n".join(text for text in pages_text if text)
    except Exception as e:
        return ""
