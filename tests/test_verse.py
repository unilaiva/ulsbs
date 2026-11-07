# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stanza parsing, independent of song-lifecycle test discovery."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import unittest
import xml.etree.ElementTree as ET

import test_song_lifecycle as song_helpers
from test_tex_integration import ROOT, TEX_ASSETS


def document(body: str, preamble: str = "") -> str:
    return song_helpers.document(body, preamble)


class VerseTests(unittest.TestCase):
    # Compose the established compiler harness without inheriting its 22 tests.
    compile_source = song_helpers.SongLifecycleTests.compile_source
    pdf_text = song_helpers.SongLifecycleTests.pdf_text
    setUp = song_helpers.SongLifecycleTests.setUp

    @classmethod
    def setUpClass(cls):
        song_helpers.SongLifecycleTests.setUpClass.__func__(cls)
        cls.diagnostics = Path(os.environ.get(
            "ULSBS_VERSE_DIAGNOSTICS", ROOT / "build/verse"))
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def words(self):
        result = subprocess.run(
            ["pdftotext", "-bbox", str(self.book / "book.pdf"), "-"],
            check=True, stdout=subprocess.PIPE, text=True)
        root = ET.fromstring(result.stdout)
        return [{"text": item.text, **{key: float(value) for key, value in item.attrib.items()}}
                for item in root.iter() if item.tag.endswith("}word")]

    def word(self, text):
        matches = [word for word in self.words() if word["text"] == text]
        self.assertEqual(len(matches), 1, (text, matches))
        return matches[0]

    def test_inline_first_paragraphs_with_and_without_chords(self):
        for mode in ("chorded", "chords-off", "lyric"):
            with self.subTest(mode=mode):
                source = document(r"""
\begin{ulSongs}{}
\beginsong{Inline source}
\beginverse* Hidden chords: \[C]still lyrics.\endverse
\beginverse Inline number: \[G]still lyrics.\endverse
\beginverse*[1] Indented inline source.\endverse
\beginverse*
Physical first line.
\endverse
\endsong
\end{ulSongs}
""", r"\chordsoff" if mode == "chords-off" else "")
                if mode == "lyric":
                    source = source.replace(r"\documentclass", r"\def\ulSongbookType{lyric}\documentclass")
                self.compile_source(source, label=mode)
                text = self.pdf_text()
                for anchor in ("Hidden chords:", "Inline number:", "Indented inline source.",
                               "Physical first line."):
                    self.assertIn(anchor, text)

    def test_physical_lines_comments_groups_and_explicit_spaces(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Token semantics}
\beginverse*
First physical
Second physical
Comment% removes the newline, no inserted space
joined \textbf{grouped words} explicit\ space \% \& \#
{Groupfirst
Groupsecond} final

Afterblank
\emptyline
Afterempty
\endverse
\endsong
\end{ulSongs}
"""))
        self.assertLess(self.word("First")["yMin"], self.word("Second")["yMin"])
        self.assertIn("Commentjoined", self.pdf_text())
        self.assertIn("grouped words", self.pdf_text())
        self.assertIn("explicit space", self.pdf_text())
        self.assertLess(self.word("Groupfirst")["yMin"], self.word("Groupsecond")["yMin"])
        gap = self.word("Afterempty")["yMin"] - self.word("Afterblank")["yMin"]
        baseline = self.word("Second")["yMin"] - self.word("First")["yMin"]
        self.assertAlmostEqual(gap, 2 * baseline, delta=.03)

    def test_modifiers_indentation_plus_spacing_and_restore(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Modifiers}
\beginverse*
Plainfirst
Plainsecond
\endverse
\beginverse*+[2]
Plusfirst
Plussecond
\endverse
\beginverse*[1]
Indentfirst
Indentsecond
\endverse
\endsong
\end{ulSongs}
"""))
        plain = self.word("Plainfirst")
        plus = self.word("Plusfirst")
        indent = self.word("Indentfirst")
        self.assertAlmostEqual(plus["xMin"] - plain["xMin"],
                               2 * (indent["xMin"] - plain["xMin"]), delta=.03)
        self.assertAlmostEqual(plus["xMin"], self.word("Plussecond")["xMin"], delta=.03)
        normalgap = self.word("Plainsecond")["yMin"] - plain["yMin"]
        plusgap = self.word("Plussecond")["yMin"] - plus["yMin"]
        restoredgap = self.word("Indentsecond")["yMin"] - indent["yMin"]
        self.assertGreater(plusgap, normalgap + 3)
        self.assertAlmostEqual(normalgap, restoredgap, delta=.03)

    def test_modifier_scanner_preserves_whitespace_and_comments(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Modifier whitespace}
\beginverse * % comment between star and plus
+
[2]
Acrossfirst
Acrosssecond
\endverse
\beginverse*+[2]
Inlinefirst
Inlinesecond
\endverse
\endsong
\end{ulSongs}
"""))
        self.assertAlmostEqual(self.word("Acrossfirst")["xMin"],
                               self.word("Inlinefirst")["xMin"], delta=.03)
        across = self.word("Acrosssecond")["yMin"] - self.word("Acrossfirst")["yMin"]
        inline = self.word("Inlinesecond")["yMin"] - self.word("Inlinefirst")["yMin"]
        self.assertAlmostEqual(across, inline, delta=.03)

    def test_once_only_effects_hooks_and_number_counter(self):
        preamble = r"""
\newcount\ProbeEffects
\newcommand\Effect{\global\advance\ProbeEffects1 EFFECT}
\renewcommand\ulPrintVerseNumber[1]{V#1\space}
\setlength\ulVerseNumberWidth{20pt}
\AddToHook{ulsbs/stanza/start}{\typeout{STANZA-START=\theulVerseNumber}}
\AddToHook{ulsbs/stanza/finish}{\typeout{STANZA-FINISH=\theulVerseNumber}}
\renewcommand\ulEveryVerse{\typeout{EVERY-VERSE}}
"""
        output = self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Numbers}
\beginverse
\Effect \textbf{\Effect}
\endverse
\beginverse*
Unnumbered
\endverse
\beginverse+[1]
Lastnumbered
\endverse
\typeout{NEXT-NUMBER=\theulVerseNumber;EFFECTS=\the\ProbeEffects}
\endsong
\beginsong{Reset}
\beginverse
Resetnumber
\endverse
\endsong
\end{ulSongs}
""", preamble))
        self.assertEqual(re.findall(r"STANZA-START=(\d+)", output), ["1", "2", "2", "1"])
        self.assertEqual(re.findall(r"STANZA-FINISH=(\d+)", output), ["1", "2", "2", "1"])
        self.assertEqual(output.count("EVERY-VERSE"), 4)
        self.assertIn("NEXT-NUMBER=3;EFFECTS=2", output)
        self.assertEqual(self.pdf_text().count("EFFECT"), 2)
        self.assertIn("V2", self.pdf_text())

    def test_stanza_glue_is_one_shot_and_resets_between_songs(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Glue}
\beginverse*
Gluefirst
\glueverses
\endverse
\beginverse*
Gluesecond
\endverse
\beginverse*
Separated
\endverse
\glueverses
\endsong
\beginsong{Reset glue}
\beginverse*
Resetfirst
\endverse
\beginverse*
Resetsecond
\endverse
\endsong
\end{ulSongs}
"""))
        glued = self.word("Gluesecond")["yMin"] - self.word("Gluefirst")["yMin"]
        separated = self.word("Separated")["yMin"] - self.word("Gluesecond")["yMin"]
        reset = self.word("Resetsecond")["yMin"] - self.word("Resetfirst")["yMin"]
        self.assertAlmostEqual(separated - glued, 14 * 72 / 72.27, delta=.05)
        self.assertAlmostEqual(separated, reset, delta=.05)

    def test_long_source_line_wraps_and_newline_starts_new_paragraph(self):
        source = (r"\begin{ulSongs}{}\beginsong{Wrap}" + "\n"
                  + r"\beginverse*[2]" + "\nWrapstart " + "wrappedword " * 60
                  + "Wrapend\nNextsource\n" + r"\endverse\endsong\end{ulSongs}")
        self.compile_source(document(source))
        self.assertGreater(self.word("Wrapend")["yMin"], self.word("Wrapstart")["yMin"])
        self.assertGreater(self.word("Nextsource")["yMin"], self.word("Wrapend")["yMin"])
        self.assertAlmostEqual(self.word("Nextsource")["xMin"], self.word("Wrapstart")["xMin"], delta=.03)

    def test_fonts_multilingual_arguments_and_scoped_catcodes(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Languages}
\beginverse*
Ääni coração canción
\textit{français português suomi}
\endverse
Outside \textbf{ordinary argument} with math $x^2$.
\endsong
\end{ulSongs}
"""))
        text = self.pdf_text()
        for value in ("Ääni", "coração", "canción", "français", "português", "suomi",
                      "ordinary argument"):
            self.assertIn(value, text)

    def test_first_active_accidentals_and_literal_escapes(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Accidentals}
\beginverse*[1]
#Sharpfirst \# literalhash
&Flatfirst \& literalampersand
\endverse
\endsong
\end{ulSongs}
"""))
        text = self.pdf_text()
        self.assertIn("Sharpfirst", text)
        self.assertIn("Flatfirst", text)
        self.assertIn("# literalhash", text)
        self.assertIn("& literalampersand", text)

    def test_explicit_breaks_disobeylines_and_obeylines(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Line controls}
\beginverse*
Explicitfirst\\Explicitsecond
Physicalthird
\disobeylines
Prosefirst
Prosesecond\par
\obeylines
Restoredfirst
Restoredsecond
\endverse
\endsong
\end{ulSongs}
"""))
        self.assertLess(self.word("Explicitfirst")["yMin"], self.word("Explicitsecond")["yMin"])
        self.assertLess(self.word("Explicitsecond")["yMin"], self.word("Physicalthird")["yMin"])
        self.assertAlmostEqual(self.word("Prosefirst")["yMin"], self.word("Prosesecond")["yMin"], delta=.03)
        self.assertLess(self.word("Restoredfirst")["yMin"], self.word("Restoredsecond")["yMin"])

    def test_true_lyric_edition_plus_keeps_independent_line_metrics(self):
        source = document(r"""
\begin{ulSongs}{}
\beginsong{Lyric metrics}
\beginverse*
Lyricfirst
Lyricsecond
\endverse
\beginverse*+
Lyricplusfirst
Lyricplussecond
\endverse
\endsong
\end{ulSongs}
""", r"\AtBeginDocument{\ifulLyricOnly\typeout{TRUE-LYRIC}\fi}")
        output = self.compile_source("\\def\\ulSongbookType{lyric}\n" + source)
        self.assertIn("TRUE-LYRIC", output)
        normal = self.word("Lyricsecond")["yMin"] - self.word("Lyricfirst")["yMin"]
        plus = self.word("Lyricplussecond")["yMin"] - self.word("Lyricplusfirst")["yMin"]
        self.assertAlmostEqual(normal, plus, delta=.03)

    def test_source_line_penalties_protect_wraps_and_brk_replaces_boundary(self):
        preamble = r"""
\interlinepenalty=1371
\ulBreakPenalty=91
\AddToHook{ulsbs/stanza/finish}{\directlua{
  for n in node.traverse(tex.nest.top.head) do
    if n.id == node.id('penalty') then
      texio.write_nl('term and log','VERSE-PENALTY='..n.penalty)
    end
  end
}}
"""
        source = ("\\begin{ulSongs}{}\\beginsong{Penalties}\n\\beginverse*\n"
                  + "Wrapstart " + "manyword " * 70
                  + "Wrapend\nBoundaryone\nBoundarytwo\n\\brk\nFinal\n"
                  + r"\endverse\endsong\end{ulSongs}")
        output = self.compile_source(document(source, preamble))
        penalties = [int(value) for value in re.findall(r"VERSE-PENALTY=(-?\d+)", output)]
        self.assertIn(1371, penalties)
        self.assertIn(91, penalties)
        self.assertTrue(any(value >= 10000 for value in penalties), penalties)
        self.assertNotEqual(penalties[-1], 1371, penalties)

    def test_plain_stanza_relative_geometry(self):
        source = document(r"""
\begin{ulSongs}{}
\beginsong{Relative metrics}
\beginverse*+[2]
Anchorfirst explicit\ space
Secondline {grouped words} % retain a word space but suppress this newline
joinedwords
Thirdline
\endverse
\endsong
\end{ulSongs}
""", r"""
\renewcommand\ulEveryVerse{\typeout{VERSE-BASELINE=\the\baselineskip}}
""")
        names = ("Anchorfirst", "explicit", "space", "Secondline", "grouped", "words",
                 "joinedwords", "Thirdline")
        self.compile_source(source)
        actual = {name: self.word(name) for name in names}
        for first, second in (("Anchorfirst", "explicit"), ("explicit", "space"),
                              ("Secondline", "grouped"), ("grouped", "words"),
                              ("words", "joinedwords")):
            self.assertAlmostEqual(actual[first]["yMin"], actual[second]["yMin"], delta=.03)
            self.assertLess(actual[first]["xMax"], actual[second]["xMin"])
        self.assertLess(actual["Anchorfirst"]["yMin"], actual["Secondline"]["yMin"])
        self.assertLess(actual["Secondline"]["yMin"], actual["Thirdline"]["yMin"])

    def test_verse_boundary_penalties_and_scoped_separation(self):
        preamble = r"""
\ulVerseVersePenalty=317
\ulGluePenalty=863
\ExplSyntaxOn
\cs_new_eq:NN \test_layout_break:n \__ulsbs_layout_break:n
\cs_set_protected:Npn \__ulsbs_layout_break:n #1
  {\typeout{STANZA-BREAK=\int_eval:n{#1}}\test_layout_break:n{#1}}
\ExplSyntaxOff
"""
        output = self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Boundary controls}
\beginverse First.\endverse
\beginverse*\beginrep Repeated.\endrep\endverse
\glueverses
\beginverse Glued.\endverse
{\ulSeparateVerses
\beginverse Separate.\endverse
}
\beginverse Restored.\endverse
\endsong
\end{ulSongs}
""", preamble))
        penalties = [int(value) for value in re.findall(r"STANZA-BREAK=(-?\d+)", output)]
        self.assertEqual([value for value in penalties if value != 0], [317, 863, -10000, 317])

    def test_legacy_stanza_entrypoints_are_never_called(self):
        preamble = r"""
\ExplSyntaxOn
\clist_map_inline:nn
 {SB@beginverse,SB@endverse,SB@obeylines,SB@par,SB@@par,SB@stanzabreak,
  SB@setbaselineskip,SB@putbox,SB@loadactives}
 {\cs_set_protected:cpn {#1}{\PackageError{test}{Vendor~stanza~fallback}{}}}
\ExplSyntaxOff
"""
        output = self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Owned}
\beginverse*[1]
Owned first
Owned second
\endverse
\begin{verse*}
Environment
\end{verse*}
\endsong
\end{ulSongs}
""", preamble))
        self.assertNotIn("Vendor stanza fallback", output)
        self.assertNotIn("SB@", (TEX_ASSETS / "ulsbs-verse.code.tex").read_text())

    def test_misordered_stanza_states_fail_actionably(self):
        cases = (("outside", r"\beginverse Text", "outside"),
                 ("end", r"\begin{ulSongs}{}\beginsong{Bad}\endverse", "without"),
                 ("nested", "\\begin{ulSongs}{}\\beginsong{Bad}\n\\beginverse\n\\beginverse", "missing"),
                 ("unclosed", "\\begin{ulSongs}{}\\beginsong{Bad}\n\\beginverse\nText\n\\endsong", "missing"))
        for label, body, diagnostic in cases:
            with self.subTest(label=label):
                output = self.compile_source(document(body), label=label, failure=diagnostic)
                self.assertNotIn("Undefined control sequence", output)

    def test_music_is_owned_including_first_token_after_modifiers(self):
        for label, notation in (("chord", r"\[C]Word"), ("replay", "^Word"),
                                ("bar", "|Word"), ("transpose", r"\transpose{1}")):
            with self.subTest(label=label):
                output = self.compile_source(document(
                    "\\begin{ulSongs}{}\\beginsong{Music}\n"
                    "\\beginverse*\n\\[C]Memory\n\\endverse\n\\beginverse*+[1]\n"
                    + notation + "\n\\endverse\\endsong\\end{ulSongs}"),
                    label=label)
                self.assertNotIn("Undefined control sequence", output)


if __name__ == "__main__":
    unittest.main()
