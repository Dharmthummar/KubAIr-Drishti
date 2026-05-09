import base64
import html
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.dirname(sys.executable)
else:
    DATA_DIR = os.path.dirname(os.path.dirname(__file__))

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
CREDENTIALS_FILE = os.path.join(DATA_DIR, "credentials.json")
TOKEN_FILE = os.path.join(DATA_DIR, "token.json")

MAX_QUERIES = 10
MAX_RESULTS_PER_QUERY = 5
MIN_ACCEPT_SCORE = 50
AMBIGUITY_GAP = 12
DATE_SEARCH_WINDOW_DAYS = 7

PARTY_STOPWORDS = {
    "and", "the", "of", "for", "m", "s", "ms", "mrs", "mr",
    "pvt", "private", "ltd", "limited", "llp", "inc", "co", "company",
    "corp", "corporation", "industries", "industry", "enterprise",
    "enterprises", "traders", "trading", "works", "suppliers", "supplier",
}


def get_gmail_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if not credentials_have_required_scopes(creds):
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError("credentials.json not found. Please set up the Gmail API.")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    try:
        return build('gmail', 'v1', credentials=creds)
    except HttpError as error:
        raise Exception(f"An error occurred with Gmail API: {error}")


def credentials_have_required_scopes(creds) -> bool:
    if not creds:
        return False

    has_scopes = getattr(creds, "has_scopes", None)
    if callable(has_scopes):
        return has_scopes(SCOPES)

    available_scopes = set(getattr(creds, "granted_scopes", None) or getattr(creds, "scopes", None) or [])
    if not available_scopes:
        return True
    return set(SCOPES).issubset(available_scopes)


def compact_text(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def words_from(value) -> list:
    return re.findall(r"[a-z0-9]+", str(value or "").lower())


def decode_body_data(data: str) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    value = re.sub(r"(?is)<br\s*/?>", "\n", value)
    value = re.sub(r"(?is)</p\s*>", "\n", value)
    value = re.sub(r"(?is)<.*?>", " ", value)
    return html.unescape(re.sub(r"\s+", " ", value)).strip()


def walk_parts(payload: dict) -> list:
    parts = []
    stack = [payload] if payload else []
    while stack:
        part = stack.pop(0)
        parts.append(part)
        stack.extend(part.get("parts", []) or [])
    return parts


def get_header(payload: dict, name: str) -> str:
    for header in payload.get("headers", []) or []:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def extract_message_body(message: dict) -> str:
    plain_parts = []
    html_parts = []
    for part in walk_parts(message.get("payload", {})):
        body_data = part.get("body", {}).get("data")
        if not body_data:
            continue
        text = decode_body_data(body_data)
        mime_type = part.get("mimeType", "")
        if mime_type == "text/plain":
            plain_parts.append(text)
        elif mime_type == "text/html":
            html_parts.append(strip_html(text))
    return "\n".join(plain_parts or html_parts).strip()


def extract_pdf_attachments(message: dict) -> list:
    attachments = []
    for part in walk_parts(message.get("payload", {})):
        filename = part.get("filename") or ""
        body = part.get("body", {}) or {}
        if filename.lower().endswith(".pdf") and body.get("attachmentId"):
            attachments.append({
                "filename": filename,
                "attachmentId": body["attachmentId"],
            })
    return attachments


def parse_date_text(value: str):
    text = re.sub(r"\bat\b", " ", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    try:
        return parsedate_to_datetime(text).date()
    except Exception:
        pass

    for fmt in ("%d %b %Y %H:%M", "%d %B %Y %H:%M", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_excel_date(value):
    if not value:
        return None
    text = str(value).strip()
    candidates = [text, text.split()[0]]
    for candidate in candidates:
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


def parse_message_date(message: dict):
    date_header = get_header(message.get("payload", {}), "Date")
    header_date = parse_date_text(date_header)
    if header_date:
        return header_date

    internal_date = message.get("internalDate")
    if internal_date:
        try:
            return datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc).date()
        except Exception:
            pass
    return None


def extract_forwarded_date(body: str):
    for match in re.finditer(r"(?im)^\s*Date:\s*(.+)$", body or ""):
        parsed = parse_date_text(match.group(1))
        if parsed:
            return parsed
    return None


def required_sent_date(invoice_data: dict):
    return parse_excel_date(invoice_data.get("sent_date"))


def sent_date_mismatch(invoice_data: dict, message_date):
    sent_date = required_sent_date(invoice_data)
    if not sent_date:
        return None
    if not message_date:
        return {
            "expected": sent_date,
            "actual": None,
            "message": f"Excel Sent Date is {sent_date.strftime('%d-%m-%Y')}, but Gmail date could not be read.",
        }
    if message_date != sent_date:
        return {
            "expected": sent_date,
            "actual": message_date,
            "message": (
                f"Excel Sent Date is {sent_date.strftime('%d-%m-%Y')}, "
                f"but Gmail email date is {message_date.strftime('%d-%m-%Y')}."
            ),
        }
    return None


def party_tokens(party_name: str) -> list:
    raw_words = words_from(party_name)
    initials = "".join(w for w in raw_words if len(w) == 1)
    tokens = []
    if len(initials) >= 2:
        tokens.append(initials)

    for word in raw_words:
        if len(word) >= 3 and word not in PARTY_STOPWORDS and word not in tokens:
            tokens.append(word)

    if not tokens:
        for word in raw_words:
            if word not in tokens:
                tokens.append(word)
            if len(tokens) >= 2:
                break
    return tokens[:4]


def invoice_variants(invoice_id: str) -> dict:
    raw = str(invoice_id or "").strip()
    tokens = words_from(raw)
    number_tokens = [t for t in tokens if t.isdigit()]
    last_number = number_tokens[-1] if number_tokens else ""
    last_number_clean = last_number.lstrip("0") or last_number

    variants = {
        "raw": raw,
        "tokens": tokens,
        "compact": compact_text(raw),
        "token_phrase": " ".join(tokens),
        "last_number": last_number,
        "last_number_clean": last_number_clean,
    }
    return variants


def inward_variants(invoice_data: dict) -> list:
    variants = []
    seen = set()
    for value in [invoice_data.get("inward_no"), invoice_data.get("mrn_number")]:
        raw = str(value or "").strip()
        compact = compact_text(raw)
        if not raw or compact in seen:
            continue
        seen.add(compact)
        parts = words_from(raw)
        variants.append({
            "raw": raw,
            "tokens": parts,
            "compact": compact,
            "token_phrase": " ".join(parts),
        })
    return variants


def contains_token(text: str, token: str) -> bool:
    if not token:
        return False
    if token.isdigit():
        pattern = rf"(?<![a-z0-9])0*{re.escape(token.lstrip('0') or token)}(?![a-z0-9])"
    else:
        pattern = rf"(?<![a-z0-9]){re.escape(token.lower())}(?![a-z0-9])"
    return re.search(pattern, text.lower()) is not None


def attachment_basename(filename: str) -> str:
    return os.path.splitext(os.path.basename(filename or ""))[0].lower()


def filename_matches_invoice(filename: str, variants: dict) -> bool:
    name = attachment_basename(filename)
    name_compact = compact_text(name)
    full_compact = variants.get("compact", "")
    if full_compact and len(full_compact) >= 5 and full_compact in name_compact:
        return True

    last_number = variants.get("last_number_clean", "")
    if last_number and contains_token(name, last_number):
        return True

    raw_tokens = variants.get("tokens", [])
    return any(len(token) >= 4 and token in name_compact for token in raw_tokens)


def text_matches_inward_number(searchable: str, filenames: list, inward_data: dict) -> str:
    compact_searchable = compact_text(searchable)
    compact_filenames = [compact_text(attachment_basename(filename)) for filename in filenames]
    compact_value = inward_data.get("compact", "")

    if compact_value and len(compact_value) >= 4:
        if compact_value in compact_searchable:
            return inward_data.get("raw", "")
        for name in compact_filenames:
            if compact_value in name:
                return inward_data.get("raw", "")

    token_phrase = inward_data.get("token_phrase", "")
    token_phrase_compact = compact_text(token_phrase)
    if token_phrase_compact and len(token_phrase_compact) >= 4 and token_phrase_compact in compact_searchable:
        return inward_data.get("raw", "")

    return ""


def score_candidate(invoice_data: dict, message_context: dict) -> dict:
    subject = message_context.get("subject", "")
    body = message_context.get("body", "")
    filenames = message_context.get("filenames", [])
    searchable = " ".join([subject, body, " ".join(filenames)])
    compact_searchable = compact_text(searchable)

    score = 0
    reasons = []
    exact_inward_match = False
    exact_invoice_match = False

    for inward_data in inward_variants(invoice_data):
        matched_inward = text_matches_inward_number(searchable, filenames, inward_data)
        if matched_inward:
            score += 130
            exact_inward_match = True
            reasons.append(f"inward number matched exactly: {matched_inward}")
            break

    variants = invoice_variants(invoice_data.get("invoice_id", ""))
    full_compact = variants.get("compact", "")
    if full_compact and len(full_compact) >= 5 and full_compact in compact_searchable:
        score += 75
        exact_invoice_match = True
        reasons.append("bill number matched exactly")

    if not exact_invoice_match and variants.get("token_phrase"):
        token_phrase_compact = compact_text(variants["token_phrase"])
        if len(token_phrase_compact) >= 5 and token_phrase_compact in compact_searchable:
            score += 60
            exact_invoice_match = True
            reasons.append("bill number tokens matched")

    invoice_filename_hits = [f for f in filenames if filename_matches_invoice(f, variants)]
    if invoice_filename_hits:
        score += 35 if exact_invoice_match else 28
        reasons.append(f"attachment name matched bill number: {invoice_filename_hits[0]}")

    last_number = variants.get("last_number_clean", "")
    if last_number and len(last_number) >= 2 and contains_token(subject, last_number):
        score += 18
        reasons.append("bill number suffix found in subject")

    party_hits = [token for token in party_tokens(invoice_data.get("party_name", "")) if token in compact_searchable]
    if party_hits:
        score += min(45, 18 + len(party_hits) * 9)
        reasons.append("party matched: " + ", ".join(party_hits[:3]))

    party_compact = compact_text(" ".join(party_tokens(invoice_data.get("party_name", ""))[:2]))
    if party_compact and len(party_compact) >= 5 and party_compact in compact_searchable:
        score += 12

    compact_subject_body = compact_text(subject + " " + body)
    if "forpayment" in compact_subject_body or "paymentprocess" in compact_subject_body:
        score += 10
        reasons.append("payment mail wording found")

    if len(filenames) >= 3:
        score += 8
        reasons.append("three PDF attachments found")
    elif filenames:
        score += 4
        reasons.append("PDF attachment found")

    message_date = message_context.get("date")
    sent_date = required_sent_date(invoice_data)
    target_date = sent_date or parse_excel_date(invoice_data.get("invoice_date"))
    date_mismatch = sent_date_mismatch(invoice_data, message_date)
    if sent_date:
        if date_mismatch:
            if exact_inward_match:
                reasons.append(f"{date_mismatch['message']} Inward number match accepted first.")
            else:
                score -= 100
                reasons.append(date_mismatch["message"])
        else:
            score += 35
            reasons.append("Gmail date matched Excel Sent Date")
    elif message_date and target_date:
        days_apart = abs((message_date - target_date).days)
        if days_apart == 0:
            score += 18
            reasons.append("email date matched Excel date")
        elif days_apart > 45:
            score -= 10
            reasons.append("email date far from Excel date")

    if exact_inward_match:
        confidence = "high"
    elif exact_invoice_match and score >= 80:
        confidence = "high"
    elif score >= MIN_ACCEPT_SCORE:
        confidence = "review"
    else:
        confidence = "low"

    return {
        "score": score,
        "confidence": confidence,
        "exact_inward_match": exact_inward_match,
        "exact_invoice_match": exact_invoice_match,
        "date_mismatch": date_mismatch,
        "reasons": reasons,
    }


def quote_query_term(term: str) -> str:
    return '"' + str(term).replace('"', " ").strip() + '"'


def gmail_search_base(invoice_data: dict) -> str:
    base = 'has:attachment filename:pdf -in:trash newer_than:180d'
    sent_date = required_sent_date(invoice_data)
    if sent_date:
        start_date = sent_date - timedelta(days=DATE_SEARCH_WINDOW_DAYS)
        end_date = sent_date + timedelta(days=DATE_SEARCH_WINDOW_DAYS + 1)
        base += f' after:{start_date.strftime("%Y/%m/%d")} before:{end_date.strftime("%Y/%m/%d")}'
    return base


def inward_search_terms(invoice_data: dict) -> list:
    inward_terms = []
    for inward_data in inward_variants(invoice_data):
        for term in [
            inward_data.get("raw"),
            inward_data.get("token_phrase"),
            inward_data.get("compact"),
        ]:
            if term and term not in inward_terms:
                inward_terms.append(term)
    return inward_terms


def build_inward_search_queries(invoice_data: dict) -> list:
    base = gmail_search_base(invoice_data)
    queries = []
    for inward_term in inward_search_terms(invoice_data)[:3]:
        queries.append(f'{base} {quote_query_term(inward_term)}')
        queries.append(f'{base} "FOR PAYMENT" {quote_query_term(inward_term)}')
    return queries[:4]


def build_search_queries(invoice_data: dict) -> list:
    base = gmail_search_base(invoice_data)
    party_terms = party_tokens(invoice_data.get("party_name", ""))
    variants = invoice_variants(invoice_data.get("invoice_id", ""))
    inward_terms = inward_search_terms(invoice_data)
    invoice_terms = []

    for term in [
        variants.get("raw"),
        variants.get("token_phrase"),
        variants.get("last_number"),
        variants.get("last_number_clean"),
        variants.get("compact"),
    ]:
        if term and term not in invoice_terms:
            invoice_terms.append(term)

    queries = []
    for inward_term in inward_terms[:3]:
        queries.append(f'{base} {quote_query_term(inward_term)}')
        queries.append(f'{base} "FOR PAYMENT" {quote_query_term(inward_term)}')

    for party in party_terms[:2]:
        queries.append(f'{base} "FOR PAYMENT" {quote_query_term(party)}')
        for invoice_term in invoice_terms[:2]:
            queries.append(f'{base} {quote_query_term(party)} {quote_query_term(invoice_term)}')

    for invoice_term in invoice_terms[:3]:
        queries.append(f'{base} "FOR PAYMENT" {quote_query_term(invoice_term)}')
        queries.append(f'{base} {quote_query_term(invoice_term)}')

    if party_terms:
        queries.append(f'{base} {quote_query_term(party_terms[0])}')

    deduped = []
    seen = set()
    for query in queries:
        if query not in seen:
            deduped.append(query)
            seen.add(query)
    return deduped[:MAX_QUERIES]


def message_context(message: dict) -> dict:
    payload = message.get("payload", {})
    attachments = extract_pdf_attachments(message)
    body = extract_message_body(message)
    message_date = extract_forwarded_date(body) or parse_message_date(message)
    return {
        "message_id": message.get("id", ""),
        "subject": get_header(payload, "Subject"),
        "from": get_header(payload, "From"),
        "date": message_date,
        "body": body,
        "attachments": attachments,
        "filenames": [att["filename"] for att in attachments],
    }


def search_candidate_messages(service, queries: list, excluded_message_ids=None, cache=None) -> list:
    excluded_message_ids = set(excluded_message_ids or [])
    cache = cache if cache is not None else {}
    query_cache = cache.setdefault("query_results", {})
    message_ids = []
    seen = set()
    for query in queries:
        if query in query_cache:
            result_ids = query_cache[query]
        else:
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=MAX_RESULTS_PER_QUERY
            ).execute()
            result_ids = [item.get("id") for item in results.get("messages", []) if item.get("id")]
            query_cache[query] = result_ids

        for msg_id in result_ids:
            if msg_id and msg_id not in seen and msg_id not in excluded_message_ids:
                message_ids.append(msg_id)
                seen.add(msg_id)
    return message_ids


def load_message_contexts(service, message_ids: list, cache=None) -> list:
    cache = cache if cache is not None else {}
    context_cache = cache.setdefault("message_contexts", {})
    candidates = []
    for msg_id in message_ids:
        if msg_id in context_cache:
            candidates.append(context_cache[msg_id])
            continue
        message = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        context = message_context(message)
        context_cache[msg_id] = context
        candidates.append(context)
    return candidates


def choose_fast_inward_candidate(invoice_data: dict, candidates: list) -> dict:
    choice = choose_best_candidate(invoice_data, candidates)
    if choice.get("success") and choice["candidate"]["match"].get("exact_inward_match"):
        return choice
    return {"success": False, "error": "No exact inward match found in priority search.", "candidates": choice.get("candidates", [])}


def choose_best_candidate(invoice_data: dict, candidates: list) -> dict:
    scored = []
    for context in candidates:
        match = score_candidate(invoice_data, context)
        scored.append({**context, "match": match})

    scored.sort(key=lambda item: item["match"]["score"], reverse=True)
    if not scored:
        return {"success": False, "error": "No candidate emails found."}

    top = scored[0]
    if top["match"].get("exact_inward_match"):
        return {"success": True, "candidate": top, "candidates": scored[:3]}

    if top["match"].get("date_mismatch"):
        return {
            "success": False,
            "error": top["match"]["date_mismatch"]["message"],
            "candidates": scored[:3],
        }

    if top["match"]["score"] < MIN_ACCEPT_SCORE:
        return {
            "success": False,
            "error": f"No reliable Gmail match. Best score was {top['match']['score']} for subject: {top.get('subject', '')}",
            "candidates": scored[:3],
        }

    if len(scored) > 1:
        second = scored[1]
        gap = top["match"]["score"] - second["match"]["score"]
        if gap < AMBIGUITY_GAP and not top["match"]["exact_invoice_match"]:
            return {
                "success": False,
                "error": (
                    "Ambiguous Gmail match. More than one email matched this party/date "
                    "and the Excel bill number was not confirmed."
                ),
                "candidates": scored[:3],
            }

    if not top["match"]["exact_invoice_match"]:
        viable = [
            item for item in scored
            if item["match"]["score"] >= MIN_ACCEPT_SCORE and not item["match"].get("date_mismatch")
        ]
        if len(viable) > 1:
            return {
                "success": False,
                "error": (
                    "Bill number was not confirmed and more than one same-date email matched this party. "
                    "Please review manually."
                ),
                "candidates": scored[:3],
            }

    return {"success": True, "candidate": top, "candidates": scored[:3]}


def guess_doc_type(filename: str, invoice_data: dict) -> str:
    lower_name = attachment_basename(filename)
    compact_name = compact_text(lower_name)
    variants = invoice_variants(invoice_data.get("invoice_id", ""))

    po_number = compact_text(invoice_data.get("po_number", ""))
    mrn_number = compact_text(invoice_data.get("mrn_number") or invoice_data.get("inward_no", ""))

    if "stpo" in compact_name or "purchaseorder" in compact_name or compact_name.startswith("po"):
        return "po"
    if po_number and po_number in compact_name:
        return "po"
    if re.search(r"(^|[^a-z])po([^a-z]|$)", lower_name):
        return "po"

    if filename_matches_invoice(filename, variants) or "invoice" in compact_name or compact_name.startswith("inv"):
        return "invoice"

    if "mrn" in compact_name or "grn" in compact_name or "inward" in compact_name:
        return "mrn"
    if compact_name.startswith(("cf", "crcpu")):
        return "mrn"
    if mrn_number and mrn_number in compact_name:
        return "mrn"

    return ""


def classify_attachment_slots(attachments: list, invoice_data: dict) -> dict:
    slots = {}
    unmatched = []

    for attachment in attachments:
        doc_type = guess_doc_type(attachment.get("filename", ""), invoice_data)
        if doc_type and doc_type not in slots:
            slots[doc_type] = attachment
        else:
            unmatched.append(attachment)

    if not slots and len(unmatched) == 3:
        for slot, attachment in zip(["po", "mrn", "invoice"], unmatched):
            slots[slot] = attachment
        return slots

    for slot in ["mrn", "po", "invoice"]:
        if slot not in slots and unmatched:
            slots[slot] = unmatched.pop(0)

    return slots


def safe_attachment_filename(filename: str) -> str:
    base = os.path.basename(filename or "attachment.pdf")
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip()
    return safe or "attachment.pdf"


def download_classified_attachments(service, message_id: str, attachments: list, invoice_data: dict, temp_dir: str) -> dict:
    os.makedirs(temp_dir, exist_ok=True)
    classified = classify_attachment_slots(attachments, invoice_data)
    downloaded = {}

    for doc_type, attachment in classified.items():
        att_data = service.users().messages().attachments().get(
            userId='me',
            messageId=message_id,
            id=attachment["attachmentId"]
        ).execute()
        file_data = base64.urlsafe_b64decode(att_data["data"] + "=" * (-len(att_data["data"]) % 4))
        filename = safe_attachment_filename(attachment["filename"])
        filepath = os.path.join(temp_dir, f"{doc_type}_{filename}")

        with open(filepath, "wb") as f:
            f.write(file_data)

        downloaded[doc_type] = filepath

    return downloaded


def mark_message_as_read(service, message_id: str) -> dict:
    try:
        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_and_download_attachments(invoice_data, temp_dir, excluded_message_ids=None, cache=None):
    party_name = invoice_data.get("party_name", "")
    invoice_id = invoice_data.get("invoice_id", "")
    has_inward = bool(inward_variants(invoice_data))

    if not party_name and not invoice_id and not has_inward:
        return {"success": False, "error": "No Party Name, Bill No., or Inward No. provided to search."}

    queries = build_search_queries(invoice_data)

    try:
        service = get_gmail_service()
        cache = cache if cache is not None else {}
        priority_queries = build_inward_search_queries(invoice_data)
        choice = None
        used_queries = queries

        if priority_queries:
            priority_message_ids = search_candidate_messages(service, priority_queries, excluded_message_ids, cache)
            priority_candidates = load_message_contexts(service, priority_message_ids, cache)
            priority_choice = choose_fast_inward_candidate(invoice_data, priority_candidates)
            if priority_choice.get("success"):
                choice = priority_choice
                used_queries = priority_queries

        if choice is None:
            message_ids = search_candidate_messages(service, queries, excluded_message_ids, cache)

            if not message_ids:
                return {
                    "success": False,
                    "error": "No emails found for this party/bill search.",
                    "queries": queries,
                }

            candidates = load_message_contexts(service, message_ids, cache)
            choice = choose_best_candidate(invoice_data, candidates)
        if not choice.get("success"):
            return {**choice, "queries": queries}

        candidate = choice["candidate"]
        attachments = candidate.get("attachments", [])
        if not attachments:
            return {"success": False, "error": "Email found, but no PDF attachments."}

        downloaded = download_classified_attachments(
            service,
            candidate["message_id"],
            attachments,
            invoice_data,
            temp_dir,
        )
        if not downloaded:
            return {"success": False, "error": "PDF attachments could not be classified/downloaded."}

        mark_read_result = mark_message_as_read(service, candidate["message_id"])

        match = candidate["match"]
        match_details = {
            "score": match["score"],
            "confidence": match["confidence"],
            "exact_inward_match": match["exact_inward_match"],
            "exact_invoice_match": match["exact_invoice_match"],
            "reasons": match["reasons"],
            "subject": candidate.get("subject", ""),
            "from": candidate.get("from", ""),
            "message_id": candidate["message_id"],
        }
        invoice_data["_gmail_match"] = match_details

        alerts = []
        if match["confidence"] != "high":
            alerts.append({
                "concept": "GMAIL_MATCH_REVIEW",
                "severity": "warning",
                "message": "Gmail Match Needs Review",
                "description": "Email was matched by party/date/payment clues, not a strong exact bill-number match.",
                "source": "Gmail Search",
                "matched_text": f"Score {match['score']} | Subject: {candidate.get('subject', '')[:80]}",
            })
        if invoice_id and not match["exact_invoice_match"] and not match["exact_inward_match"]:
            alerts.append({
                "concept": "GMAIL_MATCH_REVIEW",
                "severity": "critical",
                "message": "Excel Bill No. Not Confirmed In Email",
                "description": "The selected email did not clearly contain the Excel bill number. Check for human entry error.",
                "source": "Gmail Search",
                "matched_text": f"Excel Bill No.: {invoice_id} | Subject: {candidate.get('subject', '')[:80]}",
            })
        if not mark_read_result.get("success"):
            alerts.append({
                "concept": "GMAIL_MARK_READ_FAILED",
                "severity": "warning",
                "message": "Gmail Email Not Marked Read",
                "description": "The matching email was processed, but Gmail did not accept the mark-as-read update.",
                "source": "Gmail Search",
                "matched_text": mark_read_result.get("error", ""),
            })

        return {
            "success": True,
            "downloaded": downloaded,
            "email_body": candidate.get("body", ""),
            "message_id": candidate["message_id"],
            "marked_read": mark_read_result.get("success", False),
            "match": match_details,
            "alerts": alerts,
            "queries": used_queries,
        }

    except FileNotFoundError as e:
        return {"success": False, "error": str(e), "needs_setup": True}
    except Exception as e:
        return {"success": False, "error": f"Gmail API error: {str(e)}"}
