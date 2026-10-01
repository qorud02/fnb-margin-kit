import unittest
from decimal import Decimal

from fnb_margin_kit.analysis import InputError, MenuItem, analyze
from fnb_margin_kit.cli import markdown


def item(menu, category="Food"):
    return MenuItem(
        menu,
        category,
        Decimal("100"),
        Decimal("0"),
        Decimal("30"),
        Decimal("10"),
        Decimal("0"),
        1,
    )


class PublicApiTests(unittest.TestCase):
    def test_duplicate_normalized_menu_category_rejected(self):
        with self.assertRaisesRegex(InputError, "duplicate menu/category"):
            analyze([item(" Soup "), item("Soup")])

    def test_public_api_normalizes_text(self):
        result = analyze([item(" Soup ", " Food ")])["menus"][0]
        self.assertEqual((result["menu"], result["category"]), ("Soup", "Food"))

    def test_markdown_treats_html_as_text(self):
        result = markdown(analyze([item("<script>alert(1)</script>")]))
        self.assertIn("&lt;script&gt;", result)
        self.assertNotIn("<script>", result)


if __name__ == "__main__":
    unittest.main()
