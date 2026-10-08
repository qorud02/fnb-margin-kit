"""Exercise procurement in source, the installed wheel and the exact image."""

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path


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
version = re.search(r'^version = "([^"]+)"$', (root / "pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE).group(1)
env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE"}}
env["PYTHONIOENCODING"] = "utf-8"
if args.source:
    env["PYTHONPATH"] = str(args.source.resolve() / "src")
checks = []
with tempfile.TemporaryDirectory(prefix="fnb-procurement-smoke-") as directory:
    temp = Path(directory)
    temp.chmod(0o755)
    output = temp / "output"
    output.mkdir()
    output.chmod(0o777)
    ih = "ingredient,purchase_quantity,purchase_unit,purchase_price,yield_rate\n"
    rh = "menu,category,ingredient,quantity,unit\n"
    ph = "menu,category,units\n"
    sh = "ingredient,quantity,unit\n"
    payloads = {
        "ingredients.csv": ih + "milk,1,l,3000,.8\n",
        "recipes.csv": rh + "drink,store,milk,200,ml\ndrink,delivery,milk,200,ml\n",
        "plan.csv": ph + "drink,store,3\ndrink,delivery,3\n",
        "stock.csv": sh + "milk,.5,l\n",
        "zero.csv": ph + "drink,store,0\n",
        "fractional.csv": ph + "drink,store,.5\n",
        "negative.csv": ph + "drink,store,-1\n",
        "duplicate-plan.csv": ph + "drink,store,1\n drink , store ,2\n",
        "missing-plan.csv": ph + "missing,store,0\n",
        "unknown-stock.csv": sh + "unknown,1,l\n",
        "unit-stock.csv": sh + "milk,1,kg\n",
        "duplicate-stock.csv": sh + "milk,1,l\n milk ,2,l\n",
        "bad-recipes.csv": rh + "drink,store,milk,200,ml\nunplanned,store,milk,1,g\n",
        "exact-ingredients.csv": ih + "item,1e24,each,1,1\n",
        "exact-recipes.csv": rh + "large,store,item,1e24,each\ntiny,store,item,1e-12,each\n",
        "exact-plan.csv": ph + "large,store,1000000000000000000000000\ntiny,store,1\n",
    }
    for name, text in payloads.items():
        (temp / name).write_text(text, encoding="utf-8", newline="\n")
        (temp / name).chmod(0o644)
    guards = []
    for name in ("ingredients.csv", "recipes.csv", "plan.csv", "stock.csv"):
        guard = temp / ("guard-" + Path(name).stem)
        guard.mkdir()
        guard.chmod(0o755)
        os.link(temp / name, guard / "procurement.json")
        guards.append((name, guard))
    originals = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in temp.glob("*.csv")}
    example = root / "examples" / "procurement"
    example_hashes = {name: hashlib.sha256((example / name).read_bytes()).hexdigest()
                      for name in ("ingredients.csv", "recipes.csv", "plan.csv", "stock.csv")}
    if args.container:
        base = ["docker", "run", "--rm", "--platform", "linux/amd64", "--read-only", "--network", "none",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--mount", f"type=bind,source={root},target=/work,readonly",
                "--mount", f"type=bind,source={temp},target=/fixtures,readonly",
                "--mount", f"type=bind,source={output},target=/output", "--workdir", "/work"]
        prefix = base + ["--entrypoint", "fnb-procure", args.container]
        fixture = lambda name: "/work/examples/procurement/" + name
        extra = lambda name: "/fixtures/" + name
        out = lambda name: "/output/" + name
    else:
        prefix = ([sys.executable, "-m", "fnb_margin_kit.procurement_cli"] if args.source
                  else [str(Path(args.console).absolute())])
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

    def amount(value):
        return Fraction(int(value["numerator"]), int(value["denominator"]))

    help_text = run(["--help"], 0, "procurement-console-help").stdout
    assert all(value in help_text for value in ("ingredients", "recipes", "plan", "--stock", "--output-dir"))
    dest = destination("example")
    run([fixture("ingredients.csv"), fixture("recipes.csv"), fixture("plan.csv"),
         "--stock", fixture("stock.csv"), "--output-dir", out("example")],
        0, "stock-aware-example-three-report-files")
    assert {path.name for path in dest.iterdir()} == {"procurement.json", "procurement.md", "ingredient-procurement.csv"}
    report = json.loads((dest / "procurement.json").read_text(encoding="utf-8"))
    rows = {row["ingredient"]: row for row in report["ingredients"]}
    expected = {
        "가상 원두": (Fraction(1080), 1, Fraction(420), Fraction(24000)),
        "가상 우유": (Fraction(246000, 19), 12, Fraction(10500, 19), Fraction(36000)),
        "가상 바나나": (Fraction(1500), 2, Fraction(700), Fraction(10000)),
        "가상 시럽": (Fraction(240), 1, Fraction(610), Fraction(6000)),
        "가상 디저트 반제품": (Fraction(8), 1, Fraction(9), Fraction(18000)),
        "가상 생강": (Fraction(0), 0, Fraction(100), Fraction(0)),
    }
    for name, (demand, packs, remaining, spend) in expected.items():
        assert (amount(rows[name]["gross_required_base"]), rows[name]["purchase_packs"],
                amount(rows[name]["remaining_stock_base"]), amount(rows[name]["purchase_spend"])) == (demand, packs, remaining, spend)
    assert report["summary"]["planned_menu_units"] == 78 and report["summary"]["total_purchase_packs"] == 17
    assert amount(report["summary"]["total_purchase_spend"]) == 94000
    checks.append("exact-demand-whole-packs-spend-and-unused-stock")
    with (dest / "ingredient-procurement.csv").open(encoding="utf-8", newline="") as stream:
        exported = {row["ingredient"]: row for row in csv.DictReader(stream)}
    assert exported["가상 우유"]["gross_required_base_numerator"] == "246000"
    assert exported["가상 우유"]["gross_required_base_denominator"] == "19"
    assert exported["가상 우유"]["purchase_packs"] == "12"
    assert len(exported) == 6
    checks.append("csv-exact-fraction-audit-columns")
    no_stock = destination("without-stock")
    run([fixture("ingredients.csv"), fixture("recipes.csv"), fixture("plan.csv"), "--output-dir", out("without-stock")],
        0, "optional-stock-means-zero-opening-stock")
    no_stock_report = json.loads((no_stock / "procurement.json").read_text(encoding="utf-8"))
    assert no_stock_report["summary"]["total_purchase_packs"] == 19
    assert amount(no_stock_report["summary"]["total_purchase_spend"]) == 121000
    shared = destination("shared")
    run([extra("ingredients.csv"), extra("recipes.csv"), extra("plan.csv"),
         "--stock", extra("stock.csv"), "--output-dir", out("shared")], 0, "shared-stock-subtracted-once")
    shared_report = json.loads((shared / "procurement.json").read_text())
    assert shared_report["ingredients"][0]["purchase_packs"] == 1
    zero = destination("zero")
    run([extra("ingredients.csv"), extra("recipes.csv"), extra("zero.csv"),
         "--stock", extra("stock.csv"), "--output-dir", out("zero")], 0, "zero-sales-keeps-stock-without-purchase")
    zero_report = json.loads((zero / "procurement.json").read_text())
    assert zero_report["summary"]["total_purchase_packs"] == 0
    assert amount(zero_report["ingredients"][0]["remaining_stock_base"]) == 500
    exact = destination("exact")
    run([extra("exact-ingredients.csv"), extra("exact-recipes.csv"), extra("exact-plan.csv"),
         "--output-dir", out("exact")], 0, "exact-ceiling-beyond-decimal-display-precision")
    exact_report = json.loads((exact / "procurement.json").read_text())
    assert exact_report["ingredients"][0]["purchase_packs"] == 10**24 + 1
    assert amount(exact_report["ingredients"][0]["gross_required_base"]) == Fraction(10**60 + 1, 10**12)
    for plan, stock_name, recipe_name, label in [
        ("fractional.csv", "stock.csv", "recipes.csv", "fractional-menu-count-rejected"),
        ("negative.csv", "stock.csv", "recipes.csv", "negative-plan-rejected"),
        ("duplicate-plan.csv", "stock.csv", "recipes.csv", "duplicate-plan-rejected"),
        ("missing-plan.csv", "stock.csv", "recipes.csv", "missing-recipe-in-zero-plan-rejected"),
        ("plan.csv", "unknown-stock.csv", "recipes.csv", "unknown-stock-rejected"),
        ("plan.csv", "unit-stock.csv", "recipes.csv", "incompatible-stock-dimension-rejected"),
        ("plan.csv", "duplicate-stock.csv", "recipes.csv", "duplicate-stock-rejected"),
        ("plan.csv", "stock.csv", "bad-recipes.csv", "unused-invalid-recipe-rejected"),
    ]:
        run([extra("ingredients.csv"), extra(recipe_name), extra(plan), "--stock", extra(stock_name),
             "--output-dir", out(label)], 2, label)
        assert not (output / label).exists()
    existing = destination("existing")
    (existing / "procurement.json").write_text("keep previous report", encoding="utf-8")
    run([extra("ingredients.csv"), extra("recipes.csv"), extra("fractional.csv"),
         "--output-dir", out("existing")], 2, "invalid-plan-preserves-existing-report")
    assert list(existing.iterdir()) == [existing / "procurement.json"]
    assert (existing / "procurement.json").read_text() == "keep previous report"
    for name, guard in guards:
        result = run([extra("ingredients.csv"), extra("recipes.csv"), extra("plan.csv"),
                      "--stock", extra("stock.csv"), "--output-dir", extra(guard.name)],
                     2, "hardlink-protection-" + name)
        assert "must not overwrite" in result.stderr
        assert list(guard.iterdir()) == [guard / "procurement.json"]
    assert originals == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in temp.glob("*.csv")}
    assert example_hashes == {name: hashlib.sha256((example / name).read_bytes()).hexdigest() for name in example_hashes}
    checks.append("all-input-and-example-bytes-preserved")
    code = "import json,os,sys,fnb_margin_kit.procurement_cli as m;from importlib.metadata import version;print(json.dumps({'path':m.__file__,'prefix':sys.prefix,'version':version('fnb-margin-kit'),'uid':getattr(os,'getuid',lambda:None)()}))"
    if args.container:
        interpreter = base + ["--entrypoint", "python", args.container, "-I"]
    else:
        interpreter = [sys.executable] if args.source else [str(Path(args.python).absolute()), "-I"]
    if args.source:
        code = "import json,fnb_margin_kit.procurement_cli as m;print(json.dumps({'path':m.__file__}))"
    identity = run(["-c", code], 0, "procurement-import-identity", interpreter)
    imported = json.loads(identity.stdout)
    if args.container:
        assert imported["version"] == version and imported["uid"] == 10001 and imported["path"].startswith("/usr/local/lib/")
    elif args.source:
        assert os.path.commonpath([imported["path"], str(args.source.resolve() / "src")]) == str(args.source.resolve() / "src")
    else:
        environment = str(Path(args.python).absolute().parents[1])
        assert imported["version"] == version and os.path.commonpath([imported["path"], environment]) == environment
        assert os.path.normcase(imported["prefix"]) == os.path.normcase(environment)
    assert "--stock" in run(["-m", "fnb_margin_kit.procurement_cli", "--help"], 0,
                             "procurement-module-help", interpreter).stdout
print(json.dumps({"mode": "container" if args.container else "source" if args.source else "wheel",
                  "version": version, "checks": checks, "passed": len(checks)}))
