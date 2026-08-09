# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""LuaLaTeX compilation and generated-PDF structure tests."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TEX_ASSETS = ROOT / "src" / "ulsbs" / "assets" / "tex"
REPEAT_RECTANGLE = re.compile(rb"(?:^|\s)1\.395\s+(-?\d+(?:\.\d+)?)\s+re\s+f(?:\s|$)")


def compile_fixture(name: str) -> tuple[str, bytes]:
    source = FIXTURES / f"{name}.tex"
    with tempfile.TemporaryDirectory(prefix=f"ulsbs-test-{name}-") as temporary:
        workdir = Path(temporary)
        shutil.copy2(source, workdir / source.name)
        cache = workdir / "texmf-cache"
        cache.mkdir()
        env = os.environ.copy()
        env["TEXINPUTS"] = f"{TEX_ASSETS}//{os.pathsep}{env.get('TEXINPUTS', '')}"
        env["TEXMFVAR"] = str(cache)
        env["TEXMFCACHE"] = str(cache)
        result = subprocess.run(
            [
                "lualatex",
                "-file-line-error",
                "-halt-on-error",
                "-interaction=nonstopmode",
                source.name,
            ],
            cwd=workdir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode:
            raise AssertionError(f"LuaLaTeX failed for {source.name}:\n{result.stdout}")
        pdf = workdir / f"{source.stem}.pdf"
        if not pdf.is_file():
            raise AssertionError(f"LuaLaTeX did not produce {pdf.name}")
        return result.stdout, pdf.read_bytes()


class RepeatBarIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("lualatex") is None:
            raise unittest.SkipTest("lualatex is not installed")

    def test_nested_unsplit_repeats_emit_one_rectangle_each(self) -> None:
        output, pdf = compile_fixture("repeat-basic")
        self.assertNotIn("Fatal error", output)
        heights = [float(value) for value in REPEAT_RECTANGLE.findall(pdf)]
        self.assertEqual(len(heights), 3)
        self.assertTrue(all(height >= 2.1 for height in heights))

    def test_nested_split_repeats_emit_solid_segments_and_dashes(self) -> None:
        output, pdf = compile_fixture("repeat-break")
        self.assertNotIn("Fatal error", output)
        heights = [float(value) for value in REPEAT_RECTANGLE.findall(pdf)]
        dash_heights = [height for height in heights if height < 2.1]
        solid_heights = [height for height in heights if height >= 2.1]
        self.assertEqual(len(dash_heights), 16)
        self.assertEqual(len(solid_heights), 6)


if __name__ == "__main__":
    unittest.main()
