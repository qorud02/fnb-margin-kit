"""File-based recipe costing command, separate from sales-mix analysis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis import InputError, load_menu
from .recipes import (
    cost_recipes,
    costed_menu_csv,
    ingredient_costs_csv,
    load_ingredients,
    load_recipes,
    recipe_markdown,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calculate recipe ingredient costs from purchase units and edible yields.")
    parser.add_argument("ingredients", type=Path, help="ingredient purchase/yield CSV")
    parser.add_argument("recipes", type=Path, help="edible recipe quantities per sold menu unit")
    parser.add_argument("--output-dir", type=Path, default=Path("recipe-report"))
    parser.add_argument("--menu", type=Path, help="optional eight-column menu CSV whose ingredient costs will be replaced")
    args = parser.parse_args(argv)
    output_names = ["recipe-costs.json", "recipe-costs.md", "menu-ingredient-costs.csv"]
    if args.menu is not None:
        output_names.append("costed-menu.csv")
    try:
        try:
            for source in (args.ingredients, args.recipes, args.menu):
                if source is None:
                    continue
                resolved = source.resolve()
                for name in output_names:
                    output = args.output_dir / name
                    if output.resolve() == resolved or (output.exists() and output.samefile(source)):
                        raise InputError("Recipe output must not overwrite an input CSV")
        except RuntimeError as exc:
            raise InputError(f"Unable to resolve input or recipe-output path: {exc}") from exc
        report = cost_recipes(
            load_ingredients(args.ingredients), load_recipes(args.recipes),
            None if args.menu is None else load_menu(args.menu),
        )
        texts = {
            "recipe-costs.json": json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            "recipe-costs.md": recipe_markdown(report),
            "menu-ingredient-costs.csv": ingredient_costs_csv(report),
        }
        if args.menu is not None:
            texts["costed-menu.csv"] = costed_menu_csv(report)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, text in texts.items():
            (args.output_dir / name).write_text(text, encoding="utf-8", newline="\n")
    except (InputError, OSError, UnicodeError) as exc:
        print(f"fnb-recipe: {exc}", file=sys.stderr)
        return 2
    print("Wrote " + ", ".join(str(args.output_dir / name) for name in output_names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
