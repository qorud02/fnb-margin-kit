"""Validate CSV inputs and compute contributions before fixed costs."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, DecimalException, localcontext
from pathlib import Path
from typing import Iterable, TextIO

from ._decimal import decimal_context

FIELDS = (
    "menu",
    "category",
    "price_gross",
    "vat_rate",
    "ingredient_cost",
    "packaging_cost",
    "platform_fee_rate",
    "units",
)
CHANNEL_COST_FIELDS = ("category", "additional_variable_cost")
ZERO = Decimal("0")


class InputError(ValueError):
    """The input cannot be interpreted as a valid sales-mix record."""


def number(value: str, field: str, row: int | None = None) -> Decimal:
    """Parse a finite nonnegative decimal, retaining its decimal representation."""
    where = f"row {row}, " if row is not None else ""
    try:
        value = value.strip()
        if not value or len(value) > 64:
            raise ValueError
        result = Decimal(value)
    except (DecimalException, ValueError, AttributeError) as exc:
        raise InputError(
            f"{where}{field}: expected a finite nonnegative number"
        ) from exc
    if not result.is_finite() or result < ZERO:
        raise InputError(f"{where}{field}: expected a finite nonnegative number")
    # Bounds avoid silent loss of significance in Decimal operations and abusive exponents.
    if (
        len(result.as_tuple().digits) > 28
        or result.adjusted() > 24
        or result.as_tuple().exponent < -12
    ):
        raise InputError(
            f"{where}{field}: use at most 28 digits, 12 decimal places, and magnitude below 1e25"
        )
    return result


@dataclass(frozen=True)
class MenuItem:
    menu: str
    category: str
    price_gross: Decimal
    vat_rate: Decimal
    ingredient_cost: Decimal
    packaging_cost: Decimal
    platform_fee_rate: Decimal
    units: int


@dataclass(frozen=True)
class ChannelCost:
    category: str
    additional_variable_cost: Decimal


def _text(value: str | None, field: str, row: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ord(char) < 32 for char in value)
    ):
        raise InputError(
            f"row {row}, {field}: expected nonempty text without control characters"
        )
    return value.strip()


def read_menu(stream: TextIO) -> list[MenuItem]:
    """Read a validated CSV stream. A UTF-8 BOM on the first header is supported."""
    reader = csv.DictReader(stream, strict=True)
    try:
        headers = reader.fieldnames
        if headers:
            headers[0] = headers[0].removeprefix("\ufeff")
        if (
            headers is None
            or len(headers) != len(FIELDS)
            or set(headers) != set(FIELDS)
        ):
            raise InputError("CSV header must contain each of: " + ",".join(FIELDS))
        result = []
        seen = set()
        for row in reader:
            line = reader.line_num
            if None in row or any(value is None for value in row.values()):
                raise InputError(f"row {line}: expected exactly {len(FIELDS)} columns")
            menu = _text(row["menu"], "menu", line)
            category = _text(row["category"], "category", line)
            if (menu, category) in seen:
                raise InputError(
                    f"row {line}: duplicate menu/category: {menu} / {category}"
                )
            seen.add((menu, category))
            values = {key: number(row[key], key, line) for key in FIELDS[2:]}
            for rate in ("vat_rate", "platform_fee_rate"):
                if values[rate] > Decimal("1"):
                    raise InputError(
                        f"row {line}, {rate}: expected a fraction between 0 and 1"
                    )
            if values["units"] != values["units"].to_integral_value():
                raise InputError(f"row {line}, units: expected a nonnegative integer")
            result.append(
                MenuItem(
                    menu,
                    category,
                    **{k: v for k, v in values.items() if k != "units"},
                    units=int(values["units"]),
                )
            )
    except csv.Error as exc:
        raise InputError(f"Invalid CSV: {exc}") from exc
    if not result:
        raise InputError("CSV must contain at least one menu row")
    return result


def load_menu(path: str | Path) -> list[MenuItem]:
    """Load a UTF-8 CSV, including files exported with a BOM."""
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return read_menu(stream)


def read_channel_costs(stream: TextIO) -> list[ChannelCost]:
    """Read one period-level additional variable cost per menu category."""
    reader = csv.DictReader(stream, strict=True)
    try:
        headers = reader.fieldnames
        if headers:
            headers[0] = headers[0].removeprefix("\ufeff")
        if (
            headers is None
            or len(headers) != len(CHANNEL_COST_FIELDS)
            or set(headers) != set(CHANNEL_COST_FIELDS)
        ):
            raise InputError(
                "Channel-cost CSV header must contain each of: "
                + ",".join(CHANNEL_COST_FIELDS)
            )
        result = []
        seen = set()
        for row in reader:
            line = reader.line_num
            if None in row or any(value is None for value in row.values()):
                raise InputError(f"row {line}: expected exactly 2 columns")
            category = _text(row["category"], "category", line)
            if category in seen:
                raise InputError(f"row {line}: duplicate channel-cost category: {category}")
            seen.add(category)
            result.append(
                ChannelCost(
                    category,
                    number(row["additional_variable_cost"], "additional_variable_cost", line),
                )
            )
    except csv.Error as exc:
        raise InputError(f"Invalid channel-cost CSV: {exc}") from exc
    if not result:
        raise InputError("Channel-cost CSV must contain at least one cost row")
    return result


def load_channel_costs(path: str | Path) -> list[ChannelCost]:
    """Load a UTF-8 channel-cost CSV, including a BOM."""
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return read_channel_costs(stream)


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def _sum_exact(values: Iterable[Decimal]) -> Decimal:
    """Sum finite computed amounts without rounding away cancellation residuals."""
    values = list(values)
    if not values:
        return ZERO
    with localcontext(decimal_context(50)) as ctx:
        # Align all coefficients, allowing carry digits for every summand.
        # Per-menu divisions still use the documented 50-digit precision.
        ctx.prec = max(
            50,
            max(value.adjusted() for value in values)
            - min(value.as_tuple().exponent for value in values)
            + len(str(len(values))) + 2,
        )
        return sum(values, ZERO)


def analyze(
    items: list[MenuItem],
    fixed_cost: Decimal | None = None,
    *,
    channel_costs: list[ChannelCost] | None = None,
) -> dict:
    """Rank sales contributions using VAT-exclusive sales and gross-based fees.

    Ingredient and packaging costs are supplied VAT-exclusive. The report is
    contribution before labor, rent, other fixed costs, and income tax. Optional
    channel costs are VAT-exclusive totals for the same sales period and unit,
    deducted once per category without changing menu unit margins or rankings.
    """
    if not items:
        raise InputError("At least one menu item is required")
    if fixed_cost is not None:
        fixed_cost = number(str(fixed_cost), "fixed_cost")
    with localcontext(decimal_context(50)):
        rows = []
        seen = set()
        categories = {}
        amounts_by_field = {
            key: []
            for key in (
                "gross_sales",
                "net_sales",
                "ingredient_cost",
                "packaging_cost",
                "platform_fees",
                "variable_cost",
                "contribution",
            )
        }
        for item in items:
            # Keep public API validation as strict as the CSV entry point.
            numeric = {
                field: number(str(getattr(item, field)), field) for field in FIELDS[2:]
            }
            if any(numeric[field] > 1 for field in ("vat_rate", "platform_fee_rate")):
                raise InputError(
                    "vat_rate and platform_fee_rate must be fractions between 0 and 1"
                )
            if numeric["units"] != numeric["units"].to_integral_value():
                raise InputError("units must be a nonnegative integer")
            menu = _text(item.menu, "menu", 0)
            category = _text(item.category, "category", 0)
            if (menu, category) in seen:
                raise InputError(f"duplicate menu/category: {menu} / {category}")
            seen.add((menu, category))
            gross = numeric["price_gross"]
            net = gross / (Decimal("1") + numeric["vat_rate"])
            fee = gross * numeric["platform_fee_rate"]
            variable = numeric["ingredient_cost"] + numeric["packaging_cost"] + fee
            margin = net - variable
            units = numeric["units"]
            total_margin = margin * units
            amounts = {
                "gross_sales": gross * units,
                "net_sales": net * units,
                "ingredient_cost": numeric["ingredient_cost"] * units,
                "packaging_cost": numeric["packaging_cost"] * units,
                "platform_fees": fee * units,
                "variable_cost": variable * units,
                "contribution": total_margin,
            }
            for key, value in amounts.items():
                amounts_by_field[key].append(value)
            category_totals = categories.setdefault(
                category, {"units": 0, "contributions": []}
            )
            category_totals["units"] += int(units)
            category_totals["contributions"].append(total_margin)
            rows.append(
                {
                    "menu": menu,
                    "category": category,
                    "units": int(units),
                    "net_price_per_unit": _decimal(net),
                    "platform_fee_per_unit": _decimal(fee),
                    "variable_cost_per_unit": _decimal(variable),
                    "contribution_per_unit": _decimal(margin),
                    "total_contribution": _decimal(total_margin),
                    "margin_flag": "negative"
                    if margin < 0
                    else "zero"
                    if margin == 0
                    else "positive",
                }
            )
        rows.sort(
            key=lambda row: (
                -Decimal(row["total_contribution"]),
                row["menu"],
                row["category"],
            )
        )
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
        totals = {key: _sum_exact(values) for key, values in amounts_by_field.items()}
        for category_totals in categories.values():
            category_totals["contribution"] = _sum_exact(category_totals["contributions"])
        report = {
            "schema_version": "1.0",
            "basis": {
                "sales": "price_gross / (1 + vat_rate)",
                "ingredient_and_packaging": "supplied VAT-exclusive costs",
                "platform_fee": "price_gross * platform_fee_rate",
                "contribution": "net sales minus ingredient, packaging, and platform fees",
                "excluded": ["labor", "rent", "other fixed costs", "income tax"],
                "rounding": "50-digit per-menu Decimal arithmetic with exact aggregation; JSON amounts are decimal strings",
            },
            "total_units": sum(row["units"] for row in rows),
            "totals": {key: _decimal(value) for key, value in totals.items()},
            "menus": rows,
        }
        contribution_before_fixed_cost = totals["contribution"]
        if channel_costs is not None:
            if not channel_costs:
                raise InputError("At least one channel cost is required")
            costs = {}
            for cost in channel_costs:
                category = _text(cost.category, "category", 0)
                if category in costs:
                    raise InputError(f"duplicate channel-cost category: {category}")
                if category not in categories:
                    raise InputError(f"Channel-cost category not found in menu CSV: {category}")
                costs[category] = number(
                    str(cost.additional_variable_cost), "additional_variable_cost"
                )
            additional_total = _sum_exact(costs.values())
            contribution_before_fixed_cost = _sum_exact(
                (contribution_before_fixed_cost, additional_total.copy_negate())
            )
            report["channel_cost_scenario"] = {
                "categories": [
                    {
                        "category": category,
                        "units": categories[category]["units"],
                        "contribution_before_additional_cost": _decimal(
                            categories[category]["contribution"]
                        ),
                        "additional_variable_cost": _decimal(costs.get(category, ZERO)),
                        "contribution_after_additional_cost": _decimal(
                            _sum_exact((categories[category]["contribution"],
                                        costs.get(category, ZERO).copy_negate()))
                        ),
                    }
                    for category in sorted(categories)
                ],
                "total_additional_variable_cost": _decimal(additional_total),
                "contribution_after_additional_costs": _decimal(contribution_before_fixed_cost),
                "basis": (
                    "Supplied VAT-exclusive variable costs for the same period and "
                    "monetary unit are deducted once per category. Menu margins and "
                    "rankings remain before these additional costs."
                ),
            }
        if fixed_cost is not None:
            report["fixed_cost_scenario"] = {
                "specified_fixed_cost": _decimal(fixed_cost),
                "contribution_after_specified_fixed_cost": _decimal(
                    _sum_exact((contribution_before_fixed_cost, fixed_cost.copy_negate()))
                ),
                "basis": "Only the supplied fixed cost is deducted; this is not a net-profit calculation.",
            }
            if channel_costs is not None:
                report["fixed_cost_scenario"]["basis"] = (
                    "The supplied fixed cost is deducted after the additional channel "
                    "costs. Other operating expenses and income tax remain excluded."
                )
        return report
