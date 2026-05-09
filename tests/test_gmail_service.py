import unittest
from datetime import date

import core.gmail_service as gmail_service
from core.gmail_service import (
    SCOPES,
    build_inward_search_queries,
    build_search_queries,
    choose_best_candidate,
    choose_fast_inward_candidate,
    classify_attachment_slots,
    extract_forwarded_date,
    invoice_variants,
    mark_message_as_read,
    search_candidate_messages,
    search_and_download_attachments,
    score_candidate,
)


class GmailServiceTests(unittest.TestCase):
    def test_gmail_scope_allows_marking_messages_read(self):
        self.assertEqual(SCOPES, ["https://www.googleapis.com/auth/gmail.modify"])

    def test_invoice_variants_include_short_pdf_number(self):
        variants = invoice_variants("OG/26-27/012")

        self.assertEqual(variants["compact"], "og2627012")
        self.assertEqual(variants["last_number"], "012")
        self.assertEqual(variants["last_number_clean"], "12")

    def test_scores_forwarded_payment_mail_with_full_bill_number(self):
        invoice = {
            "party_name": "DELTA GLOBAL PVT. LTD.",
            "invoice_id": "OG/26-27/012",
            "invoice_date": "23-04-2026",
        }
        context = {
            "subject": "Fwd: FOR PAYMENT (2627) : DELTA GLOBAL PVT. LTD. # OG/26-27/012",
            "body": "Please find the enclosed documents for payment process. PO MRN INVOICE",
            "filenames": ["CF-2627-147.pdf", "12.pdf", "STPO-2627-111.pdf"],
            "date": date(2026, 5, 2),
        }

        match = score_candidate(invoice, context)

        self.assertEqual(match["confidence"], "high")
        self.assertTrue(match["exact_invoice_match"])
        self.assertGreaterEqual(match["score"], 100)

    def test_scores_party_payment_mail_for_review_when_excel_bill_is_wrong(self):
        invoice = {
            "party_name": "DELTA GLOBAL PVT. LTD.",
            "invoice_id": "OG/26-27/999",
            "invoice_date": "23-04-2026",
        }
        context = {
            "subject": "Fwd: FOR PAYMENT (2627) : DELTA GLOBAL PVT. LTD. # OG/26-27/012",
            "body": "Please find the enclosed documents for payment process. PO MRN INVOICE",
            "filenames": ["CF-2627-147.pdf", "12.pdf", "STPO-2627-111.pdf"],
            "date": date(2026, 5, 2),
        }

        match = score_candidate(invoice, context)

        self.assertEqual(match["confidence"], "review")
        self.assertFalse(match["exact_invoice_match"])
        self.assertGreaterEqual(match["score"], 50)

    def test_classifies_common_payment_mail_attachments(self):
        invoice = {
            "party_name": "DELTA GLOBAL PVT. LTD.",
            "invoice_id": "OG/26-27/012",
            "mrn_number": "CF-2627-147",
        }
        attachments = [
            {"filename": "CF-2627-147.pdf", "attachmentId": "a1"},
            {"filename": "12.pdf", "attachmentId": "a2"},
            {"filename": "STPO-2627-111.pdf", "attachmentId": "a3"},
        ]

        slots = classify_attachment_slots(attachments, invoice)

        self.assertEqual(slots["mrn"]["filename"], "CF-2627-147.pdf")
        self.assertEqual(slots["invoice"]["filename"], "12.pdf")
        self.assertEqual(slots["po"]["filename"], "STPO-2627-111.pdf")

    def test_build_search_queries_use_party_and_bill_suffix(self):
        queries = build_search_queries({
            "party_name": "S.K. INDUSTRIES",
            "invoice_id": "1718",
            "sent_date": "06-05-2026",
        })
        joined = "\n".join(queries)

        self.assertIn('"sk"', joined)
        self.assertIn('"1718"', joined)
        self.assertIn("FOR PAYMENT", joined)
        self.assertIn("after:2026/04/29", joined)
        self.assertIn("before:2026/05/14", joined)

    def test_build_search_queries_prioritize_inward_number(self):
        queries = build_search_queries({
            "party_name": "S.K. INDUSTRIES",
            "invoice_id": "1718",
            "inward_no": "GS-2627-40",
            "sent_date": "06-05-2026",
        })

        self.assertIn('"GS-2627-40"', queries[0])

    def test_build_inward_search_queries_only_uses_inward_terms(self):
        queries = build_inward_search_queries({
            "party_name": "S.K. INDUSTRIES",
            "invoice_id": "1718",
            "inward_no": "GS-2627-40",
            "sent_date": "06-05-2026",
        })
        joined = "\n".join(queries)

        self.assertIn('"GS-2627-40"', joined)
        self.assertIn("after:2026/04/29", joined)
        self.assertNotIn('"1718"', joined)

    def test_accepts_single_same_date_mail_when_bill_number_is_wrong(self):
        invoice = {
            "party_name": "BLACK ROCK ENRGY",
            "invoice_id": "BRE/26-27/28",
            "sent_date": "02-05-2026",
        }
        candidates = [{
            "message_id": "m1",
            "subject": "Fwd: FOR PAYMENT (2627) : BLACK ROCK ENRGY # BRE/26-27/14",
            "body": "Please find enclosed PO MRN INVOICE for payment process.",
            "filenames": ["CF-2627-134.pdf", "14.pdf", "STPO-2627-103.pdf"],
            "attachments": [],
            "date": date(2026, 5, 2),
        }]

        choice = choose_best_candidate(invoice, candidates)

        self.assertTrue(choice["success"])
        self.assertFalse(choice["candidate"]["match"]["exact_invoice_match"])

    def test_rejects_exact_bill_match_when_sent_date_is_one_day_off(self):
        invoice = {
            "party_name": "BLACK ROCK ENRGY",
            "invoice_id": "BRE/26-27/28",
            "sent_date": "06-05-2026",
        }
        candidates = [{
            "message_id": "m1",
            "subject": "Fwd: FOR PAYMENT (2627) : BLACK ROCK ENRGY # BRE/26-27/28",
            "body": "Please find enclosed PO MRN INVOICE for payment process.",
            "filenames": ["CF-2627-154.pdf", "28.pdf", "STPO-2627-90.pdf"],
            "attachments": [],
            "date": date(2026, 5, 5),
        }]

        choice = choose_best_candidate(invoice, candidates)

        self.assertFalse(choice["success"])
        self.assertIn("Excel Sent Date is 06-05-2026", choice["error"])
        self.assertIn("Gmail email date is 05-05-2026", choice["error"])

    def test_accepts_inward_number_match_before_sent_date_mismatch(self):
        invoice = {
            "party_name": "BLACK ROCK ENRGY",
            "invoice_id": "BRE/26-27/28",
            "inward_no": "CF-2627-154",
            "sent_date": "06-05-2026",
        }
        candidates = [{
            "message_id": "m1",
            "subject": "Fwd: FOR PAYMENT (2627) : BLACK ROCK ENRGY # BRE/26-27/28",
            "body": "Please find enclosed PO MRN INVOICE for payment process.",
            "filenames": ["CF-2627-154.pdf", "28.pdf", "STPO-2627-90.pdf"],
            "attachments": [],
            "date": date(2026, 5, 5),
        }]

        choice = choose_best_candidate(invoice, candidates)

        self.assertTrue(choice["success"])
        self.assertTrue(choice["candidate"]["match"]["exact_inward_match"])
        self.assertEqual(choice["candidate"]["match"]["confidence"], "high")

    def test_fast_inward_candidate_accepts_exact_inward_match(self):
        invoice = {
            "party_name": "BLACK ROCK ENRGY",
            "invoice_id": "BRE/26-27/999",
            "inward_no": "CF-2627-154",
            "sent_date": "06-05-2026",
        }
        candidates = [{
            "message_id": "m1",
            "subject": "Fwd: FOR PAYMENT (2627) : BLACK ROCK ENRGY # BRE/26-27/28",
            "body": "Please find enclosed PO MRN INVOICE for payment process.",
            "filenames": ["CF-2627-154.pdf", "28.pdf", "STPO-2627-90.pdf"],
            "attachments": [{"filename": "CF-2627-154.pdf", "attachmentId": "a1"}],
            "date": date(2026, 5, 5),
        }]

        choice = choose_fast_inward_candidate(invoice, candidates)

        self.assertTrue(choice["success"])
        self.assertTrue(choice["candidate"]["match"]["exact_inward_match"])

    def test_accepts_exact_bill_match_when_sent_date_matches(self):
        invoice = {
            "party_name": "BLACK ROCK ENRGY",
            "invoice_id": "BRE/26-27/28",
            "sent_date": "06-05-2026",
        }
        candidates = [{
            "message_id": "m1",
            "subject": "Fwd: FOR PAYMENT (2627) : BLACK ROCK ENRGY # BRE/26-27/28",
            "body": "Please find enclosed PO MRN INVOICE for payment process.",
            "filenames": ["CF-2627-154.pdf", "28.pdf", "STPO-2627-90.pdf"],
            "attachments": [],
            "date": date(2026, 5, 6),
        }]

        choice = choose_best_candidate(invoice, candidates)

        self.assertTrue(choice["success"])

    def test_extracts_forwarded_mail_date_from_body(self):
        body = """
        ---------- Forwarded message ---------
        From: Hunnit <hunnit@example.com>
        Date: Sat, 2 May 2026 at 17:42
        Subject: FOR PAYMENT (2627)
        """

        self.assertEqual(extract_forwarded_date(body), date(2026, 5, 2))

    def test_rejects_ambiguous_party_only_matches(self):
        invoice = {
            "party_name": "DELTA GLOBAL PVT. LTD.",
            "invoice_id": "OG/26-27/999",
            "invoice_date": "23-04-2026",
        }
        candidates = [
            {
                "message_id": "m1",
                "subject": "Fwd: FOR PAYMENT (2627) : DELTA GLOBAL PVT. LTD. # OG/26-27/012",
                "body": "Please find enclosed PO MRN INVOICE for payment process.",
                "filenames": ["CF-2627-147.pdf", "12.pdf", "STPO-2627-111.pdf"],
                "attachments": [],
                "date": date(2026, 5, 2),
            },
            {
                "message_id": "m2",
                "subject": "Fwd: FOR PAYMENT (2627) : DELTA GLOBAL PVT. LTD. # OG/26-27/004",
                "body": "Please find enclosed PO MRN INVOICE for payment process.",
                "filenames": ["CF-2627-139.pdf", "4.pdf", "STPO-2627-89.pdf"],
                "attachments": [],
                "date": date(2026, 5, 2),
            },
        ]

        choice = choose_best_candidate(invoice, candidates)

        self.assertFalse(choice["success"])
        self.assertIn("Ambiguous", choice["error"])

    def test_rejects_multiple_same_date_mails_when_bill_number_is_wrong(self):
        invoice = {
            "party_name": "BLACK ROCK ENRGY",
            "invoice_id": "BRE/26-27/28",
            "sent_date": "02-05-2026",
        }
        candidates = [
            {
                "message_id": "m1",
                "subject": "Fwd: FOR PAYMENT (2627) : BLACK ROCK ENRGY # BRE/26-27/14",
                "body": "Please find enclosed PO MRN INVOICE for payment process.",
                "filenames": ["CF-2627-134.pdf", "14.pdf", "STPO-2627-103.pdf"],
                "attachments": [],
                "date": date(2026, 5, 2),
            },
            {
                "message_id": "m2",
                "subject": "Fwd: FOR PAYMENT (2627) : BLACK ROCK ENRGY # BRE/26-27/15",
                "body": "Please find enclosed PO MRN INVOICE for payment process.",
                "filenames": ["CF-2627-135.pdf", "15.pdf", "STPO-2627-104.pdf"],
                "attachments": [],
                "date": date(2026, 5, 2),
            },
        ]

        choice = choose_best_candidate(invoice, candidates)

        self.assertFalse(choice["success"])
        self.assertIn("More than one email matched", choice["error"])

    def test_search_candidate_messages_reuses_query_cache(self):
        class FakeMessages:
            def __init__(self):
                self.calls = 0

            def list(self, userId, q, maxResults):
                self.calls += 1
                return self

            def execute(self):
                return {"messages": [{"id": "m1"}, {"id": "m2"}]}

        class FakeService:
            def __init__(self):
                self.messages_api = FakeMessages()

            def users(self):
                return self

            def messages(self):
                return self.messages_api

        service = FakeService()
        cache = {}

        first = search_candidate_messages(service, ["query-one"], cache=cache)
        second = search_candidate_messages(service, ["query-one"], cache=cache)

        self.assertEqual(first, ["m1", "m2"])
        self.assertEqual(second, ["m1", "m2"])
        self.assertEqual(service.messages_api.calls, 1)

    def test_mark_message_as_read_removes_unread_label(self):
        class FakeModifyRequest:
            def __init__(self, api):
                self.api = api

            def execute(self):
                self.api.executed = True
                return {}

        class FakeMessages:
            def __init__(self):
                self.calls = []
                self.executed = False

            def modify(self, userId, id, body):
                self.calls.append({"userId": userId, "id": id, "body": body})
                return FakeModifyRequest(self)

        class FakeService:
            def __init__(self):
                self.messages_api = FakeMessages()

            def users(self):
                return self

            def messages(self):
                return self.messages_api

        service = FakeService()

        result = mark_message_as_read(service, "message-123")

        self.assertTrue(result["success"])
        self.assertTrue(service.messages_api.executed)
        self.assertEqual(service.messages_api.calls, [{
            "userId": "me",
            "id": "message-123",
            "body": {"removeLabelIds": ["UNREAD"]},
        }])

    def test_search_download_fast_inward_path_skips_bill_warning(self):
        originals = {
            "get_gmail_service": gmail_service.get_gmail_service,
            "search_candidate_messages": gmail_service.search_candidate_messages,
            "load_message_contexts": gmail_service.load_message_contexts,
            "download_classified_attachments": gmail_service.download_classified_attachments,
            "mark_message_as_read": gmail_service.mark_message_as_read,
        }
        calls = []
        candidate = {
            "message_id": "m1",
            "subject": "Fwd: FOR PAYMENT (2627) : BLACK ROCK ENRGY # BRE/26-27/28",
            "body": "Please find enclosed PO MRN INVOICE for payment process.",
            "filenames": ["CF-2627-154.pdf", "28.pdf", "STPO-2627-90.pdf"],
            "attachments": [{"filename": "CF-2627-154.pdf", "attachmentId": "a1"}],
            "date": date(2026, 5, 5),
        }

        try:
            gmail_service.get_gmail_service = lambda: object()

            def fake_search(service, queries, excluded_message_ids=None, cache=None):
                calls.append(queries)
                return ["m1"]

            gmail_service.search_candidate_messages = fake_search
            gmail_service.load_message_contexts = lambda service, ids, cache=None: [candidate]
            gmail_service.download_classified_attachments = lambda service, message_id, attachments, invoice_data, temp_dir: {"invoice": "invoice.pdf"}
            gmail_service.mark_message_as_read = lambda service, message_id: {"success": True}

            result = search_and_download_attachments(
                {
                    "party_name": "BLACK ROCK ENRGY",
                    "invoice_id": "BRE/26-27/999",
                    "inward_no": "CF-2627-154",
                    "sent_date": "06-05-2026",
                },
                "unused",
            )

        finally:
            for name, original in originals.items():
                setattr(gmail_service, name, original)

        self.assertTrue(result["success"])
        self.assertEqual(len(calls), 1)
        self.assertTrue(result["match"]["exact_inward_match"])
        self.assertEqual(result["alerts"], [])


if __name__ == "__main__":
    unittest.main()
