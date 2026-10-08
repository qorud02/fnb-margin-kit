"""Plan ingredient purchases from menu quantities and raw ingredient stock."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from html import escape
from pathlib import Path
from typing import TextIO

from .analysis import InputError, _text, number
from .recipes import (
    UNITS, Ingredient, RecipeLine, _positive, _rows, _unit, exact_value,
)

PLAN_FIELDS = ("menu", "category", "units")
STOCK_FIELDS = ("ingredient", "quantity", "unit")
AMOUNT_FIELDS = (
    "purchase_quantity_base", "edible_required_base", "gross_required_base",
    "stock_base", "shortage_base", "purchased_quantity_base",
    "remaining_stock_base", "purchase_spend",
)
CSV_FIELDS = (
    "ingredient", "base_unit", "purchase_quantity", "purchase_unit",
    "purchase_price", "yield_rate", "purchase_packs",
    *(field + suffix for field in AMOUNT_FIELDS
      for suffix in ("", "_numerator", "_denominator")),
)


@dataclass(frozen=True)
class PlanItem:
    menu: str
    category: str
    units: int


@dataclass(frozen=True)
class StockItem:
    ingredient: str
    quantity: Decimal
    unit: str


def _units(value: str, row: int) -> int:
    amount = number(value, "units", row)
    if amount != amount.to_integral_value():
        raise InputError(f"row {row}, units: expected a nonnegative integer")
    return int(amount)


def read_plan(stream: TextIO) -> list[PlanItem]:
    """Read one nonnegative whole-menu quantity per menu/category identity."""
    result, seen = [], set()
    for line, row in _rows(stream, PLAN_FIELDS, "Plan"):
        menu = _text(row["menu"], "menu", line)
        category = _text(row["category"], "category", line)
        if (menu, category) in seen:
            raise InputError(f"row {line}: duplicate plan menu/category: {menu} / {category}")
        seen.add((menu, category))
        result.append(PlanItem(menu, category, _units(row["units"], line)))
    return result


def read_stock(stream: TextIO) -> list[StockItem]:
    """Read raw purchased stock; edible/prepared quantities need conversion first."""
    result, seen = [], set()
    for line, row in _rows(stream, STOCK_FIELDS, "Stock"):
        name = _text(row["ingredient"], "ingredient", line)
        if name in seen:
            raise InputError(f"row {line}: duplicate stock ingredient: {name}")
        seen.add(name)
        result.append(StockItem(name, number(row["quantity"], "quantity", line),
                                _unit(row["unit"], "unit", line)))
    return result


def load_plan(path: str | Path) -> list[PlanItem]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return read_plan(stream)


def load_stock(path: str | Path) -> list[StockItem]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return read_stock(stream)


def plan_procurement(
    ingredients: list[Ingredient], recipes: list[RecipeLine],
    plan: list[PlanItem], stock: list[StockItem] | None = None,
) -> dict:
    """Aggregate gross demand, subtract stock once and buy complete purchase packs."""
    if not ingredients or not recipes or not plan:
        raise InputError("At least one ingredient, recipe line and plan row are required")
    catalog = {}
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
        catalog[name] = Ingredient(name, quantity, unit, price, rate)

    recipe_map, seen = {}, set()
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
        if UNITS[unit][0] != UNITS[catalog[name].purchase_unit][0]:
            raise InputError(f"Incompatible units for ingredient {name}: {unit} / {catalog[name].purchase_unit}")
        recipe_map.setdefault((menu, category), []).append(
            RecipeLine(menu, category, name, quantity, unit)
        )

    normalized_plan, seen = [], set()
    for row, item in enumerate(plan, 1):
        menu = _text(item.menu, "menu", row)
        category = _text(item.category, "category", row)
        key = (menu, category)
        if key in seen:
            raise InputError(f"duplicate plan menu/category: {menu} / {category}")
        seen.add(key)
        units = _units(str(item.units), row)
        if key not in recipe_map:
            raise InputError(f"Recipe not found for plan menu/category: {menu} / {category}")
        normalized_plan.append(PlanItem(menu, category, units))

    stocks, stock_rows = {}, []
    for row, item in enumerate(stock or [], 1):
        name = _text(item.ingredient, "ingredient", row)
        if name in stocks:
            raise InputError(f"duplicate stock ingredient: {name}")
        if name not in catalog:
            raise InputError(f"Stock ingredient not found in catalog: {name}")
        quantity = number(str(item.quantity), "quantity", row)
        unit = _unit(item.unit, "unit", row)
        base_unit, factor = UNITS[unit]
        if base_unit != UNITS[catalog[name].purchase_unit][0]:
            raise InputError(f"Incompatible stock units for ingredient {name}: {unit} / {catalog[name].purchase_unit}")
        stocks[name] = Fraction(quantity) * factor
        stock_rows.append({"ingredient": name, "quantity": format(quantity, "f"),
                           "unit": unit, "base_unit": base_unit,
                           "stock_base": exact_value(stocks[name])})

    edible = dict.fromkeys(catalog, Fraction(0))
    gross = dict.fromkeys(catalog, Fraction(0))
    requirements = []
    for item in normalized_plan:
        for line in recipe_map[(item.menu, item.category)]:
            per_menu = Fraction(line.quantity) * UNITS[line.unit][1]
            edible_total = per_menu * item.units
            gross_total = edible_total / Fraction(catalog[line.ingredient].yield_rate)
            edible[line.ingredient] += edible_total
            gross[line.ingredient] += gross_total
            requirements.append({
                "menu": item.menu, "category": item.category, "units": item.units,
                "ingredient": line.ingredient, "recipe_quantity": format(line.quantity, "f"),
                "recipe_unit": line.unit, "base_unit": UNITS[line.unit][0],
                "edible_required_base": exact_value(edible_total),
                "gross_required_base": exact_value(gross_total),
            })

    rows, total_spend, total_packs = [], Fraction(0), 0
    for name, item in catalog.items():
        base_unit, factor = UNITS[item.purchase_unit]
        pack = Fraction(item.purchase_quantity) * factor
        available = stocks.get(name, Fraction(0))
        shortage = max(Fraction(0), gross[name] - available)
        ratio = shortage / pack
        packs = (ratio.numerator + ratio.denominator - 1) // ratio.denominator
        purchased = packs * pack
        spend = packs * Fraction(item.purchase_price)
        rows.append({
            "ingredient": name, "base_unit": base_unit,
            "purchase_quantity": format(item.purchase_quantity, "f"),
            "purchase_unit": item.purchase_unit,
            "purchase_price": format(item.purchase_price, "f"),
            "yield_rate": format(item.yield_rate, "f"), "purchase_packs": packs,
            **{field: exact_value(value) for field, value in zip(AMOUNT_FIELDS, (
                pack, edible[name], gross[name], available, shortage, purchased,
                available + purchased - gross[name], spend,
            ))},
        })
        total_spend += spend
        total_packs += packs
    return {
        "schema_version": "1.0",
        "basis": {
            "plan": "units is the planned nonnegative integer count of sold menu units; menu/category selects its recipe.",
            "stock": "Stock is raw purchased quantity before preparation loss, in the same dimension as the purchase pack. Missing stock rows mean zero stock.",
            "demand": "gross_required_base = sum(recipe edible quantity in base units * planned menu units / yield_rate).",
            "purchase": "shortage = max(0, gross demand - raw stock); purchase_packs = exact ceiling(shortage / pack quantity). Shared ingredients subtract stock once.",
            "remaining": "remaining raw stock = opening raw stock + complete purchased packs - gross demand.",
            "money": "purchase_price is one complete pack price. Supply one currency and VAT-exclusive prices; no tax conversion is performed.",
            "units": "kg = 1000 g; l = 1000 ml; each is a count. Mass, volume and count remain separate dimensions.",
            "exact_amounts": "All amounts and pack ceilings use exact rational arithmetic. Decimal displays use 50 significant digits; numerator/denominator retain the exact value.",
            "scope": "The plan uses the supplied stock and sales quantities. Expiry dates, reserved stock, supplier lead times and minimum orders are not inputs.",
        },
        "plan": [{"menu": item.menu, "category": item.category, "units": item.units}
                 for item in normalized_plan],
        "stock": stock_rows, "recipe_requirements": requirements, "ingredients": rows,
        "summary": {
            "planned_menu_units": sum(item.units for item in normalized_plan),
            "ingredient_count": len(rows),
            "purchase_ingredient_count": sum(row["purchase_packs"] > 0 for row in rows),
            "total_purchase_packs": total_packs,
            "total_purchase_spend": exact_value(total_spend),
        },
    }


def procurement_csv(report: dict) -> str:
    """Export decimal displays and exact numerator/denominator audit columns."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for source in report["ingredients"]:
        row = {field: source[field] for field in CSV_FIELDS[:7]}
        for field in AMOUNT_FIELDS:
            row[field] = source[field]["decimal"]
            row[field + "_numerator"] = source[field]["numerator"]
            row[field + "_denominator"] = source[field]["denominator"]
        writer.writerow(row)
    return stream.getvalue()


def procurement_markdown(report: dict) -> str:
    def cell(value: str) -> str:
        text = escape(value).replace("\\", "\\\\")
        for char in "`*_[]~":
            text = text.replace(char, "\\" + char)
        return text.replace("|", "\\|")

    summary = report["summary"]
    lines = ["# Ingredient purchase plan", "",
             f"Planned menu units: {summary['planned_menu_units']}",
             f"Complete packs to purchase: {summary['total_purchase_packs']}",
             f"Purchase spend, excluding VAT: {summary['total_purchase_spend']['decimal']}", "",
             "| Ingredient | Base unit | Gross demand | Raw stock | Shortage | Purchase packs | Purchased quantity | Remaining raw stock | Purchase spend |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in report["ingredients"]:
        values = [cell(row["ingredient"]), row["base_unit"],
                  row["gross_required_base"]["decimal"], row["stock_base"]["decimal"],
                  row["shortage_base"]["decimal"], str(row["purchase_packs"]),
                  row["purchased_quantity_base"]["decimal"],
                  row["remaining_stock_base"]["decimal"], row["purchase_spend"]["decimal"]]
        lines.append("| " + " | ".join(values) + " |")
    lines += ["", *report["basis"].values()]
    return "\n".join(lines) + "\n"
