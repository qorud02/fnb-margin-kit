"""CLI error-status regressions for cyclic filesystem paths."""

import errno
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from fnb_margin_kit.cli import main


CSV = (
    "menu,category,price_gross,vat_rate,ingredient_cost,"
    "packaging_cost,platform_fee_rate,units\n"
    "Latte,store,5500,0.10,1200,100,0,100\n"
)


class PathResolutionTests(unittest.TestCase):
    def link_to_self(self, path):
        try:
            path.symlink_to(path.name)
        except NotImplementedError:
            self.skipTest("Symbolic links are unsupported")
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314 or exc.errno in (
                errno.EPERM, errno.EACCES
            ):
                self.skipTest("Symbolic link permission is unavailable")
            raise

    def test_cyclic_input_returns_error_without_creating_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "input.csv"
            self.link_to_self(source)
            output = root / "reports"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                status = main([str(source), "--output-dir", str(output)])
            self.assertEqual(status, 2)
            self.assertIn("fnb-margin:", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
            self.assertFalse(output.exists())
            self.assertEqual(source.readlink(), Path(source.name))

    def test_cyclic_report_returns_error_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "input.csv"
            source.write_text(CSV, encoding="utf-8")
            original = source.read_bytes()
            output = root / "reports"
            output.mkdir()
            report = output / "report.json"
            self.link_to_self(report)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                status = main([str(source), "--output-dir", str(output)])
            self.assertEqual(status, 2)
            self.assertIn("fnb-margin:", stderr.getvalue())
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse((output / "report.md").exists())
            self.assertEqual(report.readlink(), Path(report.name))

    def test_resolver_runtime_error_returns_cli_error(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "input.csv"
            source.write_text(CSV, encoding="utf-8")
            original = source.read_bytes()
            output = root / "reports"
            stderr = io.StringIO()
            with patch("fnb_margin_kit.cli.Path.resolve", side_effect=RuntimeError("Symlink loop")):
                with redirect_stderr(stderr):
                    status = main([str(source), "--output-dir", str(output)])
            self.assertEqual(status, 2)
            self.assertIn("fnb-margin:", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(output.exists())

    def test_analysis_runtime_error_remains_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "input.csv"
            source.write_text(CSV, encoding="utf-8")
            output = root / "reports"
            with patch("fnb_margin_kit.cli.analyze", side_effect=RuntimeError("Analysis failure")):
                with self.assertRaisesRegex(RuntimeError, "Analysis failure"):
                    main([str(source), "--output-dir", str(output)])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
