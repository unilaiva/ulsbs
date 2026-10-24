# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Synthetic tool logs, without dependencies on the compilation pipeline."""

from dataclasses import FrozenInstanceError
from pathlib import Path
import unittest

from ulsbs.diagnostics import Diagnostic, parse_tool_warnings


class DiagnosticsTests(unittest.TestCase):
    def test_frozen_value_and_defaults(self):
        diagnostic = Diagnostic("TeX", "other", "message")
        self.assertEqual(diagnostic.occurrences, 1)
        self.assertIsNone(diagnostic.log_path)
        self.assertIsNone(diagnostic.affected_count)
        with self.assertRaises(FrozenInstanceError):
            diagnostic.message = "changed"

    def test_tex_warning_families_and_categories(self):
        text = r"""LaTeX Font Warning: Font shape `OT1/example/m/n' undefined
(Font)              using `OT1/cmr/m/n' instead on input line 4.

LaTeX Warning: Reference `verse' on page 2 undefined on input line 8.

Package example Warning: Unknown option on input line 9.
(example)                Using the default instead.

Class example Warning: Unsupported configuration.

pdfTeX warning (ext4): destination with the same identifier ignored

LuaTeX warning: font lookup failed.

Missing character: There is no X (U+0058) in font example!
Overfull \hbox (3.0pt too wide) in paragraph at lines 3--5
 []\OT1/cmr/m/n text

Overfull \vbox (2.0pt too high) detected at line 7

Underfull \hbox (badness 10000) in paragraph at lines 5--6
LaTeX Warning: An unfamiliar future diagnostic.
"""
        results = parse_tool_warnings(text, "lualatex")
        self.assertEqual([item.category for item in results], [
            "fonts", "references", "package", "package", "other", "fonts",
            "missing-glyph", "layout", "layout", "other",
        ])
        self.assertTrue(all(item.source == "TeX" for item in results))
        self.assertIn("Using the default instead.", results[2].message)
        self.assertNotIn("(example)", results[2].message)

    def test_multiline_records_and_duplicate_grouping(self):
        text = """Package demo Warning: A warning containing the word warning
(demo)                and a wrapped continuation.

Package demo Warning: A warning containing the word warning
(demo)                and a wrapped continuation.

warning: another issue
    with an indented detail
"""
        log = Path("build/tool.log")
        results = parse_tool_warnings(text, "TeX", log)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].occurrences, 2)
        self.assertEqual(results[1].occurrences, 1)
        self.assertTrue(all(item.log_path == log for item in results))
        self.assertTrue(results[1].message.endswith("with an indented detail"))

    def test_engine_pdf_and_font_warning_headers(self):
        text = """pdfTeX warning (font expansion): auto expansion is only possible with scalable fonts.

warning  (pdf backend): ignoring duplicate destination with the name 'verse'

XeTeX warning: unknown special ignored.

LuaHBTeX warning: unexpected backend option.

Fontconfig warning: unknown font family.

Package fontspec Warning: Font feature unavailable.
"""
        results = parse_tool_warnings(text, "TeX")
        self.assertEqual([item.category for item in results], [
            "fonts", "other", "other", "other", "fonts", "fonts",
        ])

    def test_complete_long_warning_does_not_swallow_progress(self):
        text = ("LaTeX Warning: An unfamiliar diagnostic with a very long description that ends here.\n"
                "Output written on book.pdf (2 pages).\n")
        results = parse_tool_warnings(text, "TeX")
        self.assertEqual(len(results), 1)
        self.assertNotIn("Output written", results[0].message)

    def test_tex_hard_wrapped_lines(self):
        text = ("LaTeX Warning: Reference `a-very-long-reference-name-that-reaches-the-wrap'\n"
                "undefined on input line 7.\n\n"
                "LaTeX Warning: There were undefined references.\n")
        results = parse_tool_warnings(text, "TeX")
        self.assertEqual(len(results), 1)
        self.assertIn("undefined on input line 7.", results[0].message)

    def test_recaps_only_removed_when_specific_records_exist(self):
        recaps = ("LaTeX Warning: There were undefined references.\n\n"
                  "LaTeX Font Warning: Some font shapes were not available, defaults substituted.\n")
        self.assertEqual(len(parse_tool_warnings(recaps, "TeX")), 2)
        specifics = ("LaTeX Warning: Reference `x' undefined on input line 3.\n\n"
                     "LaTeX Font Warning: Font shape `foo' undefined.\n\n")
        results = parse_tool_warnings(specifics + recaps, "TeX")
        self.assertEqual(len(results), 2)
        self.assertTrue(all("There were" not in item.message for item in results))
        self.assertEqual(len(parse_tool_warnings(specifics.split("\n\n")[0] + "\n\n" + recaps, "TeX")), 2)

    def test_lilypond_exact_harmless_warning_suppressed_every_time(self):
        text = """warning: Unable to auto-detect default settings
score.ly:2:3: warning: Unable to auto-detect default settings
warning: Unable to auto-detect default settings (unexpected detail)
score.ly:4:5: warning: strange new warning
score.ly:4:5: warning: strange new warning
"""
        results = parse_tool_warnings(text, "lilypond", Path("lily.log"))
        self.assertEqual(len(results), 2)
        self.assertEqual(results[1].occurrences, 2)
        self.assertTrue(all(item.source == "LilyPond" for item in results))
        self.assertIn("(unexpected detail)", results[0].message)
        self.assertEqual(len(parse_tool_warnings("warning: Unable to auto-detect default settings", "other")), 1)

    def test_generic_source_aware_headers_and_unknown_warning(self):
        text = """converter: warning: a new kind of problem
converter Warning: another problem
input.txt:12:4: warning: located problem
WARNING: generic problem
unrelated: warning: not from converter
"""
        results = parse_tool_warnings(text, "converter")
        self.assertEqual(len(results), 4)
        self.assertTrue(all(item.source == "converter" and item.category == "other" for item in results))

    def test_step_sources_accept_actual_program_names_and_barchecks(self):
        for source, program in (("Audio", "fluidsynth"), ("Images", "magick"),
                                ("Index", "songidx"), ("ConTeXt", "context")):
            with self.subTest(source=source):
                result, = parse_tool_warnings(f"{program}: warning: current issue\n", source)
                self.assertEqual(result.source, source)
        result, = parse_tool_warnings("score.ly:4:2: warning: barcheck failed\n", "LilyPond")
        self.assertEqual(result.category, "barcheck")

    def test_false_positives_and_informational_boxes(self):
        text = r"""(./warning.tex)
warning.tex
/tmp/warning:notes.ly
0 warnings
There were 0 warnings.
Output written on warning.pdf (2 pages).
This paragraph discusses a warning: but is not a header.
Underfull \hbox (badness 10000) in paragraph at lines 1--2
Underfull \vbox (badness 10000) detected at line 9
"""
        for source in ("TeX", "LilyPond", "converter"):
            with self.subTest(source=source):
                self.assertEqual(parse_tool_warnings(text, source), ())
                self.assertEqual(parse_tool_warnings("", source), ())


if __name__ == "__main__":
    unittest.main()
