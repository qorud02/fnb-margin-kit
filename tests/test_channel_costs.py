"""Period costs must be counted once and preserve the existing sales calculation."""

import errno
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from fnb_margin_kit.analysis import (
    ChannelCost,
    InputError,
    MenuItem,
    analyze,
    load_channel_costs,
    load_menu,
    read_channel_costs,
)
from fnb_margin_kit.cli import main, markdown


ROOT = Path(__file__).resolve().parents[1]
HEADER = "category,additional_variable_cost\n"


def item(menu="Latte", category="Delivery", units=40):
    return MenuItem(
        menu, category, Decimal("5500"), Decimal("0.10"),
        Decimal("1200"), Decimal("300"), Decimal("0.15"), units,
    )


class ChannelCostInputTests(unittest.TestCase):
    def test_bom_reordered_headers_and_korean_category(self):
        costs = read_channel_costs(io.StringIO(
            "\ufeffadditional_variable_cost,category\n60000, 배달 \n"
        ))
        self.assertEqual(costs, [ChannelCost("배달", Decimal("60000"))])
        self.assertEqual(load_channel_costs(ROOT / "examples/channel-costs.csv"), costs)

    def test_invalid_headers_and_row_shapes(self):
        for text in ("", HEADER, "category,cost\nx,1\n",
                     "category,category\nx,x\n", HEADER + "x\n",
                     HEADER + "x,1,extra\n", HEADER + 'x,"1\n'):
            with self.subTest(text=text), self.assertRaises(InputError):
                read_channel_costs(io.StringIO(text))

    def test_duplicate_and_blank_categories(self):
        for text in (HEADER + "x,1\n x ,2\n", HEADER + " ,1\n",
                     HEADER + '"x\ny",1\n'):
            with self.subTest(text=text), self.assertRaises(InputError):
                read_channel_costs(io.StringIO(text))

    def test_invalid_amounts(self):
        for amount in ("", "-1", "NaN", "Infinity", "-Infinity", "1e25",
                       "0.0000000000001", "12345678901234567890123456789"):
            with self.subTest(amount=amount), self.assertRaises(InputError):
                read_channel_costs(io.StringIO(HEADER + f"x,{amount}\n"))


class ChannelCostAnalysisTests(unittest.TestCase):
    def test_independent_synthetic_example(self):
        menus = load_menu(ROOT / "examples/store-versus-delivery.csv")
        baseline = analyze(menus, Decimal("300000"))
        report = analyze(menus, Decimal("300000"), channel_costs=[
            ChannelCost("배달", Decimal("60000"))
        ])
        # Independent gross/net and category arithmetic from the documented inputs.
        self.assertEqual(Decimal(report["totals"]["gross_sales"]), 5500 * 140)
        self.assertEqual(Decimal(report["totals"]["net_sales"]), 5000 * 140)
        store = (5000 - 1200 - 100) * 100
        delivery = (5000 - 1200 - 300 - 825) * 40
        categories = {r["category"]: r for r in report["channel_cost_scenario"]["categories"]}
        self.assertEqual(Decimal(categories["매장"]["contribution_after_additional_cost"]), store)
        self.assertEqual(Decimal(categories["배달"]["contribution_after_additional_cost"]), delivery - 60000)
        self.assertEqual(Decimal(report["channel_cost_scenario"]["contribution_after_additional_costs"]), store + delivery - 60000)
        self.assertEqual(Decimal(report["fixed_cost_scenario"]["contribution_after_specified_fixed_cost"]), store + delivery - 60000 - 300000)
        self.assertEqual(report["menus"], baseline["menus"])
        self.assertEqual(report["totals"], baseline["totals"])
        self.assertIn("60,000.00", markdown(report))
        self.assertIn("117,000.00", markdown(report))

    def test_split_row_invariance_and_cost_once(self):
        costs = [ChannelCost("Delivery", Decimal("60000"))]
        original = analyze([item()], channel_costs=costs)
        split = analyze([item("A", units=15), item("B", units=25)], channel_costs=costs)
        self.assertEqual(original["totals"], split["totals"])
        self.assertEqual(original["channel_cost_scenario"], split["channel_cost_scenario"])
        self.assertEqual(split["channel_cost_scenario"]["total_additional_variable_cost"], "60000")

    def test_zero_sales_and_negative_adjusted_contribution(self):
        report = analyze([item(units=0)], channel_costs=[ChannelCost("Delivery", Decimal("60000"))])
        self.assertEqual(Decimal(report["channel_cost_scenario"]["contribution_after_additional_costs"]), -60000)
        report = analyze([item()], channel_costs=[ChannelCost("Delivery", Decimal("200000"))])
        self.assertEqual(Decimal(report["channel_cost_scenario"]["contribution_after_additional_costs"]), -93000)

    def test_matching_normalization_and_zero_cost(self):
        report = analyze([replace(item(), category=" Delivery "), item("Other", "Store")],
                         channel_costs=[ChannelCost(" Delivery ", Decimal("0"))])
        self.assertEqual([r["category"] for r in report["channel_cost_scenario"]["categories"]], ["Delivery", "Store"])
        self.assertEqual(report["channel_cost_scenario"]["contribution_after_additional_costs"], report["totals"]["contribution"])

    def test_public_api_rejects_invalid_costs(self):
        for costs in ([], [ChannelCost("delivery", Decimal("1"))],
                      [ChannelCost("Missing", Decimal("1"))],
                      [ChannelCost("Delivery", Decimal("1")), ChannelCost(" Delivery ", Decimal("2"))],
                      [ChannelCost(" ", Decimal("1"))], [ChannelCost(None, Decimal("1"))],
                      [ChannelCost("Delivery", Decimal("NaN"))], [ChannelCost("Delivery", Decimal("-1"))],
                      [ChannelCost("Delivery", Decimal("Infinity"))]):
            with self.subTest(costs=costs), self.assertRaises(InputError):
                analyze([item()], channel_costs=costs)

    def test_option_absent_keeps_legacy_structure(self):
        report = analyze([item()], Decimal("300000"))
        self.assertNotIn("channel_cost_scenario", report)
        self.assertEqual(Decimal(report["fixed_cost_scenario"]["contribution_after_specified_fixed_cost"]), -193000)


class ChannelCostCliTests(unittest.TestCase):
    def invoke(self, args):
        stderr = io.StringIO()
        with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
            status = main(args)
        return status, stderr.getvalue()

    def test_cli_preserves_both_inputs_and_writes_scenario(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            menu = root / "menu.csv"
            costs = root / "costs.csv"
            menu.write_bytes((ROOT / "examples/store-versus-delivery.csv").read_bytes())
            costs.write_bytes((ROOT / "examples/channel-costs.csv").read_bytes())
            before = (menu.read_bytes(), costs.read_bytes())
            output = root / "output"
            status, error = self.invoke([str(menu), "--channel-costs", str(costs), "--fixed-cost", "300000", "--output-dir", str(output)])
            self.assertEqual((status, error), (0, ""))
            self.assertEqual((menu.read_bytes(), costs.read_bytes()), before)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(Decimal(report["channel_cost_scenario"]["contribution_after_additional_costs"]), 417000)
            markdown = (output / "report.md").read_text(encoding="utf-8")
            self.assertIn("Contribution before additional channel and fixed costs: **477,000.00**", markdown)
            self.assertIn("Contribution after additional costs: **417,000.00**", markdown)

    def test_invalid_costs_create_no_reports(self):
        for text in (HEADER + "Unknown,1\n", HEADER + "배달,NaN\n", HEADER + "배달,\n"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                costs = root / "costs.csv"
                costs.write_text(text, encoding="utf-8")
                before = costs.read_bytes()
                output = root / "output"
                status, error = self.invoke([str(ROOT / "examples/store-versus-delivery.csv"), "--channel-costs", str(costs), "--output-dir", str(output)])
                self.assertEqual(status, 2)
                self.assertNotIn("Traceback", error)
                self.assertFalse(output.exists())
                self.assertEqual(costs.read_bytes(), before)

    def check_aliases(self, alias):
        for filename in ("report.json", "report.md"):
                with self.subTest(filename=filename), tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    output = root / "output"
                    output.mkdir()
                    target = output / filename
                    costs = target if alias == "direct" else root / "costs.csv"
                    costs.write_text(HEADER + "배달,60000\n", encoding="utf-8")
                    before = costs.read_bytes()
                    if alias == "hardlink":
                        os.link(costs, target)
                    if alias == "symlink":
                        try:
                            target.symlink_to(costs)
                        except NotImplementedError:
                            self.skipTest("Symbolic links are unsupported")
                        except OSError as exc:
                            if getattr(exc, "winerror", None) == 1314 or exc.errno in (errno.EPERM, errno.EACCES):
                                self.skipTest("Symbolic link permission is unavailable")
                            raise
                    status, error = self.invoke([str(ROOT / "examples/store-versus-delivery.csv"), "--channel-costs", str(costs), "--output-dir", str(output)])
                    self.assertEqual(status, 2)
                    self.assertIn("overwrite", error)
                    self.assertEqual(costs.read_bytes(), before)
                    other = "report.md" if filename == "report.json" else "report.json"
                    self.assertFalse((output / other).exists())

    def test_channel_csv_direct_output_aliases_are_rejected(self):
        self.check_aliases("direct")

    def test_channel_csv_hardlink_output_aliases_are_rejected(self):
        self.check_aliases("hardlink")

    def test_channel_csv_symlink_output_aliases_are_rejected(self):
        self.check_aliases("symlink")


if __name__ == "__main__":
    unittest.main()
