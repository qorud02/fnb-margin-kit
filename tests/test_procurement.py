"""Exact purchasing, raw stock semantics and pre-write input protection."""

import csv
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

from fnb_margin_kit.analysis import InputError
from fnb_margin_kit.procurement import (
    PlanItem, StockItem, plan_procurement, procurement_csv, procurement_markdown,
    read_plan, read_stock,
)
from fnb_margin_kit.procurement_cli import OUTPUT_NAMES, main
from fnb_margin_kit.recipes import Ingredient, RecipeLine, load_ingredients, load_recipes

IHEADER = "ingredient,purchase_quantity,purchase_unit,purchase_price,yield_rate\n"
RHEADER = "menu,category,ingredient,quantity,unit\n"
PHEADER = "menu,category,units\n"
SHEADER = "ingredient,quantity,unit\n"


def ingredient(name="milk", quantity="1", unit="l", price="3000", rate=".8"):
    return Ingredient(name, Decimal(quantity), unit, Decimal(price), Decimal(rate))


def recipe(menu="drink", category="store", name="milk", quantity="200", unit="ml"):
    return RecipeLine(menu, category, name, Decimal(quantity), unit)


def stock(name="milk", quantity="100", unit="ml"):
    return StockItem(name, Decimal(quantity), unit)


def fraction(record):
    return Fraction(int(record["numerator"]), int(record["denominator"]))


def rows(report):
    return {row["ingredient"]: row for row in report["ingredients"]}


class ProcurementArithmeticTests(unittest.TestCase):
    def test_shared_stock_subtracted_once_across_categories_and_menus(self):
        report = plan_procurement([ingredient()],
                                  [recipe(), recipe(category="delivery"), recipe(menu="other")],
                                  [PlanItem("drink", "store", 2), PlanItem("drink", "delivery", 3),
                                   PlanItem("other", "store", 1)], [stock(quantity="500")])
        milk = rows(report)["milk"]
        self.assertEqual(fraction(milk["edible_required_base"]), 1200)
        self.assertEqual(fraction(milk["gross_required_base"]), 1500)
        self.assertEqual(fraction(milk["shortage_base"]), 1000)
        self.assertEqual(milk["purchase_packs"], 1)
        self.assertEqual(fraction(milk["remaining_stock_base"]), 0)
        self.assertEqual(fraction(report["summary"]["total_purchase_spend"]), 3000)

    def test_exact_pack_boundary_just_below_equal_and_above(self):
        for quantity, expected in [("999.999999999999", 1), ("1000", 1), ("1000.000000000001", 2)]:
            with self.subTest(quantity=quantity):
                result = plan_procurement([ingredient(rate="1")], [recipe(quantity=quantity)],
                                          [PlanItem("drink", "store", 1)])
                self.assertEqual(rows(result)["milk"]["purchase_packs"], expected)

    def test_preparation_yield_keeps_raw_stock_raw(self):
        report = plan_procurement([ingredient(rate=".5")], [recipe(quantity="500")],
                                  [PlanItem("drink", "store", 1)], [stock(quantity="1", unit="l")])
        milk = rows(report)["milk"]
        self.assertEqual(fraction(milk["gross_required_base"]), 1000)
        self.assertEqual(milk["purchase_packs"], 0)
        self.assertEqual(fraction(milk["remaining_stock_base"]), 0)

    def test_insufficient_stock_purchases_complete_pack_and_retains_overage(self):
        report = plan_procurement([ingredient()], [recipe()], [PlanItem("drink", "store", 1)],
                                  [stock()])
        milk = rows(report)["milk"]
        self.assertEqual(fraction(milk["shortage_base"]), 150)
        self.assertEqual(milk["purchase_packs"], 1)
        self.assertEqual(fraction(milk["remaining_stock_base"]), 850)

    def test_sufficient_excess_and_zero_stock_are_nonnegative(self):
        for quantity, packs, remaining in [("250", 0, 0), ("300", 0, 50), ("0", 1, 750)]:
            with self.subTest(quantity=quantity):
                report = plan_procurement([ingredient()], [recipe()], [PlanItem("drink", "store", 1)],
                                          [stock(quantity=quantity)])
                milk = rows(report)["milk"]
                self.assertEqual(milk["purchase_packs"], packs)
                self.assertEqual(fraction(milk["remaining_stock_base"]), remaining)
                self.assertGreaterEqual(fraction(milk["shortage_base"]), 0)

    def test_mass_volume_count_conversions_and_free_packs(self):
        report = plan_procurement(
            [ingredient("fruit", "1", "KG", "5000", ".8"),
             ingredient("milk", "1000", "ML", "3000", "1"),
             ingredient("piece", "12", "EaCh", "0", "1")],
            [recipe(name="fruit", quantity=".12", unit="KG"),
             recipe(name="milk", quantity=".2", unit="L"),
             recipe(name="piece", quantity="1", unit="EaCh")],
            [PlanItem("drink", "store", 10)],
            [stock("fruit", ".2", "kg"), stock("piece", "5", "each")],
        )
        items = rows(report)
        self.assertEqual([items[name]["base_unit"] for name in ("fruit", "milk", "piece")], ["g", "ml", "each"])
        self.assertEqual([items[name]["purchase_packs"] for name in ("fruit", "milk", "piece")], [2, 2, 1])
        self.assertEqual(fraction(report["summary"]["total_purchase_spend"]), 16000)

    def test_zero_plan_and_unused_catalog_preserve_stock_without_purchase(self):
        report = plan_procurement([ingredient(), ingredient("unused")], [recipe()],
                                  [PlanItem("drink", "store", 0)], [stock(), stock("unused", "300")])
        self.assertEqual(report["summary"]["total_purchase_packs"], 0)
        self.assertEqual(fraction(rows(report)["unused"]["remaining_stock_base"]), 300)
        self.assertEqual(fraction(rows(report)["milk"]["gross_required_base"]), 0)

    def test_fraction_ceiling_preserves_tiny_term_beyond_display_precision(self):
        result = plan_procurement(
            [ingredient(quantity="1e24", unit="each", price="1", rate="1")],
            [recipe(quantity="1e24", unit="each"), recipe(menu="tiny", quantity="1e-12", unit="each")],
            [PlanItem("drink", "store", 10**24), PlanItem("tiny", "store", 1)],
        )
        milk = rows(result)["milk"]
        self.assertEqual(fraction(milk["gross_required_base"]), Fraction(10**60 + 1, 10**12))
        self.assertEqual(milk["purchase_packs"], 10**24 + 1)
        self.assertEqual(fraction(milk["remaining_stock_base"]), Fraction(10**36 - 1, 10**12))

    def test_low_decimal_context_and_reordered_inputs_keep_exact_totals(self):
        ingredients = [ingredient(), ingredient("fruit", rate=".7")]
        recipes = [recipe(), recipe(name="fruit"), recipe(category="delivery")]
        plan = [PlanItem("drink", "store", 3), PlanItem("drink", "delivery", 2)]
        stocks = [stock(), stock("fruit")]
        baseline = plan_procurement(ingredients, recipes, plan, stocks)
        with localcontext() as context:
            context.prec = 2
            actual = plan_procurement(ingredients, recipes, plan, stocks)
        self.assertEqual(actual, baseline)
        reordered = plan_procurement(ingredients[::-1], recipes[::-1], plan[::-1], stocks[::-1])
        self.assertEqual(rows(reordered), rows(baseline))
        self.assertEqual(reordered["summary"], baseline["summary"])

    def test_worked_example_independent_constants_and_without_stock(self):
        root = Path(__file__).resolve().parents[1] / "examples" / "procurement"
        ingredients, recipes = load_ingredients(root / "ingredients.csv"), load_recipes(root / "recipes.csv")
        with (root / "plan.csv").open(encoding="utf-8") as stream:
            plan = read_plan(stream)
        with (root / "stock.csv").open(encoding="utf-8") as stream:
            stocks = read_stock(stream)
        result = plan_procurement(ingredients, recipes, plan, stocks)
        expected = {
            "가상 원두": (Fraction(1080), 1, Fraction(420), Fraction(24000)),
            "가상 우유": (Fraction(246000, 19), 12, Fraction(10500, 19), Fraction(36000)),
            "가상 바나나": (Fraction(1500), 2, Fraction(700), Fraction(10000)),
            "가상 시럽": (Fraction(240), 1, Fraction(610), Fraction(6000)),
            "가상 디저트 반제품": (Fraction(8), 1, Fraction(9), Fraction(18000)),
            "가상 생강": (Fraction(0), 0, Fraction(100), Fraction(0)),
        }
        for row in result["ingredients"]:
            self.assertEqual((fraction(row["gross_required_base"]), row["purchase_packs"],
                              fraction(row["remaining_stock_base"]), fraction(row["purchase_spend"])),
                             expected[row["ingredient"]])
        self.assertEqual(result["summary"]["planned_menu_units"], 78)
        self.assertEqual(result["summary"]["total_purchase_packs"], 17)
        self.assertEqual(fraction(result["summary"]["total_purchase_spend"]), 94000)
        no_stock = plan_procurement(ingredients, recipes, plan)
        self.assertEqual(no_stock["summary"]["total_purchase_packs"], 19)
        self.assertEqual(fraction(no_stock["summary"]["total_purchase_spend"]), 121000)

    def test_csv_fraction_audit_reconstructs_exact_amounts(self):
        result = plan_procurement([ingredient(rate=".7")], [recipe()], [PlanItem("drink", "store", 2)])
        exported = list(csv.DictReader(io.StringIO(procurement_csv(result))))[0]
        self.assertEqual(exported["gross_required_base_numerator"], "4000")
        self.assertEqual(exported["gross_required_base_denominator"], "7")
        self.assertEqual(exported["purchase_packs"], "1")
        self.assertEqual(Fraction(int(exported["remaining_stock_base_numerator"]),
                                  int(exported["remaining_stock_base_denominator"])), Fraction(3000, 7))

    def test_markdown_escapes_names_and_explains_quantity_basis(self):
        name = '[x](https://invalid.test)|<img>*'
        result = plan_procurement([ingredient(name)], [recipe(name=name)], [PlanItem("drink", "store", 1)])
        text = procurement_markdown(result)
        self.assertIn("\\[x\\]", text)
        self.assertIn("\\|&lt;img&gt;\\*", text)
        self.assertIn("raw purchased quantity", text)


class ProcurementInputTests(unittest.TestCase):
    def test_bom_reordered_columns_quoted_names_and_case_sensitive_identity(self):
        plan = read_plan(io.StringIO('\ufeffunits,category,menu\n2,매장,"음료, 큰잔"\n0,배달,"음료, 큰잔"\n'))
        stocks = read_stock(io.StringIO('\ufeffunit,ingredient,quantity\nKG,"재료, 하나",.5\n'))
        self.assertEqual(plan[0], PlanItem("음료, 큰잔", "매장", 2))
        self.assertEqual(stocks[0], StockItem("재료, 하나", Decimal(".5"), "kg"))
        with self.assertRaises(InputError):
            plan_procurement([ingredient()], [recipe()], [PlanItem("Drink", "store", 1)])

    def test_invalid_plan_quantity_fraction_negative_nonfinite_and_bounds(self):
        for value in ("-1", "0.5", "NaN", "Infinity", "1e25", "1e-13", "", "1" * 29):
            with self.subTest(value=value), self.assertRaises(InputError):
                read_plan(io.StringIO(PHEADER + f"drink,store,{value}\n"))
        self.assertEqual(read_plan(io.StringIO(PHEADER + "drink,store,1.0\n"))[0].units, 1)

    def test_invalid_stock_quantity_and_units(self):
        for value in ("-1", "NaN", "Infinity", "1e25", "1e-13", ""):
            with self.subTest(value=value), self.assertRaises(InputError):
                read_stock(io.StringIO(SHEADER + f"milk,{value},ml\n"))
        for unit in ("oz", "litre", ""):
            with self.subTest(unit=unit), self.assertRaises(InputError):
                read_stock(io.StringIO(SHEADER + f"milk,1,{unit}\n"))

    def test_strict_header_columns_csv_quoting_and_nonempty_rows(self):
        for reader, header, valid in ((read_plan, PHEADER, "m,c,1\n"),
                                      (read_stock, SHEADER, "x,1,g\n")):
            for text in ("", header, header.replace("quantity", "units") if reader is read_stock else header.replace("units", "quantity"),
                         header + "x,1\n", header + valid.strip() + ",extra\n",
                         header + '"unclosed,1,g\n'):
                with self.subTest(reader=reader.__name__, text=text), self.assertRaises(InputError):
                    reader(io.StringIO(text))

    def test_duplicate_names_trim_and_control_character_rejection(self):
        for reader, data in ((read_plan, PHEADER + "drink,store,1\n drink , store ,2\n"),
                             (read_stock, SHEADER + "milk,1,l\n milk ,2,l\n"),
                             (read_plan, PHEADER + "drink\t,store,1\n"),
                             (read_stock, SHEADER + ",1,l\n")):
            with self.subTest(data=data), self.assertRaises(InputError):
                reader(io.StringIO(data))

    def test_missing_plan_recipe_including_zero_rows(self):
        for units in (0, 1):
            with self.subTest(units=units), self.assertRaises(InputError):
                plan_procurement([ingredient()], [recipe()], [PlanItem("missing", "store", units)])

    def test_unknown_stock_and_different_dimension_including_unused_stock(self):
        catalog = [ingredient(), ingredient("unused")]
        for supplied in ([stock("unknown")], [stock(unit="g")], [stock("unused", unit="each")]):
            with self.subTest(stock=supplied), self.assertRaises(InputError):
                plan_procurement(catalog, [recipe()], [PlanItem("drink", "store", 1)], supplied)

    def test_public_api_validates_catalog_recipe_plan_and_stock_records(self):
        base = ([ingredient()], [recipe()], [PlanItem("drink", "store", 1)], [stock()])
        invalid = [([], base[1], base[2], base[3]), (base[0], [], base[2], base[3]),
                   (base[0], base[1], [], base[3]),
                   ([ingredient(), ingredient(" milk ")], *base[1:]),
                   ([ingredient(), ingredient("unused", rate="0")], *base[1:]),
                   ([ingredient(rate="1.1")], *base[1:]),
                   (base[0], [recipe(), recipe()], *base[2:]),
                   (base[0], [recipe(), recipe(menu="unused", unit="g")], *base[2:]),
                   (base[0], [recipe(quantity="0")], *base[2:]),
                   (*base[:2], [base[2][0], base[2][0]], base[3]),
                   (*base[:2], [PlanItem("drink", "store", Decimal(".5"))], base[3]),
                   (*base[:3], [stock(), stock(" milk ")]),
                   (*base[:3], [stock(quantity="-1")])]
        for case in invalid:
            with self.subTest(case=case), self.assertRaises(InputError):
                plan_procurement(*case)


class ProcurementCliTests(unittest.TestCase):
    def inputs(self, root):
        texts = [IHEADER + "milk,1,l,3000,.8\n", RHEADER + "drink,store,milk,200,ml\n",
                 PHEADER + "drink,store,6\n", SHEADER + "milk,.5,l\n"]
        paths = [root / name for name in ("ingredients.csv", "recipes.csv", "plan.csv", "stock.csv")]
        for path, text in zip(paths, texts):
            path.write_text(text, encoding="utf-8-sig")
        return paths

    def invoke(self, paths, output, with_stock=True):
        args = [str(path) for path in paths[:3]] + ["--output-dir", str(output)]
        if with_stock:
            args += ["--stock", str(paths[3])]
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            status = main(args)
        return status, err.getvalue()

    def test_success_three_reports_inputs_unchanged_and_unrelated_file_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            original = [path.read_bytes() for path in paths]
            out = root / "reports"
            out.mkdir()
            (out / "notes.txt").write_text("keep", encoding="utf-8")
            self.assertEqual(self.invoke(paths, out)[0], 0)
            self.assertEqual({path.name for path in out.iterdir()}, {*OUTPUT_NAMES, "notes.txt"})
            report = json.loads((out / "procurement.json").read_text(encoding="utf-8"))
            self.assertEqual(report["ingredients"][0]["purchase_packs"], 1)
            self.assertEqual((out / "notes.txt").read_text(), "keep")
            self.assertEqual([path.read_bytes() for path in paths], original)
            self.assertEqual(self.invoke(paths, out, with_stock=False)[0], 0)
            self.assertEqual(json.loads((out / "procurement.json").read_text())["ingredients"][0]["purchase_packs"], 2)

    def test_invalid_plan_creates_no_output_and_preserves_existing_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            paths[2].write_text(PHEADER + "drink,store,.5\n", encoding="utf-8")
            out = root / "new"
            self.assertEqual(self.invoke(paths, out)[0], 2)
            self.assertFalse(out.exists())
            out.mkdir()
            for name in OUTPUT_NAMES:
                (out / name).write_text("previous " + name)
            before = {path.name: path.read_bytes() for path in out.iterdir()}
            self.assertEqual(self.invoke(paths, out)[0], 2)
            self.assertEqual({path.name: path.read_bytes() for path in out.iterdir()}, before)

    def test_all_output_names_guard_every_input_hardlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            original = [path.read_bytes() for path in paths]
            for index, source in enumerate(paths):
                for name in OUTPUT_NAMES:
                    with self.subTest(source=source.name, output=name):
                        out = root / f"guard-{index}-{name}"
                        out.mkdir()
                        os.link(source, out / name)
                        status, error = self.invoke(paths, out)
                        self.assertEqual(status, 2)
                        self.assertIn("must not overwrite", error)
                        self.assertEqual(list(out.iterdir()), [out / name])
            self.assertEqual([path.read_bytes() for path in paths], original)

    def test_exact_input_output_path_alias_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            renamed = root / "procurement.json"
            paths[2].rename(renamed)
            paths[2] = renamed
            before = renamed.read_bytes()
            status, error = self.invoke(paths, root)
            self.assertEqual(status, 2)
            self.assertIn("must not overwrite", error)
            self.assertEqual(renamed.read_bytes(), before)

    def test_symbolic_input_output_alias_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            out = root / "guard"
            out.mkdir()
            try:
                (out / "procurement.json").symlink_to(paths[2])
            except OSError as exc:
                self.skipTest(f"Symlink creation unavailable: {exc}")
            before = paths[2].read_bytes()
            self.assertEqual(self.invoke(paths, out)[0], 2)
            self.assertEqual(paths[2].read_bytes(), before)

    def test_existing_outputs_that_alias_each_other_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            out = root / "guard"
            out.mkdir()
            (out / "procurement.json").write_text("previous", encoding="utf-8")
            os.link(out / "procurement.json", out / "procurement.md")
            status, error = self.invoke(paths, out)
            self.assertEqual(status, 2)
            self.assertIn("must not alias", error)
            self.assertEqual((out / "procurement.json").read_text(), "previous")
            self.assertFalse((out / "ingredient-procurement.csv").exists())

    def test_output_nonfile_and_unreadable_csv_leave_existing_files_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            out = root / "guard"
            out.mkdir()
            (out / "procurement.json").write_text("previous")
            (out / "procurement.md").mkdir()
            self.assertEqual(self.invoke(paths, out)[0], 2)
            self.assertEqual((out / "procurement.json").read_text(), "previous")
            paths[2].write_bytes(b"\xff\xff")
            fresh = root / "new"
            self.assertEqual(self.invoke(paths, fresh)[0], 2)
            self.assertFalse(fresh.exists())


if __name__ == "__main__":
    unittest.main()
