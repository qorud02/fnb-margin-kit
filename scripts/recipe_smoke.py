"""Exercise the real recipe console in source, installed wheel and exact image."""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib


parser = argparse.ArgumentParser()
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument("--container")
mode.add_argument("--python")
mode.add_argument("--source", type=Path, help="Source-only functional preflight")
parser.add_argument("--console")
args = parser.parse_args()
if args.python and not args.console:
    parser.error("--python requires --console")
root = Path.cwd().resolve()
version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE"}}
env["PYTHONIOENCODING"] = "utf-8"
if args.source:
    env["PYTHONPATH"] = str(args.source.resolve() / "src")
checks = []
with tempfile.TemporaryDirectory(prefix="fnb-recipe-smoke-") as directory:
    temp = Path(directory)
    temp.chmod(0o755)
    output = temp / "output"
    output.mkdir()
    output.chmod(0o777)
    ih = "ingredient,purchase_quantity,purchase_unit,purchase_price,yield_rate\n"
    rh = "menu,category,ingredient,quantity,unit\n"
    payloads = {
        "simple-ingredients.csv": ih + "milk,1,l,3000,.95\n",
        "simple-recipes.csv": rh + "latte,store,milk,180,ml\n",
        "bad-yield.csv": ih + "milk,1,l,3000,0\n",
        "bad-unit.csv": rh + "latte,store,milk,180,g\n",
        "duplicate.csv": ih + "milk,1,l,3000,.95\n milk ,1,l,3000,1\n",
        "missing.csv": rh + "latte,store,unknown,180,ml\n",
        "huge.csv": ih + "milk,1e-12,ml,1e24,1\n",
        "tiny.csv": ih + "milk,1e24,l,1e-12,1\n",
        "tiny-recipe.csv": rh + "latte,store,milk,1e-12,ml\n",
    }
    for name, text in payloads.items():
        (temp / name).write_text(text, encoding="utf-8", newline="\n")
        (temp / name).chmod(0o644)
    guard = temp / "guard"
    guard.mkdir()
    guard.chmod(0o755)
    os.link(temp / "simple-ingredients.csv", guard / "recipe-costs.json")
    original_inputs = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in temp.glob("*.csv")}
    example = root / "examples" / "recipe-costing"
    example_hashes = {name: hashlib.sha256((example / name).read_bytes()).hexdigest() for name in ("ingredients.csv", "recipes.csv", "menu.csv")}
    if args.container:
        base = ["docker", "run", "--rm", "--platform", "linux/amd64", "--read-only", "--network", "none",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--mount", f"type=bind,source={root},target=/work,readonly",
                "--mount", f"type=bind,source={temp},target=/fixtures,readonly",
                "--mount", f"type=bind,source={output},target=/output", "--workdir", "/work"]
        prefix = base + ["--entrypoint", "fnb-recipe", args.container]
        margin_prefix = base + [args.container]
        fixture = lambda name: "/work/examples/recipe-costing/" + name
        extra = lambda name: "/fixtures/" + name
        out = lambda name: "/output/" + name
    else:
        prefix = ([sys.executable, "-m", "fnb_margin_kit.recipe_cli"] if args.source
                  else [str(Path(args.console).absolute())])
        console_path = Path(args.console).absolute() if args.console else None
        margin_prefix = ([sys.executable, "-m", "fnb_margin_kit.cli"] if args.source else
                         [str(console_path.with_name("fnb-margin.exe" if console_path.suffix == ".exe" else "fnb-margin"))])
        fixture = lambda name: str(example / name)
        extra = lambda name: str(temp / name)
        out = lambda name: str(output / name)

    def run(arguments, status, label, command=None):
        result = subprocess.run((prefix if command is None else command) + arguments,
                                cwd=temp, env=env, capture_output=True, text=True,
                                encoding="utf-8", timeout=180)
        assert result.returncode == status, (label, result.returncode, result.stdout, result.stderr)
        checks.append(label)
        return result

    def destination(name):
        path = output / name
        path.mkdir()
        path.chmod(0o777)
        return path

    help_text = run(["--help"], 0, "recipe-console-help").stdout
    assert all(value in help_text for value in ("ingredients", "recipes", "--menu", "--output-dir"))
    dest = destination("example")
    run([fixture("ingredients.csv"), fixture("recipes.csv"), "--menu", fixture("menu.csv"), "--output-dir", out("example")],
        0, "purchase-yield-example-four-output-files")
    assert {path.name for path in dest.iterdir()} == {"recipe-costs.json", "recipe-costs.md", "menu-ingredient-costs.csv", "costed-menu.csv"}
    report = json.loads((dest / "recipe-costs.json").read_text(encoding="utf-8"))
    assert len(report["ingredient_catalog"]) == 5 and len(report["recipe_lines"]) == 9 and len(report["menus"]) == 4
    rows = {(row["menu"], row["category"]): row for row in report["menus"]}
    expected = {("가상 라테", "매장"): ("19008", "19", "1000.421052631579"),
                ("가상 라테", "배달"): ("19008", "19", "1000.421052631579"),
                ("가상 바나나 음료", "매장"): ("26290", "19", "1383.684210526316"),
                ("가상 디저트", "디저트"): ("1540", "1", "1540")}
    for key, (numerator, denominator, exported) in expected.items():
        assert rows[key]["ingredient_cost"]["numerator"] == numerator and rows[key]["ingredient_cost"]["denominator"] == denominator
        assert rows[key]["export_ingredient_cost"] == exported
    checks.append("exact-rational-cost-and-single-rounded-exports")
    original_rows = list(csv.DictReader((example / "menu.csv").open(encoding="utf-8-sig", newline="")))
    costed_rows = list(csv.DictReader((dest / "costed-menu.csv").open(encoding="utf-8", newline="")))
    assert [(row["menu"], row["category"]) for row in costed_rows] == [(row["menu"], row["category"]) for row in original_rows]
    for original, costed in zip(original_rows, costed_rows):
        assert all(original[field].strip() == costed[field] for field in original if field != "ingredient_cost")
    checks.append("menu-order-and-other-fields-preserved")
    margin = destination("margin")
    run([out("example/costed-menu.csv"), "--output-dir", out("margin"), "--html"], 0,
        "costed-menu-consumed-by-existing-margin-console", margin_prefix)
    margin_report = json.loads((margin / "report.json").read_text(encoding="utf-8"))
    assert margin_report["total_units"] == sum(int(row["units"]) for row in original_rows)
    assert {row["menu"] for row in margin_report["menus"]} == {row["menu"] for row in original_rows}
    no_menu = destination("without-menu")
    run([fixture("ingredients.csv"), fixture("recipes.csv"), "--output-dir", out("without-menu")], 0, "optional-menu-omitted")
    assert len(list(no_menu.iterdir())) == 3
    tiny = destination("tiny")
    run([extra("tiny.csv"), extra("tiny-recipe.csv"), "--output-dir", out("tiny")], 0, "tiny-cost-exact-audit-zero-export")
    tiny_report = json.loads((tiny / "recipe-costs.json").read_text(encoding="utf-8"))
    assert tiny_report["menus"][0]["ingredient_cost"]["numerator"] == "1"
    assert tiny_report["menus"][0]["ingredient_cost"]["denominator"] == str(10**51)
    assert tiny_report["menus"][0]["export_ingredient_cost"] == "0"
    for ingredients, recipes, label in [
        ("bad-yield.csv", "simple-recipes.csv", "zero-yield-rejected"),
        ("simple-ingredients.csv", "bad-unit.csv", "cross-dimension-rejected"),
        ("duplicate.csv", "simple-recipes.csv", "duplicate-catalog-rejected"),
        ("simple-ingredients.csv", "missing.csv", "missing-ingredient-rejected"),
        ("huge.csv", "simple-recipes.csv", "unexportable-cost-rejected"),
    ]:
        run([extra(ingredients), extra(recipes), "--output-dir", out(label)], 2, label)
        assert not (output / label).exists()
    protected = run([extra("simple-ingredients.csv"), extra("simple-recipes.csv"), "--output-dir", extra("guard")], 2, "hardlink-input-protected")
    assert "must not overwrite" in protected.stderr
    assert list(guard.iterdir()) == [guard / "recipe-costs.json"]
    assert original_inputs == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in temp.glob("*.csv")}
    assert example_hashes == {name: hashlib.sha256((example / name).read_bytes()).hexdigest() for name in example_hashes}
    checks.append("all-supplied-input-bytes-preserved")
    code = "import json,os,sys,fnb_margin_kit.recipe_cli as m;from importlib.metadata import version;print(json.dumps({'path':m.__file__,'prefix':sys.prefix,'version':version('fnb-margin-kit'),'uid':getattr(os,'getuid',lambda:None)()}))"
    if args.container:
        interpreter = base + ["--entrypoint", "python", args.container, "-I"]
    else:
        interpreter = [sys.executable] if args.source else [str(Path(args.python).absolute()), "-I"]
    if args.source:
        code = "import json,fnb_margin_kit.recipe_cli as m;print(json.dumps({'path':m.__file__}))"
    identity = run(["-c", code], 0, "recipe-import-identity", interpreter)
    imported = json.loads(identity.stdout)
    if args.container:
        assert imported["version"] == version and imported["uid"] == 10001 and imported["path"].startswith("/usr/local/lib/")
    elif args.source:
        assert os.path.commonpath([imported["path"], str(args.source.resolve() / "src")]) == str(args.source.resolve() / "src")
    else:
        environment = str(Path(args.python).absolute().parents[1])
        assert imported["version"] == version and os.path.commonpath([imported["path"], environment]) == environment
        assert os.path.normcase(imported["prefix"]) == os.path.normcase(environment)
    result = run(["-m", "fnb_margin_kit.recipe_cli", "--help"], 0, "recipe-module-help", interpreter)
    assert "--menu" in result.stdout
print(json.dumps({"mode": "container" if args.container else "source" if args.source else "wheel",
                  "version": version, "checks": checks, "passed": len(checks)}))
