import os
import tempfile
import unittest

import fitz

from core.pdf_merger import merge_pdfs


def create_pdf(path, labels):
    doc = fitz.open()
    for label in labels:
        page = doc.new_page()
        page.insert_text((72, 72), label, fontsize=14)
    doc.save(path)
    doc.close()


def page_texts(path):
    doc = fitz.open(path)
    texts = [page.get_text().strip() for page in doc]
    doc.close()
    return texts


class PdfMergerTests(unittest.TestCase):
    def test_invoice_po_mrn_order_and_each_section_starts_on_front(self):
        with tempfile.TemporaryDirectory() as tmp:
            mrn = os.path.join(tmp, "mrn.pdf")
            invoice = os.path.join(tmp, "invoice.pdf")
            po = os.path.join(tmp, "po.pdf")
            output = os.path.join(tmp, "merged.pdf")

            create_pdf(mrn, ["MRN page 1", "MRN page 2"])
            create_pdf(invoice, ["INVOICE page 1"])
            create_pdf(po, ["PO page 1"])

            result = merge_pdfs(
                {"invoice_id": "TEST-1", "inward_no": "INW-1"},
                {"mrn": mrn, "invoice": invoice, "po": po},
                [],
                output,
            )

            texts = page_texts(output)

        self.assertTrue(result["success"])
        self.assertEqual(result["document_order"], ["invoice", "po", "mrn"])
        self.assertEqual(result["inward_no"], "INW-1")
        self.assertEqual(result["duplex_blank_pages"], 2)
        self.assertEqual(len(texts), 6)
        self.assertIn("INVOICE page 1", texts[0])
        self.assertIn("Inward No. INW-1 Page 1 of 6", texts[0])
        self.assertNotIn("PO page 1", texts[1])
        self.assertIn("PO page 1", texts[2])
        self.assertNotIn("MRN page 1", texts[3])
        self.assertIn("MRN page 1", texts[4])
        self.assertIn("MRN page 2", texts[5])

    def test_packet_is_even_pages_without_po_and_still_starts_mrn_on_front(self):
        with tempfile.TemporaryDirectory() as tmp:
            mrn = os.path.join(tmp, "mrn.pdf")
            invoice = os.path.join(tmp, "invoice.pdf")
            output = os.path.join(tmp, "merged.pdf")

            create_pdf(mrn, ["MRN page 1"])
            create_pdf(invoice, ["INVOICE page 1"])

            result = merge_pdfs(
                {"invoice_id": "TEST-2"},
                {"mrn": mrn, "invoice": invoice},
                [],
                output,
            )

            texts = page_texts(output)

        self.assertTrue(result["success"])
        self.assertEqual(len(texts) % 2, 0)
        self.assertEqual(result["duplex_blank_pages"], 2)
        self.assertIn("INVOICE page 1", texts[0])
        self.assertNotIn("MRN page 1", texts[1])
        self.assertIn("MRN page 1", texts[2])

    def test_alerts_do_not_create_printed_cover_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            invoice = os.path.join(tmp, "invoice.pdf")
            output = os.path.join(tmp, "merged.pdf")

            create_pdf(invoice, ["INVOICE page 1"])

            result = merge_pdfs(
                {"invoice_id": "TEST-3", "inward_no": "INW-3"},
                {"invoice": invoice},
                [{"severity": "critical", "message": "Hold payment"}],
                output,
            )

            texts = page_texts(output)

        self.assertTrue(result["success"])
        self.assertTrue(result["has_alerts"])
        self.assertFalse(result["alert_cover_printed"])
        self.assertNotIn("ALERT REPORT", "\n".join(texts))
        self.assertIn("INVOICE page 1", texts[0])

    def test_inward_number_prefers_excel_then_makes_duplicates_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_invoice = os.path.join(tmp, "first_invoice.pdf")
            second_invoice = os.path.join(tmp, "second_invoice.pdf")
            first_mrn = os.path.join(tmp, "first_mrn.pdf")
            second_mrn = os.path.join(tmp, "second_mrn.pdf")
            first_output = os.path.join(tmp, "first_merged.pdf")
            second_output = os.path.join(tmp, "second_merged.pdf")
            used = set()

            create_pdf(first_invoice, ["INVOICE page 1"])
            create_pdf(second_invoice, ["INVOICE page 1"])
            create_pdf(first_mrn, ["Inward No. PDF-ONLY-1"])
            create_pdf(second_mrn, ["Inward No. PDF-ONLY-2"])

            first = merge_pdfs(
                {"invoice_id": "TEST-4", "inward_no": "EXCEL-INW"},
                {"invoice": first_invoice, "mrn": first_mrn},
                [],
                first_output,
                used,
            )
            second = merge_pdfs(
                {"invoice_id": "TEST-5", "inward_no": "EXCEL-INW"},
                {"invoice": second_invoice, "mrn": second_mrn},
                [],
                second_output,
                used,
            )

        self.assertEqual(first["inward_no"], "EXCEL-INW")
        self.assertEqual(second["inward_no"], "EXCEL-INW-2")


if __name__ == "__main__":
    unittest.main()
