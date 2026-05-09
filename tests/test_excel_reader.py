import os
import tempfile
import unittest

import pandas as pd

from core.excel_reader import create_sample_excel, read_excel_file


class ExcelReaderTests(unittest.TestCase):
    def test_erp_header_maps_to_invoice_fields(self):
        data = {
            "Bill No.": ["ELE/007/2026-27"],
            "Bill Date": ["23-04-2026"],
            "Party Name": ["ELMECH ENGINEERING AND SOLUTIONS"],
            "Inward No": ["EEPU-2627-10"],
            "Inward Date": ["25-04-2026"],
            "Passing Date": ["27-04-2026"],
            "Bill Due Date": ["25-05-2026"],
            "Bill Amount": [58198],
            "Passed Amount": [58198],
            "Remark": ["PLEASE PROCESS FOR PAYMENT"],
            "Passing No.": ["APPL-J-AC-2627-0475"],
            "Sent Date": ["06-05-2026"],
            "Purchase Book": ["ELECTRIAL & ELECTRONIC"],
            "Paid Amount": [0],
            "Pay Mode": ["NORMAL"],
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "erp.xlsx")
            pd.DataFrame(data).to_excel(path, index=False, engine="openpyxl")

            result = read_excel_file(path)

        self.assertTrue(result["success"])
        self.assertEqual(result["total"], 1)
        invoice = result["invoices"][0]
        self.assertEqual(invoice["invoice_id"], "ELE/007/2026-27")
        self.assertEqual(invoice["invoice_date"], "23-04-2026")
        self.assertEqual(invoice["party_name"], "ELMECH ENGINEERING AND SOLUTIONS")
        self.assertEqual(invoice["amount"], "58198")
        self.assertEqual(invoice["passed_amount"], "58198")
        self.assertEqual(invoice["notes"], "PLEASE PROCESS FOR PAYMENT")
        self.assertEqual(invoice["mrn_number"], "EEPU-2627-10")
        self.assertEqual(invoice["pay_mode"], "NORMAL")

    def test_sample_template_uses_erp_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sample.xlsx")
            create_sample_excel(path)
            result = read_excel_file(path)

        self.assertTrue(result["success"])
        self.assertIn("invoice_id", result["columns"])
        self.assertIn("amount", result["columns"])
        self.assertIn("notes", result["columns"])
        self.assertEqual(result["total"], 2)


if __name__ == "__main__":
    unittest.main()
