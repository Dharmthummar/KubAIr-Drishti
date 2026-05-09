import re
from core.finance_concepts import CONCEPTS
from core.pdf_extractor import extract_structured_data

STATUS_RULES = [
    ("HOLD_PAYMENT", "Hold Payment"),
    ("DEBIT_NOTE", "Debit Note"),
    ("TAX_MISMATCH", "Tax Issue"),
    ("DISCREPANCY", "Mismatch"),
    ("AMOUNT_MISMATCH", "Amount Mismatch"),
    ("SHORT_RECEIPT", "Short Receipt"),
    ("DUE_DATE_STAMP", "Due Date Stamp"),
    ("URGENCY", "Urgent"),
    ("GMAIL_MATCH_REVIEW", "Gmail Review"),
]


def derive_review_flags(alerts: list) -> dict:
    concepts = {alert.get("concept") for alert in alerts or []}
    return {
        "has_debit_note": "DEBIT_NOTE" in concepts,
        "has_due_date_stamp": "DUE_DATE_STAMP" in concepts,
    }


def scan_text_for_alerts(text: str, source: str) -> list:
    alerts = []
    if not text: return alerts
    
    for concept_id, data in CONCEPTS.items():
        if "pattern" not in data: continue
        
        match = re.search(data["pattern"], text, re.IGNORECASE)
        if match:
            # Find context around match
            start = max(0, match.start() - 40)
            end = min(len(text), match.end() + 40)
            context = text[start:end].strip().replace("\n", " ")
            
            alerts.append({
                "concept": concept_id,
                "severity": data["severity"],
                "message": data["title"],
                "description": data["description"],
                "source": source,
                "matched_text": f"...{context}..."
            })
    return alerts


def derive_review_status(alerts: list) -> str:
    concepts = {alert.get("concept") for alert in alerts or []}
    labels = [label for concept, label in STATUS_RULES if concept in concepts]
    if not labels:
        return "Clear"
    return " / ".join(labels[:2])


def generate_alerts_for_invoice(invoice: dict, pdf_texts: dict, email_body: str) -> list:
    all_alerts = []
    
    # 1. Text Scanning
    if invoice.get("notes"):
        all_alerts.extend(scan_text_for_alerts(str(invoice["notes"]), "Excel Notes"))
    if email_body:
        all_alerts.extend(scan_text_for_alerts(email_body, "Email Body"))
        
    # 2. Data Reconciliation & PDF Scanning
    excel_amount = str(invoice.get("amount", "")).replace(",", "").strip()
    excel_inv_no = str(invoice.get("invoice_id", "")).strip().lower()

    for doc_type, text in pdf_texts.items():
        all_alerts.extend(scan_text_for_alerts(text, f"{doc_type.upper()} PDF"))
        
        structured = extract_structured_data(text)
        
        # Amount Mismatch Logic
        if structured["amount"] and excel_amount:
            try:
                if abs(float(structured["amount"]) - float(excel_amount)) > 0.01:
                    all_alerts.append({
                        "concept": "DISCREPANCY",
                        "severity": "critical",
                        "message": "Amount Mismatch Detected",
                        "description": f"Excel expects {excel_amount}, but PDF contains {structured['amount']}",
                        "source": f"{doc_type.upper()} PDF",
                        "matched_text": f"Found: {structured['amount']}"
                    })
            except: pass

        # ID Validation
        if structured["invoice_no"] and excel_inv_no:
            clean_struct = re.sub(r'[^a-z0-9]', '', structured["invoice_no"].lower())
            clean_excel = re.sub(r'[^a-z0-9]', '', excel_inv_no)
            if clean_excel not in clean_struct and clean_struct not in clean_excel:
                 all_alerts.append({
                        "concept": "DISCREPANCY",
                        "severity": "warning",
                        "message": "Invoice Number Mismatch",
                        "description": f"Excel ID {excel_inv_no} not found in PDF {structured['invoice_no']}",
                        "source": f"{doc_type.upper()} PDF",
                        "matched_text": f"Extracted: {structured['invoice_no']}"
                    })

    # Deduplicate
    unique_alerts = []
    seen = set()
    for a in all_alerts:
        key = f"{a['concept']}|{a['message']}|{a['source']}"
        if key not in seen:
            unique_alerts.append(a)
            seen.add(key)
            
    return unique_alerts
