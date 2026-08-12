import importlib.util
import unittest
from decimal import Decimal
from pathlib import Path


module_path = Path(__file__).resolve().parents[2] / "item_display.py"
module_spec = importlib.util.spec_from_file_location("item_display_under_test", module_path)
if module_spec is None or module_spec.loader is None:
    raise RuntimeError("failed to load item_display for tests")
item_display = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(item_display)


class ItemDisplayTests(unittest.TestCase):
    def test_converts_enuri_rate_to_percentage(self):
        cases = (
            ("EMP_ENURI_RT", Decimal("0.1"), "10%"),
            ("GRP_CMP_ENURI_RT", 0.075, "7.5%"),
            ("GNRL_MEM_ENURI_RT", "0", "0%"),
            ("JSMN_BLK_ENURI_RT", "1", "100%"),
        )
        for field_name, value, expected in cases:
            with self.subTest(field_name=field_name, value=value):
                self.assertEqual(
                    item_display.format_product_result_value(field_name, value),
                    expected,
                )

    def test_keeps_non_percentage_value_unchanged(self):
        self.assertEqual(
            item_display.format_product_result_value("ITEM_NM", "테스트 상품"),
            "테스트 상품",
        )
        self.assertEqual(
            item_display.format_product_result_value("EMP_ENURI_RT", "미설정"),
            "미설정",
        )


if __name__ == "__main__":
    unittest.main()
