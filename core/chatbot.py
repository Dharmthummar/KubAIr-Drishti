import google.generativeai as genai
from core.database import get_all_history_text
from core.gemini_config import gemini_api_key, gemini_model_name

_MODEL_CACHE = {"api_key": None, "model_name": None, "model": None}


def get_model():
    api_key = gemini_api_key()
    model_name = gemini_model_name()
    if not api_key:
        _MODEL_CACHE.update({"api_key": None, "model_name": None, "model": None})
        return None

    if (
        _MODEL_CACHE["model"] is None
        or _MODEL_CACHE["api_key"] != api_key
        or _MODEL_CACHE["model_name"] != model_name
    ):
        genai.configure(api_key=api_key)
        _MODEL_CACHE.update({
            "api_key": api_key,
            "model_name": model_name,
            "model": genai.GenerativeModel(model_name),
        })

    return _MODEL_CACHE["model"]


def ask_chatbot(user_query: str) -> str:
    model = get_model()
    if not model:
        return "Error: GEMINI_API_KEY is not configured in .env file."
    
    history_context = get_all_history_text()
    if not history_context:
        history_context = "No invoices have been processed yet."

    prompt = f"""
You are a Financial Automation Expert assistant for this specific project.
Your primary knowledge source is the 'finance-automation' directory.

CONCEPTS & RULES:
- TAX_COMPLIANCE: Check for TDS, GST, VAT.
- PAYMENT_ADVISORY: Monitor for Debit/Credit Notes or Payment Holds.
- DISCREPANCY: Alert if Excel data (Source of Truth) doesn't match PDF/Email content.
- URGENCY: Prioritize processing for urgent requests.

CURRENT DATA CONTEXT (from processed history):
{history_context}

Task: Based ON THE DATA ABOVE and the concepts mentioned, answer: {user_query}
If the information is not in the history context, say you don't know, but mention you are searching the local finance directory.
"""
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error: {str(e)}"
