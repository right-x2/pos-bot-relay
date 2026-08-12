import unittest

from app.refund_tools import normalize_refund_key


class RefundToolTests(unittest.TestCase):
    def test_normalizes_supported_sale_date_formats(self):
        for value in ("20260812", "2026-08-12", "2026/08/12", "2026.08.12"):
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_refund_key("210", value, "0011", "000123"),
                    ("210", "20260812", "0011", "000123"),
                )

    def test_preserves_leading_zeroes(self):
        result = normalize_refund_key("0210", "20260812", "0011", "000123")
        self.assertEqual(result, ("0210", "20260812", "0011", "000123"))

    def test_rejects_invalid_or_missing_keys(self):
        invalid_cases = (
            ("", "20260812", "0011", "000123"),
            ("210", "20260230", "0011", "000123"),
            ("210", "2026-8-12", "0011", "000123"),
            ("210", "20260812", "", "000123"),
            ("210", "20260812", "0011", ""),
        )
        for values in invalid_cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    normalize_refund_key(*values)


if __name__ == "__main__":
    unittest.main()
