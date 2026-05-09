import os
import tempfile
import unittest

import fitz

from core import pdf_extractor


class PdfExtractorTests(unittest.TestCase):
    def test_scanned_page_does_not_ocr_when_disabled(self):
        calls = []
        original_ocr = pdf_extractor._ocr_with_gemini
        pdf_extractor._ocr_with_gemini = lambda pages: calls.append(pages) or []

        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "blank.pdf")
                doc = fitz.open()
                doc.new_page()
                doc.save(path)
                doc.close()

                text = pdf_extractor.extract_text_from_pdf(path, allow_ocr=False)

            self.assertEqual(text, "")
            self.assertEqual(calls, [])
        finally:
            pdf_extractor._ocr_with_gemini = original_ocr

    def test_scanned_page_ocr_is_opt_in(self):
        calls = []
        original_ocr = pdf_extractor._ocr_with_gemini

        def fake_ocr(pages):
            calls.append(pages)
            return [(idx, "OCR TEXT") for idx, _ in pages]

        pdf_extractor._ocr_with_gemini = fake_ocr

        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "blank.pdf")
                doc = fitz.open()
                doc.new_page()
                doc.save(path)
                doc.close()

                text = pdf_extractor.extract_text_from_pdf(path, allow_ocr=True, max_pages=1)

            self.assertEqual(text, "OCR TEXT")
            self.assertEqual(len(calls), 1)
        finally:
            pdf_extractor._ocr_with_gemini = original_ocr

    def test_ocr_supplements_native_text_when_enabled_for_stamps(self):
        calls = []
        original_ocr = pdf_extractor._ocr_with_gemini

        def fake_ocr(pages):
            calls.append(pages)
            return [(idx, "Due Date 22/04/26") for idx, _ in pages]

        pdf_extractor._ocr_with_gemini = fake_ocr

        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "native.pdf")
                doc = fitz.open()
                page = doc.new_page()
                page.insert_text(
                    (72, 72),
                    "Invoice text without stamp words " * 4,
                    fontsize=12,
                )
                doc.save(path)
                doc.close()

                text = pdf_extractor.extract_text_from_pdf(path, allow_ocr=True, max_pages=1)

            self.assertIn("Invoice text without stamp words", text)
            self.assertIn("Due Date 22/04/26", text)
            self.assertEqual(len(calls), 1)
        finally:
            pdf_extractor._ocr_with_gemini = original_ocr


if __name__ == "__main__":
    unittest.main()
