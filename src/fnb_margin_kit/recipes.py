"""Cost edible recipe quantities from purchase units and ingredient yields."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction
from html import escape
from pathlib import Path
from typing import TextIO

from .analysis import FIELDS, InputError, MenuItem, _text, analyze, number

INGREDIENT_FIELDS = (
    "ingredient", "purchase_quantity", "purchase_unit", "purchase_price", "yield_rate"
)
RECIPE_FIELDS = ("menu", "category", "ingredient", "quantity", "unit")
UNITS = {
    "g": ("g", 1), "kg": ("g", 1000),
    "ml": ("ml", 1), "l": ("ml", 1000), "each": ("each", 1),
}


@dataclass(frozen=True)
class Ingredient:
    ingredient: str
    purchase_quantity: Decimal
    purchase_unit: str
    purchase_price: Decimal
    yield_rate: Decimal


@dataclass(frozen=True)
class RecipeLine:
    menu: str
    category: str
    ingredient: str
    quantity: Decimal
    unit: str


def _unit(value: str, field: str, row: int) -> str:
    value = _text(value, field, row).casefold()
    if value not in UNITS:
        raise InputError(f"row {row}, {field}: expected g, kg, ml, l, or each")
    return value


def _positive(value: str, field: str, row: int) -> Decimal:
    result = number(value, field, row)
    if result <= 0:
        raise InputError(f"row {row}, {field}: expected a positive number")
    return result


def _rows(stream: TextIO, fields: tuple[str, ...], label: str):
    reader = csv.DictReader(stream, strict=True)
    try:
        headers = reader.fieldnames
        if headers:
            headers[0] = headers[0].removeprefix("\ufeff")
        if headers is None or len(headers) != len(fields) or set(headers) != set(fields):
            raise InputError(f"{label} CSV header must contain each of: " + ",".join(fields))
        found = False
        for row in reader:
            found = True
            if None in row or any(value is None for value in row.values()):
                raise InputError(f"row {reader.line_num}: expected exactly {len(fields)} columns")
            yield reader.line_num, row
        if not found:
            raise InputError(f"{label} CSV must contain at least one row")
    except csv.Error as exc:
        raise InputError(f"Invalid {label} CSV: {exc}") from exc


def read_ingredients(stream: TextIO) -> list[Ingredient]:
    """Read a BOM-aware ingredient catalog with strict purchase/yield validation."""
    result, seen = [], set()
    for line, row in _rows(stream, INGREDIENT_FIELDS, "Ingredient"):
        name = _text(row["ingredient"], "ingredient", line)
        if name in seen:
            raise InputError(f"row {line}: duplicate ingredient: {name}")
        seen.add(name)
        yield_rate = _positive(row["yield_rate"], "yield_rate", line)
        if yield_rate > 1:
            raise InputError(f"row {line}, yield_rate: expected a fraction greater than 0 and at most 1")
        result.append(Ingredient(
            name, _positive(row["purchase_quantity"], "purchase_quantity", line),
            _unit(row["purchase_unit"], "purchase_unit", line),
            number(row["purchase_price"], "purchase_price", line), yield_rate,
        ))
    return result


def read_recipes(stream: TextIO) -> list[RecipeLine]:
    """Read edible quantities used by one sold unit of each menu/category."""
    result, seen = [], set()
    for line, row in _rows(stream, RECIPE_FIELDS, "Recipe"):
        names = [_text(row[field], field, line) for field in RECIPE_FIELDS[:3]]
        key = tuple(names)
        if key in seen:
            raise InputError(f"row {line}: duplicate menu/category/ingredient: {' / '.join(key)}")
        seen.add(key)
        result.append(RecipeLine(
            *names, _positive(row["quantity"], "quantity", line),
            _unit(row["unit"], "unit", line),
        ))
    return result


def load_ingredients(path: str | Path) -> list[Ingredient]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return read_ingredients(stream)


def load_recipes(path: str | Path) -> list[RecipeLine]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return read_recipes(stream)


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def exact_value(value: Fraction) -> dict[str, str]:
    """Keep the exact rational beside a context-independent 50-digit display."""
    with localcontext() as ctx:
        ctx.prec = 50
        ctx.rounding = ROUND_HALF_UP
        display = format(Decimal(value.numerator) / Decimal(value.denominator), "f")
    return {"numerator": str(value.numerator), "denominator": str(value.denominator),
            "decimal": display}


def export_cost(value: Fraction) -> tuple[str, int]:
    """Round raw nonnegative fractions once to the existing menu CSV bounds."""
    if value < 0 or value >= 10**25:
        raise InputError("Computed ingredient cost must be nonnegative and below 1e25")
    integer_digits = len(str(value.numerator // value.denominator))
    places = min(12, 28 - integer_digits)
    scale = 10**places
    quotient, remainder = divmod(value.numerator * scale, value.denominator)
    if 2 * remainder >= value.denominator:
        quotient += 1
    if places:
        whole, fraction = divmod(quotient, scale)
        text = (str(whole) + "." + str(fraction).zfill(places)).rstrip("0").rstrip(".")
    else:
        text = str(quotient)
    number(text, "computed ingredient_cost")
    return text, places


def cost_recipes(
    ingredients: list[Ingredient], recipes: list[RecipeLine],
    menu_items: list[MenuItem] | None = None,
) -> dict:
    """Calculate exact recipe costs and optionally replace an explicit menu cost."""
    if not ingredients or not recipes:
        raise InputError("At least one ingredient and one recipe line are required")
    catalog, catalog_rows = {}, []
    for row, item in enumerate(ingredients, 1):
        name = _text(item.ingredient, "ingredient", row)
        if name in catalog:
            raise InputError(f"duplicate ingredient: {name}")
        quantity = _positive(str(item.purchase_quantity), "purchase_quantity", row)
        unit = _unit(item.purchase_unit, "purchase_unit", row)
        price = number(str(item.purchase_price), "purchase_price", row)
        rate = _positive(str(item.yield_rate), "yield_rate", row)
        if rate > 1:
            raise InputError("yield_rate must be greater than 0 and at most 1")
        normalized = Ingredient(name, quantity, unit, price, rate)
        catalog[name] = normalized
        catalog_rows.append({
            "ingredient": name, "purchase_quantity": _decimal(quantity),
            "purchase_unit": unit, "purchase_price": _decimal(price),
            "yield_rate": _decimal(rate), "base_unit": UNITS[unit][0],
            "usable_quantity_base": exact_value(Fraction(quantity) * UNITS[unit][1] * Fraction(rate)),
        })
    lines, totals, seen = [], {}, set()
    for row, item in enumerate(recipes, 1):
        menu = _text(item.menu, "menu", row)
        category = _text(item.category, "category", row)
        name = _text(item.ingredient, "ingredient", row)
        key = (menu, category, name)
        if key in seen:
            raise InputError(f"duplicate menu/category/ingredient: {' / '.join(key)}")
        seen.add(key)
        if name not in catalog:
            raise InputError(f"Ingredient not found in catalog: {name}")
        quantity = _positive(str(item.quantity), "quantity", row)
        unit = _unit(item.unit, "unit", row)
        ingredient = catalog[name]
        base_unit, factor = UNITS[unit]
        purchase_base_unit, purchase_factor = UNITS[ingredient.purchase_unit]
        if base_unit != purchase_base_unit:
            raise InputError(f"Incompatible units for ingredient {name}: {unit} / {ingredient.purchase_unit}")
        edible = Fraction(quantity) * factor
        purchase_base = Fraction(ingredient.purchase_quantity) * purchase_factor
        purchase_required = edible / Fraction(ingredient.yield_rate)
        cost = Fraction(ingredient.purchase_price) * purchase_required / purchase_base
        totals[(menu, category)] = totals.get((menu, category), Fraction(0)) + cost
        lines.append({
            "menu": menu, "category": category, "ingredient": name,
            "quantity": _decimal(quantity), "unit": unit,
            "purchase_quantity": _decimal(ingredient.purchase_quantity),
            "purchase_unit": ingredient.purchase_unit,
            "purchase_price": _decimal(ingredient.purchase_price),
            "yield_rate": _decimal(ingredient.yield_rate), "base_unit": base_unit,
            "recipe_quantity_base": exact_value(edible),
            "purchase_quantity_required_base": exact_value(purchase_required),
            "purchase_quantity_required_in_purchase_unit": exact_value(purchase_required / purchase_factor),
            "line_cost": exact_value(cost),
        })
    menus, exported = [], {}
    for (menu, category), cost in totals.items():
        text, places = export_cost(cost)
        exported[(menu, category)] = text
        menus.append({
            "menu": menu, "category": category, "ingredient_cost": exact_value(cost),
            "export_ingredient_cost": text, "export_decimal_places": places,
            "ingredient_count": sum(line["menu"] == menu and line["category"] == category for line in lines),
        })
    report = {
        "schema_version": "1.0",
        "basis": {
            "recipe_quantity": "Edible quantity used by one sold menu unit; yield is the edible share of the purchased quantity.",
            "cost": "purchase_price * normalized_recipe_quantity / (normalized_purchase_quantity * yield_rate)",
            "units": "kg = 1000 g; l = 1000 ml; each is a count. Mass, volume and count are separate dimensions.",
            "money": "Purchase prices and exported ingredient costs use the same supplied monetary and tax basis; no VAT conversion is performed.",
            "exact_amounts": "Line and menu costs are exact rational values, summed before rounding.",
            "display": "Decimal displays use 50 significant digits with half-up rounding; numerator/denominator retain the exact value.",
            "export": "Round the raw menu fraction once, half-up, to at most 12 decimal places and 28 digits. Tiny positive costs can round to zero in CSV; the exact cost remains in this report.",
        },
        "ingredient_catalog": catalog_rows, "recipe_lines": lines, "menus": menus,
    }
    if menu_items is not None:
        analyze(menu_items)  # Existing public API enforces every menu-schema constraint.
        normalized_rows = []
        keys = set()
        for item in menu_items:
            menu, category = _text(item.menu, "menu", 0), _text(item.category, "category", 0)
            key = (menu, category)
            keys.add(key)
            normalized_rows.append({
                "menu": menu, "category": category,
                **{field: _decimal(number(str(getattr(item, field)), field)) for field in FIELDS[2:]},
            })
        if keys != set(totals):
            missing = sorted(keys - set(totals))
            extra = sorted(set(totals) - keys)
            raise InputError(f"Menu and recipe menu/category identities must match; missing recipes: {missing}; unexpected recipes: {extra}")
        for row in normalized_rows:
            row["ingredient_cost"] = exported[(row["menu"], row["category"])]
            row["units"] = str(int(Decimal(row["units"])))
        report["costed_menu"] = normalized_rows
    return report


def _csv_text(fields: tuple[str, ...], rows: list[dict]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def ingredient_costs_csv(report: dict) -> str:
    return _csv_text(("menu", "category", "ingredient_cost"), [
        {"menu": row["menu"], "category": row["category"],
         "ingredient_cost": row["export_ingredient_cost"]} for row in report["menus"]
    ])


def costed_menu_csv(report: dict) -> str:
    return _csv_text(FIELDS, report["costed_menu"])


def recipe_markdown(report: dict) -> str:
    def cell(value: str) -> str:
        value = escape(value).replace("\\", "\\\\")
        for char in "`*_[]~":
            value = value.replace(char, "\\" + char)
        return value.replace("|", "\\|")

    lines = ["# Recipe ingredient costs", "",
             "| Menu | Category | Ingredients | Exact-cost decimal display | Exported ingredient cost/unit |",
             "| --- | --- | ---: | ---: | ---: |"]
    for row in report["menus"]:
        lines.append(f"| {cell(row['menu'])} | {cell(row['category'])} | {row['ingredient_count']} | {row['ingredient_cost']['decimal']} | {row['export_ingredient_cost']} |")
    lines += ["", "## Ingredient quantities and yields", "",
              "| Menu | Category | Ingredient | Edible quantity | Purchased quantity / price | Yield | Purchase quantity required | Line cost |",
              "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in report["recipe_lines"]:
        lines.append(f"| {cell(row['menu'])} | {cell(row['category'])} | {cell(row['ingredient'])} | {row['quantity']} {row['unit']} | {row['purchase_quantity']} {row['purchase_unit']} / {row['purchase_price']} | {row['yield_rate']} | {row['purchase_quantity_required_in_purchase_unit']['decimal']} {row['purchase_unit']} | {row['line_cost']['decimal']} |")
    lines += ["", *report["basis"].values()]
    return "\n".join(lines) + "\n"
