import unittest

from app.faq_categories import FAQ_CATEGORY_NAMES, normalize_faq_category


class FaqCategoryTests(unittest.TestCase):
    def test_category_codes_and_names(self):
        self.assertEqual(
            FAQ_CATEGORY_NAMES,
            {
                "1": "POS공통",
                "2": "PPOS",
                "3": "APOS",
                "4": "서버",
                "5": "HBO",
                "6": "키오스크",
            },
        )

    def test_names_are_normalized_to_new_codes(self):
        self.assertEqual(normalize_faq_category("POS공통"), "1")
        self.assertEqual(normalize_faq_category("ppos"), "2")
        self.assertEqual(normalize_faq_category("APOS"), "3")
        self.assertEqual(normalize_faq_category("POS서버"), "4")
        self.assertEqual(normalize_faq_category("hbo"), "5")
        self.assertEqual(normalize_faq_category("KIOSK"), "6")

    def test_unknown_category_is_rejected(self):
        self.assertIsNone(normalize_faq_category("7"))
        self.assertIsNone(normalize_faq_category(""))


if __name__ == "__main__":
    unittest.main()
