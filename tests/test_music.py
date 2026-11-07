# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Token transposition and independently composed music ink."""

import os
from pathlib import Path
import re
import unittest

import test_song_lifecycle as helpers
from test_tex_integration import ROOT, compile_fixture


ADAPTER = r"""
\ExplSyntaxOn
\cs_if_exist:NF \__ulsbs_music_transpose:nN
 {\box_new:N \l__ulsbs_chord_box
  \file_input:n {ulsbs-music.code.tex}}
\ExplSyntaxOn
\NewDocumentCommand\MusicProbe{m}
 {\__ulsbs_music_transpose:nN {#1}\l_tmpa_tl
  \iow_term:x {MUSIC=[\tl_to_str:V \l_tmpa_tl]}}
\NewDocumentCommand\MusicAnnotation{m}
 {\__ulsbs_music_annotation:n {#1}\box_use:N \l__ulsbs_chord_box}
\ExplSyntaxOff
"""


class MusicTests(unittest.TestCase):
    compile_source = helpers.SongLifecycleTests.compile_source
    pdf_text = helpers.SongLifecycleTests.pdf_text
    setUp = helpers.SongLifecycleTests.setUp

    @classmethod
    def setUpClass(cls):
        helpers.SongLifecycleTests.setUpClass.__func__(cls)
        cls.diagnostics = Path(os.environ.get(
            "ULSBS_MUSIC_DIAGNOSTICS", ROOT / "build/music"))
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def test_transpose_preserves_groups_spaces_and_unexpanded_effects(self):
        output = self.compile_source(helpers.document(r"""
\transpose{2}
\MusicProbe{C m/G \textbf{F} \Effect}
\typeout{MUSIC-EFFECTS=\the\Effects}
Text.
""", ADAPTER + r"\newcount\Effects\def\Effect{\global\advance\Effects1 X}"))
        self.assertIn(r"MUSIC=[D m/A \textbf {F} \Effect ]", output)
        self.assertEqual(re.findall(r"MUSIC-EFFECTS=(\d+)", output), ["0"])

    def test_effective_key_major_minor_and_enharmonic_fallback(self):
        output = self.compile_source(helpers.document(r"""
\begin{ulSongs}{}
\beginsong{Major}[key={D}]
\transpose{2}\MusicProbe{C F G B}
\endsong
\beginsong{Minor}[key={F#m}]
\transpose{-2}\MusicProbe{G A B C D E F}
\endsong
\end{ulSongs}
""", ADAPTER))
        self.assertIn("MUSIC=[D G A C\\shrp ]", output)
        self.assertIn("MUSIC=[F G A B\\flt  C D E\\flt ]", output)

    def test_zero_preserves_enharmonic_notes_and_explicit_accidentals(self):
        output = self.compile_source(helpers.document(r"""
\MusicProbe{B\shrp C\flt F\shrp{}m/C\shrp{}}
Text.
""", ADAPTER))
        self.assertIn(r"MUSIC=[B\shrp C\flt F\shrp {}m/C\shrp {}]", output)

    def test_transposition_matches_current_policy_all_offsets_and_keys(self):
        body = [r"\begin{ulSongs}{}"]
        for key in ("C", "D", "B&", "F#", "Am", "F#m", "B&m"):
            for offset in range(-6, 7):
                body.extend((rf"\beginsong{{Policy}}[key={{{key}}}]",
                             rf"\transpose{{{offset}}}",
                             r"\MusicProbe{C C\shrp D E\flt E F F\shrp G A\flt A B\flt B}",
                             r"\endsong"))
        body.append(r"\end{ulSongs}")
        source = helpers.document("\n".join(body), ADAPTER)
        output = self.compile_source(source, label="transposition")
        rows = re.findall(r"MUSIC=\[([^\n]*)\]", output)
        self.assertEqual(len(rows), 7 * 13)
        for start in range(0, len(rows), 13):
            self.assertEqual(rows[start], rows[start + 12])
            self.assertEqual(rows[start + 6], r"C C\shrp D E\flt E F F\shrp G A\flt A B\flt B")

    def test_melody_voices_beats_offsets_and_unpitched_marks(self):
        self.compile_source(helpers.document(r"""
\begin{ulSongs}{}
\beginsong{Music}[key={C}]
\beginverse*
\MusicAnnotation{<* CDE; G_/@1em>Am} First
\ulMelodyPrimaryPosition{low}\ulMelodySecondaryPosition{below}
\MusicAnnotation{<!* C; /@-1em>G} Second
\notesoff\MusicAnnotation{<* CDE>F} Hidden
\beatsoff\MusicAnnotation{<* CDE>} Empty
\noteson\beatson\ulMelodyStyleMapping{swapped}
\MusicAnnotation{<C; G>} Last
\endverse
\endsong
\end{ulSongs}
""", ADAPTER))
        text = self.pdf_text()
        self.assertIn("First", text)
        self.assertIn("Last", text)
        self.assertIn("/", text)

    def compile_checked(self, body, preamble=""):
        source = helpers.document(body, preamble)
        output = self.compile_source(source)
        self.assertTrue(self.pdf_text().strip())
        self.assertNotIn("Missing character:", output)

    def test_melody_annotation_positions_compile(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Melody}[key={D}]
\transpose{2}
\beginverse*+
\[<* CDE; G_/@1em>Am]First \[<!* C; /@-1em>G]Second
\ulMelodyPrimaryPosition{low}\ulMelodySecondaryPosition{below}
\[<* FG; C/>F]Low \[<*>]Beat
\notesoff\[<* CDE>F]Hidden \beatsoff\[<CDE>]Invisible
\noteson\beatson\ulMelodyStyleMapping{swapped}
\[<C; G>]Last
\endverse
\endsong
\end{ulSongs}
""")

    def test_nested_repeat_and_meter_compile(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Repeats}
\beginverse*
\beginrep\prep{3}
\[C]First | \[G]Second \rep{2}
\beginrep
\lrep \[Am]Nested \rrep
\endrep
\meter{3}{4}| \[F]Last
\endrep
Outside.
\endverse
\endsong
\end{ulSongs}
""")

    def test_empty_chord_and_adjacent_melody_compile(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Cora\c{c}\~ao, luz e ora\c{c}\~ao}[key={D&},by={Jos\'e da Silva}]
\beginverse+
\[<* C D;E F @ .3em>Am]MelodyAnchor \[<A _ C;E _ G>]rest slots.
\[<!C>]ZeroAdvanceAnchor \[</>Am]unpitched \[<* @ 1em>]beat only.
\[<C>]\[<D>]AdjacentMelodyAnchor
\endverse
\endsong
\end{ulSongs}
""")

    def test_accidental_macros_groups_and_slash_bass_under_source_transposition(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Tokens}[key={E}]
\transpose{1}
\beginverse*
\[F\shrp{}m/C\shrp{}]MacroAnchor \[B\flt{}]FlatAnchor
\[F#m/C#]LiteralAnchor \[{C}m]GroupedAnchor
\endverse
\endsong
\end{ulSongs}
""")

    def test_existing_accidental_context_fixture(self):
        output, pdf = compile_fixture("accidental-contexts", multikey=False)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertNotIn("Missing character:", output)

    def test_plus_modifier_scopes_repeat_prefix_raise(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Raised repeat}
\beginverse*+
\beginrep\prep{4}
\[<C>C]RaisedAnchor
\endrep
\endverse
\beginverse*
\beginrep\prep{4}
\[G]OrdinaryAnchor
\endrep
\endverse
\endsong\end{ulSongs}
""")

    def test_missing_key_fallback_keeps_ambient_accidental_preference(self):
        for label, preference in (("default", ""), ("sharps", r"\prefersharps")):
            with self.subTest(preference=label):
                source = helpers.document(r"""
\begin{ulSongs}{}
\beginsong{Fallback}
\transpose{1}
\beginverse*
\[C]FirstFallbackAnchor \[F]SecondFallbackAnchor \[G]ThirdFallbackAnchor
\endverse
\endsong\end{ulSongs}
""", preference)
                self.compile_source(source, label=label)
                text = self.pdf_text()
                for anchor in ("FirstFallbackAnchor", "SecondFallbackAnchor", "ThirdFallbackAnchor"):
                    self.assertIn(anchor, text)


if __name__ == "__main__":
    unittest.main()
