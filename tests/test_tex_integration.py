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


def compile_fixture(name: str, *, expect_success: bool = True) -> tuple[str, bytes]:
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
        if result.returncode and expect_success:
            raise AssertionError(f"LuaLaTeX failed for {source.name}:\n{result.stdout}")
        if not result.returncode and not expect_success:
            raise AssertionError(f"LuaLaTeX unexpectedly accepted {source.name}")
        pdf = workdir / f"{source.stem}.pdf"
        if not pdf.is_file() and expect_success:
            raise AssertionError(f"LuaLaTeX did not produce {pdf.name}")
        return result.stdout, pdf.read_bytes() if pdf.is_file() else b""


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


class MelodySyntaxIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("lualatex") is None:
            raise unittest.SkipTest("lualatex is not installed")

    def test_melody_dsl_syntax_and_policies_compile(self) -> None:
        output, pdf = compile_fixture("melody-syntax")
        self.assertNotIn("Malformed melody block", output)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_melody_only_positions_stay_aligned_during_chord_replay(self) -> None:
        output, pdf = compile_fixture("melody-replay")
        self.assertNotIn("Replayed chord has no matching chord", output)
        flattened = output.replace("\n", "")
        register = flattened.split("ULSBS-REGISTER-BEGIN:", 1)[1].split(
            ":ULSBS-REGISTER-END", 1
        )[0]
        self.assertIn("!C*", register)
        self.assertNotIn("D*", register)
        self.assertIn("E*", register)
        replay_draws = re.search(r"ULSBS-REPLAY-BEAT-DRAWS:(\d+)", output)
        hidden_draws = re.search(r"ULSBS-HIDDEN-BEAT-DRAWS:(\d+)", output)
        self.assertIsNotNone(replay_draws)
        self.assertIsNotNone(hidden_draws)
        self.assertGreater(int(replay_draws.group(1)), 0)
        self.assertEqual(int(hidden_draws.group(1)), 0)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_adjacent_melody_and_beat_layers_do_not_leak_paragraph_glue(self) -> None:
        output, pdf = compile_fixture("melody-adjacent")
        self.assertNotIn("Infinite glue shrinkage", output)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_malformed_melody_blocks_fail_clearly(self) -> None:
        for name in (
            "melody-malformed-double-secondary",
            "melody-malformed-many-secondary",
            "melody-malformed-missing-offset",
            "melody-malformed-many-offsets",
            "melody-malformed-lowercase",
            "melody-malformed-token",
            "melody-malformed-multiple-blocks",
        ):
            with self.subTest(name=name):
                output, _ = compile_fixture(name, expect_success=False)
                self.assertIn("Malformed melod", output)


class AccidentalContextIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("lualatex") is None:
            raise unittest.SkipTest("lualatex is not installed")

    def test_contextual_accidentals_and_optional_alt_transposition_compile(self) -> None:
        output, pdf = compile_fixture("accidental-contexts")
        self.assertIn("ULSBS-ALT-TRANSPOSE-COUNT:3", output)
        # One pass handles the plain body, then the opaque \id and \ac
        # arguments each get their own pass. \notrans deliberately adds none.
        self.assertEqual(output.count("ULSBS-TRANSPOSED-"), 3)
        self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
