import re
from datetime import date, datetime

import pandas as pd

COLUMN_ALIASES = {
    "erp_status": ["", "status", "bill status", "approval status"],
    "invoice_id": ["bill no", "bill number", "invoice id", "invoice no", "inv id", "inv no", "invoice_id"],
    "invoice_date": ["bill date", "invoice date", "date", "inv date", "invoice_date"],
    "party_name": ["party name", "party", "vendor", "supplier", "party_name"],
    "inward_no": ["inward no", "inward number", "inward_no"],
    "inward_date": ["inward date", "inward_date"],
    "passing_date": ["passing date", "passed date", "passing_date"],
    "due_date": ["bill due date", "due date", "payment due date", "bill_due_date"],
    "amount": ["bill amount", "invoice amount", "amount", "total", "total amount", "net amount", "inv amount"],
    "passed_amount": ["passed amount", "approved amount", "passed_amount"],
    "passing_no": ["passing no", "passing number", "passing_no"],
    "sent_date": ["sent date", "sent_date"],
    "purchase_book": ["purchase book", "purchase ledger", "purchase_book"],
    "paid_amount": ["paid amount", "amount paid", "paid_amount"],
    "pay_mode": ["pay mode", "payment mode", "pay_mode"],
    "po_number": ["po number", "po no", "po", "po_number"],
    "mrn_number": ["mrn number", "mrn no", "mrn", "grn", "mrn_number"],
    "notes": ["remark", "remarks", "notes", "note", "instructions", "comment"],
}

SAMPLE_COLUMNS = [
    "Bill No.",
    "Bill Date",
    "Party Name",
    "Inward No",
    "Inward Date",
    "Passing Date",
    "Bill Due Date",
    "Bill Amount",
    "Passed Amount",
    "Remark",
    "Passing No.",
    "Sent Date",
    "Purchase Book",
    "Paid Amount",
    "Pay Mode",
]


def canonical_header(value) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip().lower()
    if text.startswith("unnamed:"):
        return ""
    return re.sub(r"[^a-z0-9]+", "", text)


def fallback_column_name(value) -> str:
    if value is None or pd.isna(value):
        return "column"
    text = str(value).strip().lower()
    if not text or text.startswith("unnamed:"):
        return "column"
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "column"


def build_alias_lookup() -> dict:
    lookup = {}
    for standard_name, aliases in COLUMN_ALIASES.items():
        lookup[canonical_header(standard_name)] = standard_name
        for alias in aliases:
            lookup[canonical_header(alias)] = standard_name
    return lookup


ALIAS_LOOKUP = build_alias_lookup()


def unique_name(name: str, used: set) -> str:
    if name not in used:
        used.add(name)
        return name

    suffix = 2
    while f"{name}_{suffix}" in used:
        suffix += 1
    unique = f"{name}_{suffix}"
    used.add(unique)
    return unique


def recognized_header_count(columns) -> int:
    recognized = set()
    for col in columns:
        canonical = canonical_header(col)
        standard_name = ALIAS_LOOKUP.get(canonical)
        if standard_name and standard_name != "erp_status":
            recognized.add(standard_name)
    return len(recognized)


def find_header_row(raw_df: pd.DataFrame):
    best_idx = None
    best_count = 0
    for idx, row in raw_df.head(10).iterrows():
        count = recognized_header_count(row.tolist())
        if count > best_count:
            best_idx = idx
            best_count = count
    return best_idx if best_count >= 3 else None


def read_table(filepath: str) -> pd.DataFrame:
    is_csv = filepath.lower().endswith(".csv")
    reader = pd.read_csv if is_csv else pd.read_excel
    kwargs = {} if is_csv else {"engine": "openpyxl"}

    df = reader(filepath, **kwargs)
    if recognized_header_count(df.columns) >= 2:
        return df

    raw_df = reader(filepath, header=None, **kwargs)
    header_idx = find_header_row(raw_df)
    if header_idx is None:
        return df

    df = raw_df.iloc[header_idx + 1:].copy()
    df.columns = raw_df.iloc[header_idx].tolist()
    return df.reset_index(drop=True)


def normalize_columns(df):
    used = set()
    normalized_columns = []

    for col in df.columns:
        canonical = canonical_header(col)
        standard_name = ALIAS_LOOKUP.get(canonical)
        if standard_name and standard_name not in used:
            normalized_columns.append(unique_name(standard_name, used))
        else:
            normalized_columns.append(unique_name(fallback_column_name(col), used))

    df = df.copy()
    df.columns = normalized_columns
    return df


def format_cell_value(value) -> str:
    if pd.isna(value):
        return ""

    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()

    if isinstance(value, datetime):
        if value.hour or value.minute or value.second:
            return value.strftime("%d-%m-%Y %H:%M:%S")
        return value.strftime("%d-%m-%Y")

    if isinstance(value, date):
        return value.strftime("%d-%m-%Y")

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value).strip()


def add_derived_fields(invoice: dict) -> None:
    if invoice.get("inward_no") and not invoice.get("mrn_number"):
        invoice["mrn_number"] = invoice["inward_no"]
    if invoice.get("passed_amount") and not invoice.get("amount"):
        invoice["amount"] = invoice["passed_amount"]


def read_excel_file(filepath: str) -> dict:
    result = {"success": False, "invoices": [], "columns": [], "warnings": [], "total": 0}
    try:
        df = read_table(filepath)
        if df.empty:
            result["warnings"].append("Empty file")
            result["success"] = True
            return result

        df = normalize_columns(df)
        result["columns"] = list(df.columns)
        
        has_standard_cols = "invoice_id" in df.columns or "party_name" in df.columns
        invoices = []
        
        for idx, row in df.iterrows():
            inv = {}
            if has_standard_cols:
                for col in df.columns:
                    inv[col] = format_cell_value(row[col])
                add_derived_fields(inv)
                if not inv.get("invoice_id") and not inv.get("party_name"):
                    continue
            else:
                row_text = " ".join([str(val) for val in row.values if pd.notna(val)])
                if not row_text.strip():
                    continue
                if "#" in row_text:
                    parts = row_text.split("#", 1)
                    inv["party_name"] = parts[0].strip()
                    inv["invoice_id"] = parts[1].strip()
                else:
                    inv["party_name"] = row_text.strip()
                    inv["invoice_id"] = ""
            inv["_row_index"] = idx
            inv["_status"] = "pending"
            invoices.append(inv)
            
        if not has_standard_cols:
            first_col_name = str(df.columns[0])
            if "unnamed" not in first_col_name.lower():
                header_inv = {"_row_index": -1, "_status": "pending"}
                if "#" in first_col_name:
                    parts = first_col_name.split("#", 1)
                    header_inv["party_name"] = parts[0].strip()
                    header_inv["invoice_id"] = parts[1].strip()
                else:
                    header_inv["party_name"] = first_col_name.strip()
                    header_inv["invoice_id"] = ""
                invoices.insert(0, header_inv)

        result["invoices"] = invoices
        result["total"] = len(invoices)
        result["success"] = True
    except Exception as e:
        result["warnings"].append(f"Error: {str(e)}")
    return result

def create_sample_excel(output_path):
    data = {
        "Bill No.": ["OG/26-27/012", "OG/26-27/013"],
        "Bill Date": ["23-04-2026", "24-04-2026"],
        "Party Name": ["DELTA GLOBAL PVT. LTD.", "RIDHI ENTERPRISES"],
        "Inward No": ["GS-2627-40", "MPPU-2627-44"],
        "Inward Date": ["25-04-2026", "26-04-2026"],
        "Passing Date": ["27-04-2026", "28-04-2026"],
        "Bill Due Date": ["25-05-2026", "26-05-2026"],
        "Bill Amount": [58198, 13233],
        "Passed Amount": [58198, 13233],
        "Remark": ["PLEASE PROCESS FOR PAYMENT", "Make debit note for short supply"],
        "Passing No.": ["APPL-J-AC-2627-0475", "APPL-J-AC-2627-0476"],
        "Sent Date": ["06-05-2026", "06-05-2026"],
        "Purchase Book": ["GENERAL STORES", "MECHANICAL PURCHASE"],
        "Paid Amount": [0, 0],
        "Pay Mode": ["NORMAL", "NORMAL"],
    }
    data = {column: data[column] for column in SAMPLE_COLUMNS}
    pd.DataFrame(data).to_excel(output_path, index=False, engine="openpyxl")
    return output_path
