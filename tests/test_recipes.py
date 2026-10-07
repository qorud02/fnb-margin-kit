"""Recipe purchase/yield costing, exact rounding and protected CSV exports."""

import csv
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal, localcontext
from fractions import Fraction
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from markdown_it import MarkdownIt

from fnb_margin_kit.analysis import InputError, MenuItem, analyze, load_menu
from fnb_margin_kit.recipe_cli import main
from fnb_margin_kit.recipes import (
    Ingredient, RecipeLine, cost_recipes, costed_menu_csv, export_cost,
    read_ingredients, read_recipes, recipe_markdown,
)

IHEADER = "ingredient,purchase_quantity,purchase_unit,purchase_price,yield_rate\n"
RHEADER = "menu,category,ingredient,quantity,unit\n"
MHEADER = "menu,category,price_gross,vat_rate,ingredient_cost,packaging_cost,platform_fee_rate,units\n"
IDATA = IHEADER + "coffee,1,kg,24000,1\nmilk,1,l,3000,0.95\n"
RDATA = RHEADER + "latte,store,coffee,18,g\nlatte,store,milk,180,ml\n"
MDATA = MHEADER + "latte,store,5500,0.1,999,100,0.03,100\n"


def ingredient(name="item", quantity="1", unit="kg", price="100", rate="1"):
    return Ingredient(name, Decimal(quantity), unit, Decimal(price), Decimal(rate))


def line(menu="food", category="store", name="item", quantity="10", unit="g"):
    return RecipeLine(menu, category, name, Decimal(quantity), unit)


def fraction(record):
    return Fraction(int(record["numerator"]), int(record["denominator"]))


class RecipeArithmeticTests(unittest.TestCase):
    def test_mass_volume_count_conversion_and_yield(self):
        items = [ingredient("coffee", "1", "KG", "24000"),
                 ingredient("milk", "1", "L", "3000", ".95"),
                 ingredient("piece", "12", "EaCh", "18000")]
        recipes = [line(name="coffee", quantity=".018", unit="kg"),
                   line(name="milk", quantity="180", unit="ml"),
                   line(menu="cake", name="piece", quantity="1", unit="each")]
        report = cost_recipes(items, recipes)
        self.assertEqual(fraction(report["menus"][0]["ingredient_cost"]), Fraction(19008, 19))
        self.assertEqual(report["menus"][0]["export_ingredient_cost"], "1000.421052631579")
        self.assertEqual(fraction(report["menus"][1]["ingredient_cost"]), 1500)
        milk = report["recipe_lines"][1]
        self.assertEqual(fraction(milk["purchase_quantity_required_base"]), Fraction(3600, 19))
        self.assertEqual(fraction(milk["purchase_quantity_required_in_purchase_unit"]), Fraction(18, 95))
        self.assertEqual(milk["purchase_quantity"], "1")
        self.assertEqual(milk["yield_rate"], "0.95")

    def test_exact_sum_preserves_small_terms_and_recipe_order(self):
        items = [ingredient("large", "1", "each", "1e24"),
                 ingredient("tiny", "1", "each", "1e-12")]
        rows = [line(name="large", quantity="1", unit="each"),
                line(name="tiny", quantity="1", unit="each")]
        a = cost_recipes(items, rows)["menus"][0]
        b = cost_recipes(items, rows[::-1])["menus"][0]
        self.assertEqual(fraction(a["ingredient_cost"]), Fraction(10**36 + 1, 10**12))
        self.assertEqual(a, b)
        self.assertEqual(a["export_decimal_places"], 3)
        self.assertEqual(a["export_ingredient_cost"], str(10**24))

    def test_zero_price_is_valid_and_tiny_positive_cost_keeps_exact_value(self):
        report = cost_recipes([ingredient(price="0")], [line()])
        self.assertEqual(report["menus"][0]["export_ingredient_cost"], "0")
        tiny = cost_recipes([ingredient(price="1e-12", quantity="1e24")], [line(quantity="1e-12")])
        row = tiny["menus"][0]
        self.assertEqual(fraction(row["ingredient_cost"]), Fraction(1, 10**51))
        self.assertEqual(row["export_ingredient_cost"], "0")
        self.assertIn("round to zero", tiny["basis"]["export"])

    def test_raw_fraction_single_rounding_half_up_and_below_tie(self):
        self.assertEqual(export_cost(Fraction(1, 2 * 10**12))[0], "0.000000000001")
        below = Fraction(5 * 10**70 - 1, 10**83)
        self.assertEqual(export_cost(below)[0], "0")
        self.assertEqual(export_cost(Fraction(10**25 - 1))[0], str(10**25 - 1))

    def test_rounding_carry_above_numeric_bound_rejects(self):
        with self.assertRaises(InputError):
            export_cost(Fraction(10**29 - 1, 10000))
        with self.assertRaises(InputError):
            cost_recipes([ingredient("item", "1e-12", "g", "1e24")], [line(quantity="1")])

    def test_low_decimal_context_does_not_change_exact_values_or_exports(self):
        ingredients, recipes = read_ingredients(io.StringIO(IDATA)), read_recipes(io.StringIO(RDATA))
        expected = cost_recipes(ingredients, recipes)
        with localcontext() as ctx:
            ctx.prec = 3
            actual = cost_recipes(ingredients, recipes)
        self.assertEqual(actual, expected)

    def test_unused_catalog_and_case_sensitive_names(self):
        report = cost_recipes([ingredient("Item"), ingredient("item", price="50"), ingredient("unused")],
                              [line(name="Item"), line(name="item")])
        self.assertEqual(fraction(report["menus"][0]["ingredient_cost"]), Fraction(3, 2))
        self.assertEqual(len(report["ingredient_catalog"]), 3)

    def test_names_trim_units_casefold_and_fraction_records(self):
        report = cost_recipes([ingredient(" item ", unit=" KG ")], [line(name=" item ", menu=" food ", unit=" G ")])
        row = report["recipe_lines"][0]
        self.assertEqual((row["menu"], row["ingredient"], row["unit"]), ("food", "item", "g"))
        self.assertEqual(row["line_cost"], {"numerator": "1", "denominator": "1", "decimal": "1"})


class RecipeInputTests(unittest.TestCase):
    def test_bom_reordered_columns_korean_and_csv_quoted_names(self):
        ingredients = read_ingredients(io.StringIO('\ufeffpurchase_unit,yield_rate,purchase_price,ingredient,purchase_quantity\nkg,.8,5000,"바나나, 재료",1\n'))
        recipes = read_recipes(io.StringIO('\ufeffunit,quantity,ingredient,category,menu\ng,120,"바나나, 재료",음료,바나나 음료\n'))
        result = cost_recipes(ingredients, recipes)
        self.assertEqual(fraction(result["menus"][0]["ingredient_cost"]), 750)
        self.assertEqual(result["recipe_lines"][0]["ingredient"], "바나나, 재료")

    def test_invalid_header_row_shape_and_quotes(self):
        for read, header, valid in [(read_ingredients, IHEADER, "x,1,kg,100,1\n"),
                                    (read_recipes, RHEADER, "x,c,x,1,g\n")]:
            for text in ("", header, header.replace("ingredient", "unknown"),
                         header + "x,1\n", header + valid.strip() + ",extra\n",
                         header + '"unclosed,1,kg,100,1\n'):
                with self.subTest(read=read.__name__, text=text), self.assertRaises(InputError):
                    read(io.StringIO(text))

    def test_quantity_price_and_yield_validation(self):
        for field, invalid in (("purchase_quantity", ["0", "-1", "NaN", "1e25", "1e-13"]),
                               ("purchase_price", ["-1", "Infinity", "", "1e25"]),
                               ("yield_rate", ["0", "-1", "1.1", "NaN", "1e-13"])):
            for value in invalid:
                row = dict(ingredient="x", purchase_quantity="1", purchase_unit="kg", purchase_price="100", yield_rate="1")
                row[field] = value
                data = IHEADER + ",".join(row[key] for key in IHEADER.strip().split(",")) + "\n"
                with self.subTest(field=field, value=value), self.assertRaises(InputError):
                    read_ingredients(io.StringIO(data))
        for quantity in ("0", "-1", "NaN", "Infinity", "1e25", "1e-13", ""):
            with self.subTest(quantity=quantity), self.assertRaises(InputError):
                read_recipes(io.StringIO(RHEADER + f"m,c,x,{quantity},g\n"))

    def test_duplicate_and_control_character_names(self):
        for data, read in [(IHEADER + "x,1,kg,100,1\n x ,2,g,1,1\n", read_ingredients),
                           (RHEADER + "m,c,x,1,g\n m , c , x ,2,g\n", read_recipes),
                           (IHEADER + "x\t,1,kg,100,1\n", read_ingredients),
                           (RHEADER + "m,c,,1,g\n", read_recipes)]:
            with self.subTest(data=data), self.assertRaises(InputError):
                read(io.StringIO(data))

    def test_missing_ingredient_and_cross_dimension_conversion(self):
        for recipe in [line(name="unknown"), line(unit="ml"), line(unit="each")]:
            with self.subTest(recipe=recipe), self.assertRaises(InputError):
                cost_recipes([ingredient()], [recipe])
        for unit in ("oz", "piece", "", "litre"):
            with self.subTest(unit=unit), self.assertRaises(InputError):
                cost_recipes([ingredient(unit=unit)], [line()])

    def test_public_api_validates_all_records_including_unused_catalog(self):
        cases = [([], [line()]), ([ingredient()], []),
                 ([ingredient(), ingredient(" item ")], [line()]),
                 ([ingredient()], [line(), line()]),
                 ([ingredient(), ingredient("unused", rate="0")], [line()]),
                 ([ingredient(rate="1.2")], [line()]),
                 ([ingredient()], [line(quantity="0")])]
        for ingredients, recipes in cases:
            with self.subTest(ingredients=ingredients, recipes=recipes), self.assertRaises(InputError):
                cost_recipes(ingredients, recipes)

    def test_optional_menu_schema_and_exact_identity_set(self):
        base = MenuItem("food", "store", Decimal(100), Decimal(0), Decimal(10), Decimal(2), Decimal(0), 1)
        for menus in ([], [MenuItem("other", *list(base.__dict__.values())[1:])],
                      [base, base], [MenuItem("food", "store", Decimal(-1), Decimal(0), Decimal(10), Decimal(2), Decimal(0), 1)]):
            with self.subTest(menus=menus), self.assertRaises(InputError):
                cost_recipes([ingredient()], [line()], menus)

    def test_optional_menu_preserves_order_and_all_other_normalized_values(self):
        menus = [MenuItem(" b ", " c ", Decimal("1e3"), Decimal(".1"), Decimal("9"), Decimal(".2"), Decimal(".03"), 2),
                 MenuItem("a", "c", Decimal("2e3"), Decimal(".1"), Decimal("8"), Decimal(".3"), Decimal(".04"), 0)]
        report = cost_recipes([ingredient()], [line(menu="a", category="c"), line(menu="b", category="c")], menus)
        rows = list(csv.DictReader(io.StringIO(costed_menu_csv(report))))
        self.assertEqual([row["menu"] for row in rows], ["b", "a"])
        self.assertEqual(rows[0], {"menu": "b", "category": "c", "price_gross": "1000", "vat_rate": "0.1", "ingredient_cost": "1", "packaging_cost": "0.2", "platform_fee_rate": "0.03", "units": "2"})


class RecipeCliTests(unittest.TestCase):
    def invoke(self, args):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            status = main(args)
        return status, err.getvalue()

    def setup_inputs(self, root):
        paths = [root / "ingredients.csv", root / "recipes.csv", root / "menu.csv"]
        for path, text in zip(paths, (IDATA, RDATA, MDATA)):
            path.write_text(text, encoding="utf-8-sig")
        return paths

    def test_actual_exports_are_loadable_by_existing_margin_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.setup_inputs(root)
            before = [path.read_bytes() for path in paths]
            out = root / "output"
            status, error = self.invoke([str(paths[0]), str(paths[1]), "--menu", str(paths[2]), "--output-dir", str(out)])
            self.assertEqual((status, error), (0, ""))
            self.assertEqual([path.read_bytes() for path in paths], before)
            self.assertEqual({path.name for path in out.iterdir()}, {"recipe-costs.json", "recipe-costs.md", "menu-ingredient-costs.csv", "costed-menu.csv"})
            loaded = load_menu(out / "costed-menu.csv")
            self.assertEqual(loaded[0].ingredient_cost, Decimal("1000.421052631579"))
            self.assertEqual(loaded[0].units, 100)
            report = analyze(loaded)
            self.assertEqual(Decimal(report["menus"][0]["contribution_per_unit"]), Decimal("3734.578947368421"))

    def test_menu_omitted_writes_only_three_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.setup_inputs(root)
            out = root / "output"
            self.assertEqual(self.invoke([str(paths[0]), str(paths[1]), "--output-dir", str(out)])[0], 0)
            self.assertEqual(len(list(out.iterdir())), 3)
            self.assertNotIn("costed_menu", json.loads((out / "recipe-costs.json").read_text(encoding="utf-8")))

    def test_invalid_inputs_and_unexportable_costs_write_no_partial_output(self):
        for ingredient_data, recipe_data, menu_data in (
            (IDATA.replace("0.95", "0"), RDATA, MDATA),
            (IDATA, RDATA.replace("milk,180,ml", "milk,180,g"), MDATA),
            (IDATA, RDATA, MDATA.replace("latte", "other")),
            (IHEADER + "coffee,1e-12,g,1e24,1\n", RHEADER + "latte,store,coffee,18,g\n", MDATA),
        ):
            with self.subTest(data=ingredient_data), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = self.setup_inputs(root)
                for path, data in zip(paths, (ingredient_data, recipe_data, menu_data)):
                    path.write_text(data, encoding="utf-8")
                out = root / "output"
                self.assertEqual(self.invoke([str(paths[0]), str(paths[1]), "--menu", str(paths[2]), "--output-dir", str(out)])[0], 2)
                self.assertFalse(out.exists())

    def test_all_three_inputs_against_all_four_outputs_direct_hardlink_symlink(self):
        names = ("recipe-costs.json", "recipe-costs.md", "menu-ingredient-costs.csv", "costed-menu.csv")
        for source_index in range(3):
            for name in names:
                for kind in ("direct", "hardlink", "symlink"):
                    with self.subTest(input=source_index, output=name, alias=kind), tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        paths = self.setup_inputs(root)
                        out = root / "output"
                        out.mkdir()
                        target = out / name
                        if kind == "direct":
                            paths[source_index].rename(target)
                            paths[source_index] = target
                        elif kind == "hardlink":
                            os.link(paths[source_index], target)
                        else:
                            target.symlink_to(paths[source_index])
                        before = [path.read_bytes() for path in paths]
                        status, error = self.invoke([str(paths[0]), str(paths[1]), "--menu", str(paths[2]), "--output-dir", str(out)])
                        self.assertEqual(status, 2)
                        self.assertIn("must not overwrite", error)
                        self.assertEqual([path.read_bytes() for path in paths], before)
                        self.assertEqual([path.name for path in out.iterdir()], [name])

    def test_resolver_runtime_error_is_actionable_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.setup_inputs(root)
            out = root / "output"
            with patch("pathlib.Path.resolve", side_effect=RuntimeError("loop")):
                status, error = self.invoke([str(paths[0]), str(paths[1]), "--output-dir", str(out)])
            self.assertEqual(status, 2)
            self.assertIn("Unable to resolve", error)
            self.assertFalse(out.exists())

    def test_actual_markdown_renderer_keeps_names_literal(self):
        name = "![milk](https://example.test/p.png) **bold** _em_ ~~old~~ `code` | \\"
        report = cost_recipes([ingredient(name)], [line(menu=name, category=name, name=name)])
        rendered = MarkdownIt("commonmark").enable(["table", "strikethrough"]).render(recipe_markdown(report))
        class Cells(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.cells, self.cell, self.nested = [], None, []
            def handle_starttag(self, tag, attrs):
                if self.cell is not None:
                    self.nested.append(tag)
                if tag == "td":
                    self.cell = []
            def handle_data(self, data):
                if self.cell is not None:
                    self.cell.append(data)
            def handle_endtag(self, tag):
                if tag == "td" and self.cell is not None:
                    self.cells.append("".join(self.cell))
                    self.cell = None
        parser = Cells()
        parser.feed(rendered)
        self.assertEqual(parser.nested, [])
        self.assertEqual([parser.cells[i] for i in (0, 1, 5, 6, 7)], [name] * 5)


if __name__ == "__main__":
    unittest.main()
