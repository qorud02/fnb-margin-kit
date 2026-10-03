"""Run source-preservation regressions against the local F&B package."""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from fnb_margin_kit.cli import main

DATA = (
    "menu,category,price_gross,vat_rate,ingredient_cost,packaging_cost,platform_fee_rate,units\n"
    "coffee,drink,4400,0.10,700,100,0.03,100\n"
)


class SourcePreservationTests(unittest.TestCase):
    def check_collision(self, target_name, alias=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            source = output / target_name if alias is None else root / "menu.csv"
            source.write_text(DATA, encoding="utf-8")
            target = output / target_name
            if alias == "hardlink":
                os.link(source, target)
            elif alias == "symlink":
                try:
                    target.symlink_to(source)
                except OSError as exc:
                    self.skipTest(f"Symlink creation unavailable: {exc}")
            before = source.read_bytes()
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                result = main([str(source), "--output-dir", str(output)])
            self.assertEqual(source.read_bytes(), before, "input was overwritten")
            self.assertEqual(result, 2)
            self.assertIn("overwrite", stderr.getvalue())
            other = "report.md" if target_name == "report.json" else "report.json"
            self.assertFalse((output / other).exists(), "wrote partial report")

    def test_input_is_json_output_path(self):
        self.check_collision("report.json")

    def test_input_is_markdown_output_path(self):
        self.check_collision("report.md")

    def test_input_is_json_output_hardlink(self):
        self.check_collision("report.json", "hardlink")

    def test_input_is_markdown_output_hardlink(self):
        self.check_collision("report.md", "hardlink")

    def test_input_is_json_output_symlink(self):
        self.check_collision("report.json", "symlink")

    def test_input_is_markdown_output_symlink(self):
        self.check_collision("report.md", "symlink")


if __name__ == "__main__":
    unittest.main()
