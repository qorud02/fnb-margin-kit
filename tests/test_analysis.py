from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from pathlib import Path

from fnb_margin_kit.analysis import (
    FIELDS,
    InputError,
    MenuItem,
    analyze,
    load_menu,
    number,
    read_menu,
)
from fnb_margin_kit.cli import main, markdown

HEADER = ",".join(FIELDS)
ROW = "아메리카노,커피,4400,0.10,700,100,0.03,100"


class CsvValidationTests(unittest.TestCase):
    def parse(self, row=ROW, header=HEADER):
        return read_menu(io.StringIO(header + "\n" + row + "\n"))

    def test_utf8_bom_and_korean_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "메뉴.csv"
            path.write_text(HEADER + "\n" + ROW + "\n", encoding="utf-8-sig")
            data = load_menu(path)
        self.assertEqual(data[0].menu, "아메리카노")
        self.assertEqual(data[0].price_gross, Decimal("4400"))
        self.assertEqual(self.parse(header="\ufeff" + HEADER)[0].category, "커피")

    def test_column_order_can_change(self):
        parts = ROW.split(",")
        self.assertEqual(
            self.parse(",".join(reversed(parts)), ",".join(reversed(FIELDS)))[0].units,
            100,
        )

    def test_invalid_headers_and_row_shapes(self):
        for header, row in [
            (HEADER + ",extra", ROW + ",x"),
            (HEADER.replace("units", "menu"), ROW),
            (HEADER, ROW + ",x"),
            (HEADER, ",".join(ROW.split(",")[:-1])),
            (HEADER, ""),
        ]:
            with self.subTest(header=header, row=row), self.assertRaises(InputError):
                self.parse(row, header)

    def test_duplicate_menu_category_and_blank_names(self):
        for row in [
            ROW + "\n" + ROW,
            ROW.replace("아메리카노", " "),
            ROW.replace("커피", ""),
        ]:
            with self.subTest(row=row), self.assertRaises(InputError):
                self.parse(row)

    def test_every_number_rejects_negative_nonfinite_and_empty(self):
        for index in range(2, 8):
            for bad in ["-1", "NaN", "Infinity", "-Infinity", "", "abc"]:
                row = ROW.split(",")
                row[index] = bad
                with (
                    self.subTest(field=FIELDS[index], bad=bad),
                    self.assertRaises(InputError),
                ):
                    self.parse(",".join(row))

    def test_units_must_be_integer_and_rates_fractional(self):
        for index, bad in [(7, "1.5"), (3, "1.01"), (6, "1.01")]:
            row = ROW.split(",")
            row[index] = bad
            with self.subTest(index=index), self.assertRaises(InputError):
                self.parse(",".join(row))

    def test_quoted_name_with_comma_and_invalid_quotes(self):
        data = self.parse(ROW.replace("아메리카노", '"아메리카노, 아이스"'))
        self.assertEqual(data[0].menu, "아메리카노, 아이스")
        with self.assertRaises(InputError):
            self.parse('"unterminated')

    def test_numeric_bounds_prevent_overflow_and_tiny_values(self):
        for value in ["1e999999", "1e-999999", "1.1234567890123", "9" * 65]:
            with self.subTest(value=value), self.assertRaises(InputError):
                number(value, "cost")


class ContributionTests(unittest.TestCase):
    def item(self, **overrides):
        data = dict(
            menu="아메리카노",
            category="커피",
            price_gross=Decimal("4400"),
            vat_rate=Decimal("0.10"),
            ingredient_cost=Decimal("700"),
            packaging_cost=Decimal("100"),
            platform_fee_rate=Decimal("0.03"),
            units=100,
        )
        data.update(overrides)
        return MenuItem(**data)

    def test_vat_and_gross_fee_basis(self):
        report = analyze([self.item()])
        row = report["menus"][0]
        self.assertEqual(Decimal(row["net_price_per_unit"]), Decimal("4000"))
        self.assertEqual(Decimal(row["platform_fee_per_unit"]), Decimal("132"))
        self.assertEqual(Decimal(row["contribution_per_unit"]), Decimal("3068"))
        self.assertEqual(Decimal(report["totals"]["contribution"]), Decimal("306800"))
        self.assertNotIn("net_profit", report)

    def test_decimal_inputs_avoid_binary_float_artifacts(self):
        item = self.item(
            price_gross=Decimal("0.30"),
            vat_rate=Decimal("0"),
            ingredient_cost=Decimal("0.10"),
            packaging_cost=Decimal("0.10"),
            platform_fee_rate=Decimal("0"),
            units=3,
        )
        self.assertEqual(
            Decimal(analyze([item])["totals"]["contribution"]), Decimal("0.30")
        )

    def test_zero_and_negative_margins_with_zero_units(self):
        zero = self.item(
            menu="zero",
            price_gross=Decimal("1100"),
            ingredient_cost=Decimal("900"),
            packaging_cost=Decimal("100"),
            platform_fee_rate=Decimal("0"),
        )
        negative = self.item(menu="negative", price_gross=Decimal("0"), units=0)
        rows = {row["menu"]: row for row in analyze([zero, negative])["menus"]}
        self.assertEqual(rows["zero"]["margin_flag"], "zero")
        self.assertEqual(rows["negative"]["margin_flag"], "negative")
        self.assertEqual(Decimal(rows["negative"]["total_contribution"]), 0)

    def test_ranking_uses_total_contribution_and_deterministic_ties(self):
        items = [
            self.item(menu="B", units=1),
            self.item(menu="A", units=1),
            self.item(menu="C", units=2),
        ]
        rows = analyze(items)["menus"]
        self.assertEqual([row["menu"] for row in rows], ["C", "A", "B"])
        self.assertEqual([row["rank"] for row in rows], [1, 2, 3])

    def test_fixed_cost_scenario_is_explicit_and_optional(self):
        report = analyze([self.item()], fixed_cost=Decimal("400000"))
        self.assertEqual(
            Decimal(
                report["fixed_cost_scenario"]["contribution_after_specified_fixed_cost"]
            ),
            -93200,
        )
        self.assertNotIn("fixed_cost_scenario", analyze([self.item()]))
        for bad in [Decimal("-1"), Decimal("NaN")]:
            with self.subTest(bad=bad), self.assertRaises(InputError):
                analyze([self.item()], fixed_cost=bad)

    def test_public_api_rejects_invalid_items(self):
        for item in [
            self.item(units=-1),
            self.item(units=1.5),
            self.item(vat_rate=Decimal("NaN")),
            self.item(platform_fee_rate=Decimal("2")),
            self.item(menu=""),
            self.item(menu=42),
        ]:
            with self.subTest(item=item), self.assertRaises(InputError):
                analyze([item])
        with self.assertRaises(InputError):
            analyze([])

    def test_sample_totals_and_margin_flags(self):
        sample = Path(__file__).resolve().parents[1] / "examples" / "menu.csv"
        report = analyze(load_menu(sample))
        self.assertEqual(report["total_units"], 190)
        self.assertEqual(Decimal(report["totals"]["net_sales"]), 770000)
        self.assertEqual(Decimal(report["totals"]["contribution"]), 512000)
        self.assertEqual(
            [row["margin_flag"] for row in report["menus"]],
            ["positive", "positive", "zero", "negative"],
        )


class CliTests(unittest.TestCase):
    def test_cli_writes_utf8_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "menu.csv"
            output = Path(directory) / "output"
            path.write_text(HEADER + "\n" + ROW, encoding="utf-8-sig")
            source = path.read_bytes()
            with redirect_stdout(io.StringIO()):
                result = main(
                    [str(path), "--output-dir", str(output), "--fixed-cost", "100000"]
                )
            self.assertEqual(result, 0)
            self.assertEqual(path.read_bytes(), source)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["menus"][0]["menu"], "아메리카노")
            self.assertIn(
                "206,800.00", (output / "report.md").read_text(encoding="utf-8")
            )

    def test_invalid_input_does_not_create_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            output = Path(directory) / "output"
            path.write_text(
                HEADER + "\n" + ROW.replace("4400", "NaN"), encoding="utf-8"
            )
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = main([str(path), "--output-dir", str(output)])
            self.assertEqual(result, 2)
            self.assertFalse(output.exists())
            self.assertIn("price_gross", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_markdown_escapes_table_delimiters(self):
        report = analyze([ContributionTests().item(menu="A|B\\C")])
        self.assertIn("A\\|B\\\\C", markdown(report))


if __name__ == "__main__":
    unittest.main()
