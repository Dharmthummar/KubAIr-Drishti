import sqlite3
import os
import json
import sys
from core.alert_engine import derive_review_flags, derive_review_status

if getattr(sys, 'frozen', False):
    # Running as compiled executable
    DATA_DIR = os.path.dirname(sys.executable)
else:
    # Running from source
    DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_FILE = os.path.join(DATA_DIR, "finance_history.db")

def get_connection():
    return sqlite3.connect(DB_FILE)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processed_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id TEXT,
            party_name TEXT,
            invoice_date TEXT,
            amount REAL,
            po_number TEXT,
            mrn_number TEXT,
            alerts TEXT,
            notes TEXT,
            output_pdf_path TEXT,
            processed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute("PRAGMA table_info(processed_invoices)")
    columns = {row[1] for row in cursor.fetchall()}
    migrations = {
        "review_status": "ALTER TABLE processed_invoices ADD COLUMN review_status TEXT DEFAULT 'Clear'",
        "inward_no": "ALTER TABLE processed_invoices ADD COLUMN inward_no TEXT",
        "due_date": "ALTER TABLE processed_invoices ADD COLUMN due_date TEXT",
        "passed_amount": "ALTER TABLE processed_invoices ADD COLUMN passed_amount REAL",
        "purchase_book": "ALTER TABLE processed_invoices ADD COLUMN purchase_book TEXT",
        "paid_amount": "ALTER TABLE processed_invoices ADD COLUMN paid_amount REAL",
        "pay_mode": "ALTER TABLE processed_invoices ADD COLUMN pay_mode TEXT",
        "has_debit_note": "ALTER TABLE processed_invoices ADD COLUMN has_debit_note INTEGER DEFAULT 0",
        "has_due_date_stamp": "ALTER TABLE processed_invoices ADD COLUMN has_due_date_stamp INTEGER DEFAULT 0",
    }
    for column, statement in migrations.items():
        if column not in columns:
            cursor.execute(statement)
    conn.commit()
    conn.close()


def numeric_amount(value) -> float:
    try:
        return float(str(value or 0).replace(",", ""))
    except ValueError:
        return 0.0


def save_invoice_history(invoice_data, alerts, output_pdf_path):
    conn = get_connection()
    cursor = conn.cursor()
    
    amount = numeric_amount(invoice_data.get("amount", 0))
    passed_amount = numeric_amount(invoice_data.get("passed_amount", 0))
    paid_amount = numeric_amount(invoice_data.get("paid_amount", 0))
    review_status = invoice_data.get("_review_status") or derive_review_status(alerts)
    review_flags = derive_review_flags(alerts)
    has_debit_note = invoice_data.get("_has_debit_note", review_flags["has_debit_note"])
    has_due_date_stamp = invoice_data.get("_has_due_date_stamp", review_flags["has_due_date_stamp"])

    cursor.execute('''
        INSERT INTO processed_invoices 
        (
            invoice_id, party_name, invoice_date, amount, po_number, mrn_number,
            alerts, notes, output_pdf_path, review_status, inward_no, due_date,
            passed_amount, purchase_book, paid_amount, pay_mode,
            has_debit_note, has_due_date_stamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        invoice_data.get("invoice_id", ""),
        invoice_data.get("party_name", ""),
        invoice_data.get("invoice_date", ""),
        amount,
        invoice_data.get("po_number", ""),
        invoice_data.get("mrn_number", ""),
        json.dumps(alerts),
        invoice_data.get("notes", ""),
        output_pdf_path,
        review_status,
        invoice_data.get("inward_no", ""),
        invoice_data.get("due_date", ""),
        passed_amount,
        invoice_data.get("purchase_book", ""),
        paid_amount,
        invoice_data.get("pay_mode", ""),
        1 if has_debit_note else 0,
        1 if has_due_date_stamp else 0,
    ))
    conn.commit()
    conn.close()

def get_history(limit=50):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM processed_invoices ORDER BY processed_at DESC LIMIT ?', (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        d = dict(row)
        if d['alerts']:
            try:
                d['alerts'] = json.loads(d['alerts'])
            except:
                d['alerts'] = []
        else:
            d['alerts'] = []
        d["review_status"] = d.get("review_status") or derive_review_status(d["alerts"])
        flags = derive_review_flags(d["alerts"])
        d["has_debit_note"] = bool(d.get("has_debit_note")) or flags["has_debit_note"]
        d["has_due_date_stamp"] = bool(d.get("has_due_date_stamp")) or flags["has_due_date_stamp"]
        result.append(d)
    return result

def clear_history():
    """Deletes all records from the processed_invoices table."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM processed_invoices')
    conn.commit()
    conn.close()
    return True

def get_all_history_text():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM processed_invoices ORDER BY processed_at DESC')
    rows = cursor.fetchall()
    conn.close()
    
    history_lines = []
    for row in rows:
        d = dict(row)
        status = d.get("review_status") or "Clear"
        line = f"Invoice ID: {d['invoice_id']} | Party: {d['party_name']} | Date: {d['invoice_date']} | Due: {d.get('due_date', '')} | Amount: {d['amount']} | Status: {status} | Processed: {d['processed_at']}"
        if d['notes']:
            line += f" | Notes: {d['notes']}"
        if d['alerts']:
            try:
                alerts_data = json.loads(d['alerts'])
                alerts_summary = [f"[{a.get('severity', '').upper()}] {a.get('message', '')}" for a in alerts_data]
                if alerts_summary:
                    line += f" | Alerts: {' ; '.join(alerts_summary)}"
            except:
                pass
        history_lines.append(line)
        
    return "\n".join(history_lines)

init_db()
