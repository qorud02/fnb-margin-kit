"""Command-line interface and Markdown rendering."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import ROUND_HALF_UP, Decimal, localcontext
from html import escape
from pathlib import Path

from ._decimal import decimal_context
from .analysis import InputError, analyze, load_channel_costs, load_menu, number
from .html_report import render_html
from .scenarios import analyze_comparison, comparison_markdown


def money(value: str) -> str:
    with localcontext(decimal_context(80)):
        return (
            f"{Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"
        )


def markdown(report: dict) -> str:
    def cell(value: str) -> str:
        text = escape(value).replace("\\", "\\\\")
        for char in "`*_[]~":
            text = text.replace(char, "\\" + char)
        return text.replace("|", "\\|")

    totals = report["totals"]
    contribution_label = (
        "Contribution before additional channel and fixed costs"
        if "channel_cost_scenario" in report
        else "Contribution before fixed costs"
    )
    lines = [
        "# F&B sales-mix contribution",
        "",
        f"Units sold: **{report['total_units']:,}**",
        f"VAT-exclusive sales: **{money(totals['net_sales'])}**",
        f"{contribution_label}: **{money(totals['contribution'])}**",
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
    if "channel_cost_scenario" in report:
        scenario = report["channel_cost_scenario"]
        lines += [
            "",
            "## Additional channel variable costs",
            "",
            "| Category | Units | Contribution before additional cost | Additional variable cost | Contribution after additional cost |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for row in scenario["categories"]:
            lines.append(
                f"| {cell(row['category'])} | {row['units']} | "
                f"{money(row['contribution_before_additional_cost'])} | "
                f"{money(row['additional_variable_cost'])} | "
                f"{money(row['contribution_after_additional_cost'])} |"
            )
        lines += [
            "",
            f"Total additional variable cost: **{money(scenario['total_additional_variable_cost'])}**",
            f"Contribution after additional costs: **{money(scenario['contribution_after_additional_costs'])}**",
            scenario["basis"],
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
    parser.add_argument(
        "--channel-costs",
        type=Path,
        help="optional category-level variable-cost CSV for the same period and monetary unit",
    )
    parser.add_argument(
        "--html", action="store_true",
        help="also write a self-contained offline report.html dashboard",
    )
    parser.add_argument(
        "--compare-menu", type=Path,
        help="proposed eight-column menu CSV with the same menu/category identities",
    )
    parser.add_argument(
        "--compare-channel-costs", type=Path,
        help="proposed plan's independent channel-cost CSV; requires --compare-menu",
    )
    args = parser.parse_args(argv)
    try:
        if args.compare_channel_costs is not None and args.compare_menu is None:
            raise InputError("--compare-channel-costs requires --compare-menu")
        try:
            inputs = [args.csv]
            inputs += [source for source in (args.channel_costs, args.compare_menu,
                                             args.compare_channel_costs) if source is not None]
            output_names = ["report.json", "report.md"]
            if args.html:
                output_names.append("report.html")
            if args.compare_menu is not None:
                output_names += ["comparison.json", "comparison.md"]
            for source in inputs:
                input_path = source.resolve()
                for name in output_names:
                    output_path = args.output_dir / name
                    if output_path.resolve() == input_path or (
                        output_path.exists() and output_path.samefile(source)
                    ):
                        raise InputError("Report output must not overwrite the input CSV")
        except RuntimeError as exc:
            raise InputError(f"Unable to resolve input or report path: {exc}") from exc
        fixed = (
            None if args.fixed_cost is None else number(args.fixed_cost, "fixed_cost")
        )
        channel_costs = (
            None if args.channel_costs is None else load_channel_costs(args.channel_costs)
        )
        items = load_menu(args.csv)
        report = analyze(items, fixed_cost=fixed, channel_costs=channel_costs)
        comparison = None
        if args.compare_menu is not None:
            proposed_costs = (None if args.compare_channel_costs is None else
                              load_channel_costs(args.compare_channel_costs))
            comparison = analyze_comparison(
                items, load_menu(args.compare_menu), fixed,
                channel_costs=channel_costs, proposed_channel_costs=proposed_costs)
        json_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        md_text = markdown(report)
        html_text = render_html(report) if args.html else None
        comparison_json = (None if comparison is None else
                           json.dumps(comparison, ensure_ascii=False, indent=2) + "\n")
        comparison_md = None if comparison is None else comparison_markdown(comparison)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "report.json").write_text(json_text, encoding="utf-8")
        (args.output_dir / "report.md").write_text(md_text, encoding="utf-8")
        if html_text is not None:
            (args.output_dir / "report.html").write_text(html_text, encoding="utf-8")
        if comparison_json is not None:
            (args.output_dir / "comparison.json").write_text(comparison_json, encoding="utf-8")
            (args.output_dir / "comparison.md").write_text(comparison_md, encoding="utf-8")
    except (InputError, OSError, UnicodeError) as exc:
        print(f"fnb-margin: {exc}", file=sys.stderr)
        return 2
    if args.html:
        print(f"Wrote {args.output_dir / 'report.md'}, {args.output_dir / 'report.json'} and {args.output_dir / 'report.html'}")
    else:
        print(f"Wrote {args.output_dir / 'report.md'} and {args.output_dir / 'report.json'}")
    if comparison is not None:
        print(f"Wrote {args.output_dir / 'comparison.md'} and {args.output_dir / 'comparison.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
