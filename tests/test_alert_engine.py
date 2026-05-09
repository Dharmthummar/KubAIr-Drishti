import unittest

from core.alert_engine import derive_review_flags, derive_review_status, generate_alerts_for_invoice


class AlertEngineTests(unittest.TestCase):
    def test_detects_due_date_and_debit_note_stamps(self):
        alerts = generate_alerts_for_invoice(
            {"invoice_id": "INV-1", "amount": "100"},
            {"invoice": "Due Date 22/04/26\nD.N.No. 407\nTotal Amount 100"},
            "",
        )
        concepts = {alert["concept"] for alert in alerts}

        self.assertIn("DUE_DATE_STAMP", concepts)
        self.assertIn("DEBIT_NOTE", concepts)
        self.assertEqual(
            derive_review_flags(alerts),
            {"has_debit_note": True, "has_due_date_stamp": True},
        )
        self.assertEqual(derive_review_status(alerts), "Debit Note / Due Date Stamp")

    def test_clear_status_when_no_alerts(self):
        self.assertEqual(derive_review_status([]), "Clear")


if __name__ == "__main__":
    unittest.main()
