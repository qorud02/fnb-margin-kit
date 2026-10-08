"""Stock-aware whole-pack ingredient purchase command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis import InputError
from .procurement import (
    load_plan, load_stock, plan_procurement, procurement_csv, procurement_markdown,
)
from .recipes import load_ingredients, load_recipes

OUTPUT_NAMES = ("procurement.json", "procurement.md", "ingredient-procurement.csv")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan whole-pack ingredient purchases from sales quantities and raw stock.")
    parser.add_argument("ingredients", type=Path, help="ingredient purchase/yield CSV")
    parser.add_argument("recipes", type=Path, help="edible recipe quantities per sold menu unit")
    parser.add_argument("plan", type=Path, help="planned menu,category,units CSV")
    parser.add_argument("--stock", type=Path, help="optional raw ingredient,quantity,unit CSV")
    parser.add_argument("--output-dir", type=Path, default=Path("procurement-report"))
    args = parser.parse_args(argv)
    try:
        sources = [path for path in (args.ingredients, args.recipes, args.plan, args.stock)
                   if path is not None]
        outputs = [args.output_dir / name for name in OUTPUT_NAMES]
        try:
            if args.output_dir.exists() and not args.output_dir.is_dir():
                raise InputError("Procurement output directory must be a directory")
            for output in outputs:
                if output.exists() and not output.is_file():
                    raise InputError(f"Procurement output must be a file: {output}")
                for source in sources:
                    if output.resolve() == source.resolve() or (output.exists() and output.samefile(source)):
                        raise InputError("Procurement output must not overwrite an input CSV")
            for index, output in enumerate(outputs):
                for other in outputs[:index]:
                    if output.resolve() == other.resolve() or (output.exists() and other.exists() and output.samefile(other)):
                        raise InputError("Procurement output files must not alias each other")
        except RuntimeError as exc:
            raise InputError(f"Unable to resolve input or procurement-output path: {exc}") from exc
        report = plan_procurement(
            load_ingredients(args.ingredients), load_recipes(args.recipes), load_plan(args.plan),
            None if args.stock is None else load_stock(args.stock),
        )
        texts = (json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                 procurement_markdown(report), procurement_csv(report))
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for output, text in zip(outputs, texts):
            output.write_text(text, encoding="utf-8", newline="\n")
    except (InputError, OSError, UnicodeError) as exc:
        print(f"fnb-procure: {exc}", file=sys.stderr)
        return 2
    print("Wrote " + ", ".join(str(path) for path in outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
