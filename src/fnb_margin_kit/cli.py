"""Command-line interface and Markdown rendering."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import ROUND_HALF_UP, Decimal, localcontext
from html import escape
from pathlib import Path

from .analysis import InputError, analyze, load_menu, number


def money(value: str) -> str:
    with localcontext() as ctx:
        ctx.prec = 80
        return (
            f"{Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"
        )


def markdown(report: dict) -> str:
    def cell(value: str) -> str:
        return escape(value).replace("\\", "\\\\").replace("|", "\\|")

    totals = report["totals"]
    lines = [
        "# F&B sales-mix contribution",
        "",
        f"Units sold: **{report['total_units']:,}**",
        f"VAT-exclusive sales: **{money(totals['net_sales'])}**",
        f"Contribution before fixed costs: **{money(totals['contribution'])}**",
        "",
        "| Rank | Menu | Category | Units | Net price/unit | Fee/unit | Contribution/unit | Total contribution | Margin |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report["menus"]:
        lines.append(
            f"| {row['rank']} | {cell(row['menu'])} | {cell(row['category'])} | {row['units']} | "
            f"{money(row['net_price_per_unit'])} | {money(row['platform_fee_per_unit'])} | "
            f"{money(row['contribution_per_unit'])} | {money(row['total_contribution'])} | {row['margin_flag']} |"
        )
    lines += [
        "",
        "Platform fees use the VAT-inclusive selling price. Ingredient and packaging costs are VAT-exclusive.",
        "Labor, rent, other fixed costs, and income tax are excluded. This report measures contribution, not net profit.",
        "Markdown amounts round to two decimal places; JSON retains the calculation precision.",
    ]
    if "fixed_cost_scenario" in report:
        scenario = report["fixed_cost_scenario"]
        lines += [
            "",
            "## Specified fixed-cost scenario",
            "",
            f"Specified fixed cost: **{money(scenario['specified_fixed_cost'])}**",
            f"Contribution after that cost: **{money(scenario['contribution_after_specified_fixed_cost'])}**",
            scenario["basis"],
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze F&B sales-mix contribution from a UTF-8 CSV."
    )
    parser.add_argument(
        "csv", type=Path, help="menu CSV with the documented eight columns"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("report"),
        help="directory for report.md and report.json",
    )
    parser.add_argument(
        "--fixed-cost",
        help="optional fixed cost for the same sales period, in the same monetary unit",
    )
    args = parser.parse_args(argv)
    try:
        try:
            input_path = args.csv.resolve()
            for name in ("report.json", "report.md"):
                output_path = args.output_dir / name
                if output_path.resolve() == input_path or (
                    output_path.exists() and output_path.samefile(args.csv)
                ):
                    raise InputError("Report output must not overwrite the input CSV")
        except RuntimeError as exc:
            raise InputError(f"Unable to resolve input or report path: {exc}") from exc
        fixed = (
            None if args.fixed_cost is None else number(args.fixed_cost, "fixed_cost")
        )
        report = analyze(load_menu(args.csv), fixed_cost=fixed)
        json_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        md_text = markdown(report)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "report.json").write_text(json_text, encoding="utf-8")
        (args.output_dir / "report.md").write_text(md_text, encoding="utf-8")
    except (InputError, OSError, UnicodeError) as exc:
        print(f"fnb-margin: {exc}", file=sys.stderr)
        return 2
    print(
        f"Wrote {args.output_dir / 'report.md'} and {args.output_dir / 'report.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
