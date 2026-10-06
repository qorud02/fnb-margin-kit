"""Totals must sum computed rows without input-order-dependent cancellation."""
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from itertools import permutations
import random
import unittest

from fnb_margin_kit.analysis import ChannelCost, MenuItem, analyze
from fnb_margin_kit.html_report import dashboard_data


def item(name, price='0', *, cost='0', units=1, category='Channel'):
    return MenuItem(name, category, Decimal(price), Decimal(0), Decimal(cost),
                    Decimal(0), Decimal(0), units)


def cancellation_items():
    return [item('Positive', '1e24', units=10**24),
            item('Cent', '.01'),
            item('Negative', cost='1e24', units=10**24)]


class ExactAggregationTests(unittest.TestCase):
    def test_all_row_orders_keep_the_small_residual_and_dashboard_agrees(self):
        for items in permutations(cancellation_items()):
            with self.subTest(order=[row.menu for row in items]):
                report = analyze(list(items))
                expected = sum((Fraction(row['total_contribution']) for row in report['menus']), Fraction())
                self.assertEqual(expected, Fraction(1, 100))
                self.assertEqual(Fraction(report['totals']['contribution']), expected)
                self.assertEqual(Fraction(report['totals']['gross_sales']), Fraction(10**48) + expected)
                self.assertEqual(Fraction(report['totals']['net_sales']), Fraction(10**48) + expected)
                category = dashboard_data(report)['categories'][0]
                self.assertEqual(Fraction(category['contribution_before_additional_cost']), expected)
                self.assertEqual(Fraction(category['contribution_after_additional_cost']), expected)

    def test_channel_and_fixed_cost_scenarios_use_exact_aggregate(self):
        for items in permutations(cancellation_items()):
            with self.subTest(order=[row.menu for row in items]):
                report = analyze(list(items), fixed_cost=Decimal('.03'),
                                 channel_costs=[ChannelCost('Channel', Decimal('.02'))])
                scenario = report['channel_cost_scenario']
                category = scenario['categories'][0]
                self.assertEqual(Fraction(category['contribution_before_additional_cost']), Fraction(1, 100))
                self.assertEqual(Fraction(category['contribution_after_additional_cost']), Fraction(-1, 100))
                self.assertEqual(Fraction(scenario['contribution_after_additional_costs']), Fraction(-1, 100))
                self.assertEqual(Fraction(report['fixed_cost_scenario']['contribution_after_specified_fixed_cost']), Fraction(-4, 100))
                self.assertEqual(dashboard_data(report)['categories'][0]['contribution_after_additional_cost'], category['contribution_after_additional_cost'])

    def test_tiny_channel_cost_is_not_rounded_away_from_large_contribution(self):
        report = analyze([item('Positive', '1e24', units=10**24)],
                         fixed_cost=Decimal('.000000000001'),
                         channel_costs=[ChannelCost('Channel', Decimal('.000000000001'))])
        expected = Fraction(10**48) - Fraction(1, 10**12)
        scenario = report['channel_cost_scenario']
        self.assertEqual(Fraction(scenario['contribution_after_additional_costs']), expected)
        self.assertEqual(Fraction(scenario['categories'][0]['contribution_after_additional_cost']), expected)
        self.assertEqual(Fraction(report['fixed_cost_scenario']['contribution_after_specified_fixed_cost']), expected - Fraction(1, 10**12))

    def test_category_split_and_zero_cost_keep_global_sum(self):
        rows = [replace(row, category=('Small' if row.menu == 'Cent' else 'Large'))
                for row in cancellation_items()]
        report = analyze(rows, channel_costs=[ChannelCost('Large', Decimal(0))])
        categories = report['channel_cost_scenario']['categories']
        expected = sum((Fraction(row['contribution_before_additional_cost']) for row in categories), Fraction())
        self.assertEqual(expected, Fraction(1, 100))
        self.assertEqual(Fraction(report['totals']['contribution']), expected)

    def test_seeded_reordering_matches_fraction_sum_of_reported_rows(self):
        rng = random.Random(20261005)
        rows = cancellation_items() + [
            item('Menu' + str(i), str(rng.randrange(1, 1000) / 100),
                 cost=str(rng.randrange(1, 1000) / 100),
                 units=rng.choice((0, 1, 17, 10**12, 10**24)))
            for i in range(25)
        ]
        for _ in range(10):
            rng.shuffle(rows)
            report = analyze(rows)
            expected = sum((Fraction(row['total_contribution']) for row in report['menus']), Fraction())
            self.assertEqual(Fraction(report['totals']['contribution']), expected)


if __name__ == '__main__':
    unittest.main()
