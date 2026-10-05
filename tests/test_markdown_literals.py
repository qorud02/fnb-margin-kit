"""Menu and category strings remain literal in rendered Markdown tables."""
import random
import unittest
from decimal import Decimal
from html.parser import HTMLParser

from markdown_it import MarkdownIt

from fnb_margin_kit.analysis import ChannelCost, MenuItem, analyze
from fnb_margin_kit.cli import markdown


class TableCells(HTMLParser):
    def __init__(self, rendered):
        super().__init__(convert_charrefs=True)
        self.cells, self.current, self.nested_tags = [], None, []
        self.feed(rendered)

    def handle_starttag(self, tag, attrs):
        if self.current is not None:
            self.nested_tags.append(tag)
        if tag == 'td':
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == 'td' and self.current is not None:
            self.cells.append(''.join(self.current))
            self.current = None


def rendered_tables(name, *, channel=False):
    zero = Decimal(0)
    row = MenuItem(name, name, Decimal(10), zero, zero, zero, zero, 1)
    costs = [ChannelCost(name, Decimal(2))] if channel else None
    text = markdown(analyze([row], channel_costs=costs))
    rendered = MarkdownIt('commonmark').enable(['table', 'strikethrough']).render(text)
    return TableCells(rendered)


class MarkdownLiteralTests(unittest.TestCase):
    def test_menu_and_category_formatting_characters_remain_text(self):
        for name in ('**bold** _em_ ~~old~~ `code`', '[Latte](https://example.test)',
                     '![Latte](https://example.test/pixel.png)', 'a | b',
                     r'backslash \\ [brackets] `tick` | pipe',
                     '<script>alert(1)</script> & &amp;', '카페 라테 👋'):
            with self.subTest(name=name):
                table = rendered_tables(name)
                self.assertEqual(len(table.cells), 9)
                self.assertEqual(table.cells[1:3], [name, name])
                self.assertEqual(table.nested_tags, [])

    def test_channel_cost_categories_are_literal_too(self):
        name = '![Delivery](https://example.test/pixel.png) **special** | `code`'
        table = rendered_tables(name, channel=True)
        self.assertEqual(len(table.cells), 14)
        self.assertEqual([table.cells[i] for i in (1, 2, 9)], [name] * 3)
        self.assertEqual(table.nested_tags, [])
        self.assertEqual(table.cells[10:], ['1', '10.00', '2.00', '8.00'])

    def test_seeded_punctuation_round_trips_through_the_renderer(self):
        rng = random.Random(20261005)
        alphabet = 'a한é &;\\`*_[]~|!<>:/#='
        for _ in range(100):
            name = ''.join(rng.choice(alphabet) for _ in range(40)).strip()
            table = rendered_tables(name)
            self.assertEqual(table.cells[1:3], [name, name])
            self.assertEqual(table.nested_tags, [])


if __name__ == '__main__':
    unittest.main()
