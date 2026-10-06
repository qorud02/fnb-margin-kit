"""Compare two explicit sales plans without changing either contribution report."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction
from html import escape

from .analysis import FIELDS, ChannelCost, InputError, MenuItem, _sum_exact, analyze

UNIT_LIMIT = 10**25 - 1
QUANTITY_BASIS = (
    "Exact rational arithmetic on the original inputs: ceil(baseline unit "
    "contribution * baseline units / proposed unit contribution). This menu "
    "threshold precedes period-level channel costs and fixed costs."
)


def _inputs(item: MenuItem) -> dict:
    return {
        "menu": item.menu.strip(), "category": item.category.strip(),
        **{field: format(Decimal(str(getattr(item, field))), "f")
           for field in FIELDS[2:-1]},
        "units": int(item.units),
    }


def _difference(proposed: str, baseline: str) -> str:
    return format(_sum_exact((Decimal(proposed), Decimal(baseline).copy_negate())), "f")


def _unit_fraction(inputs: dict) -> Fraction:
    values = {field: Fraction(Decimal(inputs[field])) for field in FIELDS[2:-1]}
    gross = values["price_gross"]
    return (gross / (1 + values["vat_rate"]) - values["ingredient_cost"]
            - values["packaging_cost"] - gross * values["platform_fee_rate"])


def retained_quantity(baseline_inputs: dict, proposed_inputs: dict) -> dict:
    """Return the exact integer retention threshold from validated original inputs."""
    target = _unit_fraction(baseline_inputs) * baseline_inputs["units"]
    proposed_unit = _unit_fraction(proposed_inputs)
    result = {"basis": QUANTITY_BASIS, "min_units": None,
              "within_input_unit_limit": None, "current_units_meet_threshold": None,
              "additional_units_required": None}
    if target <= 0:
        result["status"] = "baseline_nonpositive"
    elif proposed_unit <= 0:
        result["status"] = "proposed_unit_zero" if proposed_unit == 0 else "proposed_unit_negative"
    else:
        ratio = target / proposed_unit
        minimum = (ratio.numerator + ratio.denominator - 1) // ratio.denominator
        result.update(status="required", min_units=minimum,
                      within_input_unit_limit=minimum <= UNIT_LIMIT,
                      current_units_meet_threshold=proposed_inputs["units"] >= minimum,
                      additional_units_required=max(0, minimum - proposed_inputs["units"]))
    return result


def _sales(inputs: dict, row: dict) -> dict:
    # Match the existing per-menu computation; aggregate only the recorded amounts.
    with localcontext() as ctx:
        ctx.prec = 50
        return {
            "gross_sales": format(Decimal(inputs["price_gross"]) * inputs["units"], "f"),
            "net_sales": format(Decimal(row["net_price_per_unit"]) * inputs["units"], "f"),
        }


def _summary(report: dict, channel_costs_supplied: bool) -> dict:
    channels = report.get("channel_cost_scenario", {})
    fixed = report.get("fixed_cost_scenario", {})
    return {
        "total_units": report["total_units"], **report["totals"],
        "channel_costs_supplied": channel_costs_supplied,
        "additional_variable_cost": channels.get("total_additional_variable_cost", "0"),
        "contribution_after_additional_costs": channels.get(
            "contribution_after_additional_costs", report["totals"]["contribution"]),
        "specified_fixed_cost": fixed.get("specified_fixed_cost"),
        "contribution_after_specified_fixed_cost": fixed.get(
            "contribution_after_specified_fixed_cost"),
    }


def _categories(report: dict, inputs: dict) -> dict:
    grouped = {}
    for row in report["menus"]:
        record = grouped.setdefault(row["category"], {"units": 0,
                                                     "gross_sales": [], "net_sales": [],
                                                     "contribution": []})
        record["units"] += row["units"]
        for field, value in _sales(inputs[(row["menu"], row["category"])], row).items():
            record[field].append(Decimal(value))
        record["contribution"].append(Decimal(row["total_contribution"]))
    channels = {row["category"]: row for row in report.get(
        "channel_cost_scenario", {}).get("categories", [])}
    result = {}
    for category, record in grouped.items():
        contribution = format(_sum_exact(record["contribution"]), "f")
        channel = channels.get(category, {})
        result[category] = {
            "units": record["units"],
            "gross_sales": format(_sum_exact(record["gross_sales"]), "f"),
            "net_sales": format(_sum_exact(record["net_sales"]), "f"),
            "contribution": contribution,
            "additional_variable_cost": channel.get("additional_variable_cost", "0"),
            "contribution_after_additional_costs": channel.get(
                "contribution_after_additional_cost", contribution),
        }
    return result


def _deltas(baseline: dict, proposed: dict, count_field: str) -> dict:
    result = {}
    for field in baseline:
        if field == "channel_costs_supplied":
            continue
        if field == count_field:
            result[field] = proposed[field] - baseline[field]
        elif baseline[field] is None:
            result[field] = None
        else:
            result[field] = _difference(proposed[field], baseline[field])
    return result


def analyze_comparison(
    baseline_items: list[MenuItem], proposed_items: list[MenuItem],
    fixed_cost: Decimal | None = None, *,
    channel_costs: list[ChannelCost] | None = None,
    proposed_channel_costs: list[ChannelCost] | None = None,
) -> dict:
    """Analyze each explicit plan independently, then compare matching identities."""
    baseline = analyze(baseline_items, fixed_cost, channel_costs=channel_costs)
    proposed = analyze(proposed_items, fixed_cost, channel_costs=proposed_channel_costs)
    before = {(row["menu"], row["category"]): row for row in baseline["menus"]}
    after = {(row["menu"], row["category"]): row for row in proposed["menus"]}
    if before.keys() != after.keys():
        missing = sorted(before.keys() - after.keys())
        unexpected = sorted(after.keys() - before.keys())
        details = []
        if missing:
            details.append("missing from proposed: " + "; ".join(f"{m} / {c}" for m, c in missing))
        if unexpected:
            details.append("unexpected in proposed: " + "; ".join(f"{m} / {c}" for m, c in unexpected))
        raise InputError("Comparison menu/category identities must match; " + "; ".join(details))
    base_inputs = {(item.menu.strip(), item.category.strip()): _inputs(item)
                   for item in baseline_items}
    plan_inputs = {(item.menu.strip(), item.category.strip()): _inputs(item)
                   for item in proposed_items}
    menus = []
    for key in sorted(before):
        old, new = before[key], after[key]
        old_inputs, new_inputs = base_inputs[key], plan_inputs[key]
        changed = {field: {"baseline": old_inputs[field], "proposed": new_inputs[field]}
                   for field in FIELDS[2:] if (Decimal(str(old_inputs[field]))
                                               != Decimal(str(new_inputs[field])))}
        old_amounts = {field: old[field] for field in (
            "units", "net_price_per_unit", "platform_fee_per_unit", "variable_cost_per_unit",
            "contribution_per_unit", "total_contribution")}
        new_amounts = {field: new[field] for field in old_amounts}
        old_amounts.update(_sales(old_inputs, old))
        new_amounts.update(_sales(new_inputs, new))
        menus.append({
            "menu": key[0], "category": key[1], "baseline_inputs": old_inputs,
            "proposed_inputs": new_inputs, "changed_inputs": changed,
            "baseline": dict(old, **_sales(old_inputs, old)),
            "proposed": dict(new, **_sales(new_inputs, new)),
            "delta": _deltas(old_amounts, new_amounts, "units"),
            "retained_contribution_quantity": retained_quantity(old_inputs, new_inputs),
        })
    base_summary = _summary(baseline, channel_costs is not None)
    plan_summary = _summary(proposed, proposed_channel_costs is not None)
    base_categories = _categories(baseline, base_inputs)
    plan_categories = _categories(proposed, plan_inputs)
    return {
        "schema_version": "1.0",
        "basis": {
            "monetary_values": baseline["basis"]["rounding"],
            "delta": "Proposed minus baseline, with exact subtraction of recorded Decimal amounts.",
            "quantity": QUANTITY_BASIS,
            "channel_costs": "Each side uses only its own supplied channel-cost CSV; omission means zero additional channel costs for that side.",
            "fixed_cost": "The same supplied period-level fixed cost applies to both sides; it is not allocated to categories or menus.",
            "units": "Each plan's units are supplied inputs for the same period, not a demand forecast.",
        },
        "baseline": baseline, "proposed": proposed,
        "summary": {"baseline": base_summary, "proposed": plan_summary,
                    "delta": _deltas(base_summary, plan_summary, "total_units")},
        "categories": [{"category": category, "baseline": base_categories[category],
                        "proposed": plan_categories[category],
                        "delta": _deltas(base_categories[category], plan_categories[category], "units")}
                       for category in sorted(base_categories)],
        "menus": menus,
    }


def comparison_markdown(comparison: dict) -> str:
    """Render the scenario decision table; retain original precision in JSON."""
    def cell(value: str) -> str:
        text = escape(value).replace("\\", "\\\\")
        for char in "`*_[]~":
            text = text.replace(char, "\\" + char)
        return text.replace("|", "\\|")

    def money(value: str) -> str:
        with localcontext() as ctx:
            ctx.prec = max(80, Decimal(value).adjusted() + 4)
            return f"{Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"

    summary = comparison["summary"]
    labels = {"total_units": "Units", "gross_sales": "Gross sales",
              "net_sales": "VAT-exclusive sales", "contribution": "Menu contribution",
              "additional_variable_cost": "Additional channel costs",
              "contribution_after_additional_costs": "Contribution after channel costs",
              "specified_fixed_cost": "Same specified fixed cost",
              "contribution_after_specified_fixed_cost": "Contribution after specified fixed cost"}
    lines = ["# 가격·원가·판매량 비교 / Price, cost and quantity comparison", "",
             "Delta = proposed minus baseline. Both plans use the same sales period and monetary unit.",
             "Quantities are supplied plan inputs. Each side uses its own channel costs; an omitted CSV means zero additional channel costs.",
             "The same specified fixed cost applies to both plans. Category and menu values precede that shared fixed cost.", "",
             "## Overall", "", "| Measure | Baseline | Proposed | Delta |",
             "| --- | ---: | ---: | ---: |"]
    for field, label in labels.items():
        if summary["baseline"][field] is None:
            continue
        values = [summary[side][field] for side in ("baseline", "proposed", "delta")]
        displayed = [f"{value:,}" for value in values] if field == "total_units" else [money(value) for value in values]
        lines.append(f"| {label} | " + " | ".join(displayed) + " |")
    lines += ["", "## Categories", "",
              "| Category | Baseline units | Proposed units | Baseline after channel costs | Proposed after channel costs | Delta |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in comparison["categories"]:
        lines.append(f"| {cell(row['category'])} | {row['baseline']['units']:,} | {row['proposed']['units']:,} | "
                     + " | ".join(money(row[side]["contribution_after_additional_costs"])
                                  for side in ("baseline", "proposed", "delta")) + " |")
    lines += ["", "## Menus", "",
              "| Menu | Category | Baseline units | Proposed units | Baseline contribution/unit | Proposed contribution/unit | Baseline total | Proposed total | Delta | Minimum units to retain baseline |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in comparison["menus"]:
        quantity = row["retained_contribution_quantity"]
        minimum = (f"{quantity['min_units']:,}" if quantity["status"] == "required" else
                   "Baseline contribution ≤ 0" if quantity["status"] == "baseline_nonpositive" else
                   "Proposed unit contribution ≤ 0")
        if quantity["within_input_unit_limit"] is False:
            minimum += " (exceeds CSV unit limit)"
        lines.append(f"| {cell(row['menu'])} | {cell(row['category'])} | {row['baseline']['units']:,} | {row['proposed']['units']:,} | "
                     + " | ".join(money(value) for value in (
                         row["baseline"]["contribution_per_unit"], row["proposed"]["contribution_per_unit"],
                         row["baseline"]["total_contribution"], row["proposed"]["total_contribution"],
                         row["delta"]["total_contribution"])) + f" | {minimum} |")
    lines += ["", "Minimum quantities use exact rational arithmetic on the original inputs, before period-level channel and fixed costs. Money uses the existing 50-digit per-menu calculation; displayed amounts round to two decimals.",
              "", "## Changed inputs", "", "| Menu | Category | Field | Baseline | Proposed |",
              "| --- | --- | --- | ---: | ---: |"]
    changes = 0
    for row in comparison["menus"]:
        for field, values in row["changed_inputs"].items():
            lines.append(f"| {cell(row['menu'])} | {cell(row['category'])} | {field} | {values['baseline']} | {values['proposed']} |")
            changes += 1
    if not changes:
        lines.append("| All menus | All categories | No numerical input changes | — | — |")
    return "\n".join(lines) + "\n"
