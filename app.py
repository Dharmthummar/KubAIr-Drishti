import os
import fitz
from flask import Flask, request, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename
from datetime import datetime
from dotenv import load_dotenv, set_key
import sys

if getattr(sys, 'frozen', False):
    # Running as compiled executable
    DATA_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = sys._MEIPASS
else:
    # Running from source
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = DATA_DIR

ENV_PATH = os.path.join(DATA_DIR, ".env")
load_dotenv(ENV_PATH if os.path.exists(ENV_PATH) else None, override=True)

from core.excel_reader import read_excel_file, create_sample_excel
from core.pdf_extractor import extract_text_from_pdf
from core.alert_engine import derive_review_flags, derive_review_status, generate_alerts_for_invoice
from core.pdf_merger import merge_pdfs
from core.database import save_invoice_history, get_history, clear_history
from core.chatbot import ask_chatbot
from core.gemini_config import gemini_api_key, gemini_model_name, gemini_ocr_model_name
from core.gmail_service import search_and_download_attachments

app = Flask(__name__, static_folder=os.path.join(BUNDLE_DIR, "static"), static_url_path="")

# Setup directories for data
TEMP_DIR = os.path.join(DATA_DIR, "temp_pdfs")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
OUTPUT_DIR = os.path.join(DATA_DIR, "output")

for d in [TEMP_DIR, UPLOADS_DIR, OUTPUT_DIR]:
    os.makedirs(d, exist_ok=True)


def env_enabled(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


FAST_MODE = True
PDF_OCR_ENABLED = False
PDF_TEXT_DOC_TYPES = {"invoice"}
PDF_TEXT_MAX_PAGES = 2


def refresh_runtime_config():
    global FAST_MODE, PDF_OCR_ENABLED, PDF_TEXT_DOC_TYPES, PDF_TEXT_MAX_PAGES
    FAST_MODE = env_enabled("FAST_MODE", "1")
    PDF_OCR_ENABLED = env_enabled("ENABLE_PDF_OCR", "0")
    PDF_TEXT_DOC_TYPES = {"invoice"} if FAST_MODE else {"po", "mrn", "invoice"}
    PDF_TEXT_MAX_PAGES = 2 if FAST_MODE else None


refresh_runtime_config()


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def update_env_value(name: str, value: str):
    if not os.path.exists(ENV_PATH):
        with open(ENV_PATH, "a", encoding="utf-8"):
            pass
    set_key(ENV_PATH, name, value)
    os.environ[name] = value

# Simple in-memory session (For production, use a real database/session)
session_data = {
    "excel_path": None,
    "excel_data": None,
    "invoices": [],
    "uploaded_pdfs": {},  # row_idx -> {doc_type: path}
    "alerts": {},         # row_idx -> [alerts]
    "processed": {}       # row_idx -> output_path
}


@app.route("/")
def serve_index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/upload-excel", methods=["POST"])
def api_upload_excel():
    refresh_runtime_config()

    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"})

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "Empty filename"})

    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOADS_DIR, filename)
    file.save(filepath)

    # Parse Excel
    result = read_excel_file(filepath)

    if result["success"]:
        session_data["excel_data"] = result
        session_data["excel_path"] = filepath
        session_data["invoices"] = result["invoices"]
        session_data["uploaded_pdfs"] = {}
        session_data["alerts"] = {}
        session_data["processed"] = {}
        
        # Start the Auto-Process Pipeline
        auto_process_results = []
        used_gmail_message_ids = set()
        used_inward_numbers = set()
        gmail_cache = {"query_results": {}, "message_contexts": {}}
        for idx, invoice in enumerate(result["invoices"]):
            inv_id = str(invoice.get("invoice_id", f"row_{idx}"))
            safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(inv_id))
            save_dir = os.path.join(TEMP_DIR, safe_id)
            process_result = {
                "invoice_id": inv_id,
                "success": False,
                "alerts": 0
            }
            
            # 1. Fetch from Gmail
            gmail_res = search_and_download_attachments(invoice, save_dir, used_gmail_message_ids, gmail_cache)
            if not gmail_res.get("success"):
                # Mark as failed but keep in session for manual upload
                invoice["_status"] = "gmail_failed"
                invoice["_review_status"] = "Gmail Failed"
                invoice["_has_debit_note"] = False
                invoice["_has_due_date_stamp"] = False
                invoice["_error"] = gmail_res.get("error")
                process_result["error"] = invoice["_error"]
                process_result["review_status"] = invoice["_review_status"]
                process_result["has_debit_note"] = False
                process_result["has_due_date_stamp"] = False
                auto_process_results.append(process_result)
                continue
            if gmail_res.get("message_id"):
                used_gmail_message_ids.add(gmail_res["message_id"])
                
            downloaded = gmail_res["downloaded"]
            session_data["uploaded_pdfs"][idx] = downloaded
            
            # 2. Extract Text & Generate Alerts
            pdf_texts = {}
            for doc_type, pdf_path in downloaded.items():
                if doc_type in PDF_TEXT_DOC_TYPES:
                    pdf_texts[doc_type] = extract_text_from_pdf(
                        pdf_path,
                        allow_ocr=PDF_OCR_ENABLED,
                        max_pages=PDF_TEXT_MAX_PAGES,
                    )
                
            email_body = gmail_res.get("email_body", "") + "\n" + invoice.get("notes", "")
            
            alerts = generate_alerts_for_invoice(invoice, pdf_texts, email_body)
            alerts.extend(gmail_res.get("alerts", []))
            review_flags = derive_review_flags(alerts)
            invoice["_review_status"] = derive_review_status(alerts)
            invoice["_has_debit_note"] = review_flags["has_debit_note"]
            invoice["_has_due_date_stamp"] = review_flags["has_due_date_stamp"]
            session_data["alerts"][idx] = alerts
            
            # 3. Merge PDFs
            output_filename = f"{safe_id}_combined_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            output_path = os.path.join(OUTPUT_DIR, output_filename)
            
            merge_res = merge_pdfs(invoice, downloaded, alerts, output_path, used_inward_numbers)
            
            if merge_res["success"]:
                session_data["processed"][idx] = {
                    "output_path": output_path,
                    "output_filename": output_filename,
                    "page_count": merge_res["page_count"],
                    "inward_no": merge_res.get("inward_no", "")
                }
                invoice["_print_inward_no"] = merge_res.get("inward_no", "")
                invoice["_status"] = "processed"
                
                # 4. Save to SQLite History
                save_invoice_history(invoice, alerts, output_filename)
                
            process_result["success"] = merge_res["success"]
            process_result["alerts"] = len(alerts)
            process_result["review_status"] = invoice.get("_review_status", "Clear")
            process_result["has_debit_note"] = invoice.get("_has_debit_note", False)
            process_result["has_due_date_stamp"] = invoice.get("_has_due_date_stamp", False)
            auto_process_results.append(process_result)
            
        result["auto_processed"] = auto_process_results
        result["processed"] = {
            idx: {
                "output_filename": data["output_filename"],
                "page_count": data["page_count"],
                "inward_no": data.get("inward_no", ""),
            }
            for idx, data in session_data["processed"].items()
        }
        result["alerts"] = {
            idx: alerts
            for idx, alerts in session_data["alerts"].items()
        }
        result["performance_mode"] = {
            "fast_mode": FAST_MODE,
            "pdf_ocr_enabled": PDF_OCR_ENABLED,
            "pdf_text_doc_types": sorted(PDF_TEXT_DOC_TYPES),
        }

    return jsonify(result)

@app.route("/api/download-sample-excel")
def download_sample_excel():
    """Generates and serves a sample Excel template."""
    sample_path = os.path.join(TEMP_DIR, "finance_automation_template.xlsx")
    create_sample_excel(sample_path)
    return send_file(sample_path, as_attachment=True, download_name="finance_automation_template.xlsx")


@app.route("/api/history")
def api_history():
    """Fetch invoice history."""
    return jsonify({"history": get_history(50)})


@app.route("/api/clear-history", methods=["POST"])
def api_clear_history():
    """Clear all invoice history from database."""
    try:
        from core.database import clear_history
        clear_history()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Handle Gemini Chatbot query."""
    data = request.get_json()
    query = data.get("query")
    if not query:
        return jsonify({"error": "No query provided"}), 400
        
    answer = ask_chatbot(query)
    return jsonify({"answer": answer})


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        return jsonify({
            "success": True,
            "gemini_api_key_set": bool(gemini_api_key()),
            "gemini_api_key_masked": mask_secret(gemini_api_key()),
            "gemini_model": gemini_model_name(),
            "gemini_ocr_model": gemini_ocr_model_name(),
            "fast_mode": FAST_MODE,
            "pdf_ocr_enabled": PDF_OCR_ENABLED,
        })

    data = request.get_json(silent=True) or {}
    api_key = str(data.get("gemini_api_key", "")).strip()
    model_name = str(data.get("gemini_model", "")).strip()
    ocr_model_name = str(data.get("gemini_ocr_model", "")).strip()

    if api_key and "*" not in api_key and "..." not in api_key:
        update_env_value("GEMINI_API_KEY", api_key)
    if model_name:
        update_env_value("GEMINI_MODEL", model_name)
    if ocr_model_name:
        update_env_value("GEMINI_OCR_MODEL", ocr_model_name)
    if "fast_mode" in data:
        update_env_value("FAST_MODE", "1" if bool(data.get("fast_mode")) else "0")
    if "pdf_ocr_enabled" in data:
        update_env_value("ENABLE_PDF_OCR", "1" if bool(data.get("pdf_ocr_enabled")) else "0")

    refresh_runtime_config()
    return jsonify({
        "success": True,
        "gemini_api_key_set": bool(gemini_api_key()),
        "gemini_api_key_masked": mask_secret(gemini_api_key()),
        "gemini_model": gemini_model_name(),
        "gemini_ocr_model": gemini_ocr_model_name(),
        "fast_mode": FAST_MODE,
        "pdf_ocr_enabled": PDF_OCR_ENABLED,
    })


@app.route("/api/clear")
def clear_session():
    """Clear all session data and temp files."""
    session_data["excel_path"] = None
    session_data["excel_data"] = None
    session_data["invoices"] = []
    session_data["uploaded_pdfs"] = {}
    session_data["alerts"] = {}
    session_data["processed"] = {}
    return jsonify({"success": True})

@app.route("/api/print-all")
def api_print_all():
    """Merge all processed PDFs in the current session into one master PDF."""
    if not session_data["processed"]:
        return jsonify({"success": False, "error": "No processed PDFs to print."})
        
    try:
        master_doc = fitz.open()
        for idx in session_data["processed"]:
            pData = session_data["processed"][idx]
            path = pData["output_path"]
            if os.path.exists(path):
                if len(master_doc) % 2 == 1:
                    rect = master_doc[-1].rect
                    master_doc.new_page(width=rect.width, height=rect.height)
                src = fitz.open(path)
                master_doc.insert_pdf(src)
                src.close()

        if len(master_doc) % 2 == 1:
            rect = master_doc[-1].rect
            master_doc.new_page(width=rect.width, height=rect.height)
                
        master_filename = f"MASTER_PRINT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        master_path = os.path.join(OUTPUT_DIR, master_filename)
        master_doc.save(master_path)
        master_doc.close()
        
        return jsonify({"success": True, "url": f"/api/view/{master_filename}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/download-all-zip")
def download_all_zip():
    """Zips all processed PDFs in the current session."""
    import zipfile
    import io
    
    if not session_data["processed"]:
        return jsonify({"success": False, "error": "No files to zip"}), 400
        
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        for idx, pData in session_data["processed"].items():
            path = pData["output_path"]
            if os.path.exists(path):
                zf.write(path, pData["output_filename"])
    
    memory_file.seek(0)
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f"processed_invoices_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    )


@app.route("/api/status")
def status():
    refresh_runtime_config()
    return jsonify({
        "has_excel": session_data["excel_path"] is not None,
        "total_invoices": len(session_data["invoices"]),
        "processed_count": len(session_data["processed"]),
        "gemini_configured": bool(gemini_api_key()),
        "gemini_model": gemini_model_name(),
        "gemini_ocr_model": gemini_ocr_model_name(),
        "fast_mode": FAST_MODE,
        "pdf_ocr_enabled": PDF_OCR_ENABLED
    })

@app.route("/api/config-check")
def config_check():
    refresh_runtime_config()
    return jsonify({
        "gemini_api_key_set": bool(gemini_api_key()),
        "gemini_model": gemini_model_name(),
        "gemini_ocr_model": gemini_ocr_model_name(),
        "gmail_credentials_found": os.path.exists("credentials.json"),
        "gmail_token_found": os.path.exists("token.json")
    })

@app.route("/api/view/<filename>")
def view_pdf(filename):
    """Serve a merged PDF for viewing in browser."""
    path = os.path.join(OUTPUT_DIR, secure_filename(filename))
    if os.path.exists(path):
        return send_file(path, mimetype='application/pdf')
    return "File not found", 404

@app.route("/api/download/<filename>")
def download_pdf(filename):
    """Serve a merged PDF for download."""
    path = os.path.join(OUTPUT_DIR, secure_filename(filename))
    if os.path.exists(path):
        return send_file(path, as_attachment=True)
    return "File not found", 404

if __name__ == "__main__":
    import threading
    import webbrowser
    import time
    
    def open_browser():
        time.sleep(1.5)
        webbrowser.open("http://localhost:5000")
        
    threading.Thread(target=open_browser).start()
    app.run(port=5000)
