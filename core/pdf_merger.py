import os
import re

import fitz

DOCUMENT_ORDER = ["invoice", "po", "mrn"]
HEADER_FONT_SIZE = 8

INWARD_PATTERNS = [
    re.compile(
        r"\binward\s*(?:no|number|#)?\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/._\-]{2,})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mrn|grn)\s*(?:no|number|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/._\-]{2,})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mrn|grn)\s*[:\-]\s*([A-Z0-9][A-Z0-9/._\-]{2,})",
        re.IGNORECASE,
    ),
]


def add_duplex_blank_page(doc):
    if len(doc) > 0:
        rect = doc[-1].rect
        doc.new_page(width=rect.width, height=rect.height)
    else:
        doc.new_page()


def ensure_next_page_is_front(doc):
    if len(doc) % 2 == 1:
        add_duplex_blank_page(doc)
        return 1
    return 0


def append_pdf_section(final_doc, pdf_path, start_on_front=False):
    if not os.path.exists(pdf_path):
        return {"inserted": 0, "blank_pages": 0}

    blank_pages = ensure_next_page_is_front(final_doc) if start_on_front and len(final_doc) > 0 else 0

    src = fitz.open(pdf_path)
    inserted = len(src)
    final_doc.insert_pdf(src)
    src.close()
    return {"inserted": inserted, "blank_pages": blank_pages}


def clean_inward_number(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def inward_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def extract_inward_number_from_mrn(pdf_path: str) -> str:
    if not pdf_path or not os.path.exists(pdf_path):
        return ""

    try:
        doc = fitz.open(pdf_path)
        page_limit = min(len(doc), 2)
        text = "\n".join(doc[i].get_text() for i in range(page_limit))
        doc.close()
    except Exception:
        return ""

    for pattern in INWARD_PATTERNS:
        match = pattern.search(text)
        if match:
            return clean_inward_number(match.group(1))
    return ""


def unique_inward_number(base_value: str, used_numbers=None) -> str:
    value = clean_inward_number(base_value)
    if used_numbers is None:
        return value

    candidate = value
    suffix = 2
    while inward_key(candidate) in used_numbers:
        candidate = f"{value}-{suffix}"
        suffix += 1

    used_numbers.add(inward_key(candidate))
    return candidate


def resolve_inward_number(invoice: dict, downloaded_pdfs: dict, used_numbers=None) -> str:
    candidates = [
        invoice.get("_print_inward_no"),
        invoice.get("inward_no"),
        invoice.get("mrn_number"),
        extract_inward_number_from_mrn(downloaded_pdfs.get("mrn")),
        invoice.get("invoice_id"),
        invoice.get("_row_index"),
    ]

    for candidate in candidates:
        value = clean_inward_number(candidate)
        if value:
            return unique_inward_number(value, used_numbers)

    return unique_inward_number("UNKNOWN", used_numbers)


def stamp_page_headers(doc, inward_no: str):
    total_pages = len(doc)
    for page_number, page in enumerate(doc, start=1):
        text = f"Inward No. {inward_no}  |  Page {page_number} of {total_pages}"
        
        # Use direct text insertion instead of a textbox to avoid clipping
        # Placing baseline at y=12 (just above document content)
        r = page.rect
        fontsize = 9
        text_width = fitz.get_text_length(text, fontname="helv", fontsize=fontsize)
        x_pos = r.x0 + (r.width - text_width) / 2
        
        page.insert_text(
            (x_pos, r.y0 + 12),
            text,
            fontsize=fontsize,
            fontname="helv",
            color=(0, 0, 0),
            overlay=True,
        )


def merge_pdfs(invoice: dict, downloaded_pdfs: dict, alerts: list, output_path: str, used_inward_numbers=None) -> dict:
    try:
        final_doc = fitz.open()
        duplex_blank_pages = 0
        inward_no = resolve_inward_number(invoice, downloaded_pdfs, used_inward_numbers)

        first_section = True
        for doc_type in DOCUMENT_ORDER:
            pdf_path = downloaded_pdfs.get(doc_type)
            if not pdf_path:
                continue

            # Every document section starts on the front side of a fresh sheet
            # for predictable duplex printing: invoice, PO, then MRN.
            start_on_front = not first_section
            try:
                result = append_pdf_section(final_doc, pdf_path, start_on_front=start_on_front)
                duplex_blank_pages += result["blank_pages"]
                if result["inserted"]:
                    first_section = False
            except Exception:
                pass

        if len(final_doc) % 2 == 1:
            add_duplex_blank_page(final_doc)
            duplex_blank_pages += 1

        stamp_page_headers(final_doc, inward_no)
        final_doc.save(output_path)
        page_count = len(final_doc)
        final_doc.close()

        return {
            "success": True,
            "page_count": page_count,
            "has_alerts": bool(alerts),
            "alert_cover_printed": False,
            "duplex_blank_pages": duplex_blank_pages,
            "document_order": DOCUMENT_ORDER,
            "inward_no": inward_no,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
