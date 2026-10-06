"""Independent arithmetic, plan semantics and input-preservation regressions."""

import csv
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from markdown_it import MarkdownIt

from fnb_margin_kit.analysis import ChannelCost, FIELDS, InputError, MenuItem, analyze, read_menu
from fnb_margin_kit.cli import main, markdown
from fnb_margin_kit.html_report import render_html
from fnb_margin_kit.scenarios import analyze_comparison, comparison_markdown


def item(**overrides):
    values = dict(menu="라테", category="매장", price_gross=Decimal("5500"),
                  vat_rate=Decimal("0.10"), ingredient_cost=Decimal("1200"),
                  packaging_cost=Decimal("100"), platform_fee_rate=Decimal("0"), units=100)
    values.update(overrides)
    return MenuItem(**values)


def csv_data(items):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(FIELDS)
    for row in items:
        writer.writerow([getattr(row, field) for field in FIELDS])
    return stream.getvalue()


class ScenarioArithmeticTests(unittest.TestCase):
    def test_prices_costs_quantities_vat_and_gross_fee_are_independent(self):
        base = item(category="배달", packaging_cost=Decimal("600"),
                    platform_fee_rate=Decimal("0.20"), units=40)
        proposed = replace(base, price_gross=Decimal("6050"), ingredient_cost=Decimal("1350"),
                           packaging_cost=Decimal("650"), platform_fee_rate=Decimal("0.18"), units=38)
        report = analyze_comparison([base], [proposed])
        row = report["menus"][0]
        self.assertEqual(Decimal(row["baseline"]["contribution_per_unit"]), Decimal("2100"))
        self.assertEqual(Decimal(row["proposed"]["net_price_per_unit"]), Decimal("5500"))
        self.assertEqual(Decimal(row["proposed"]["platform_fee_per_unit"]), Decimal("1089"))
        self.assertEqual(Decimal(row["proposed"]["contribution_per_unit"]), Decimal("2411"))
        self.assertEqual(Decimal(row["delta"]["total_contribution"]), Decimal("7618"))
        self.assertEqual(Decimal(row["delta"]["gross_sales"]), Decimal("9900"))
        self.assertEqual(Decimal(row["baseline"]["gross_sales"]), Decimal("220000"))
        self.assertEqual(Decimal(row["proposed"]["gross_sales"]), Decimal("229900"))
        self.assertEqual(Decimal(row["baseline"]["net_sales"]), Decimal("200000"))
        self.assertEqual(Decimal(row["proposed"]["net_sales"]), Decimal("209000"))
        self.assertEqual(set(row["changed_inputs"]), {"price_gross", "ingredient_cost",
                                                     "packaging_cost", "platform_fee_rate", "units"})
        self.assertEqual(row["retained_contribution_quantity"]["min_units"], 35)

    def test_same_fixed_cost_and_independent_channel_costs(self):
        base, proposed = item(), item(price_gross=Decimal("6050"), ingredient_cost=Decimal("1350"), units=90)
        report = analyze_comparison([base], [proposed], Decimal("300000"),
                                    channel_costs=[ChannelCost("매장", Decimal("3000"))],
                                    proposed_channel_costs=[ChannelCost("매장", Decimal("4000"))])
        summary = report["summary"]
        self.assertEqual(Decimal(summary["baseline"]["contribution_after_specified_fixed_cost"]), Decimal("67000"))
        self.assertEqual(Decimal(summary["proposed"]["contribution_after_specified_fixed_cost"]), Decimal("60500"))
        self.assertEqual(Decimal(summary["delta"]["contribution_after_additional_costs"]), Decimal("-6500"))
        self.assertEqual(summary["delta"]["contribution_after_specified_fixed_cost"],
                         summary["delta"]["contribution_after_additional_costs"])
        self.assertNotIn("specified_fixed_cost", report["categories"][0]["baseline"])
        self.assertEqual(report["menus"][0]["retained_contribution_quantity"]["min_units"], 92)

    def test_proposed_channel_omission_means_its_own_zero(self):
        report = analyze_comparison([item()], [item()], channel_costs=[ChannelCost("매장", Decimal("3"))])
        summary = report["summary"]
        self.assertTrue(summary["baseline"]["channel_costs_supplied"])
        self.assertFalse(summary["proposed"]["channel_costs_supplied"])
        self.assertEqual(summary["proposed"]["additional_variable_cost"], "0")
        self.assertEqual(Decimal(summary["delta"]["contribution_after_additional_costs"]), 3)
        self.assertIsNone(summary["delta"]["contribution_after_specified_fixed_cost"])

    def test_row_order_and_independent_ranks(self):
        first, second = item(menu="A", units=10), item(menu="B", units=5)
        report = analyze_comparison([first, second], [replace(second, units=20), first])
        rows = {row["menu"]: row for row in report["menus"]}
        self.assertEqual(rows["A"]["baseline"]["rank"], 1)
        self.assertEqual(rows["A"]["proposed"]["rank"], 2)
        self.assertEqual(rows["B"]["proposed"]["rank"], 1)

    def test_mismatched_keys_name_missing_and_unexpected(self):
        with self.assertRaisesRegex(InputError, "missing from proposed: 라테 / 매장; unexpected in proposed: 라테 / 배달"):
            analyze_comparison([item()], [item(category="배달")])

    def test_repeating_vat_same_plan_has_same_integer_threshold(self):
        for vat, units in [("0.3", 7), ("0.7", 3)]:
            row = item(price_gross=Decimal("1"), vat_rate=Decimal(vat), ingredient_cost=Decimal("0"),
                       packaging_cost=Decimal("0"), units=units)
            threshold = analyze_comparison([row], [row])["menus"][0]["retained_contribution_quantity"]
            self.assertEqual(threshold["min_units"], units)
            self.assertTrue(threshold["current_units_meet_threshold"])
            self.assertIn("original inputs", threshold["basis"])

    def test_exact_integer_boundary_and_just_below_boundary(self):
        base = item(price_gross=Decimal("1"), vat_rate=Decimal("0"), ingredient_cost=Decimal("0"),
                    packaging_cost=Decimal("0"), units=1)
        proposed = replace(base, price_gross=Decimal("0.5"))
        exact = analyze_comparison([base], [proposed])["menus"][0]["retained_contribution_quantity"]
        self.assertEqual(exact["min_units"], 2)
        below = replace(proposed, ingredient_cost=Decimal("0.000000000001"))
        self.assertEqual(analyze_comparison([base], [below])["menus"][0]["retained_contribution_quantity"]["min_units"], 3)

    def test_extreme_quantity_is_exact_and_marks_input_bound(self):
        base = item(price_gross=Decimal("999999999999999999999999.999"), vat_rate=Decimal("0"),
                    ingredient_cost=Decimal("0"), packaging_cost=Decimal("0"), units=10**24)
        proposed = replace(base, price_gross=Decimal("0.000000000001"), units=1)
        quantity = analyze_comparison([base], [proposed])["menus"][0]["retained_contribution_quantity"]
        self.assertEqual(quantity["min_units"], 10**60 - 10**33)
        self.assertFalse(quantity["within_input_unit_limit"])
        self.assertEqual(quantity["additional_units_required"], 10**60 - 10**33 - 1)

    def test_nonpositive_regimes_and_zero_sales_have_null_thresholds(self):
        positive = item()
        zero = replace(positive, price_gross=Decimal("0"), ingredient_cost=Decimal("0"), packaging_cost=Decimal("0"))
        negative = replace(positive, price_gross=Decimal("0"))
        for base, plan, status in [(zero, positive, "baseline_nonpositive"),
                                   (negative, positive, "baseline_nonpositive"),
                                   (replace(positive, units=0), positive, "baseline_nonpositive"),
                                   (positive, zero, "proposed_unit_zero"),
                                   (positive, negative, "proposed_unit_negative")]:
            with self.subTest(status=status, base=base, proposed=plan):
                quantity = analyze_comparison([base], [plan])["menus"][0]["retained_contribution_quantity"]
                self.assertEqual(quantity["status"], status)
                self.assertIsNone(quantity["min_units"])
                self.assertIsNone(quantity["within_input_unit_limit"])

    def test_zero_proposed_sales_retains_positive_unit_margin_and_gap(self):
        result = analyze_comparison([item(units=7)], [item(units=0)])
        row = result["menus"][0]
        self.assertEqual(row["proposed"]["margin_flag"], "positive")
        self.assertEqual(Decimal(row["proposed"]["total_contribution"]), 0)
        self.assertEqual(row["retained_contribution_quantity"]["min_units"], 7)
        self.assertEqual(row["retained_contribution_quantity"]["additional_units_required"], 7)

    def test_delta_subtraction_preserves_tiny_terms_against_huge_amount(self):
        base = item(price_gross=Decimal("1e24"), vat_rate=Decimal("0"), ingredient_cost=Decimal("0"),
                    packaging_cost=Decimal("0"), units=10**24)
        plan = replace(base, price_gross=Decimal("1e-12"), units=1)
        report = analyze_comparison([base], [plan])
        expected = Fraction(1, 10**12) - 10**48
        for value in [report["summary"]["delta"]["contribution"],
                      report["categories"][0]["delta"]["contribution"],
                      report["menus"][0]["delta"]["total_contribution"]]:
            self.assertEqual(Fraction(Decimal(value)), expected)
        self.assertEqual(json.loads(json.dumps(report))["summary"], report["summary"])

    def test_numeric_representations_do_not_create_false_changed_inputs(self):
        report = analyze_comparison([item(vat_rate=Decimal("0.10"))], [item(vat_rate=Decimal("0.1"))])
        self.assertEqual(report["menus"][0]["changed_inputs"], {})

    def test_context_does_not_change_threshold_or_deltas(self):
        row = item(price_gross=Decimal("1"), vat_rate=Decimal("0.3"), ingredient_cost=Decimal("0"),
                   packaging_cost=Decimal("0"), units=7)
        expected = analyze_comparison([row], [row])
        with localcontext() as ctx:
            ctx.prec = 6
            self.assertEqual(analyze_comparison([row], [row]), expected)


class ScenarioCliTests(unittest.TestCase):
    def run_cli(self, arguments):
        stderr = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            status = main(arguments)
        return status, stderr.getvalue()

    def test_bom_unicode_column_order_and_report_byte_equality(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, plan = root / "baseline.csv", root / "proposed.csv"
            rows = [item(menu="가상 라테 🍵"), item(menu="가상 디저트", category="배달", units=4)]
            base.write_text(csv_data(rows), encoding="utf-8-sig")
            reversed_csv = io.StringIO(newline="")
            writer = csv.writer(reversed_csv)
            writer.writerow(reversed(FIELDS))
            for row in reversed(rows):
                writer.writerow([getattr(row, field) for field in reversed(FIELDS)])
            plan.write_text(reversed_csv.getvalue(), encoding="utf-8-sig")
            costs = root / "costs.csv"
            costs.write_text("category,additional_variable_cost\n매장,100\n", encoding="utf-8-sig")
            original = {path: path.read_bytes() for path in (base, plan, costs)}
            for html in (False, True):
                for fixed in (None, "300000"):
                    with self.subTest(html=html, fixed=fixed):
                        ordinary, compared = root / f"ordinary-{html}-{fixed}", root / f"compared-{html}-{fixed}"
                        arguments = [str(base), "--channel-costs", str(costs)]
                        if html:
                            arguments += ["--html"]
                        if fixed:
                            arguments += ["--fixed-cost", fixed]
                        self.assertEqual(self.run_cli(arguments + ["--output-dir", str(ordinary)])[0], 0)
                        self.assertEqual(self.run_cli(arguments + ["--compare-menu", str(plan), "--output-dir", str(compared)])[0], 0)
                        for name in ("report.json", "report.md") + (("report.html",) if html else ()):
                            self.assertEqual((ordinary / name).read_bytes(), (compared / name).read_bytes())
                        report = analyze(rows, None if fixed is None else Decimal(fixed),
                                         channel_costs=[ChannelCost("매장", Decimal("100"))])
                        self.assertEqual((ordinary / "report.json").read_text(encoding="utf-8"), json.dumps(report, ensure_ascii=False, indent=2) + "\n")
                        self.assertEqual((ordinary / "report.md").read_text(encoding="utf-8"), markdown(report))
                        if html:
                            self.assertEqual((ordinary / "report.html").read_text(encoding="utf-8"), render_html(report))
                        self.assertFalse((ordinary / "comparison.json").exists())
                        self.assertTrue((compared / "comparison.md").exists())
            self.assertEqual({path: path.read_bytes() for path in original}, original)

    def test_invalid_proposed_inputs_do_not_write_partial_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, plan, output = root / "baseline.csv", root / "proposed.csv", root / "output"
            base.write_text(csv_data([item()]), encoding="utf-8")
            invalids = ["menu,price\nx,1\n", csv_data([item(units=-1)]), csv_data([item(units=Decimal("1.5"))]),
                        csv_data([item(price_gross=Decimal("NaN"))]), csv_data([item(category="다른 채널")]),
                        csv_data([item(), item()])]
            for data in invalids:
                with self.subTest(data=data):
                    plan.write_text(data, encoding="utf-8")
                    status, stderr = self.run_cli([str(base), "--compare-menu", str(plan), "--output-dir", str(output)])
                    self.assertEqual(status, 2)
                    self.assertNotIn("Traceback", stderr)
                    self.assertFalse(output.exists())

    def test_proposed_channel_flag_requires_comparison_and_unknown_cost_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, plan, costs = root / "baseline.csv", root / "proposed.csv", root / "costs.csv"
            base.write_text(csv_data([item()]), encoding="utf-8")
            plan.write_bytes(base.read_bytes())
            costs.write_text("category,additional_variable_cost\nunknown,1\n", encoding="utf-8")
            status, stderr = self.run_cli([str(base), "--compare-channel-costs", str(costs), "--output-dir", str(root / "bad")])
            self.assertEqual(status, 2)
            self.assertIn("requires --compare-menu", stderr)
            status, stderr = self.run_cli([str(base), "--compare-menu", str(plan), "--compare-channel-costs", str(costs), "--output-dir", str(root / "bad")])
            self.assertEqual(status, 2)
            self.assertIn("not found", stderr)
            self.assertFalse((root / "bad").exists())

    def test_every_supplied_input_against_every_output_direct_hardlink_symlink(self):
        names = ("report.json", "report.md", "report.html", "comparison.json", "comparison.md")
        for source_index in range(4):
            for name in names:
                for alias in ("direct", "hardlink", "symlink"):
                    with self.subTest(source=source_index, output=name, alias=alias), tempfile.TemporaryDirectory() as directory:
                        root, output = Path(directory), Path(directory) / "output"
                        output.mkdir()
                        paths = [root / name for name in ("base.csv", "plan.csv", "base-costs.csv", "plan-costs.csv")]
                        for index, path in enumerate(paths):
                            path.write_text(csv_data([item()]) if index < 2 else "category,additional_variable_cost\n매장,1\n", encoding="utf-8")
                        target, source = output / name, paths[source_index]
                        if alias == "direct":
                            source.replace(target)
                            paths[source_index] = target
                        elif alias == "hardlink":
                            os.link(source, target)
                        else:
                            try:
                                target.symlink_to(source)
                            except OSError as exc:
                                self.skipTest(f"Symlink creation unavailable: {exc}")
                        original = {path: path.read_bytes() for path in paths}
                        status, stderr = self.run_cli([str(paths[0]), "--compare-menu", str(paths[1]),
                                                      "--channel-costs", str(paths[2]), "--compare-channel-costs", str(paths[3]),
                                                      "--html", "--output-dir", str(output)])
                        self.assertEqual(status, 2)
                        self.assertIn("must not overwrite", stderr)
                        self.assertEqual({path: path.read_bytes() for path in original}, original)
                        self.assertEqual({path.name for path in output.iterdir()}, {name})

    def test_comparison_markdown_preserves_adversarial_names_as_text(self):
        label = "![라테](https://example.test/a.png) **굵게** _기울임_ ~~취소~~ `code` | \\ 끝"
        report = analyze_comparison([item(menu=label, category="[매장](https://example.test)")],
                                    [item(menu=label, category="[매장](https://example.test)", units=50)])
        html = MarkdownIt("commonmark").enable(["table", "strikethrough"]).render(comparison_markdown(report))
        class Cells(HTMLParser):
            def __init__(self):
                super().__init__()
                self.cells, self.current, self.nested = [], None, []
            def handle_starttag(self, tag, attrs):
                if self.current is not None:
                    self.nested.append(tag)
                if tag == "td":
                    self.current = []
            def handle_data(self, data):
                if self.current is not None:
                    self.current.append(data)
            def handle_endtag(self, tag):
                if tag == "td" and self.current is not None:
                    self.cells.append("".join(self.current))
                    self.current = None
        cells = Cells()
        cells.feed(html)
        self.assertIn(label, cells.cells)
        self.assertFalse(cells.nested)


if __name__ == "__main__":
    unittest.main()
