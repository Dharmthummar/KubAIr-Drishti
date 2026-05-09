import os


DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
PLACEHOLDER_KEYS = {"your_api_key_here", "your-gemini-api-key", "paste_api_key_here"}


def gemini_api_key() -> str:
    value = os.getenv("GEMINI_API_KEY", "").strip()
    if value.lower() in PLACEHOLDER_KEYS:
        return ""
    return value


def gemini_model_name() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL


def gemini_ocr_model_name() -> str:
    return os.getenv("GEMINI_OCR_MODEL", gemini_model_name()).strip() or gemini_model_name()
