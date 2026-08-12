import importlib.util
import unittest
from pathlib import Path


module_path = Path(__file__).resolve().parents[2] / "family_sale_display.py"
module_spec = importlib.util.spec_from_file_location("family_sale_display_under_test", module_path)
if module_spec is None or module_spec.loader is None:
    raise RuntimeError("failed to load family_sale_display for tests")
display = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(display)


class FamilySaleDisplayTests(unittest.TestCase):
    def test_formats_amount_and_change_rate(self):
        self.assertEqual(display.format_amount(1234567), "1,234,567원")
        self.assertEqual(display.format_change_rate(12.34), "+12.3%")
        self.assertEqual(display.format_change_rate(-5), "-5.0%")
        self.assertEqual(display.format_change_rate(None), "산정 불가 (전년도 0원)")


if __name__ == "__main__":
    unittest.main()
