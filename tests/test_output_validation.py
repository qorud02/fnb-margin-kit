"""Output collisions must fail before any report is created or overwritten."""

import errno
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from itertools import combinations
from pathlib import Path

from fnb_margin_kit.cli import main as margin_main
from fnb_margin_kit.recipe_cli import main as recipe_main

# Synthetic input only; no real store records.
MENU = (
    "menu,category,price_gross,vat_rate,ingredient_cost,"
    "packaging_cost,platform_fee_rate,units\n"
    "Latte,store,5500,0.1,1200,100,0.03,100\n"
)
INGREDIENTS = (
    "ingredient,purchase_quantity,purchase_unit,purchase_price,yield_rate\n"
    "coffee,1,kg,24000,1\n"
)
RECIPES = "menu,category,ingredient,quantity,unit\nLatte,store,coffee,18,g\n"
OUTPUTS = {
    "margin": ("report.json", "report.md", "report.html",
               "comparison.json", "comparison.md"),
    "recipe": ("recipe-costs.json", "recipe-costs.md",
               "menu-ingredient-costs.csv", "costed-menu.csv"),
}


class OutputValidationTests(unittest.TestCase):
    def prepare(self, root, command, extended=True):
        sources = {
            root / "menu.csv": MENU,
            root / "proposed.csv": MENU.replace("5500", "6000"),
            root / "ingredients.csv": INGREDIENTS,
            root / "recipes.csv": RECIPES,
        }
        for path, text in sources.items():
            path.write_text(text, encoding="utf-8")
        out = root / "output"
        if command == "margin":
            main = margin_main
            args = [str(root / "menu.csv")]
            if extended:
                args += ["--html", "--compare-menu", str(root / "proposed.csv")]
        else:
            main = recipe_main
            args = [str(root / "ingredients.csv"), str(root / "recipes.csv")]
            if extended:
                args += ["--menu", str(root / "menu.csv")]
        args += ["--output-dir", str(out)]
        before = {path: path.read_bytes() for path in sources}
        return main, args, out, before

    def invoke(self, main, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(args)
        return status, stdout.getvalue(), stderr.getvalue()

    def snapshot(self, out):
        return {
            path.name: None if path.is_dir() else path.read_bytes()
            for path in out.iterdir()
        }

    def assert_rejected(self, main, args, out, sources, message):
        before = self.snapshot(out)
        status, stdout, stderr = self.invoke(main, args)
        self.assertEqual(status, 2, stderr)
        self.assertEqual(stdout, "")
        self.assertIn(message, stderr)
        self.assertEqual(self.snapshot(out), before)
        self.assertEqual({path: path.read_bytes() for path in sources}, sources)

    def symlink(self, path, target):
        try:
            path.symlink_to(target)
        except NotImplementedError:
            self.skipTest("Symbolic links are unsupported")
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314 or exc.errno in (
                errno.EPERM, errno.EACCES
            ):
                self.skipTest("Symbolic link permission is unavailable")
            raise

    def check_aliases(self, kind):
        for command, names in OUTPUTS.items():
            for first, second in combinations(names, 2):
                with self.subTest(command=command, first=first, second=second):
                    with tempfile.TemporaryDirectory() as directory:
                        main, args, out, sources = self.prepare(Path(directory), command)
                        out.mkdir()
                        (out / first).write_bytes(b"previous report\n")
                        (out / "notes.txt").write_bytes(b"keep notes\n")
                        if kind == "hardlink":
                            os.link(out / first, out / second)
                        else:
                            self.symlink(out / second, first)
                        self.assert_rejected(
                            main, args, out, sources, "output files must not alias"
                        )

    def test_all_active_output_pairs_reject_hardlinks_before_writing(self):
        self.check_aliases("hardlink")

    def test_all_active_output_pairs_reject_symlinks_before_writing(self):
        self.check_aliases("symlink")

    def test_symlinks_to_same_missing_target_do_not_create_reports(self):
        for command, names in OUTPUTS.items():
            with self.subTest(command=command):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    main, args, out, sources = self.prepare(root, command)
                    out.mkdir()
                    target = root / "not-created.txt"
                    for name in names[:2]:
                        self.symlink(out / name, target)
                    link_targets = {name: (out / name).readlink() for name in names[:2]}
                    status, stdout, stderr = self.invoke(main, args)
                    self.assertEqual(status, 2, stderr)
                    self.assertEqual(stdout, "")
                    self.assertIn("output files must not alias", stderr)
                    self.assertFalse(target.exists())
                    self.assertEqual({path.name for path in out.iterdir()}, set(names[:2]))
                    for name in names[:2]:
                        self.assertEqual((out / name).readlink(), link_targets[name])
                    self.assertEqual(
                        {path: path.read_bytes() for path in sources}, sources
                    )

    def test_each_active_output_directory_preserves_existing_reports(self):
        for command, names in OUTPUTS.items():
            for invalid in names:
                with self.subTest(command=command, invalid=invalid):
                    with tempfile.TemporaryDirectory() as directory:
                        main, args, out, sources = self.prepare(Path(directory), command)
                        out.mkdir()
                        for name in names:
                            if name == invalid:
                                (out / name).mkdir()
                            else:
                                (out / name).write_bytes(b"previous report\n")
                        self.assert_rejected(
                            main, args, out, sources, "output must be a file"
                        )

    def test_late_output_directory_does_not_create_earlier_reports(self):
        for command, names in OUTPUTS.items():
            with self.subTest(command=command):
                with tempfile.TemporaryDirectory() as directory:
                    main, args, out, sources = self.prepare(Path(directory), command)
                    out.mkdir()
                    (out / names[-1]).mkdir()
                    self.assert_rejected(
                        main, args, out, sources, "output must be a file"
                    )

    def test_output_dir_must_be_a_directory(self):
        for command in OUTPUTS:
            with self.subTest(command=command):
                with tempfile.TemporaryDirectory() as directory:
                    main, args, out, sources = self.prepare(Path(directory), command)
                    out.write_bytes(b"keep existing file\n")
                    status, stdout, stderr = self.invoke(main, args)
                    self.assertEqual(status, 2, stderr)
                    self.assertEqual(stdout, "")
                    self.assertIn("output directory must be a directory", stderr)
                    self.assertEqual(out.read_bytes(), b"keep existing file\n")
                    self.assertEqual(
                        {path: path.read_bytes() for path in sources}, sources
                    )

    def test_inactive_optional_outputs_do_not_block_valid_output(self):
        for command, names in OUTPUTS.items():
            active_count = 2 if command == "margin" else 3
            for kind in ("directory", "hardlink"):
                with self.subTest(command=command, kind=kind):
                    with tempfile.TemporaryDirectory() as directory:
                        main, args, out, sources = self.prepare(
                            Path(directory), command, extended=False
                        )
                        out.mkdir()
                        (out / names[0]).write_bytes(b"previous report\n")
                        for name in names[active_count:]:
                            if kind == "directory":
                                (out / name).mkdir()
                            else:
                                os.link(out / names[0], out / name)
                        self.assertEqual(self.invoke(main, args)[0], 0)
                        json.loads((out / names[0]).read_text(encoding="utf-8"))
                        self.assertEqual(
                            {path: path.read_bytes() for path in sources}, sources
                        )

    def test_distinct_existing_outputs_are_updated_and_notes_preserved(self):
        for command, names in OUTPUTS.items():
            with self.subTest(command=command):
                with tempfile.TemporaryDirectory() as directory:
                    main, args, out, sources = self.prepare(Path(directory), command)
                    out.mkdir()
                    for name in names:
                        (out / name).write_bytes(b"previous report\n")
                    (out / "notes.txt").write_bytes(b"keep notes\n")
                    status, stdout, stderr = self.invoke(main, args)
                    self.assertEqual((status, stderr), (0, ""))
                    self.assertIn("Wrote ", stdout)
                    self.assertEqual(
                        {path.name for path in out.iterdir()}, {*names, "notes.txt"}
                    )
                    for name in names:
                        self.assertNotEqual((out / name).read_bytes(), b"previous report\n")
                    json.loads((out / names[0]).read_text(encoding="utf-8"))
                    self.assertEqual((out / "notes.txt").read_bytes(), b"keep notes\n")
                    self.assertEqual(
                        {path: path.read_bytes() for path in sources}, sources
                    )


if __name__ == "__main__":
    unittest.main()

