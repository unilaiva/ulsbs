# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Body-first font allocation, lifecycle scopes and retained song assembly."""

import os
from pathlib import Path
import re
import unittest

import test_song_lifecycle as lifecycle
from test_tex_integration import ROOT


PERSIAN = r"""
\beginsong{\texorpdfstring{Wild Gazelle --- \textpersian{اهوی وحشی}}{Wild Gazelle}}
[id={wild-gazelle},by={\texorpdfstring{Faramarz Aslani --- \textpersian{فرامرز اصلانی}, Hafez --- \textpersian{حافظ}}{Faramarz Aslani, Hafez}},key={Am}]
\beginverse*
\textpersian{الا ای آهوی وحشی کجائی}
{\scriptsize\textpersian{مـرا با تـُست چندین آشـنائی}}
\endverse
\endsong
"""

SANSKRIT = r"""
\beginsong{Mahāmṛtyuñjaya Mantra \\ Oṃ Tryámbakaṃ}
[id={sanskrit},by={trad., Shantala},ex={from Upaniṣad, the first prayer}]
\beginverse*
Pūrṇamadaḥ Pūrṇamidam Oṃ Tryámbakaṃ
{\tiny Upaniṣad, Mahāmṛtyuñjaya}
\endverse
\endsong
"""


class SongOrderTests(unittest.TestCase):
    setUp = lifecycle.SongLifecycleTests.setUp
    compile_source = lifecycle.SongLifecycleTests.compile_source

    @classmethod
    def setUpClass(cls):
        lifecycle.SongLifecycleTests.setUpClass.__func__(cls)
        cls.diagnostics = Path(os.environ.get(
            "ULSBS_SONG_ORDER_DIAGNOSTICS", ROOT / "build/song-order"))
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def compile_checked(self, source, label=""):
        output = self.compile_source(source, label=label or "song-order", passes=2)
        self.assertTrue((self.book / "book.ulsbs.psv").is_file())
        return {"output": output}

    def test_multilingual_font_first_use_with_and_without_layers(self):
        for name, body in (("persian", PERSIAN), ("sanskrit", SANSKRIT)):
            for layers in (False, True):
                with self.subTest(language=name, layers=layers):
                    source = lifecycle.document(
                        r"\begin{ulSongs}{titleidx,authidx}" + "\n" + body + r"\end{ulSongs}")
                    source = (r"\def\ulPdfTranspositionLayers{" + str(layers).lower()
                              + "}\n" + source)
                    outputs = self.compile_checked(source, f"{name}-{layers}")
                    self.assertNotIn("Missing character:", outputs["output"])

    def test_prelude_precedes_postlude_for_shared_first_used_glyphs(self):
        source = lifecycle.document(r"""
\begin{ulSongs}{titleidx}
\beginsong{Shared font}[id={shared}]
\typeout{ORDER:body}\beginverse*
Body uses no rare glyphs.
\endverse\endsong\end{ulSongs}
""", r"""
\renewcommand\ulMakePrelude{\typeout{ORDER:prelude}\hbox{Oṃ}}
\renewcommand\ulMakePostlude{\typeout{ORDER:postlude}\hbox{Oṃ}}
""")
        outputs = self.compile_checked(source)
        for output in outputs.values():
            self.assertEqual(re.findall(r"ORDER:(\w+)", output),
                             ["body", "prelude", "postlude"] * 2)

    def test_hooks_keep_inner_mode_local_effects_and_once_only_source_order(self):
        output = self.compile_source(lifecycle.document(r"""
\begin{ulSongs}{titleidx}
\beginsong{Hook scope}[id={hook-scope}]
\typeout{ORDER:body-\ScopeState-\IndexState-\MarkState}
\def\ScopeState{body}\global\advance\Effects1
\beginverse*
Hook body.
\endverse\endsong
\typeout{ORDER:after-\ScopeState-\IndexState-\MarkState}
\end{ulSongs}
\typeout{EFFECTS:\the\Effects}
""", r"""
\newcount\Effects
\def\ScopeState{outside}\def\IndexState{outside}\def\MarkState{outside}
\AddToHook{ulsbs/song/begin}{%
  \ifinner\def\ProbeInner{inner}\else\def\ProbeInner{outer}\fi
  \ifvmode\def\ProbeMode{vertical}\else\def\ProbeMode{horizontal}\fi
  \typeout{ORDER:begin-\ProbeInner-\ProbeMode}%
  \def\ScopeState{begin}\global\advance\Effects1}
\AddToHook{ulsbs/song/anchor}{%
  \typeout{ORDER:anchor-\ScopeState}\def\ScopeState{anchor}\global\advance\Effects1}
\AddToHook{ulsbs/index/record}{%
  \typeout{ORDER:index-\ScopeState}\def\IndexState{index}\global\advance\Effects1}
\AddToHook{ulsbs/song/finish}{%
  \typeout{ORDER:finish-\ScopeState}\global\advance\Effects1}
\renewcommand\ulSongMark{\typeout{ORDER:mark}\def\MarkState{marked}\global\advance\Effects1}
\let\OriginalPrelude\ulMakePrelude
\renewcommand\ulMakePrelude{%
  \typeout{ORDER:prelude-\ScopeState-\MarkState}\def\ScopeState{prelude}%
  \global\advance\Effects1\OriginalPrelude}
\let\OriginalPostlude\ulMakePostlude
\renewcommand\ulMakePostlude{%
  \typeout{ORDER:postlude-\ScopeState-\MarkState}\global\advance\Effects1\OriginalPostlude}
"""), passes=2)
        expected = ["begin-inner-vertical", "anchor-begin", "index-anchor",
                    "body-anchor-outside-outside", "finish-body", "mark",
                    "prelude-anchor-marked", "postlude-anchor-marked",
                    "after-outside-outside-outside"]
        self.assertEqual(re.findall(r"ORDER:([^\n\r]+)", output), expected * 2)
        self.assertEqual(re.findall(r"EFFECTS:(\d+)", output), ["8", "8"])

    def test_selection_repeated_boxes_preserve_order_and_once_only_effects(self):
        source = lifecycle.document(r"""
\ulIncludeOnlySongs{2,1,2}
\begin{ulSongs}{titleidx}
\beginsong{First}[id={same}]
\global\advance\Effects1
\beginverse*
First selected body.
\endverse\endsong
\beginsong{Second}[id={same}]
\global\advance\Effects1
\beginverse*
Second selected body.
\endverse\endsong
\beginsong{Omitted}[id={omitted}]
\global\advance\Effects1
\beginverse*
Omitted body.
\endverse\endsong
\end{ulSongs}\typeout{EFFECTS:\the\Effects}
""", r"""
\newcount\Effects
\let\OriginalPrelude\ulMakePrelude
\renewcommand\ulMakePrelude{\global\advance\Effects1\OriginalPrelude}
\let\OriginalPostlude\ulMakePostlude
\renewcommand\ulMakePostlude{\global\advance\Effects1\OriginalPostlude}
""")
        outputs = self.compile_checked(source)
        for output in outputs.values():
            self.assertEqual(re.findall(r"EFFECTS:(\d+)", output), ["9", "9"])
        rows = [line.split("|")[1] for line in (self.book / "book.ulsbs.psv").read_text().splitlines()
                if line.startswith("ID-NR-PAGE-Y|")]
        self.assertEqual(rows, ["same-2", "same", "same-2"])
        text = lifecycle.SongLifecycleTests.pdf_text(self)
        self.assertEqual(text.count("Second selected body."), 2)
        self.assertEqual(text.count("First selected body."), 1)
        self.assertNotIn("Omitted body.", text)
        self.assertLess(text.index("Second selected body."), text.index("First selected body."))

    def test_multipage_assembly_keeps_lines_and_effect_counts(self):
        verses = "\n".join(
            r"\beginverse*" + "\n" + "\n".join(
                rf"\Effect \[C]Line {verse:02d}-{line:02d}." for line in range(5))
            + "\n" + r"\endverse" for verse in range(14))
        source = lifecycle.document(
            r"\begin{ulSongs}{titleidx}\beginsong{Long}[id={long},by={J. Author}]"
            + "\n" + verses + "\n" + r"\endsong\end{ulSongs}\typeout{EFFECTS:\the\Effects}",
            r"\newcount\Effects\def\Effect{\global\advance\Effects1 }")
        outputs = self.compile_checked(source)
        for output in outputs.values():
            self.assertEqual(re.findall(r"EFFECTS:(\d+)", output), ["70", "70"])
            self.assertNotIn(r"Overfull \vbox", output)
        text = lifecycle.SongLifecycleTests.pdf_text(self)
        for verse in range(14):
            for line in range(5):
                self.assertEqual(text.count(f"Line {verse:02d}-{line:02d}."), 1)

    def test_ordinary_comprehensive_fixture_and_basic_layout_compile(self):
        fixture = Path(__file__).parent / "fixtures/source-effects.tex"
        self.compile_checked(r"\def\ulPdfTranspositionLayers{false}" + "\n"
                     + fixture.read_text(), "comprehensive")
        self.compile_checked(lifecycle.document(r"""
\begin{ulSongs}{titleidx,authidx,tagidx}
\beginsong{Basic Layout}[id={basic},by={J. Author},tags={fire},key={Am},index={Alias}]
\beginverse
\[Am]One line.
Second line.
\endverse
\beginverse*
Another verse.
\endverse\endsong
\beginsong{Second Song}[id={second},by={Another},key={C}]
\beginverse*
\[C]Next song.
\endverse\endsong\end{ulSongs}
"""), "basic")


if __name__ == "__main__":
    unittest.main()
