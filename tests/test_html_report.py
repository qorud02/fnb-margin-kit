"""Offline rendering, exact sort metadata, and opt-in file preservation."""

import copy
import errno
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

from fnb_margin_kit.analysis import ChannelCost, MenuItem, analyze, load_menu
from fnb_margin_kit.cli import main
from fnb_margin_kit.html_report import dashboard_data, render_html

ROOT = Path(__file__).resolve().parents[1]
MENU_CSV = (ROOT / "examples/store-versus-delivery.csv").read_bytes()
COST_CSV = "category,additional_variable_cost\n배달,60000\n".encode("utf-8")


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.attributes = []
        self.scripts = []
        self.current_script = None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)
        if tag == "script":
            self.current_script = {"attrs": dict(attrs), "data": ""}
            self.scripts.append(self.current_script)

    def handle_endtag(self, tag):
        if tag == "script":
            self.current_script = None

    def handle_data(self, data):
        if self.current_script is not None:
            self.current_script["data"] += data

    def payload(self):
        return json.loads(next(script["data"] for script in self.scripts if script["attrs"].get("id") == "report-data"))


def item(name, price, category="Channel", units=1):
    return MenuItem(name, category, Decimal(price), Decimal(0), Decimal(0), Decimal(0), Decimal(0), units)


class DashboardTests(unittest.TestCase):
    def test_actual_scenario_values_and_source_unchanged(self):
        report = analyze(load_menu(ROOT / "examples/store-versus-delivery.csv"), Decimal("300000"),
                         channel_costs=[ChannelCost("배달", Decimal("60000"))])
        original = copy.deepcopy(report)
        html = render_html(report)
        self.assertEqual(report, original)
        payload = Document(html).payload()
        self.assertEqual(payload["summary"]["net_sales"], "700000")
        self.assertEqual(Decimal(payload["summary"]["channel_cost_scenario"]["contribution_after_additional_costs"]), 417000)
        self.assertEqual(Decimal(payload["summary"]["fixed_cost_scenario"]["contribution_after_specified_fixed_cost"]), 117000)
        for text in ("추가 채널비·고정비 차감 전", "지정 고정비 차감 후 공헌이익", "417,000.00", "117,000.00", "700,000.00"):
            self.assertIn(text, html)
        self.assertNotIn("KRW", html)
        self.assertNotIn("₩", html)

    def test_no_scenario_and_zero_fixed_cost_labels(self):
        report = analyze([item("Zero", "0", units=0)])
        html = render_html(report)
        self.assertIn("고정비 차감 전 공헌이익", html)
        self.assertNotIn("지정 고정비 차감 후 공헌이익", html)
        self.assertEqual(Document(html).payload()["summary"]["total_units"], "0")
        self.assertIn("지정 고정비 차감 후 공헌이익", render_html(analyze([item("Zero", "0")], Decimal(0))))

    def test_zero_sales_negative_channel_cost_is_retained(self):
        report = analyze([item("Idle", "1", units=0)], channel_costs=[ChannelCost("Channel", Decimal("2.000000000001"))])
        html = render_html(report)
        row = Document(html).payload()["categories"][0]
        self.assertEqual(row["units"], "0")
        self.assertEqual(row["contribution_after_additional_cost"], "-2.000000000001")
        self.assertIn('class="bar negative"', html)
        self.assertIn('data-exact="-2.000000000001"', html)

    def test_exact_large_small_and_negative_sort_ranks(self):
        report = analyze([item("Large A", "9007199254740992"), item("Large B", "9007199254740993"),
                          item("Small", "0.000000000001"), item("Zero", "0"),
                          replace(item("Negative", "0"), ingredient_cost=Decimal("2"))])
        data = dashboard_data(report)
        rows = {row["menu"]: row for row in data["menus"]}
        self.assertLess(rows["Large A"]["sort"]["total_contribution"], rows["Large B"]["sort"]["total_contribution"])
        self.assertLess(rows["Zero"]["sort"]["total_contribution"], rows["Small"]["sort"]["total_contribution"])
        self.assertLess(rows["Negative"]["sort"]["total_contribution"], rows["Zero"]["sort"]["total_contribution"])
        self.assertEqual(rows["Small"]["values"]["total_contribution"], "0.000000000001")
        for field in rows["Large A"]["values"]:
            self.assertIsInstance(rows["Large A"]["values"][field], str)
        html = render_html(report)
        self.assertNotIn("parseFloat", html)
        self.assertNotIn("Number(", html)
        self.assertIn('id="exact-values"', html)

    def test_adversarial_names_stay_text_and_json(self):
        name = '</script><img src=x onerror="alert(1)"> & @@PAYLOAD@@ \u2028\u2029 end'
        category = '\"><svg onload="alert(2)"> @@CARDS@@'
        html = render_html(analyze([item(name, "1", category=category)]))
        document = Document(html)
        self.assertEqual(len(document.scripts), 2)
        self.assertNotIn("img", document.tags)
        self.assertNotIn("svg", document.tags)
        self.assertEqual(document.payload()["menus"][0]["menu"], name)
        self.assertEqual(document.payload()["menus"][0]["category"], category)
        self.assertIn("\\u003c/script\\u003e", html)
        self.assertIn("\\u2028", html)
        self.assertIn("&lt;img", html)
        self.assertFalse(any(key.lower().startswith("on") for key, value in document.attributes))
        self.assertNotIn("innerHTML", html)

    def test_document_has_no_network_resources_and_print_support(self):
        html = render_html(analyze([item("Latte", "1")]))
        document = Document(html)
        self.assertFalse(any(key in ("src", "href", "srcset") for key, value in document.attributes))
        for text in ("fetch(", "XMLHttpRequest", "@import", "url("):
            self.assertNotIn(text, html)
        self.assertIn("connect-src 'none'", html)
        self.assertIn("@media print", html)
        self.assertIn("window.print()", html)
        self.assertIn('id="search"', html)
        self.assertIn('id="category"', html)
        self.assertIn('id="margin"', html)
        self.assertIn('id="sort"', html)

    def test_category_aggregation_preserves_small_cancellation_residual(self):
        report = analyze([
            item("Plus", "1000000000000000000000000", units=10**24),
            replace(item("Minus", "0", units=10**24), ingredient_cost=Decimal("1e24")),
            item("Cent", "0.01"),
        ])
        self.assertEqual(Decimal(report["totals"]["contribution"]), Decimal("0.01"))
        data = dashboard_data(report)
        self.assertEqual(Decimal(data["categories"][0]["contribution_after_additional_cost"]), Decimal("0.01"))


class HtmlCliTests(unittest.TestCase):
    def invoke(self, arguments):
        error = io.StringIO()
        with redirect_stderr(error), redirect_stdout(io.StringIO()):
            status = main(arguments)
        return status, error.getvalue()

    def test_opt_in_generates_html_and_identical_json_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            menu = root / "menu.csv"
            costs = root / "costs.csv"
            menu.write_bytes(MENU_CSV)
            costs.write_bytes(COST_CSV)
            common = [str(menu), "--channel-costs", str(costs), "--fixed-cost", "300000"]
            plain, html = root / "plain", root / "html"
            self.assertEqual(self.invoke(common + ["--output-dir", str(plain)])[0], 0)
            self.assertEqual(self.invoke(common + ["--html", "--output-dir", str(html)])[0], 0)
            for name in ("report.json", "report.md"):
                self.assertEqual((plain / name).read_bytes(), (html / name).read_bytes())
            self.assertFalse((plain / "report.html").exists())
            self.assertIn("117,000.00", (html / "report.html").read_text(encoding="utf-8"))
            self.assertEqual(menu.read_bytes(), MENU_CSV)
            self.assertEqual(costs.read_bytes(), COST_CSV)

    def test_report_html_can_remain_an_input_when_option_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.html"
            source.write_bytes(MENU_CSV)
            self.assertEqual(self.invoke([str(source), "--output-dir", str(root)])[0], 0)
            self.assertEqual(source.read_bytes(), MENU_CSV)

    def check_alias(self, alias):
        for source_kind in ("menu", "costs"):
            with self.subTest(source=source_kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                output = root / "output"
                output.mkdir()
                menu, costs = root / "menu.csv", root / "costs.csv"
                menu.write_bytes(MENU_CSV)
                costs.write_bytes(COST_CSV)
                source = menu if source_kind == "menu" else costs
                target = output / "report.html"
                if alias == "direct":
                    target.write_bytes(source.read_bytes())
                    source = target
                    if source_kind == "menu":
                        menu = target
                    else:
                        costs = target
                elif alias == "hardlink":
                    os.link(source, target)
                else:
                    try:
                        target.symlink_to(source)
                    except NotImplementedError:
                        self.skipTest("Symbolic links are unsupported")
                    except OSError as exc:
                        if getattr(exc, "winerror", None) == 1314 or exc.errno in (errno.EPERM, errno.EACCES):
                            self.skipTest("Symbolic link permission is unavailable")
                        raise
                before = source.read_bytes()
                status, error = self.invoke([str(menu), "--channel-costs", str(costs), "--html", "--output-dir", str(output)])
                self.assertEqual(status, 2)
                self.assertIn("overwrite", error)
                self.assertEqual(source.read_bytes(), before)
                self.assertFalse((output / "report.json").exists())
                self.assertFalse((output / "report.md").exists())

    def test_html_direct_aliases_protect_both_csvs(self):
        self.check_alias("direct")

    def test_html_hardlink_aliases_protect_both_csvs(self):
        self.check_alias("hardlink")

    def test_html_symlink_aliases_protect_both_csvs(self):
        self.check_alias("symlink")

    def test_invalid_input_with_html_creates_no_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "menu.csv"
            source.write_text("menu,category\nBad,Store\n", encoding="utf-8")
            output = root / "output"
            status, error = self.invoke([str(source), "--html", "--output-dir", str(output)])
            self.assertEqual(status, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
