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
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TEX_ASSETS = ROOT / "src" / "ulsbs" / "assets" / "tex"
REPEAT_RECTANGLE = re.compile(rb"(?:^|\s)1\.395\s+(-?\d+(?:\.\d+)?)\s+re\s+f(?:\s|$)")
REPEAT_STYLE = r"""
\AtBeginDocument{%
  \setlength\ulRepeatBarWidth{1.4pt}%
  \ulRepeatBarContinuationDashLength=2pt
  \ulRepeatBarContinuationDashGap=1.25pt
  \renewcommand\ulLyricFontStyle{\normalfont\fontsize{10}{12}\selectfont}%
  \ulSongColumns{1}\ulSongPosition{0}}
"""


def compile_fixture(
    name: str, *, expect_success: bool = True, preamble: str = "", passes: int = 1,
    draft_passes: int = 0, files: dict[str, bytes] | None = None, multikey: bool | None = True,
    artifacts: dict[str, bytes | None] | None = None,
) -> tuple[str, bytes]:
    source = FIXTURES / f"{name}.tex"
    with tempfile.TemporaryDirectory(prefix=f"ulsbs-test-{name}-") as temporary:
        workdir = Path(temporary)
        shutil.copy2(source, workdir / source.name)
        # Exercise the layered renderer by default; explicit fixture overrides
        # still win. Production/manual builds default to conventional notation.
        edition = "true" if multikey else "false"
        definition = "" if multikey is None else f"\\providecommand{{\\ulPdfTranspositionLayers}}{{{edition}}}\n"
        (workdir / source.name).write_text(preamble + definition + source.read_text())
        for filename, contents in (files or {}).items():
            (workdir / filename).write_bytes(contents)
        env = os.environ.copy()
        cache = env.get("TEXMFCACHE")
        if not cache:
            cache = str(workdir / "texmf-cache")
            Path(cache).mkdir()
        env["TEXINPUTS"] = f"{TEX_ASSETS}//{os.pathsep}"
        env["LUAINPUTS"] = f"{TEX_ASSETS}//{os.pathsep}"
        env["TEXMFVAR"] = cache
        env["TEXMFCACHE"] = cache
        command = [
            "lualatex",
            "-file-line-error",
            "-halt-on-error",
            "-interaction=nonstopmode",
            source.name,
        ]
        for pass_number in range(passes):
            pass_command = command[:1] + (["-draftmode"] if pass_number < draft_passes else []) + command[1:]
            result = subprocess.run(
                pass_command,
                cwd=workdir,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            if result.returncode:
                break
        if result.returncode and expect_success:
            raise AssertionError(f"LuaLaTeX failed for {source.name}:\n{result.stdout}")
        if not result.returncode and not expect_success:
            raise AssertionError(f"LuaLaTeX unexpectedly accepted {source.name}")
        pdf = workdir / f"{source.stem}.pdf"
        if not pdf.is_file() and expect_success:
            raise AssertionError(f"LuaLaTeX did not produce {pdf.name}")
        if artifacts is not None:
            for filename in artifacts:
                path = workdir / filename
                artifacts[filename] = path.read_bytes() if path.is_file() else None
        return result.stdout, pdf.read_bytes() if pdf.is_file() else b""


class CompileFixtureTests(unittest.TestCase):
    def test_source_override_preserves_assets_and_source(self):
        name = "repeat-basic"
        override = b"PREFIX\nBODY\n"
        artifacts = {f"{name}.tex": None}
        with patch("test_tex_integration.subprocess.run", return_value=
                   subprocess.CompletedProcess([], 1, "synthetic stop")) as run:
            compile_fixture(name, expect_success=False, preamble="ignored preamble\n",
                            files={f"{name}.tex": override, "idx_tag.sbx": b""},
                            artifacts=artifacts)
        for variable in ("TEXINPUTS", "LUAINPUTS"):
            self.assertEqual(run.call_args.kwargs["env"][variable], f"{TEX_ASSETS}//{os.pathsep}")
        self.assertEqual(artifacts[f"{name}.tex"], override)


class ChapterCornerMarkIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("lualatex"), "lualatex is not installed")
    def test_elbows_and_symmetric_dashes_are_filled_once_and_reused(self) -> None:
        output, pdf = compile_fixture("chapter-corner-marks", passes=2, multikey=False)
        self.assertEqual(output.count("ULSBS-TEST-MARK-BUILD"), 5)

        number = rb"-?\d+(?:\.\d+)?"
        # Match the reflected canvas transform, chapter color and paint path.
        marks = re.findall(
            rb"(?m)^(-?1(?:\.0+)?)\s+0(?:\.0+)?\s+0(?:\.0+)?\s+(-?1(?:\.0+)?)\s+"
            + number + rb"\s+" + number + rb"\s+cm\s+([01] 0 [01]) rg\s+(?:q\s+)+([^Q]+)Q",
            pdf,
        )
        self.assertEqual(len(marks), 14)  # Two per page, except the disabled last page.
        for page, (reach, rectangles) in enumerate([
            (17, []), (17, []), (5, [(8, 3), (14, 3)]), (5, [(8, 3), (14, 3)]),
            (2.6, [(3.2, 0.6), (4.4, 0.6)]), (3, [(4, 1)]), (2, []),
        ]):
            for corner in range(2):
                with self.subTest(page=page + 1, corner=corner):
                    sx, sy, color, path = marks[2 * page + corner]
                    self.assertEqual(float(sx), -1 if page % 2 == 0 else 1)
                    self.assertEqual(float(sy), -1 if corner == 0 else 1)
                    self.assertEqual(color, b"1 0 0" if page == 0 else b"0 0 1")
                    # The elbow is a single closed outline; each additional dash
                    # is a rectangle, reflected across x=y for the other leg.
                    operators = re.findall(rb"[a-zA-Z*]+", path)
                    self.assertEqual(operators, [b"m", *[b"l"] * 5, b"h",
                                                 *[b"re"] * (2 * len(rectangles)), b"f"])
                    expected = [-2, -2, reach, -2, reach, 2, 2, 2, 2, reach, -2, reach]
                    for start, length in rectangles:
                        expected.extend([start, -2, length, 4, -2, start, 4, length])
                    self.assertEqual([round(float(v), 3) for v in re.findall(number, path)], expected)


class RepeatBarIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("lualatex") is None:
            raise unittest.SkipTest("lualatex is not installed")

    def test_nested_unsplit_repeats_emit_one_rectangle_each(self) -> None:
        output, pdf = compile_fixture("repeat-basic", preamble=REPEAT_STYLE)
        self.assertNotIn("Fatal error", output)
        heights = [float(value) for value in REPEAT_RECTANGLE.findall(pdf)]
        self.assertEqual(len(heights), 3)
        self.assertTrue(all(height >= 2.1 for height in heights))

    def test_nested_split_repeats_emit_solid_segments_and_dashes(self) -> None:
        output, pdf = compile_fixture("repeat-break", preamble=REPEAT_STYLE +
                                      r"\AtBeginDocument{\setlength\textheight{200pt}}")
        self.assertNotIn("Fatal error", output)
        heights = [float(value) for value in REPEAT_RECTANGLE.findall(pdf)]
        dash_heights = [height for height in heights if height < 2.1]
        solid_heights = [height for height in heights if height >= 2.1]
        self.assertGreaterEqual(len(dash_heights), 2)
        self.assertGreaterEqual(len(solid_heights), 4)

    def test_wrapped_repeat_only_dashes_at_the_physical_break(self) -> None:
        for columns in (1, 2):
            with self.subTest(columns=columns):
                source = REPEAT_STYLE + r"""
\pdfvariable compresslevel=0
\pdfvariable objcompresslevel=0
\documentclass[paper={a5paper}]{ulsbs-songbook}
\begin{document}
""" + rf"\ulSongColumns{{{columns}}}" + r"""
\begin{ulSongs}{}
\beginsong{Wrapped repeat with a physical break}
\beginverse[1]
\beginrep
First segment\hfil\break wraps here.
\forcebrk
Last segment\hfil\break wraps here.\endrep
\endverse
\endsong
\end{ulSongs}
\end{document}
"""
                _, pdf = compile_fixture("repeat-break", files={"repeat-break.tex": source.encode()})
                heights = [float(value) for value in REPEAT_RECTANGLE.findall(pdf)]
                self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", pdf)), 3 - columns)
                self.assertEqual(sum(height < 2.1 for height in heights), 4)
                self.assertEqual(sum(height >= 2.1 for height in heights), 2)


class MelodySyntaxIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("lualatex") is None:
            raise unittest.SkipTest("lualatex is not installed")

    def test_melody_dsl_syntax_and_policies_compile(self) -> None:
        output, pdf = compile_fixture("melody-syntax")
        self.assertNotIn("Malformed melody block", output)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_verse_modifiers_restore_baseline_and_preserve_indentation(self) -> None:
        # Probe the renderer's actual indent register without a runtime alias.
        probe = (r"\ExplSyntaxOn\AddToHook{begindocument/end}"
                 r"{\cs_set_eq:cN{ulsbsTestVerseIndent}"
                 r"\l__ulsbs_verse_indent_dim}\ExplSyntaxOff" + "\n")
        output, pdf = compile_fixture("verse-modifiers", preamble=probe)
        self.assertNotIn("verse baseline", output.lower())
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
