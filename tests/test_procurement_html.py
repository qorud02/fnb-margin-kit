"""Human-readable purchasing output, escaped content and four-output file guards."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal, localcontext
from html.parser import HTMLParser
from pathlib import Path

from fnb_margin_kit.procurement import PlanItem, StockItem, plan_procurement
from fnb_margin_kit.procurement_cli import OUTPUT_NAMES, main
from fnb_margin_kit.procurement_html import render_procurement_html
from fnb_margin_kit.recipes import Ingredient, RecipeLine


class ParsedHtml(HTMLParser):
    def __init__(self, document):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.texts = []
        self.feed(document)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.texts.append(data)


def make_report(name="milk", menu="drink", category="store", quantity="200", rate=".8",
                units=6, stock="500", pack="1", purchase_unit="l", recipe_unit="ml", price="3000"):
    return plan_procurement(
        [Ingredient(name, Decimal(pack), purchase_unit, Decimal(price), Decimal(rate))],
        [RecipeLine(menu, category, name, Decimal(quantity), recipe_unit)],
        [PlanItem(menu, category, units)],
        [StockItem(name, Decimal(stock), recipe_unit)],
    )


class ProcurementHtmlTests(unittest.TestCase):
    def test_korean_report_keeps_purchase_demand_stock_and_menu_plan_distinct(self):
        parsed = ParsedHtml(render_procurement_html(make_report()))
        text = " ".join(parsed.texts)
        for label in ("재료 구매계획", "구매 원물량", "원물 필요량", "현재 원물 재고", "부족 원물량",
                      "사용 후 예상 잔량", "예상 구매 지출", "3,000", "1,500 ml", "500 ml",
                      "1,000 ml", "기준 판매계획", "drink", "store"):
            self.assertIn(label, text)
        tables = [attrs.get("aria-label") for tag, attrs in parsed.tags if tag == "table"]
        self.assertEqual(tables, ["재료별 구매 내역", "재료 필요량과 원물 재고", "기준 판매계획"])

    def test_zero_plan_shows_no_purchase_and_preserves_existing_stock(self):
        report = make_report(units=0, stock="500")
        text = " ".join(ParsedHtml(render_procurement_html(report)).texts)
        self.assertIn("추가 구매 없음", text)
        self.assertIn("500 ml", text)
        self.assertNotIn("구매 필요", text)
        self.assertEqual(report["summary"]["total_purchase_packs"], 0)

    def test_repeating_fraction_is_marked_approximate_with_exact_audit(self):
        report = make_report(units=1, rate=".3", stock="0")
        parsed = ParsedHtml(render_procurement_html(report))
        self.assertIn("≈666.6667 ml", " ".join(parsed.texts))
        titles = [attrs.get("title", "") for _, attrs in parsed.tags]
        self.assertTrue(any("정확값: 2000/3;" in title for title in titles))
        self.assertEqual(report["ingredients"][0]["purchase_packs"], 1)

    def test_huge_integer_and_small_fraction_do_not_use_binary_float(self):
        report = make_report(units=10**24, quantity="1e24", pack="1e24",
                             purchase_unit="each", recipe_unit="each", rate="1", stock="0", price="1")
        document = render_procurement_html(report)
        self.assertIn("1,000,000,000,000,000,000,000,000", document)
        self.assertNotIn("1e+", document)
        self.assertNotIn("≈1,000,000,000,000,000,000,000,000", document)
        tiny = render_procurement_html(make_report(quantity=".000000000001", units=1, rate="1", stock="0"))
        self.assertIn("≈0 ml", tiny)

    def test_render_is_independent_of_decimal_context_and_does_not_mutate_report(self):
        report = make_report(rate=".3", units=1)
        before = json.dumps(report, ensure_ascii=False, sort_keys=True)
        expected = render_procurement_html(report)
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(render_procurement_html(report), expected)
        self.assertEqual(json.dumps(report, ensure_ascii=False, sort_keys=True), before)

    def test_names_and_categories_cannot_create_markup_attributes_or_network_loads(self):
        name = '재료 "><img src="https://example.invalid/steal" onerror="alert(1)"> & 우유'
        menu = '<script>alert("menu")</script>'
        category = '</td><iframe src="https://example.invalid"></iframe>'
        document = render_procurement_html(make_report(name=name, menu=menu, category=category))
        parsed = ParsedHtml(document)
        tags = [tag for tag, _ in parsed.tags]
        self.assertNotIn("img", tags)
        self.assertNotIn("script", tags)
        self.assertNotIn("iframe", tags)
        self.assertIn(name, parsed.texts)
        self.assertIn(menu, parsed.texts)
        self.assertIn(category, parsed.texts)
        self.assertIn("&lt;img", document)

    def test_report_is_offline_and_has_responsive_and_print_styles(self):
        document = render_procurement_html(make_report())
        parsed = ParsedHtml(document)
        for tag, attrs in parsed.tags:
            self.assertNotIn(tag, {"script", "link", "iframe", "img", "object", "form"})
            self.assertFalse(set(attrs) & {"src", "href", "action", "srcset"})
            self.assertFalse(any(key.startswith("on") for key in attrs))
        self.assertIn("default-src 'none'", document)
        self.assertIn("@media print", document)
        self.assertIn("@media(max-width:700px)", document)
        self.assertIn("A4 landscape", document)
        self.assertIn("lang=\"ko\"", document)
        self.assertIn("실제 매출·재고 실적이 아닙니다", document)

    def test_spreadsheet_looking_values_stay_literal_text_in_html(self):
        formula = '=HYPERLINK("https://example.invalid","재료")'
        text = ParsedHtml(render_procurement_html(make_report(name=formula, menu="=1+1"))).texts
        self.assertIn(formula, text)
        self.assertIn("=1+1", text)


class ProcurementHtmlCliTests(unittest.TestCase):
    def inputs(self, root):
        texts = {
            "ingredients.csv": "ingredient,purchase_quantity,purchase_unit,purchase_price,yield_rate\nmilk,1,l,3000,.8\n",
            "recipes.csv": "menu,category,ingredient,quantity,unit\ndrink,store,milk,200,ml\n",
            "plan.csv": "menu,category,units\ndrink,store,6\n",
            "stock.csv": "ingredient,quantity,unit\nmilk,.5,l\n",
        }
        paths = []
        for name, text in texts.items():
            path = root / name
            path.write_text(text, encoding="utf-8-sig")
            paths.append(path)
        return paths

    def invoke(self, paths, output, html=True):
        args = [str(path) for path in paths[:3]] + ["--stock", str(paths[3]), "--output-dir", str(output)]
        if html:
            args.append("--html")
        errors = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(errors):
            status = main(args)
        return status, errors.getvalue()

    def test_optional_html_keeps_all_legacy_outputs_byte_identical_and_inputs_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            before = [path.read_bytes() for path in paths]
            plain, html = root / "plain", root / "html"
            self.assertEqual(self.invoke(paths, plain, html=False)[0], 0)
            self.assertEqual(self.invoke(paths, html)[0], 0)
            self.assertEqual({path.name for path in plain.iterdir()}, set(OUTPUT_NAMES))
            self.assertEqual({path.name for path in html.iterdir()}, {*OUTPUT_NAMES, "procurement.html"})
            for name in OUTPUT_NAMES:
                self.assertEqual((plain / name).read_bytes(), (html / name).read_bytes())
            report = json.loads((html / "procurement.json").read_text(encoding="utf-8"))
            self.assertEqual((html / "procurement.html").read_text(encoding="utf-8"), render_procurement_html(report))
            self.assertEqual([path.read_bytes() for path in paths], before)

    def test_new_html_output_cannot_hardlink_any_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            for index, source in enumerate(paths):
                with self.subTest(source=source.name):
                    dest = root / f"guard-{index}"
                    dest.mkdir()
                    os.link(source, dest / "procurement.html")
                    before = source.read_bytes()
                    status, error = self.invoke(paths, dest)
                    self.assertEqual(status, 2)
                    self.assertIn("must not overwrite", error)
                    self.assertEqual(source.read_bytes(), before)
                    self.assertEqual(list(dest.iterdir()), [dest / "procurement.html"])

    def test_new_html_output_cannot_alias_another_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            dest = root / "guard"
            dest.mkdir()
            (dest / "procurement.json").write_text("previous")
            os.link(dest / "procurement.json", dest / "procurement.html")
            status, error = self.invoke(paths, dest)
            self.assertEqual(status, 2)
            self.assertIn("must not alias", error)
            self.assertEqual((dest / "procurement.json").read_text(), "previous")
            self.assertFalse((dest / "procurement.md").exists())

    def test_bad_plan_preserves_existing_html_and_all_legacy_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            dest = root / "guard"
            dest.mkdir()
            for name in (*OUTPUT_NAMES, "procurement.html"):
                (dest / name).write_text("previous " + name)
            before = {path.name: path.read_bytes() for path in dest.iterdir()}
            paths[2].write_text("menu,category,units\ndrink,store,-1\n")
            self.assertEqual(self.invoke(paths, dest)[0], 2)
            self.assertEqual({path.name: path.read_bytes() for path in dest.iterdir()}, before)

    def test_html_nonfile_is_rejected_before_writing_legacy_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            dest = root / "guard"
            (dest / "procurement.html").mkdir(parents=True)
            self.assertEqual(self.invoke(paths, dest)[0], 2)
            self.assertEqual(list(dest.iterdir()), [dest / "procurement.html"])


if __name__ == "__main__":
    unittest.main()
