# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Token scanning, replay, evaluation and relative layout contracts."""

from pathlib import Path
import io
import os
import re
import unittest

import pikepdf

import test_song_lifecycle as helpers
from test_tex_integration import ROOT, TEX_ASSETS, compile_fixture
from test_pdf_transposition_layers import words_and_geometry


def document(body, preamble=""):
    return helpers.document(body, preamble)


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

    def compile_checked(self, body, preamble="", *, files=None, label="", prefix="", passes=1):
        source = prefix + document(body, preamble)
        output = self.compile_source(source, label=label or "chords", files=files, passes=passes)
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
\beginverse*\chordsoff
|^I ^ am |^open ^ to |^see ^ flowers |^blooming^
|^I ^ am here t|^o live^ thi|^{s life}^ | \e
\endverse
\endsong
\end{ulSongs}
""")

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
        self.compile_checked(body, label="-lyrics", prefix=r"\def\ulSongbookType{lyric}")
        self.compile_checked(body, label="-ordinary")

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
        for prefix, label in (("", "ordinary"), (r"\def\ulSongbookType{lyric}", "lyrics")):
            with self.subTest(label=label):
                output = self.compile_checked(body, r"\newcount\Effects\def\Effect{\global\advance\Effects1 }",
                                      prefix=prefix, label=label)
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
\[\ac{1}{C} \ac{2}{Am}]Main \[G]line \altchords{\id[2]{Peter (D)}|D |A |\ac{2}{Bm} |\notrans{G}}
\endverse
\musicnote{Inline \ac{1}{C} and \ac{2}{G}.}
\endsong
\end{ulSongs}
""")

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

    def test_scanner_has_no_vendor_consumers(self):
        for name in ("ulsbs-chords.code.tex", "ulsbs-music.code.tex",
                     "ulsbs-multikey.code.tex"):
            with self.subTest(module=name):
                self.assertNotIn("SB@", (TEX_ASSETS / name).read_text())

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
                            + r"\begin{ulSongs}{}\chordsoff\ulBaselineAdjustment=1pt" + "\n"
                            + r"\renewcommand{\ulLyricFont}{\small}\ulSongColumns{2}" + "\n"
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
                passes = 2 if label == "layers" else 1
                output = self.compile_checked(body, preamble, label=label, prefix=prefix,
                                      passes=passes)
                self.assertEqual(re.findall(r"REPLAY-EFFECTS=(\d+)", output), ["1"] * passes)
                self.assertIn("Jor", self.pdf_text())

    def test_first_note_keeps_pending_glue_until_a_real_stanza_boundary(self):
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
