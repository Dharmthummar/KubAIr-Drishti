# Financial Concepts and Rules for Automation
# Based on the Advanced Finance Reference

CONCEPTS = {
    "DEBIT_NOTE": {
        "type": "debit-note",
        "severity": "critical",
        "title": "Debit Note Instruction",
        "pattern": r"\b(make|create|raise|prepare)\s+(a\s+)?debit\s+note\b|\bdebit\s+note\b|\bd\.?\s*n\.?\s*(no|number)?\.?\b|\bdn\s*(no|number)\b",
        "description": "The source text or invoice stamp indicates a debit note."
    },
    "DUE_DATE_STAMP": {
        "type": "due-date-stamp",
        "severity": "info",
        "title": "Due Date Stamp Found",
        "pattern": r"\bdue\s*(date|dt)\b|\bdue\s*dt\.?\b",
        "description": "The invoice contains a due-date stamp or due-date marking."
    },
    "HOLD_PAYMENT": {
        "type": "hold-payment",
        "severity": "critical",
        "title": "Payment Hold Instruction",
        "pattern": r"\bhold\s+(the\s+)?payment\b|\bdo\s+not\s+pay\b|\bstop\s+payment\b",
        "description": "The source text contains a direct hold-payment instruction."
    },
    "TAX_MISMATCH": {
        "type": "tax-mismatch",
        "severity": "critical",
        "title": "Tax/GST Mismatch Flagged",
        "pattern": r"\b(gst|tax|vat)\s+(mismatch|difference|issue|not\s+matching)\b",
        "description": "Tax mismatch language was found in the email or invoice text."
    },
    "AMOUNT_MISMATCH": {
        "type": "amount-mismatch",
        "severity": "warning",
        "title": "Amount Mismatch Mentioned",
        "pattern": r"\b(amount|rate|price|value)\s+(mismatch|difference|variance|not\s+matching)\b",
        "description": "The source text mentions an amount, rate, or price mismatch."
    },
    "SHORT_RECEIPT": {
        "type": "short-receipt",
        "severity": "warning",
        "title": "Short Receipt Mentioned",
        "pattern": r"\b(short\s+(received|receipt|supply)|quantity\s+(short|mismatch))\b",
        "description": "The source text indicates a possible quantity or material receipt variance."
    },
    "URGENCY": {
        "type": "urgent",
        "severity": "info",
        "title": "Urgent Processing Note",
        "pattern": r"\burgent\b|\bpriority\b|\bimmediate\b|\basap\b",
        "description": "The source text asks for faster-than-normal handling."
    },
    "DISCREPANCY": {
        "type": "discrepancy",
        "severity": "warning",
        "title": "Data Reconciliation Error",
        "description": "Calculated mismatch between Excel source and PDF content."
    }
}

def get_concept_details(concept_id):
    return CONCEPTS.get(concept_id, {})
