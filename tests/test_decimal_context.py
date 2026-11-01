"""The caller's Decimal settings must not change calculations or reports."""

import unittest
from dataclasses import replace
from decimal import (
    ROUND_DOWN,
    ROUND_UP,
    Decimal,
    DefaultContext,
    Inexact,
    Rounded,
    localcontext,
)

from fnb_margin_kit.analysis import ChannelCost, MenuItem, analyze
from fnb_margin_kit.cli import markdown, money
from fnb_margin_kit.html_report import dashboard_data, render_html
from fnb_margin_kit.recipes import Ingredient, RecipeLine, cost_recipes
from fnb_margin_kit.scenarios import analyze_comparison, comparison_markdown


def menu():
    return MenuItem("Tea", "Store", Decimal("1000"), Decimal(".1"),
                    Decimal(".01"), Decimal(".02"), Decimal(".03"), 17)


class DecimalContextTests(unittest.TestCase):
    def test_mutable_default_context_does_not_change_results(self):
        items = [menu()]
        ingredients = [Ingredient("Tea leaves", Decimal("3"), "g", Decimal("1"), Decimal("1"))]
        recipes = [RecipeLine("Tea", "Store", "Tea leaves", Decimal("1"), "g")]

        def outputs():
            report = analyze(items)
            comparison = analyze_comparison(items, [replace(menu(), units=19)])
            return (report, comparison, markdown(report), render_html(report),
                    comparison_markdown(comparison), cost_recipes(ingredients, recipes, items))

        expected = outputs()
        snapshot = DefaultContext.copy()
        try:
            DefaultContext.prec = 3
            DefaultContext.rounding = ROUND_DOWN
            DefaultContext.Emax = 2
            DefaultContext.Emin = -2
            DefaultContext.clamp = 1
            DefaultContext.capitals = 0
            DefaultContext.traps[Inexact] = True
            DefaultContext.traps[Rounded] = True
            self.assertEqual(outputs(), expected)
        finally:
            for field in ("prec", "rounding", "Emax", "Emin", "clamp", "capitals"):
                setattr(DefaultContext, field, getattr(snapshot, field))
            DefaultContext.traps = snapshot.traps
            DefaultContext.flags = snapshot.flags

    def test_analysis_and_comparison_ignore_rounding_traps_and_exponent_limits(self):
        items = [menu()]
        proposed = [replace(menu(), price_gross=Decimal("999"), units=19)]
        costs = [ChannelCost("Store", Decimal(".03"))]
        expected = analyze(items, Decimal(".01"), channel_costs=costs)
        comparison = analyze_comparison(items, proposed)
        for rounding in (ROUND_DOWN, ROUND_UP):
            with self.subTest(rounding=rounding), localcontext() as ctx:
                ctx.prec = 3
                ctx.rounding = rounding
                ctx.Emax = 2
                ctx.Emin = -2
                ctx.traps[Inexact] = True
                ctx.traps[Rounded] = True
                ctx.clear_flags()
                self.assertEqual(analyze(items, Decimal(".01"), channel_costs=costs), expected)
                self.assertEqual(analyze_comparison(items, proposed), comparison)
                self.assertEqual(ctx.prec, 3)
                self.assertEqual(ctx.rounding, rounding)
                self.assertTrue(ctx.traps[Inexact])
                self.assertTrue(ctx.traps[Rounded])
                self.assertFalse(any(ctx.flags.values()))

    def test_report_renderers_ignore_strict_context_and_keep_half_up_money(self):
        report = analyze([menu()])
        comparison = analyze_comparison([menu()], [replace(menu(), units=19)])
        expected = (markdown(report), dashboard_data(report), render_html(report),
                    comparison_markdown(comparison), money("1.005"))
        with localcontext() as ctx:
            ctx.prec = 3
            ctx.rounding = ROUND_DOWN
            ctx.Emax = 2
            ctx.Emin = -2
            ctx.traps[Inexact] = True
            ctx.traps[Rounded] = True
            ctx.clear_flags()
            actual = (markdown(report), dashboard_data(report), render_html(report),
                      comparison_markdown(comparison), money("1.005"))
            self.assertEqual(actual, expected)
            self.assertEqual(actual[-1], "1.01")
            self.assertFalse(any(ctx.flags.values()))

    def test_recipe_decimal_displays_and_optional_menu_ignore_strict_context(self):
        ingredients = [Ingredient("Tea leaves", Decimal("3"), "g", Decimal("1"), Decimal("1"))]
        recipes = [RecipeLine("Tea", "Store", "Tea leaves", Decimal("1"), "g")]
        expected = cost_recipes(ingredients, recipes, [menu()])
        with localcontext() as ctx:
            ctx.prec = 3
            ctx.rounding = ROUND_UP
            ctx.Emax = 2
            ctx.Emin = -2
            ctx.traps[Inexact] = True
            ctx.traps[Rounded] = True
            ctx.clear_flags()
            self.assertEqual(cost_recipes(ingredients, recipes, [menu()]), expected)
            self.assertFalse(any(ctx.flags.values()))


if __name__ == "__main__":
    unittest.main()
