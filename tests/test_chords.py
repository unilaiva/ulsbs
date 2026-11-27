# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Token scanning, replay, evaluation and relative layout contracts."""

from pathlib import Path
import io
import json
import os
import re
import unittest

import pikepdf

from ulsbs.multikey_ranges import check_pdf_property_resources

import test_song_lifecycle as helpers
from test_tex_integration import ROOT, compile_fixture
from test_pdf_transposition_layers import words_and_geometry
from test_pdf_transposition_layers import PdfStructure


def document(body, preamble="", *, variant="default"):
    return helpers.document(body, preamble, variant=variant)


class ChordTests(unittest.TestCase):
    compile_source = helpers.SongLifecycleTests.compile_source
    pdf_text = helpers.SongLifecycleTests.pdf_text
    setUp = helpers.SongLifecycleTests.setUp

    @classmethod
    def setUpClass(cls):
        helpers.SongLifecycleTests.setUpClass.__func__(cls)
        cls.diagnostics = Path(os.environ.get(
            "ULSBS_CHORD_DIAGNOSTICS", ROOT / "build/chords"))
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def compile_checked(self, body, preamble="", *, files=None, label="", prefix="", passes=1,
                        variant="default"):
        source = prefix + document(body, preamble, variant=variant)
        output = self.compile_source(source, label=label or "chords", files=files, passes=passes)
        # Require settled multikey aux references before Poppler inspects the PDF.
        check_pdf_property_resources(self.book / "book.pdf")
        self.assertTrue(self.pdf_text().strip())
        self.assertNotIn("Missing character:", output)
        return output

    def word_box(self, text):
        matches = [row for row in words_and_geometry((self.book / "book.pdf").read_bytes())
                   if row[1] == text]
        self.assertEqual(len(matches), 1, (text, matches))
        return matches[0]

    def test_adjacent_chords_groups_spaces_and_syllables(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Scanner}[id={scanner},key={C}]
\beginverse*
\[C]\[G]AdjacentAnchor \[F#m/C#]slash \[B&]flat \[C#]sharp.
\[C]sylla\[G]ble hy\[Am]phen-\[E7]ation \[F]{grouped lyric words}.
\[C]a\[G]narrow \[C]explicit\ \[G]space \[C]tie~word.
\[C\kern.5em]SpaceAnchor \[C\textsuperscript7]suffix.
\[F\shrp{}m/C\shrp{}]grouped \[F#\symdim7]diminished.
\endverse
\endsong
\end{ulSongs}
""")

    def test_lane_aware_spacing_uses_visual_lanes_and_preserves_anchors(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Lane spacing}[id={lane-spacing},key={F}]
\beginverse*
{\ulLaneAwareAnnotationSpacing{false}
\[<F>Fmaj7]lo\[<E>]ve\[<C>]ly Disabled
}
\[<F>]lo\[<E>]ve\[<C>]ly Control
\[<F>Fmaj7]lo\[<E>]ve\[<C>]ly Default
\[<* F>Fmaj7]lo\[<E>]ve\[<C>]ly Beat
{\ulMelodyPrimaryPosition{low}\[<F>Fmaj7]lo\[<E>]ve\[<C>]ly Low}
{\renewcommand{\ulMelodyHighHeightFactor}{4.2}\[<FFD>Fmaj7]lo\[<;E>]ve\[<;C>]ly High}
{\ulMelodySecondaryPosition{same}\[<FFD>Fmaj7]lo\[<;E>]ve\[<;C>]ly Same}
{\ulMelodySecondaryPosition{below}\[<F>Fmaj7]lo\[<;E>]ve\[<;C>]ly Below}
\[<F>Fmaj7]lo\[<E>]ve\[<C>C]ly Carry
\memorize[spacing]
\[<F>Fmaj7]lo\[<E>]ve\[<C>]ly Recorded
\replay[spacing]
^lo^ve^ly Replayed
\endverse
\endsong
\end{ulSongs}
""", r"\newchords{spacing}")
        rows = {tokens[-1]: " ".join(tokens[:-1]) for line in self.pdf_text().splitlines()
                if (tokens := line.split())}
        for label in ("Control", "Default", "Beat", "High", "Recorded", "Replayed"):
            self.assertEqual(rows[label], "lovely", rows)
        for label in ("Disabled", "Low", "Same", "Below"):
            self.assertRegex(rows[label], r"^lo\s*-\s*vely$", rows)
        self.assertRegex(rows["Carry"], r"^love\s*-\s*ly$", rows)

        # The compact word and its melody reproduce the melody-only control's
        # exact horizontal positions; the carried chord clears the first label.
        words = words_and_geometry((self.book / "book.pdf").read_bytes())
        for text in ("lo", "ve", "ly", "e", "c"):
            matches = sorted((word for word in words if word[1] == text), key=lambda w: w[3])
            control, compact = matches[1:3]
            self.assertAlmostEqual(control[2], compact[2], delta=.02)
            self.assertAlmostEqual(control[4], compact[4], delta=.02)
        _, _, next_chord_x, next_chord_y, *_ = self.word_box("C")
        previous_edge = max(w[4] for w in words if w[1] == "Fmaj7" and abs(w[3] - next_chord_y) < .1)
        self.assertGreater(next_chord_x, previous_edge)

    def test_chord_hyphen_allowance_is_configurable_and_fits_the_glyph(self):
        output = self.compile_checked(r"""
\begin{ulSongs}{}\beginsong{Hyphen allowance}[key={F}]
\beginverse*
\setbox0=\hbox{\char\hyphenchar\font}
\dimen0=0.4em\relax
\typeout{HYPHEN-WIDTH=\the\wd0;ALLOWANCE=\the\dimen0}
\[C]admi-\[C]ro NormalDefault
{\renewcommand{\ulChordHyphenAllowance}{0.4em+2pt}
\[C]admi-\[C]ro NormalWider
}
{\renewcommand{\ulChordHyphenAllowance}{0pt}
\[C]admi-\[C]ro NormalGlyph
}
\[<F>Fmaj7]lo\[<E>]ve\[<C>C]ly Default
{\renewcommand{\ulChordHyphenAllowance}{0.4em}
\[<F>Fmaj7]lo\[<E>]ve\[<C>C]ly Explicit
}
{\renewcommand{\ulChordHyphenAllowance}{0.4em+2pt}
\[<F>Fmaj7]lo\[<E>]ve\[<C>C]ly Wider
}
{\renewcommand{\ulChordHyphenAllowance}{0pt}
\[<F>Fmaj7]lo\[<E>]ve\[<C>C]ly Glyph
}
\[<F>Fmaj7]lo\[<E>]ve\[<C>C]ly Restored
\endverse\endsong\end{ulSongs}
""")
        words = words_and_geometry((self.book / "book.pdf").read_bytes())
        def position(label, text):
            _, _, _, y, *_ = self.word_box(label)
            x, = (w[2] for w in words if w[1] == text and abs(w[3] - y) < .1)
            return x

        glyph, allowance = map(float, re.search(r"HYPHEN-WIDTH=([\d.]+)pt;ALLOWANCE=([\d.]+)pt", output).groups())
        self.assertGreater(allowance, glyph)
        self.assertEqual(position("Default", "ly"), position("Explicit", "ly"))
        self.assertEqual(position("Default", "ly"), position("Restored", "ly"))
        for prefix, text in (("", "ly"), ("Normal", "ro")):
            default = position(prefix + "Default", text)
            self.assertAlmostEqual(position(prefix + "Wider", text) - default, 2 * 72 / 72.27, delta=.03)
            self.assertAlmostEqual(default - position(prefix + "Glyph", text), (allowance - glyph) * 72 / 72.27, delta=.03)
        self.assertNotIn("Overfull \\hbox", output)

    def test_lane_aware_spacing_preserves_authored_boundaries_and_wraps(self):
        source = r"""
\[<F>Fmaj7]lo-\[<E>]ve\[<C>]ly Hyphen
\[<F>Fmaj7]lo\[<E@.2em>]ve\[<C>]ly Offset
\[<F>Fmaj7]lo\[<!E>]ve\[<C>]ly Overlay
\[<F>Fmaj7]lo\[<E>]\[G]ve\[<C>]ly Adjacent
\[<F>Fmaj7]lo|\[<E>]ve\[<C>]ly Bar
\[<F>Fmaj7]lo {\notesoff\[<E>]ve}\[<C>]ly Hidden
"""
        output = self.compile_checked(r"""
\begin{ulSongs}{}\beginsong{Authored spacing}[key={F}]
\beginverse*
""" + source + r"""
{\ulLaneAwareAnnotationSpacing{false}
""" + source + r"""
}
{
\[<F>Fmaj7/G\kern2em]lo\[<E>]ve\[<C>]ly \[G]After
}
{\hsize=68pt
Earlier \[<F>Fmaj7]lo\[<E>]ve\[<C>]ly
}
\endverse\endsong\end{ulSongs}
""")
        rows = [" ".join(line.split()) for line in self.pdf_text().splitlines()]
        for label in ("Hyphen", "Offset", "Overlay", "Adjacent", "Bar", "Hidden"):
            before, after = (row for row in rows if row.endswith(" " + label))
            self.assertEqual(before, after)
        self.assertGreater(self.word_box("After")[2], self.word_box("Fmaj7/G")[4])
        self.assertIn("Earlier", rows)
        self.assertEqual(rows.count("lovely"), 1, rows)
        self.assertNotIn("Overfull \\hbox", output)

    def test_lane_aware_spacing_keeps_multikey_lyric_anchors(self):
        self.compile_checked(r"""
\begin{ulSongs}{}\beginsong{Layered spacing}[id={layered-spacing},key={F}]
\beginverse*
\[<F>Fmaj7]lo\[<E>]ve\[<C>]ly
\endverse\endsong\end{ulSongs}
""", prefix=r"\def\ulPdfTranspositionLayers{true}", passes=3)
        pdf = (self.book / "book.pdf").read_bytes()
        original = words_and_geometry(pdf)
        transposed = words_and_geometry(PdfStructure(pdf).selected_pdf(pdf, {1: 1}))
        for text in ("lo", "ve", "ly"):
            self.assertEqual([w for w in original if w[1] == text],
                             [w for w in transposed if w[1] == text])
        self.assertIn("Fmaj7", [w[1] for w in original])
        self.assertNotIn("Fmaj7", [w[1] for w in transposed])
        self.assertNotIn("-", [w[1] for w in original + transposed])

    def test_ul_space_uses_real_scaled_lyric_glue(self):
        output = self.compile_checked(r"""
\begin{ulSongs}{}\beginsong{Space measurements}
\beginverse*
\spaceskip=5pt plus 2pt minus 1pt\relax
\MeasureSpace{literal}{ }
\MeasureSpace{default}{\ulSpace}
\MeasureSpace{one}{\ulSpace[1]}
\MeasureSpace{scaled}{\ulSpace[1.5] }
\MeasureSpace{zero}{\ulSpace[0]}
\meter{}{}\[<*>]|\[C]BarZero
\meter{}{}\[<*>]\ulSpace|\[C]BarOne
\meter{}{}\[<*>]\ulSpace[1.5]|\[C]BarWide
\endverse\endsong\end{ulSongs}
""", r"""
\newcommand\MeasureSpace[2]{\setbox0=\hbox{X\spacefactor=1000\relax
  #2\skip0=\lastskip\relax\typeout{SPACE-#1=\the\skip0}}}
""")
        widths = dict(re.findall(r"SPACE-([a-z]+)=([^\r\n]+)", output))
        self.assertEqual(widths, {"literal": "5.0pt plus 2.0pt minus 1.0pt",
                                  "default": "5.0pt plus 2.0pt minus 1.0pt",
                                  "one": "5.0pt plus 2.0pt minus 1.0pt",
                                  "scaled": "7.5pt plus 3.0pt minus 1.5pt", "zero": "0.0pt"})
        bar_zero, bar_one, bar_wide = (self.word_box(label)[2]
                                      for label in ("BarZero", "BarOne", "BarWide"))
        self.assertAlmostEqual(bar_one - bar_zero, 5 * 72 / 72.27, delta=.03)
        self.assertAlmostEqual(bar_wide - bar_zero, 7.5 * 72 / 72.27, delta=.03)

    def test_ul_space_overrides_the_consecutive_measure_bar_gap(self):
        output = self.compile_checked(r"""
\begin{ulSongs}{}\beginsong{Consecutive measure spacing}
\beginverse*
\spaceskip=5pt plus 2pt minus 1pt\relax
\typeout{DEFAULT-BAR-GAP=\the\dimexpr1.2em\relax}
\meter{}{}blah blah ||Bare
blah blah | |Ordinary
blah blah |\ulSpace[0] |Zero
blah blah |\ulSpace[1] |Single
blah blah |\ulSpace[5] |Scaled
blah blah | \ulSpace[5] |Spaced
{\ulLaneAwareAnnotationSpacing{false}
blah blah |\ulSpace[0] |DisabledZero
blah blah |\ulSpace[1] |DisabledSingle
blah blah |\ulSpace[5] |DisabledScaled
}
{\renewcommand{\ulMeasureBarGap}{8pt}
blah blah ||Custom
blah blah |\ulSpace[5]|CustomScaled
}
blah blah ||Restored
\endverse\endsong\end{ulSongs}
""")
        zero = self.word_box("Zero")[2]
        default_gap = float(re.search(r"DEFAULT-BAR-GAP=([\d.]+)pt", output)[1])
        expected_gaps = {"Bare": default_gap, "Ordinary": default_gap, "Single": 5,
                         "Scaled": 25, "Spaced": 30, "DisabledZero": 0, "DisabledSingle": 5,
                         "DisabledScaled": 25, "Custom": 8, "CustomScaled": 25,
                         "Restored": default_gap}
        for label, gap in expected_gaps.items():
            with self.subTest(label=label):
                self.assertAlmostEqual(self.word_box(label)[2] - zero, gap * 72 / 72.27, delta=.03)

    def test_ul_space_marks_only_selected_word_boundaries(self):
        self.compile_checked(r"""
\begin{ulSongs}{}\beginsong{Boundary geometry}
\beginverse*
\[<C>]Tu |luz, \[<E>]tu Control
{\ulLaneAwareAnnotationSpacing{false}
\[<C>]Tu |\[Fmaj7]luz,\ulSpace\[<E>]tu Disabled
}
\[<C>]Tu |\[Fmaj7]luz, \[<E>]tu Ordinary
\[<C>]Tu |\[Fmaj7]luz,\ulSpace\[<E>]tu Marked
\[<C>]Tu |\[Fmaj7]luz,\ulSpace[1.5]\[<E>]tu Scaled
{\ulMelodyPrimaryPosition{low}\[<C>]Tu |\[Fmaj7]luz,\ulSpace\[<E>]tu Low}
\[<C>]Tu |\[Fmaj7]luz,\ulSpace\[<E @ 0pt>]tu Offset
\endverse\endsong\end{ulSongs}
""")
        words = words_and_geometry((self.book / "book.pdf").read_bytes())
        gaps, note_starts = {}, {}
        labels = ("Control", "Disabled", "Ordinary", "Marked", "Scaled", "Low", "Offset")
        for label in labels:
            _, _, _, y, *_ = self.word_box(label)
            line = {w[1]: w for w in words if w[1] in {"luz,", "tu"} and abs(w[3] - y) < .1}
            gaps[label] = line["tu"][2] - line["luz,"][4]
            note_starts[label] = line["tu"][2]
        self.assertAlmostEqual(gaps["Marked"], gaps["Control"], delta=.04)
        self.assertAlmostEqual(gaps["Scaled"], 1.5 * gaps["Control"], delta=.05)
        self.assertGreater(gaps["Ordinary"], gaps["Marked"] + 2)
        self.assertAlmostEqual(gaps["Disabled"], gaps["Ordinary"], delta=.02)
        self.assertAlmostEqual(gaps["Offset"], gaps["Ordinary"], delta=.02)
        _, _, _, low_y, *_ = self.word_box("Low")
        chord_edge = max(w[4] for w in words if w[1] == "Fmaj7" and 0 < low_y - w[3] < 15)
        self.assertGreater(note_starts["Low"], chord_edge)
        self.assertNotIn("-", [w[1] for w in words])

    def test_ul_space_wrap_reserves_the_chord_without_a_hyphen(self):
        output = self.compile_checked(r"""
\begin{ulSongs}{}\beginsong{Wrapping spaces}
\beginverse*
\hsize=32pt\setlength\ulContentIndentWidth{0pt}
\[Fmaj7]luz,\ulSpace\[<E>]tu
\[Fmaj7]luz, \[<E>]tu
\hsize=53pt
Way \[Fmaj7]luz,\ulSpace\[<E>]tu
\endverse\endsong\end{ulSongs}
""")
        words = words_and_geometry((self.book / "book.pdf").read_bytes())
        first, second, last = sorted((w for w in words if w[1] == "tu"), key=lambda w: w[3])
        first_luz, second_luz, last_luz = sorted((w for w in words if w[1] == "luz,"), key=lambda w: w[3])
        self.assertGreater(first[3], first_luz[3])
        self.assertGreater(second[3], second_luz[3])
        self.assertEqual(first[2], second[2])  # no retained space at the start of the new line
        self.assertGreater(last_luz[3], self.word_box("Way")[3])
        self.assertEqual(last[3], last_luz[3])
        self.assertNotIn("-", [w[1] for w in words])
        self.assertNotIn("Overfull \\hbox", output)

    def test_starred_space_centers_one_hyphen_across_explicit_and_replayed_ink(self):
        output = self.compile_checked(r"""
\begin{ulSongs}{}\beginsong{Continuation spaces}[key={C}]
\beginverse*\memorize
\ulLaneAwareAnnotationSpacing{false}
di|\[<C>]vi\[<*>]\ulSpace*na ExplicitBeat
di|\[<C>]vi\[Fmaj7]\ulSpace*na ExplicitChord
di|\[<C>]vi\[Fmaj7]\ulSpace*[1.5]na ExplicitWide
di|\[Fmaj7]vi\[<*>]\ulSpace*na ExplicitSingle
\[Fmaj7]luz,\ulSpace\[<E>]tu ExplicitGap
vi\ulSpace*[0]na PlainText
\endverse
\beginverse*\replay
di|^vi^\ulSpace*na ReplayBeat
di|^vi^\ulSpace*na ReplayChord
di|^vi^\ulSpace*[1.5]na ReplayWide
di|^vi^\ulSpace*na ReplaySingle
^luz,\ulSpace^tu ReplayGap
\endverse
\beginverse*
\hsize=50pt\setlength\ulContentIndentWidth{0pt}
\[<C>]vi\[Fmaj7]\ulSpace*nana
\endverse\endsong\end{ulSongs}
""")
        words = words_and_geometry((self.book / "book.pdf").read_bytes())

        def row(label):
            _, _, _, y, *_ = self.word_box(label)
            return [w for w in words if w[1] in {"vi-na", "vi", "-", "na", "luz,", "tu"}
                    and abs(w[3] - y) < .1]

        for label in ("ExplicitBeat", "ReplayBeat", "PlainText"):
            self.assertIn("vi-na", [w[1] for w in row(label)])
        geometry = {}
        for mode in ("Explicit", "Replay"):
            for case in ("Chord", "Wide", "Single"):
                label = mode + case
                left, dash, right = [w for w in row(label) if w[1] in {"vi", "-", "na"}]
                self.assertEqual([w[1] for w in (left, dash, right)], ["vi", "-", "na"])
                self.assertAlmostEqual((dash[2] + dash[4]) / 2, (left[4] + right[2]) / 2, delta=.04)
                geometry[label] = right[2] - left[4]
        for case in ("Chord", "Wide", "Single"):
            self.assertAlmostEqual(geometry["Explicit" + case], geometry["Replay" + case], delta=.04)
        self.assertGreater(geometry["ExplicitWide"], geometry["ExplicitChord"] + 1)

        # The ordinary space also compacts across a replay boundary when enabled.
        def word_gap(label):
            left, right = (w for w in row(label) if w[1] in {"luz,", "tu"})
            return right[2] - left[4]

        self.assertLess(word_gap("ReplayGap"), word_gap("ExplicitGap") - 2)
        _, _, _, wrapped_y, *_ = self.word_box("nana")
        prior_lyric = max(w[3] for w in words if w[1] == "vi" and w[3] < wrapped_y)
        self.assertTrue(any(w[1] == "-" and w[3] == prior_lyric for w in words))
        self.assertNotIn("Overfull \\hbox", output)

    def test_physical_lines_comments_and_accented_lyrics(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Lines}
\beginverse*
\[C]First physical
\[G]Second% join without a new line or a space
joined \[Am]hyv\"a\"a \[C]cora\c{c}\~ao \[G]{grouped% join
words}.
\endverse
\endsong
\end{ulSongs}
""")

    def test_lyrics_evaluate_once_with_unknown_macro_and_groups(self):
        output = self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Effects}
\beginverse*
\[C]{\Effect GroupAnchor} \[G]\Effect UngroupedAnchor
\[Am]\textbf{BoldAnchor} \[F]{\Effect AnotherAnchor}
\endverse
\endsong
\end{ulSongs}
\typeout{CHORD-EFFECTS=\the\Effects}
""", r"\newcount\Effects\def\Effect{\global\advance\Effects1 EFFECT}"))
        self.assertEqual(re.findall(r"CHORD-EFFECTS=(\d+)", output), ["3"])
        self.assertIn("GroupAnchor", self.pdf_text())

    def test_default_and_named_memorization_reset_and_exclusion(self):
        output = self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Memory}[key={C}]
\newchords{memory}
\beginverse*\memorize[memory]
\[C]First \[^Am]Excluded \[G]Second.
\endverse
\ProbeMemory{memory}
\beginverse*\replay[memory]
^First ^Second.
\endverse
\beginverse*\memorize
\[Am]Default \[F]Tail.
\endverse
\ProbeMemory{}
\beginverse*
^Default ^Tail.
\endverse
\endsong
\beginsong{Reset}
\beginverse*
\[D]Fresh.
\endverse
\ProbeMemory{}
\beginverse*
^Fresh.
\endverse
\endsong
\end{ulSongs}
""", r"""
\ExplSyntaxOn
\NewDocumentCommand\ProbeMemory{m}{%
  \prop_get:NnN \g__ulsbs_chord_memory_prop {#1}\l_tmpa_tl
  \seq_set_split:NnV \l_tmpa_seq {\__ulsbs_chord_separator:}\l_tmpa_tl
  \seq_pop_left:NN \l_tmpa_seq \l_tmpa_tl
  \iow_term:x {MEMORY=[\seq_use:Nn \l_tmpa_seq {,}]}}
\ExplSyntaxOff
""")
        self.assertEqual(re.findall(r"MEMORY=\[([^\]]*)\]", output), ["C,G", "Am,F", "D"])

    def test_unknown_register_and_replay_exhaustion_are_actionable(self):
        for label, body, error in (
            ("unknown", r"\replay[missing]", "register 'missing'"),
            ("empty", "^Missing", "no matching memorized chord"),
        ):
            with self.subTest(label=label):
                self.compile_source(document(
                    "\\begin{ulSongs}{}\\beginsong{Invalid}\n\\beginverse*\n"
                    + body + "\n\\endverse\\endsong\\end{ulSongs}"),
                    label=label, failure=error)

    def test_long_chord_whitespace_and_wraps(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Whitespace}
\beginverse*
\[C] \[Fmaj7/C] \[G]Short \[C]word.
\[C]WrappingAnchor this deliberately extended lyric line contains enough words to wrap at the song width while preserving chord alignment over the middle \[G]syllables and the final words.
\endverse
\endsong
\end{ulSongs}
""")

    def test_hidden_replay_characters_do_not_split_source_spaces(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Hidden replay}
\beginverse*
\[C]First \[G]second \[F]third \[Am]fourth.
\endverse
\beginverse*
I am open to see flowers blooming
\endverse
\beginverse*\chordsoff\notesoff\beatsoff\measuresoff
|^I ^ am |^open ^ to see flowers blooming
\endverse
\endsong
\end{ulSongs}
""")
        words = words_and_geometry((self.book / "book.pdf").read_bytes())
        for text in ("I", "am", "open", "to", "see", "flowers", "blooming"):
            matches = [row for row in words if row[1] == text]
            self.assertEqual(len(matches), 2, matches)
            self.assertAlmostEqual(matches[0][2], matches[1][2], delta=.03)

    def test_hidden_annotations_and_replay_preserve_authored_spaces(self):
        # Start in horizontal mode so disabled bars do not turn the authored
        # spaces under test into ordinary discarded paragraph-leading space.
        body = r"""
\begin{ulSongs}{}
\beginsong{Source whitespace}[id={source-whitespace},key={C}]
\meter{}{}
\beginverse*
Start| Es|tá em vo|cê
Start| As |nuvens podem
Alpha Beta Gamma Delta EpsilonZeta
\endverse
\beginverse*\memorize
Start|\[C]{} Es|tá em vo|\[F]cê
Start|\[C] As |\[G]nuvens podem
Alpha \[C] Beta Gamma\[G]{} Delta Epsilon\[F]Zeta
\endverse
\beginverse*\replay
Start|^{} Es|tá em vo|^cê
Start|^ As |^nuvens podem
Alpha ^ Beta Gamma^{} Delta Epsilon^Zeta
\endverse
\endsong\end{ulSongs}
"""
        editions = []
        for variant, prefix in (("ordinary", ""),
                                ("layers", r"\def\ulPdfTranspositionLayers{true}"),
                                ("lyric", r"\def\ulBuildVariant{lyric}")):
            for measures in ("true", "false"):
                with self.subTest(variant=variant, measures=measures):
                    source = prefix + document(
                        body.replace("Start|", "|") if measures == "true" else body,
                        r"\chordsoff\notesoff\beatsoff"
                        + rf"\ulShowMeasures{{{measures}}}")
                    if variant == "lyric":
                        source = source.replace("[oneside,", "[variants={default,lyric},oneside,", 1)
                    output = self.compile_source(source, label=f"{variant}-{measures}",
                                                 passes=3 if variant == "layers" else 2)
                    self.assertNotIn("Missing character:", output)
                    words = words_and_geometry((self.book / "book.pdf").read_bytes())
                    positions = []
                    for text in ("Está", "em", "você", "As", "nuvens", "podem",
                                 "Alpha", "Beta", "Gamma", "Delta", "EpsilonZeta"):
                        matches = [row for row in words if row[1] == text]
                        self.assertEqual(len(matches), 3, (text, matches))
                        for match in matches[1:]:
                            self.assertAlmostEqual(matches[0][2], match[2], delta=.03,
                                                   msg=(text, matches))
                            self.assertAlmostEqual(matches[0][4], match[4], delta=.03,
                                                   msg=(text, matches))
                        positions.append((text, [row[2:5:2] for row in matches]))
                    editions.append((variant, measures, positions))
        for measures in ("true", "false"):
            ordinary = next(rows for variant, policy, rows in editions
                            if variant == "ordinary" and policy == measures)
            layers = next(rows for variant, policy, rows in editions
                          if variant == "layers" and policy == measures)
            self.assertEqual(ordinary, layers)

    def test_chordless_annotations_keep_raw_replay_and_only_visible_geometry(self):
        preamble = r"""
\ulShowChords{false}
\newcount\TailEffects\newcount\LyricEffects
\def\TailEffect{\global\advance\TailEffects1 BADTAIL}
\def\LyricEffect{\global\advance\LyricEffects1 }
\ExplSyntaxOn
\NewDocumentCommand\AnnotationMetrics{m m}{
  \__ulsbs_music_annotation:n {#2}
  \iow_term:x {ANNOTATION-#1=\dim_to_decimal:n {\box_wd:N \l__ulsbs_chord_box},
    \dim_to_decimal:n {\box_ht:N \l__ulsbs_chord_box},
    \dim_to_decimal:n {\box_dp:N \l__ulsbs_chord_box}}}
\ExplSyntaxOff
"""
        body = r"""
\begin{ulSongs}{}
\beginsong{Chord policy}[id={chord-policy},key={C}]
\chordson
\beginverse*\memorize
\[<* E>C\TailEffect]First\LyricEffect \[<* F>G\TailEffect]second.
\endverse
\beginverse*\replay
{\notesoff\beatsoff ^Hidden\LyricEffect} ^Visible\LyricEffect
\endverse
\beginverse*
\AnnotationMetrics{pitch}{<* E>C\TailEffect}
{\notesoff\AnnotationMetrics{beat}{<* E>C\TailEffect}}
{\notesoff\beatsoff\AnnotationMetrics{hidden}{<* E @ 2em>C\TailEffect}}
{\notesoff\beatsoff\[C\TailEffect]Plain\LyricEffect}
\endverse
\endsong\end{ulSongs}
\ac{2}{\TailEffect}\altchords{\TailEffect}
% Hidden source is opaque even to TeX's conditional-skipping scanner.
\begin{ulSongs}{}\beginsong{Opaque source}
\beginverse*\notesoff\beatsoff
\[C\iftrue]Opaque.
\endverse\endsong\end{ulSongs}
\ac{2}{C\iftrue}\altchords{C\iftrue}
\typeout{TAIL-EFFECTS=\the\TailEffects;LYRIC-EFFECTS=\the\LyricEffects}
"""
        editions = []
        for label, prefix in (("ordinary", ""),
                              ("layers", r"\def\ulPdfTranspositionLayers{true}")):
            with self.subTest(mode=label):
                output = self.compile_checked(body, preamble, label=label, prefix=prefix,
                                              passes=3 if label == "layers" else 2)
                self.assertIn("TAIL-EFFECTS=0;LYRIC-EFFECTS=4", output)
                self.assertNotIn("BADTAIL", self.pdf_text())
                metrics = {key: tuple(map(float, values.split(",")))
                           for key, values in re.findall(r"ANNOTATION-(\w+)=([^\r\n]+)", output)}
                self.assertEqual(metrics["hidden"], (0, 0, 0))
                self.assertGreater(metrics["beat"][0], 0)
                self.assertGreater(metrics["pitch"][1], metrics["beat"][1])
                # Poppler may expose alternate-layer pitch glyphs, so compare
                # retained metrics and lyric positions, not extracted note text.
                lyrics = {"First", "second.", "Hidden", "Visible", "Plain"}
                editions.append((metrics, [row for row in words_and_geometry(
                    (self.book / "book.pdf").read_bytes()) if row[1] in lyrics]))
        self.assertEqual(editions[0], editions[1])

    def test_locally_hidden_chords_record_raw_source_for_visible_replay(self):
        output = self.compile_checked(r"""
\begin{ulSongs}{}\beginsong{Request replay}[id={request-replay},key={C}]
\beginverse*\chordsoff\memorize
\[C\Effect]HiddenSource \[G\Effect]HiddenTail
\endverse
\beginverse*\replay
^RestoredSource ^RestoredTail
\endverse
\endsong\end{ulSongs}
\typeout{VISIBLE-TAIL-EFFECTS=\the\Effects}
""", r"\newcount\Effects\def\Effect{\global\advance\Effects1 }")
        self.assertIn("VISIBLE-TAIL-EFFECTS=2", output)
        self.assertIn("RestoredSource", self.pdf_text())

    def test_melody_size_shares_circle_slots_without_measuring_visual_hooks(self):
        preamble = r"""
\newcount\SizeSymbols\newcount\SizeTags\newcount\SizeTails
\renewcommand\ulMelodySymbolStyle{\global\advance\SizeSymbols1 \color{blue}}
\renewcommand\ulMelodyTagStyle{\global\advance\SizeTags1 \fontsize{3.5pt}{4.5pt}\selectfont}
\def\SizeTail{\global\advance\SizeTails1 }
\directlua{
  function size_circles(box, attribute)
    local circles = {}
    local function walk(parent, origin)
      local x = origin
      for n in node.traverse(parent.list) do
        if n.id == node.id('hlist') then
          local radius = node.has_attribute(n, attribute)
          if radius then
            circles[\string#circles+1] = {x+n.width/2, n.width, 2*radius}
          else
            walk(n, x)
          end
        end
        if n.id == node.id('glue') then
          x = x + node.effective_glue(n, parent)
        elseif n.id == node.id('kern') then
          x = x + n.kern
        elseif n.width then
          x = x + n.width
        end
      end
    end
    walk(box, 0)
    if \string#circles == 2 then
      local a,b = circles[1],circles[2]
      texio.write_nl('SIZE-CIRCLES='..a[2]..','..a[3]..','..(b[1]-a[1]))
    end
  end
}
\ExplSyntaxOn
\NewDocumentCommand\SizeProbe{m m}{
  \__ulsbs_music_annotation:n {#2}
  \iow_term:x {SIZE-#1=\number\use:c{ulsbs@melodyslotwidth},
    \number\box_wd:N\l__ulsbs_chord_box,
    \number\wd\use:c{ulsbs@melodyprimarybox},
    \number\wd\use:c{ulsbs@melodysecondarybox},
    \the\SizeSymbols,\the\SizeTags,\the\SizeTails}
  \directlua{size_circles(tex.box[\number\use:c{ulsbs@melodyprimarybox}],
    \int_use:N\c__ulsbs_music_note_radius_attribute_int)}}
\ExplSyntaxOff
"""
        body = r"""
\begin{ulSongs}{}\beginsong{Shared note sizing}[key={C}]
\beginverse*
\SizeProbe{default}{<A B>}
{\renewcommand\ulMelodySize{\fontsize{6pt}{7pt}\selectfont}
 \SizeProbe{six}{<A B>}
 \SizeProbe{grid}{<A _ B;C / _ *>}
 {\notesoff
  \SizeProbe{hidden}{<A _ B;C / _ *>}
  \SizeProbe{neutral}{<_ _ _;_ _ _ *>}
  \beatsoff\SizeProbe{opaque}{<A _ B;C / _ *>}}
 \SizeProbe{zero}{<!A B>}
 \chordson\SizeProbe{tail}{<A B>C\SizeTail}}
{\renewcommand\ulMelodySize{\fontsize{7pt}{8pt}\selectfont}
 \SizeProbe{seven}{<A B>}}
\SizeProbe{restored}{<A B>}
Sizing anchor.
\endverse\endsong\end{ulSongs}
"""
        editions = []
        for label, prefix in (("ordinary", ""),
                              ("layers", r"\def\ulPdfTranspositionLayers{true}")):
            with self.subTest(edition=label):
                passes = 3 if label == "layers" else 2
                output = self.compile_checked(body, preamble, prefix=prefix,
                                              label=label, passes=passes)
                rows = {key: tuple(map(int, values.split(","))) for key, values in
                        re.findall(r"SIZE-(\w+)=([\d,]+)", output)}
                circles = [tuple(map(float, values.split(","))) for values in
                           re.findall(r"SIZE-CIRCLES=([\d.,]+)", output)]
                self.assertEqual(len(circles), 7 * passes)
                ratios = []
                for key, circle in zip(("default", "six", "grid", "zero", "tail",
                                        "seven", "restored"), circles[:7]):
                    width, diameter, distance = circle
                    self.assertAlmostEqual(width, rows[key][0], delta=2, msg=key)
                    steps = 2 if key == "grid" else 1
                    self.assertAlmostEqual(distance, steps * width, delta=2, msg=key)
                    if key in ("six", "seven"):
                        ratios.append((distance - diameter) / diameter)
                # Font optical sizes slightly change ex-relative padding.
                self.assertAlmostEqual(*ratios, delta=.003)
                for ratio in ratios:
                    self.assertGreater(ratio, .06)
                    self.assertLess(ratio, .09)
                for start in range(7, len(circles), 7):
                    self.assertEqual(circles[:7], circles[start:start + 7])
                self.assertLess(rows["six"][0], rows["seven"][0])
                self.assertEqual(rows["default"][:4], rows["restored"][:4])
                self.assertEqual(rows["grid"][2], rows["grid"][3])
                for key in ("grid", "hidden", "neutral", "opaque", "zero", "tail"):
                    self.assertEqual(rows[key][0], rows["six"][0])
                self.assertEqual(rows["hidden"][:4], rows["neutral"][:4])
                self.assertEqual(rows["opaque"][1:4], (0, 0, 0))
                self.assertEqual(rows["zero"][1], 0)
                self.assertEqual(rows["grid"][4:6], (8, 8))
                for key in ("hidden", "neutral", "opaque"):
                    self.assertEqual(rows[key][4:6], (8, 8))
                self.assertEqual(rows["tail"][4:], (12, 12, 1))
                self.assertEqual(rows["restored"][4:], (16, 16, 1))
                editions.append((rows, circles[:7]))
        self.assertEqual(*editions)

    def test_pitch_requests_replay_raw_source_without_hidden_hooks_or_offsets(self):
        preamble = r"""
\newcount\NoteEffects\newcount\OffsetEffects\newcount\TailEffects
\renewcommand\ulMelodySymbolStyle{\global\advance\NoteEffects1 }
\def\Offset{\directlua{tex.setcount("global","OffsetEffects",tex.count.OffsetEffects+1);tex.sprint("2em")}}
\def\TailEffect{\global\advance\TailEffects1 }
\ExplSyntaxOn
\NewDocumentCommand\AnnotationMetrics{m m}{
  \__ulsbs_music_annotation:n {#2}
  \iow_term:x {PITCH-#1=\dim_to_decimal:n {\box_wd:N \l__ulsbs_chord_box},
    \dim_to_decimal:n {\box_ht:N \l__ulsbs_chord_box},
    \dim_to_decimal:n {\box_dp:N \l__ulsbs_chord_box}}
  \iow_term:x {SLOT-#1=\dim_to_decimal:n {\use:c {ulsbs@melodyslotwidth}}}}
\ExplSyntaxOff
"""
        body = r"""
\begin{ulSongs}{}\beginsong{Pitch replay}[id={pitch-replay},key={C}]
\chordsoff\beatsoff
\beginverse*\notesoff\memorize
\[<C;E @ \Offset>G\TailEffect]HiddenSource \[<F>Am\TailEffect]HiddenTail
\endverse
\beginverse*\replay
^RestoredSource ^RestoredTail
\endverse
\typeout{REPLAY-EFFECTS:\the\NoteEffects/\the\OffsetEffects/\the\TailEffects}
\beginverse*
\AnnotationMetrics{pitch}{<C;E @ 2em>}
{\notesoff
 \AnnotationMetrics{hidden}{<C;E @ \Offset>}
 \beatson\AnnotationMetrics{beat}{<C*D>}
 \AnnotationMetrics{beatplain}{<_*_>}
 \AnnotationMetrics{beatoffset}{<C*D @ \Offset>}
 \beatsoff\AnnotationMetrics{opaque}{<C @ \iftrue>}}
\endverse
\endsong\end{ulSongs}
\typeout{FINAL-EFFECTS:\the\NoteEffects/\the\OffsetEffects/\the\TailEffects}
"""
        editions = []
        for label, prefix in (("ordinary", ""),
                              ("layers", r"\def\ulPdfTranspositionLayers{true}")):
            with self.subTest(mode=label):
                output = self.compile_checked(body, preamble, prefix=prefix, label=label,
                                              passes=3 if label == "layers" else 2)
                self.assertIn("REPLAY-EFFECTS:3/1/0", output)
                self.assertIn("FINAL-EFFECTS:5/2/0", output)
                metrics = {key: tuple(map(float, values.split(",")))
                           for key, values in re.findall(r"PITCH-(\w+)=([^\r\n]+)", output)}
                slots = {key: float(value) for key, value in
                         re.findall(r"SLOT-(\w+)=([^\r\n]+)", output)}
                self.assertEqual(metrics["hidden"], (0, 0, 0))
                self.assertEqual(metrics["opaque"], (0, 0, 0))
                self.assertEqual(metrics["beat"], metrics["beatplain"])
                self.assertGreater(metrics["beat"][0], slots["beat"])
                self.assertGreater(metrics["beatoffset"][0], metrics["beat"][0])
                self.assertGreater(metrics["pitch"][1], metrics["beat"][1])
                self.assertGreater(slots["pitch"], 0)
                self.assertEqual(len(set(slots.values())), 1)
                lyrics = {"HiddenSource", "HiddenTail", "RestoredSource", "RestoredTail"}
                editions.append((metrics, [row for row in words_and_geometry(
                    (self.book / "book.pdf").read_bytes()) if row[1] in lyrics]))
        self.assertEqual(editions[0], editions[1])

    def test_beat_policy_preserves_replay_offsets_slots_and_independent_ink(self):
        preamble = r"""
\chordsoff\notesoff
\newcount\BeatEffects\newcount\BeatInk\newcount\NoteEffects\newcount\OffsetEffects\newcount\TailEffects
\renewcommand\ulMelodySymbolStyle{\global\advance\NoteEffects1 }
\def\Offset{\directlua{tex.setcount("global","OffsetEffects",tex.count.OffsetEffects+1);tex.sprint("2em")}}
\def\TailEffect{\global\advance\TailEffects1 }
\makeatletter
\let\OriginalBeatDraw\ulsbs@melodybeatdraw
\let\OriginalBeatInk\ulsbs@bmdraw
\renewcommand\ulsbs@bmdraw{\global\advance\BeatInk1 \OriginalBeatInk}
\renewcommand\ulsbs@melodybeatdraw{%
  \ifulShowBeats\global\advance\BeatEffects1 \fi\OriginalBeatDraw}
\makeatother
\ExplSyntaxOn
\NewDocumentCommand\AnnotationMetrics{m m}{
  \__ulsbs_music_annotation:n {#2}
  \iow_term:x {BEAT-#1=\dim_to_decimal:n {\box_wd:N \l__ulsbs_chord_box},
    \dim_to_decimal:n {\box_ht:N \l__ulsbs_chord_box},
    \dim_to_decimal:n {\box_dp:N \l__ulsbs_chord_box}}
  \iow_term:x {SLOT-#1=\dim_to_decimal:n {\use:c {ulsbs@melodyslotwidth}}}}
\ExplSyntaxOff
"""
        body = r"""
\begin{ulSongs}{}\beginsong{Beat replay}[id={beat-replay},key={C}]
\beginverse*\beatsoff\memorize
\[<C*D;E*F @ \Offset>G\TailEffect]HiddenSource \[<_*>Am\TailEffect]HiddenTail
\endverse
\typeout{HIDDEN-EFFECTS:\the\BeatEffects/\the\NoteEffects/\the\OffsetEffects/\the\TailEffects}
\typeout{HIDDEN-BEAT-INK:\the\BeatInk}
\beginverse*\replay\beatson
^RestoredSource ^RestoredTail
\endverse
\typeout{REPLAY-EFFECTS:\the\BeatEffects/\the\NoteEffects/\the\OffsetEffects/\the\TailEffects}
\typeout{REPLAY-BEAT-INK:\the\BeatInk}
\beginverse*
\AnnotationMetrics{beat}{<C*D>}
\AnnotationMetrics{emptygrid}{<_*_>}
\AnnotationMetrics{offset}{<C*D @ \Offset>}
{\beatsoff\AnnotationMetrics{hidden}{<C*D @ \iftrue>}}
{\noteson\AnnotationMetrics{pitch}{<*C @ \Offset>}}
{\beatsoff\chordson\AnnotationMetrics{chord}{<* @ \iftrue>C\TailEffect}}
\endverse
\endsong\end{ulSongs}
\typeout{FINAL-EFFECTS:\the\NoteEffects/\the\OffsetEffects/\the\TailEffects}
"""
        for permission in ("true", "false"):
            editions = []
            allowed = permission == "true"
            for label, prefix in (("ordinary", ""),
                                  ("layers", r"\def\ulPdfTranspositionLayers{true}")):
                with self.subTest(permission=permission, edition=label):
                    output = self.compile_checked(
                        body, preamble + rf"\ulShowBeats{{{permission}}}",
                        prefix=prefix, label=permission + "-" + label,
                        passes=3 if label == "layers" else 2)
                    self.assertIn("HIDDEN-EFFECTS:0/0/0/0", output)
                    self.assertIn("HIDDEN-BEAT-INK:0", output)
                    self.assertIn(f"REPLAY-EFFECTS:{3 * allowed}/0/{int(allowed)}/0", output)
                    self.assertIn(f"REPLAY-BEAT-INK:{5 * allowed}", output)
                    self.assertIn(f"FINAL-EFFECTS:1/{2 * allowed + 1}/1", output)
                    metrics = {key: tuple(map(float, values.split(",")))
                               for key, values in re.findall(r"BEAT-(\w+)=([^\r\n]+)", output)}
                    slots = {key: float(value) for key, value in
                             re.findall(r"SLOT-(\w+)=([^\r\n]+)", output)}
                    self.assertEqual(metrics["hidden"], (0, 0, 0))
                    self.assertEqual(metrics["beat"], metrics["emptygrid"])
                    self.assertGreater(metrics["chord"][0], 0)
                    self.assertGreater(metrics["pitch"][0], 0)
                    if allowed:
                        self.assertGreater(metrics["beat"][0], slots["beat"])
                        self.assertGreater(metrics["offset"][0], metrics["beat"][0])
                        self.assertGreater(metrics["pitch"][1], metrics["beat"][1])
                    else:
                        for key in ("beat", "emptygrid", "offset"):
                            self.assertEqual(metrics[key], (0, 0, 0))
                    self.assertGreater(slots["beat"], 0)
                    self.assertEqual(len(set(slots.values())), 1)
                    lyrics = {"HiddenSource", "HiddenTail", "RestoredSource", "RestoredTail"}
                    editions.append((metrics, [row for row in words_and_geometry(
                        (self.book / "book.pdf").read_bytes()) if row[1] in lyrics]))
            self.assertEqual(editions[0], editions[1])

    def test_empty_beat_anchors_keep_lyric_lane_without_a_full_chord_row(self):
        preamble = r"""
\newbox\LaneBox
\newcount\LaneEffects
\def\LaneEffect{\global\advance\LaneEffects1 }
\newattribute\LaneAttribute
\edef\LaneAttributeNumber{\the\allocationnumber}
\makeatletter
\let\LaneOriginalBeat\ulsbs@bmdraw
\renewcommand\ulsbs@bmdraw{\hbox attr \LaneAttributeNumber\space 1{\LaneOriginalBeat}}
\makeatother
\directlua{
  function beat_lane(box, label)
    local positions = {}
    local function walk(parent, baseline)
      local vertical = parent.id == node.id('vlist')
      local cursor = baseline + parent.height
      for n in node.traverse(parent.head) do
        if n.id == node.id('hlist') or n.id == node.id('vlist') then
          local y = vertical and (cursor - n.height) or (baseline - n.shift)
          if node.has_attribute(n, \LaneAttributeNumber) == 1 then
            positions[\string#positions + 1] = y
          else walk(n, y) end
          if vertical then cursor = cursor - n.height - n.depth end
        elseif vertical and n.id == node.id('glue') then cursor = cursor - n.width
        elseif vertical and n.id == node.id('kern') then cursor = cursor - n.kern end
      end
    end
    walk(box, 0)
    texio.write_nl('LANE-' .. label .. ':' .. box.height .. ':' .. box.depth
      .. ':' .. table.concat(positions, ','))
    % write_nl starts a line; finish it before TeX appends shipout progress.
    texio.write_nl('')
  end
  local verse = 0
  % The isolated boxes above have nominal geometry; check collisions only
  % after the retained physical lines have been aligned and fitted.
  local finish = ulsbs_music.finish_verse
  ulsbs_music.finish_verse = function(id)
    finish(id)
    if lane_audit then
      for line in node.traverse_id(node.id('hlist'), tex.box[id].list) do
        if (node.getproperty(line) or {}).ulsbs_music then
          verse = verse + 1
          beat_lane(line, 'verse' .. verse)
        end
      end
    end
  end
}
\newcommand\LaneProbe[2]{\setbox\LaneBox=\hbox{#2}%
  \directlua{beat_lane(tex.box[\number\LaneBox], '#1')}\box\LaneBox\quad}
"""
        body = r"""
\begin{ulSongs}{}\beginsong{Beat lane}[id={beat-lane},key={C}]
\beginverse*
\LaneProbe{lyric}{\[<*>]X} \LaneProbe{empty}{\[<*>]{}} \LaneProbe{space}{\[<*>] }
\LaneProbe{control}{\[<*>]\relax} \LaneProbe{groupend}{\[<*>]}
\LaneProbe{chord}{\[C]X} \LaneProbe{nolyrics}{\nolyrics\[<*>]{}}
\LaneProbe{plainchord}{\nolyrics\[C]} \LaneProbe{rawchord}{\ulChordFont C}
\LaneProbe{effect}{\[<*>]{\LaneEffect}} \LaneProbe{hidden}{\beatsoff\[<*>]{}}
\LaneProbe{mixed}{\[<*>C]X} \LaneProbe{mixedempty}{\[<*>C]{}}
\LaneProbe{lowercase}{\[<*>]x} \LaneProbe{ascender}{\[<*>]ffl}
\endverse
\directlua{lane_audit=true}
\beginverse* X \[<*>]\endverse
\beginverse*\nolyrics\[<*>]\endverse
% The beat's visual lead extends past a narrow rule; give it overlapping ink.
\beginverse*\[<*>]{\rule{6pt}{18pt}a}\endverse
\directlua{lane_audit=false}
\endsong\end{ulSongs}
\typeout{LANE-EFFECTS:\the\LaneEffects}
"""
        editions = []
        for label, prefix in (("ordinary", ""),
                              ("layers", r"\def\ulPdfTranspositionLayers{true}")):
            with self.subTest(edition=label):
                passes = 3 if label == "layers" else 2
                output = self.compile_checked(body, preamble, prefix=prefix, label=label, passes=passes)
                self.assertEqual(re.findall(r"LANE-EFFECTS:(\d+)", output), ["1"] * passes)
                metrics = {name: (int(height), int(depth), tuple(map(int, beats.split(',')))
                                 if beats else ())
                           for name, height, depth, beats in re.findall(
                               r"LANE-(\w+):(\d+):(\d+):([^\r\n]*)", output)}
                lane = metrics["lyric"][2]
                self.assertEqual(len(lane), 1, metrics)
                for name in ("empty", "space", "control", "groupend", "nolyrics", "effect",
                             "lowercase", "ascender", "verse1", "verse2"):
                    self.assertEqual(metrics[name][2], lane, (name, metrics))
                    self.assertLess(metrics[name][0], metrics["chord"][0], metrics)
                self.assertEqual(metrics["plainchord"][2], ())
                self.assertEqual(metrics["plainchord"], metrics["rawchord"])
                self.assertEqual(metrics["hidden"], (0, 0, ()))
                self.assertEqual(metrics["mixed"][2], metrics["mixedempty"][2])
                self.assertEqual(metrics["mixed"][2], lane)
                self.assertGreater(metrics["verse3"][2][0], 18 * 65536)
                editions.append(metrics)
                self.assertEqual(len(PdfStructure((self.book / "book.pdf").read_bytes()).layers),
                                 12 if prefix else 0)
        self.assertTrue(all(metrics == editions[0] for metrics in editions[1:]))

    def test_denied_beats_leave_no_phantom_height_or_offset_effects(self):
        body = r"""
\beatson
\begin{ulSongs}{}\beginsong{Denied beats}[key={C}]
\beginverse*
Plainfirst
Plainsecond
\endverse
\beginverse*+
\[<C*D @ \iftrue>]Hiddenfirst
\[<_* @ \iftrue>]Hiddensecond
\endverse
\endsong\end{ulSongs}
"""
        preamble = r"\ulShowBeats{false}\chordsoff\notesoff"
        output = self.compile_checked(body, preamble)
        plain = self.word_box("Plainsecond")[3] - self.word_box("Plainfirst")[3]
        hidden = self.word_box("Hiddensecond")[3] - self.word_box("Hiddenfirst")[3]
        self.assertAlmostEqual(plain, hidden, delta=.03)
        self.assertAlmostEqual(self.word_box("Plainfirst")[2],
                               self.word_box("Hiddenfirst")[2], delta=.03)
        # Compare any song-layout warnings with the same all-plain source, not
        # an unrelated promise that the surrounding layout never diagnoses.
        control = self.compile_checked(re.sub(r"\\\[.*?\]", "", body), preamble, label="plain")
        diagnostic = r"Overfull \\[hv]box \([^)]+\)"
        self.assertEqual(re.findall(diagnostic, output), re.findall(diagnostic, control))

    def test_denied_pitches_cannot_leak_payloads_or_extra_clearance(self):
        output = self.compile_checked(r"""
\noteson
\begin{ulSongs}{}\beginsong{Denied pitches}[id={denied-pitches},key={C}]
\beginverse*
Plainfirst
Plainsecond
\endverse
\beginverse*+
{\chordsoff\beatsoff\[<C;E @ \iftrue>]Hiddenfirst}
{\chordsoff\beatsoff\[<C;E @ \iftrue>]Hiddensecond}
\endverse
\beginverse*\beatsoff
\[<C @ \iftrue>G\TailEffect]ChordSurvives
\endverse
\beginverse*\chordsoff
\[<C*D>]Beatfirst
\[<_*_>]Beatsecond
\endverse
\endsong\end{ulSongs}
\typeout{DENIED-EFFECTS:\the\NoteEffects/\the\TailEffects}
""", r"""
\ulShowNotes{false}
\newcount\NoteEffects\newcount\TailEffects
\renewcommand\ulMelodySymbolStyle{\global\advance\NoteEffects1 }
\def\TailEffect{\global\advance\TailEffects1 }
""")
        self.assertIn("DENIED-EFFECTS:0/1", output)
        plain = self.word_box("Plainsecond")[3] - self.word_box("Plainfirst")[3]
        hidden = self.word_box("Hiddensecond")[3] - self.word_box("Hiddenfirst")[3]
        self.assertAlmostEqual(plain, hidden, delta=.03)
        self.assertIn("ChordSurvives", self.pdf_text())

    def test_hidden_and_beat_only_lines_do_not_reserve_chord_height(self):
        self.compile_checked(r"""
\begin{ulSongs}{}\beginsong{Compact}
\beginverse*
Plainfirst
Plainsecond
\endverse
\beginverse*\chordsoff\notesoff\beatsoff
\[<* E>C]Hiddenfirst
\[<* E>C]Hiddensecond
\endverse
\beginverse*\chordsoff\notesoff
\[<*>C]Beatfirst
\[<*>C]Beatsecond
\endverse
\beginverse*\chordsoff
\[<E>C]Pitchfirst
\[<E>C]Pitchsecond
\endverse
\beginverse*
\[C]Chordfirst
\[C]Chordsecond
\endverse
\endsong\end{ulSongs}
""")
        gaps = {kind: self.word_box(kind + "second")[3] - self.word_box(kind + "first")[3]
                for kind in ("Plain", "Hidden", "Beat", "Pitch", "Chord")}
        self.assertAlmostEqual(gaps["Plain"], gaps["Hidden"], delta=.03)
        self.assertLess(gaps["Beat"], gaps["Chord"])
        self.assertLess(gaps["Beat"], gaps["Pitch"])

    def test_trailing_alternate_lyrics_keep_right_alignment_at_song_end(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Trailing alternate}
\beginverse*
\[C]First lyric line.
\endverse
\altlyr{Crying, praying\ldots}
\endsong
\end{ulSongs}
""")
        first, alternate = self.word_box("First"), self.word_box("Crying,")
        self.assertEqual(first[0], alternate[0])
        self.assertLess(first[2], alternate[2])
        self.assertLess(first[3], alternate[3])

    def test_horizontal_note_entry_preserves_trailing_alternate_alignment(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Horizontal note}
\beginverse*
\[C]First lyric line.
\endverse
\altlyr{una hija, una nina, hermana}
\attachednote{Following note}
\beginverse*
\[G]Next lyric line.
\endverse
\endsong
\end{ulSongs}
""")
        alternate, note, following = (self.word_box(word) for word in ("hermana", "Following", "Next"))
        self.assertGreater(alternate[2], following[2])
        self.assertLess(alternate[3], note[3])
        self.assertLess(note[3], following[3])

    def test_explicit_group_end_is_a_lyric_word_boundary(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Grouped first note}
\beginverse*
\ilsl{\[^<F#>]\'E} \[<*>]a force of the wind.
{\[^<F#>]\'E} \[<*>]a conventional brace group.
\begingroup\[^<F#>]\'E\endgroup\[<*>]a direct group boundary.
\endverse
\endsong\end{ulSongs}
""")

    def test_wrapped_note_keeps_caller_leading_and_evaluates_once(self):
        output = self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Wrapped note}
\beginverse*
\[C]First lyric line.
\endverse
\begin{translation}[EN]
Translated first line.
\end{translation}
\attachednote{\Effect This deliberately extended prose note contains enough words
to wrap across several lines while preserving the caller's paragraph leading
and the independently selected note font throughout the whole paragraph.}
\attachednote{Short control.}
\endsong\end{ulSongs}
\typeout{NOTE-EFFECTS=\the\Effects}
""", r"\newcount\Effects\def\Effect{\global\advance\Effects1 }")
        self.assertEqual(re.findall(r"NOTE-EFFECTS=(\d+)", output), ["1"])

    def test_excluded_melody_phantom_and_multiline_echo_evaluate_once(self):
        output = self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Melody and echo}[key={Am}]
\beginverse*
\[^<E>]We are \[<A>Am]all related.
\echo{\Effect First echo source line.
Second echo source line.
Third echo source line.}
\endverse
\endsong\end{ulSongs}
\typeout{ECHO-EFFECTS=\the\Effects}
""", r"\newcount\Effects\def\Effect{\global\advance\Effects1 }")
        self.assertEqual(re.findall(r"ECHO-EFFECTS=(\d+)", output), ["1"])

    def test_true_lyrics_first_bar_and_explicit_measure_controls(self):
        body = r"""
\begin{ulSongs}{}
\beginsong{Initial measure}
\beginverse*
|\[C]First lyric line | without further bars.
\endverse
\beginverse*
|Second first-token bar | and ignored later bar.
\endverse
\measureson
\beginverse*
|Explicitly enabled | bars.
\meter{3}{4}| Next meter.
\measuresoff
\mbar{7}{8}Hidden direct bar. | Hidden active bar.
\endverse
\endsong\end{ulSongs}
"""
        self.compile_checked(body, label="-lyrics", variant="lyric")
        self.compile_checked(body, label="-ordinary")

    def test_effective_measures_control_first_tokens_live_catcodes_and_source_spaces(self):
        preamble = r"""
\newcount\MeterCalls
\renewcommand{\ulMeterFont}{\global\advance\MeterCalls1\tiny\sffamily}
\begingroup\catcode`\|=13
\gdef\PretokenizedBar{|}
\endgroup
"""
        body = r"""
\begin{ulSongs}{}
\beginsong{Measure source}[key={C}]
\beginverse*|Alpha | Beta tail
\endverse
\beginverse*
\ulLocalShow{measures}{false}Alpha | Beta tail
\PretokenizedBar\measurebar\mbar{\iftrue}{\input{missing-meter}}\e
\ulLocalShow{measures}{true}|
{\measuresoff |\PretokenizedBar}|
\measuresoff |
\endverse
\beginverse*|Restored verse
\endverse
\typeout{METER-CALLS=\the\MeterCalls}
\endsong\end{ulSongs}
"""
        # A denied pre-tokenized first bar must leave exactly the plain lyric geometry.
        for label, prefix in (("ordinary", ""),
                              ("layers", r"\def\ulPdfTranspositionLayers{true}")):
            with self.subTest(mode=label):
                self.compile_checked(body, preamble + r"\ulShowMeasures{false}",
                                     prefix=prefix, label=label + "-denied",
                                     passes=3 if label == "layers" else 1)
                denied_words = words_and_geometry((self.book / "book.pdf").read_bytes())
                self.assertIn("METER-CALLS=0", (self.book / "book.log").read_text())
                for word in ("Alpha", "Beta", "tail"):
                    matches = [row for row in denied_words if row[1] == word]
                    self.assertEqual(len(matches), 2)
                    self.assertAlmostEqual(matches[0][2], matches[1][2], delta=.03)
                self.compile_checked(body, preamble, prefix=prefix, label=label + "-allowed",
                                     passes=3 if label == "layers" else 1)
                # Two initial bars, two live re-enablings, then the restored stanza.
                self.assertIn("METER-CALLS=10", (self.book / "book.log").read_text())

    def test_explicit_paragraphs_and_empty_lines_keep_break_costs(self):
        lines = []
        for index in range(65):
            lines.append(rf"\Effect Physical line {index} with words.")
            if index % 4 == 2:
                lines.append(r"\emptyline")
            if index % 7 == 3:
                lines.append(r"Explicit paragraph\par Following paragraph\par")
        body = (r"\begin{ulSongs}{}\beginsong{Paragraph break costs}" + "\n"
                + r"\beginverse*" + "\n" + "\n".join(lines)
                + "\n" + r"\endverse\endsong\end{ulSongs}"
                + r"\typeout{PAR-EFFECTS=\the\Effects}")
        for variant, label in (("default", "ordinary"), ("lyric", "lyrics")):
            with self.subTest(label=label):
                output = self.compile_checked(body, r"\newcount\Effects\def\Effect{\global\advance\Effects1 }",
                                      variant=variant, label=label)
                self.assertEqual(re.findall(r"PAR-EFFECTS=(\d+)", output), ["65"])

    def test_physical_and_explicit_paragraph_ends_are_chord_word_boundaries(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Line-ending short syllables}
\beginverse*\memorize
\[Am7/G]a
\[F#m/C#]i\par
\[<C>Am]o
\endverse
\beginverse*
^a
^i\par
^o
\endverse
\endsong\end{ulSongs}
""")

    def test_inline_and_alternate_chords(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Alternates}[key={C}]
\transpose{2}
\beginverse*
\[\ac{1}{C} \ac{2}{Am}]Main \[G]line \altchords{\id[2]{Peter (D) \capo{2}}|D |A |\ac{2}{Bm} |\notrans{G}}
\endverse
\musicnote{Inline \ac{1}{C} and \ac{2}{G}.}
\endsong
\end{ulSongs}
""")
        self.assertIn("capo 2", " ".join(self.pdf_text().split()))

    def test_alternate_set_policy_has_lazy_zero_geometry_and_independent_inline_ac(self):
        preamble = r"""
\ulShowKey{false}
\newcount\SetEffects\newcount\IdEffects\newcount\NumberEffects\newcount\ChordEffects
\def\SetEffect{\global\advance\SetEffects1 C}
\def\IdEffect{\global\advance\IdEffects1 Label}
\def\NumberEffect{\global\advance\NumberEffects1 2}
\def\ChordEffect{\global\advance\ChordEffects1 D}
\makeatletter
\newcommand\DirectId[2]{\ulsbs@altchordsid[#1]{#2}}
\newcommand\ProbeColor[1]{\extractcolorspec{ulsbs@currentaltchordcolor}\CurrentColor
  \typeout{COLOR-#1:\CurrentColor}}
\makeatother
\newcommand\Metrics[2]{\setbox0=\hbox{#2}%
  \typeout{SET-#1:\the\wd0,\the\ht0,\the\dp0}}
\newcommand\SetMetrics[2]{\setbox0=\vbox{#2}%
  \typeout{SET-#1:\the\wd0,\the\ht0,\the\dp0}}
\newcommand\NoSet[1]{}
"""
        snapshots = []
        for permission in ("true", "false"):
            for layers in (False, True):
                with self.subTest(permission=permission, layers=layers):
                    cases = []
                    for request in ("true", "false"):
                        for chords in ("true", "false"):
                            label = f"{request}-{chords}"
                            visible = permission == request == chords == "true"
                            payload = (r"\id[2]{\IdEffect}|\SetEffect |\ac{\NumberEffect}{\ChordEffect}"
                                       if visible else
                                       r"\id[\input{missing-id.tex}\iftrue]{\iffalse}"
                                       r"\input{missing-set.tex}\iftrue")
                            cases.append("{" + rf"\ulLocalShow{{altchords}}{{{request}}}"
                                         + rf"\ulLocalShow{{chords}}{{{chords}}}" + "\n"
                                         + rf"\SetMetrics{{{label}}}{{\altchords{{{payload}}}}}" + "\n"
                                         + ("" if visible else r"""
\Metrics{direct-hidden}{\DirectId{\input{missing-number.tex}\iftrue}{\iffalse}}
\Metrics{vertical-hidden}{\vbox{\altchords{\input{missing-vertical.tex}\iftrue}}}
""") + "}")
                    body = r"""
\begin{ulSongs}{}
\beginsong{Standalone only}[id={standalone},key={C}]
\ProbeColor{before}
""" + "\n".join(cases) + r"""
\ProbeColor{after}
\beginverse*
{\ulLocalShow{altchords}{false}
\Metrics{spaces}{First \altchords{\iftrue} Last}
\Metrics{control}{First \NoSet{\iftrue} Last}}
StandaloneAnchor.
\endverse
\endsong
\beginsong{Inline repetition}[id={inline},key={C}]
\ulLocalShow{altchords}{false}
\beginverse*\memorize
\[\ac{\NumberEffect}{D\notrans{\ChordEffect}}]InlineAnchor
\endverse
\beginverse*\replay
^ReplayAnchor
\endverse
\endsong\end{ulSongs}
\typeout{EFFECTS:\the\SetEffects/\the\IdEffects/\the\NumberEffects/\the\ChordEffects}
"""
                    prefix = r"\def\ulPdfTranspositionLayers{true}" if layers else ""
                    output = self.compile_checked(
                        body, preamble + rf"\ulShowAltChords{{{permission}}}",
                        label=f"{permission}-{layers}", prefix=prefix, passes=3)
                    metrics = {key: tuple(float(value.removesuffix("pt"))
                                          for value in values.split(","))
                               for key, values in re.findall(r"SET-([\w-]+):([^\r\n]+)", output)}
                    for request in ("true", "false"):
                        for chords in ("true", "false"):
                            dimensions = metrics[f"{request}-{chords}"]
                            if permission == request == chords == "true":
                                self.assertGreater(dimensions[0], 0)
                                self.assertGreater(dimensions[1], 0)
                            else:
                                self.assertEqual(dimensions, (0, 0, 0))
                    self.assertEqual(metrics["direct-hidden"], (0, 0, 0))
                    self.assertEqual(metrics["vertical-hidden"], (0, 0, 0))
                    self.assertEqual(metrics["spaces"], metrics["control"])
                    visible_sets = int(permission == "true")
                    self.assertIn(f"EFFECTS:{visible_sets}/{visible_sets}/{visible_sets + 2}/{visible_sets + 2}",
                                  output)
                    colors = dict(re.findall(r"COLOR-(\w+):([^\r\n]+)", output))
                    self.assertEqual(colors["before"] == colors["after"], permission == "false")
                    data = (self.book / "book.pdf").read_bytes()
                    anchors = [row for row in words_and_geometry(data)
                               if row[1] in {"StandaloneAnchor.", "InlineAnchor", "ReplayAnchor"}]
                    snapshots.append((permission, metrics, anchors))
                    if layers:
                        # No standalone set, hidden ID or hidden payload may request
                        # a transposition family. Only inline repetition ink does.
                        structure = PdfStructure(data)
                        self.assertEqual(len(structure.layers), 12)
                        info = json.loads((self.book / "book.ulsbs-multikey.json").read_text())
                        songs = info["multikey_info"]["songs"]
                        self.assertEqual([song["song_id"] for song in songs], ["inline"])
        self.assertEqual(len(snapshots), 4)
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(snapshots[2], snapshots[3])

    def test_chord_only_local_passages_keep_single_row_metrics(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Chord-only}
\beginverse*
BeforeAnchor
{\nolyrics \[C] \[Fmaj7] \[G]}
AfterAnchor with \[C]lyric.
\endverse
\endsong
\end{ulSongs}
""")

    def test_replay_alternate_lyrics_then_translation_compile(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Elevo mi Canto}[by={Ilein Kuymin},key={Am}]
\beginverse\memorize
\beginrep
\[^<A>]E|\[<E>Am]levo mi can\[^<C>]to al |\[<D>Em]cielo, yo el\[^<C B>]evo |\[Am]{} \[^<E>]elevo \[^<C>]mi |\[<D C B>Em]voz
y |\[Am]busco con fe y con |\[Em]gracias |\[G]{} \up{1}la transforma|\[Am]ci\'on
ay yo busco |\[G]{} \up{1}la transforma|\[Am]ci\'on | \e
\endrep
\endverse
\notesoff
\altlyr[1]{ay la uni\'on, ay la sanaci\'on, ay la curaci\'on, ay la conexi\'on, la iluminaci\'on, \ldots}
\beginverse
\beginrep
|^Ay Pachamama, |^ay \up{2}madrecita |^ mil besos te |^doy
|^porque eres m\'usi|^ca \up{3}sanadora |^ mil besos te |^doy
\up{3}sanadora |^ mil besos te |^doy | \e
\endrep
\endverse
\altlyr[2]{curandera, \ldots}\altlyrnospace[3]{amorosa, \ldots}
\begin{translation}[EN]
I raise my song to the sky, I raise I raise my voice
And with faith and thanks I seek the transformation
Oh I seek the transformation (union, healing, connection, enlightenment)
\nextverse
Oh Pachamama, oh beloved mother, thousand kisses to you
For your healing music thousand kisses to you
Healer, a thousand kisses to you
\end{translation}
\endsong
\end{ulSongs}
""", r"\renewcommand{\ulMelodySymbolStyle}{\ulMicroSize}")

    def test_image_blocks_keep_song_state_and_following_translation(self):
        with pikepdf.Pdf.new() as image:
            page = image.add_blank_page(page_size=(120, 60))
            page.Contents = pikepdf.Stream(image, b"0.2 0.4 0.6 rg 0 0 120 60 re f\n")
            stream = io.BytesIO()
            image.save(stream)
        for command in ("imagecc", "imagecb", "imagelc", "imagerc", "imagerb"):
            with self.subTest(command=command):
                body = (r"\begin{ulSongs}{}\beginsong{Image blocks}" + "\n"
                        r"\beginverse*" + "\n" + r"\[C]BeforeImageAnchor" + "\n"
                        r"\endverse" + "\n" + "\\" + command + "[2]{picture.pdf}\n"
                        r"\begin{translation}[EN]" + "\nAfterImageAnchor\n"
                        + r"\end{translation}" + "\n"
                        r"\endsong\end{ulSongs}")
                self.compile_checked(body, files={"picture.pdf": stream.getvalue()}, label=command)
                text = self.pdf_text()
                self.assertLess(text.index("BeforeImageAnchor"), text.index("AfterImageAnchor"))

    def test_replayed_music_overflow_does_not_orphan_a_song_end_page(self):
        records = {"boundary.ulsbs.psv": None}
        _, pdf = compile_fixture("boundary", multikey=False,
                                 passes=2, artifacts=records)
        self.assertIsNotNone(records["boundary.ulsbs.psv"])
        words = words_and_geometry(pdf)
        last_page = max(row[0] for row in words if row[1] == "page")
        # A page containing only the end mark or footer is an orphan, regardless
        # of incidental overflow warnings or the default number of pages.
        self.assertTrue({row[1] for row in words if row[0] == last_page}
                        & {"Ama", "Take", "smile", "while", "way"})

    def test_italic_alt_chord_accidentals_compile(self):
        for offset in (0, 2):
            with self.subTest(offset=offset):
                body = (r"\begin{ulSongs}{}\beginsong{Italic accidentals}[key={Am}]"
                        + f"\\transpose{{{offset}}}\n" + r"""
\beginverse*+
\[Am]Anchor \altchords{\id[1]{(Bm)}|G |F#m/C# |B&maj7}
\[C]Tail \altchords{|Gmaj7 |F#m7 |B&7}
\endverse
\altchords{\id[2]{(Dm)}|B& |Am}
\musicnote{\textit{F\shrp{}m and B\flt{}.}}
\endsong\end{ulSongs}
""")
                self.compile_checked(body, label=f"offset{offset}")

    def test_consecutive_bars_keep_their_gap_and_wrapping(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Bar adjacency}
\beginverse*
\[C]Start | | | \e
\[G]A deliberately long line keeps its bar pairs and final dash at the same wrapping boundary as the source renderer \brk| | \e
\meter{}{4}| | \meter{3}{4}| | \e
\endverse
\endsong\end{ulSongs}
""")

    def test_prose_blocks_recompute_nonchord_leading(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Prose leading}
\beginverse*
\[C]LyricAnchor
\endverse
\begin{explanation}[EN]
\begin{description}
\item[First:] This description is long enough to wrap into several lines; its
  paragraph metrics must come from the selected prose size, including
  \emph{emphasized words} and ordinary text after the font group.
\item[Second:] Another paragraph wraps across lines with the same leading
  rather than inheriting the normal font baseline before chord suppression.
\end{description}
\end{explanation}
\endsong
\beginsong{Following}[id={following}]
\beginverse*
\[G]FollowingAnchor
\endverse
\endsong\end{ulSongs}
""")

    def test_external_section_keeps_first_song_on_the_existing_page(self):
        self.compile_checked(r"""
\section{Source section}
\begin{ulSongs}{}
\beginsong{Under a section}[id={under-section},key={C}]
\beginverse*
\[C]SectionAnchor
\endverse
\endsong\end{ulSongs}
""")

    def test_capo_retains_the_existing_small_attached_note(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Capo}[key={C}]
\capo{2}
\beginverse*
\[C]CapoAnchor
\endverse
\endsong\end{ulSongs}
""")

    def test_echo_rescans_bars_and_preserves_once_only_effects(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Echo}
\beginverse*
\[C]Call \echo{Re|sponse} \echo{\Effect EchoAnchor}
\endverse
\endsong\end{ulSongs}
\typeout{ECHO-EFFECTS=\the\Effects}
""", r"\newcount\Effects\def\Effect{\global\advance\Effects1 EFFECT}")
        self.assertIn("ECHO-EFFECTS=1", (self.book / "book.log").read_text())

    def test_feeler_preserves_the_open_alternate_lyric_paragraph(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Mixed blocks}
\beginverse*
\[C]BeforeNoteAnchor
\endverse
\textnotefornext{Another language:}
\beginverse*
\[G]AfterNoteAnchor
\endverse
\altlyr{Friends, circle, \ldots}
\begin{feeler}
Gratefulness is heaven itself. --- \emph{William Blake}
\end{feeler}
\endsong
\beginsong{Following}
\beginverse*
\[C]FollowingBlockAnchor
\endverse
\endsong\end{ulSongs}
""")

    def test_spread_lookahead_uses_pending_page_breakpoints(self):
        lines = "\n".join(r"\Effect LongBoundaryAnchor" for _ in range(25))
        body = (r"\setcounter{page}{350}\begin{ulSongs}{}" + "\n"
                + r"\beginsong{First}[id={first}]\ulEndSongVfill{true}" + "\n"
                + r"\beginverse*" + "\nShortBoundaryAnchor\n"
                + r"\endverse\endsong\beginsong{Long}[id={long}]" + "\n"
                + r"\beginverse*" + "\n" + lines + "\n"
                + r"\endverse\endsong\end{ulSongs}" + "\n"
                + r"\typeout{BOUNDARY-EFFECTS=\the\Effects}")
        self.compile_checked(body, r"""
\makeatletter\@twosidetrue\makeatother
\newcount\Effects\def\Effect{\global\advance\Effects1 }
""")
        self.assertIn("BOUNDARY-EFFECTS=25", (self.book / "book.log").read_text())
        psv = (self.book / "book.ulsbs.psv").read_text()
        self.assertLess(psv.index("|first|"), psv.index("|long|"))

    def test_partial_heading_columns_preserve_effects_and_order(self):
        for kind, count in (("short", 3), ("long", 65)):
            for position in range(4):
                label = f"{kind}-p{position}"
                with self.subTest(case=label):
                    lines = "\n".join(f"ColumnBoundaryAnchor {number}." for number in range(count))
                    body = (r"\section{Typeset full-width prefix}\CounterEffect" + "\n"
                            + r"\begin{ulSongs}{}\chordsoff" + "\n"
                            + r"\renewcommand{\ulLyricFont}{\small}\ulVerseBaseline{\fpeval{\ulVerseSpacingScale{baseline}{natural}+65536/(\number\fontcharht\font`A)}}{\ulVerseSpacingScale{baseline}{stretch}}{\ulVerseSpacingScale{baseline}{shrink}}\ulSongColumns{2}" + "\n"
                            + f"\\ulSongPosition{{{position}}}\n")
                    for number in range(2):
                        body += (f"\\beginsong{{Columns {number}}}[id={{columns-{number}}}]\n"
                                 + "\\beginverse*\n" + lines
                                 + "\n\\endverse\\endsong\n")
                    body += r"\end{ulSongs}\typeout{PREFIX-EFFECTS=\the\Effects}"
                    self.compile_checked(body, r"""
\makeatletter\@twosidetrue\makeatother
\newcount\Effects\def\CounterEffect{\global\advance\Effects1 }
""", label=label)
                    self.assertIn("PREFIX-EFFECTS=1", (self.book / "book.log").read_text())
                    psv = (self.book / "book.ulsbs.psv").read_text()
                    self.assertLess(psv.index("|columns-0|"), psv.index("|columns-1|"))

    def test_embedded_caret_replays_without_starting_a_second_lyric_scan(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Machi memory}[key={Am}]
\transpose{3}
\beginverse
\beginrep
|\[<A>F#m]Ma\[<B>]chi |\[<C#>A]ma\[<B>]chi |\[E]{} \[<C#>]ma\[<B>]chi|\[<F#>F#m]ma \up{2}(| \e)
\endrep
\endverse
\beginverse
|\[D]{} \[^<F#>]Ma\[^<E>]chi |\[<C#>F#m]cura |\[D]{} \[^<F#>]Ma\[^<E>]chi |\[<C#>F#m]sana
|\[D]{} Machi |\[F#m]c\'antame |\[E]una |\[F#m]nana | \e
\endverse
\notesoff
\beginverse
|^ Yo no |^lloro |^ yo s\'olo |^canto
|^ Con tu en|^canta |^Pachamama |^Madre Tierra
\endverse
\endsong\end{ulSongs}
""")

    def test_replayed_lyric_group_keeps_continuing_note_hyphen(self):
        body = r"""
\begin{ulSongs}{}
\beginsong{Replay group boundary}[id={replay-boundary},key={C}]
\newchords{boundary}
\beginverse*\memorize[boundary]
\[<E>C]First \[<D>G7]second \[<C>C]third \[C7]fourth.
\endverse
\notesoff
\beginverse*\replay[boundary]
Bati|^zou {\noteson\[<G>]\Effect no \[<F>]ri}|^{o de} Jor|^dão |^ \e
\endverse
\endsong\end{ulSongs}
\typeout{REPLAY-EFFECTS=\the\Effects}
"""
        preamble = r"\newcount\Effects\def\Effect{\global\advance\Effects1 }"
        for label, prefix in (("ordinary", ""),
                              ("layers", r"\def\ulPdfTranspositionLayers{true}")):
            with self.subTest(mode=label):
                passes = 3 if label == "layers" else 1
                output = self.compile_checked(body, preamble, label=label, prefix=prefix,
                                      passes=passes)
                self.assertEqual(re.findall(r"REPLAY-EFFECTS=(\d+)", output), ["1"] * passes)
                self.assertIn("Jor", self.pdf_text())

    def test_introductory_music_note_with_multiple_chorded_stanzas(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{First-note glue}
\musicnotefornext{Introductory note before the first stanza.}
\beginverse*
\[C]FirstGlueAnchor
\endverse
\vspace{2ex}
\beginverse*
\[G]SecondGlueAnchor
\endverse
\beginverse*
\[Am]ThirdGlueAnchor
\endverse
\endsong\end{ulSongs}
""")

    def test_credit_periods_compile(self):
        self.compile_checked(r"""
\begin{ulSongs}{}
\beginsong{Credits}[by={J. Irala, Sundaram feat. Prembabanda}]
\beginverse*
\[C]CreditAnchor
\endverse
\endsong\end{ulSongs}
""", r"\ulShowAuthors{true}")


if __name__ == "__main__":
    unittest.main()
