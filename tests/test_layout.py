# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Private page building and mixed-block regression contracts."""

from __future__ import annotations

import re
from pathlib import Path
import subprocess
import unittest
import xml.etree.ElementTree as ET

import test_song_lifecycle as lifecycle
from test_song_lifecycle import document

FIXTURES = Path(__file__).parent / "fixtures"


class LayoutTests(unittest.TestCase):
    setUpClass = classmethod(lifecycle.SongLifecycleTests.setUpClass.__func__)
    setUp = lifecycle.SongLifecycleTests.setUp
    compile_source = lifecycle.SongLifecycleTests.compile_source
    pdf_text = lifecycle.SongLifecycleTests.pdf_text

    def test_two_column_output_preserves_intentional_colors(self):
        import pikepdf

        source = document(r"""
\begin{ulSongs}{}
\beginsong{Two columns}[id={two-columns}]
\beginverse*
\ColumnEffect Left first line.
{\color{red}Intentional red left.}
Left last line.
\endverse
\forcebrk
\beginverse*
\ColumnEffect Right first line.
{\color{blue}Intentional blue right.}
Right last line.
\endverse\endsong
\end{ulSongs}
\typeout{COLUMN-EFFECTS=\the\ColumnEffects}
""", r"""
\newcount\ColumnEffects\def\ColumnEffect{\global\advance\ColumnEffects1 }
\ulSongColumns{2}\ulSongPosition{0}
RULE
""")
        streams = {}
        for label, rule in (("plain", ""), ("rule", r"\setlength\columnseprule{1pt}")):
            output = self.compile_source(source.replace("RULE", rule), label=label, passes=2)
            self.assertEqual(re.findall(r"COLUMN-EFFECTS=(\d+)", output), ["2", "2"])
            self.assertEqual(self.pages(), 1)
            with pikepdf.Pdf.open(self.book / "book.pdf") as pdf:
                contents = pdf.pages[0].Contents
                streams[label] = b"\n".join(part.read_bytes() for part in contents) if isinstance(
                    contents, pikepdf.Array) else contents.read_bytes()
            self.assertIn(b"1 0 0 rg", streams[label])
            self.assertIn(b"0 0 1 rg", streams[label])
        self.assertNotEqual(streams["plain"], streams["rule"])

    def test_kernel_clear_guard_does_not_change_pending_column_top_glue(self):
        preamble = r"""
\newcount\ClearEffects
\newcommand\ClearEffect{\global\advance\ClearEffects1 }
\AddToHook{shipout/before}{\directlua{
  local function walk(head)
    for item in node.traverse(head) do
      if item.id == node.id('glue') and item.subtype == 10 then
        texio.write_nl('term and log', 'TOPSKIP=' .. item.width)
      elseif item.id == node.id('hlist') or item.id == node.id('vlist') then
        walk(item.list)
      end
    end
  end
  walk(tex.box['ShipoutBox'].list)
}}
"""
        body = r"""
\begin{ulSongs}{}
\beginsong{Pending one-column page}
\beginverse*
\ClearEffect First pending lyric.
\endverse
\endsong
\sclearpage*
\ulSongColumns{2}
\beginsong{Pending two-column page}
\beginverse*
\ClearEffect Second pending lyric.
\endverse
\endsong
\nextcol*
\beginsong{Pending right-column page}
\beginverse*
\ClearEffect Third pending lyric.
\endverse
\endsong
\end{ulSongs}
\typeout{CLEAR-EFFECTS=\the\ClearEffects}
"""
        output = self.compile_source(document(body, preamble))
        widths = re.findall(r"TOPSKIP=(\d+)", output)
        self.assertTrue(widths, output)
        self.assertEqual(set(widths), {"0"})
        self.assertEqual(re.findall(r"CLEAR-EFFECTS=(\d+)", output), ["3"])

    def test_plain_mixed_dense_and_multipage_layout_matrix(self):
        for fixture in ("layout", "layout-dense", "layout-long",
                        "layout-mixed"):
            for edition in ("ordinary", "lyric", "two-column"):
                if edition == "two-column" and fixture != "layout-dense":
                    continue
                name = f"{fixture}-{edition}"
                with self.subTest(case=name):
                    body = (FIXTURES / f"{fixture}.tex").read_text().replace(
                        "layout-stanza.tex", str(FIXTURES / "layout-stanza.tex"))
                    preamble = r"\ulSongColumns{2}" if edition == "two-column" else ""
                    source = document(body, preamble)
                    if edition == "lyric":
                        source = r"\def\ulSongbookType{lyric}" + "\n" + source
                    output = self.compile_source(source, label=name, passes=2)
                    self.assertTrue(self.pdf_text().strip())
                    self.assertNotIn("Overfull \\vbox", output)
                    if fixture == "layout-long":
                        self.assertGreater(self.pages(), 1)

    def pages(self):
        info = subprocess.run(["pdfinfo", str(self.book / "book.pdf")], check=True,
                              capture_output=True, text=True).stdout
        return int(re.search(r"Pages:\s+(\d+)", info)[1])

    def positioned_words(self):
        result = subprocess.run(["pdftotext", "-bbox", str(self.book / "book.pdf"), "-"],
                                check=True, capture_output=True, text=True)
        root = ET.fromstring(result.stdout)
        return [[(word.text, word.attrib) for word in page.iter()
                 if word.tag.endswith("}word")]
                for page in root.iter() if page.tag.endswith("}page")]

    def test_two_column_positioning_avoids_an_unnecessary_page_turn(self):
        body = r"\begin{ulSongs}{}" + "\n"
        for name, lines in (("Alpha", 15), ("Beta", 27)):
            body += r"\beginsong{" + name + "}\n" + r"\beginverse*" + "\n"
            body += "\n".join(f"{name}{i}" for i in range(lines))
            body += "\n" + r"\endverse\endsong" + "\n"
        body += r"\end{ulSongs}"
        for position in (1, 2, 3):
            with self.subTest(songpos=position):
                self.compile_source(document(body,
                    r"\setlength\textheight{450pt}\ulSongColumns{2}\ulSongPosition{" +
                    str(position) + "}"), label=f"position-{position}")
                pages = self.positioned_words()
                beta_pages = [page for page, words in enumerate(pages, start=1)
                              if any(text and text.startswith("Beta") for text, _ in words)]
                self.assertEqual(beta_pages, [2])

    def test_text_notes_inside_stanzas_do_not_glue_the_following_stanza(self):
        source = document(r"""
\begin{ulSongs}{}\beginsong{Notes}
\beginverse*
FIRST
\attachednote{NOTE}
LAST
\endverse
\beginverse*
NEXT
\endverse\endsong\end{ulSongs}
""")
        self.compile_source(source)
        words = {text: box for page in self.positioned_words() for text, box in page}
        self.assertLess(float(words["FIRST"]["yMin"]), float(words["NOTE"]["yMin"]))
        self.assertLess(float(words["NOTE"]["yMin"]), float(words["LAST"]["yMin"]))
        self.assertGreater(float(words["NEXT"]["yMin"]) - float(words["LAST"]["yMin"]),
                           float(words["LAST"]["yMin"]) - float(words["NOTE"]["yMin"]))

    def test_attached_notes_preserve_later_explicit_break_penalty(self):
        # A preceding segno changes the later explicit break's song-scoped
        # penalty. In lyrics mode, keeping the initial 50 instead of 200 moves
        # the entire fourth stanza to the next page despite room for it.
        body = "\\begin{ulSongs}{}\n\\beginsong{Note break state}[by={Fixture author}]\n"
        for stanza, lines in enumerate((3, 8, 8, 8, 5, 4, 1)):
            if stanza == 1:
                body += "\\segno\n"
            if stanza == 3:
                body += r"\typeout{NOTE-BREAK-BEFORE=\the\ulBreakPenalty}\brk" + "\n"
            if stanza == 4:
                body += (r"\ulBreakPenalty=75\relax\dalsegno"
                         r"\typeout{NOTE-BREAK-AFTER=\the\ulBreakPenalty}" + "\n")
            body += "\\beginverse*\n"
            for line in range(lines):
                body += (r"\global\advance\NoteEffects1 \[C]Lyric" + str(stanza)
                         + "x" + str(line) + " deeply grounded")
                if stanza == 3 and line == 7:
                    body += r"\sublyr{Echo}"
                body += "\n"
            body += "\\endverse\n"
        body += r"""\endsong\end{ulSongs}
\typeout{NOTE-EFFECTS=\the\NoteEffects}
\typeout{NOTE-TEXT-EFFECTS=\the\NoteTextEffects}
\typeout{NOTE-BREAK-RESTORED=\the\ulBreakPenalty}
"""
        for edition in ("lyric", "chorded"):
            preamble = r"""\newcount\NoteEffects
\newcount\NoteTextEffects
\let\OriginalSegno\musSegno
\renewcommand\musSegno{\global\advance\NoteTextEffects1 \OriginalSegno}
"""
            if edition == "lyric":
                preamble += r"\input{ulsbs-internal-lyricbook-postsetup.tex}"
            source = (r"\def\ulSongbookType{" + edition + "}\n"
                      + document(body, preamble))
            with self.subTest(edition=edition):
                output = self.compile_source(source, label=edition)
                words = self.positioned_words()
                if edition == "lyric":
                    self.assertIn("Lyric3x0", [text for text, _ in words[0]])
                self.assertEqual(re.findall(r"NOTE-EFFECTS=(\d+)", output), ["37"])
                self.assertEqual(re.findall(r"NOTE-TEXT-EFFECTS=(\d+)", output), ["1"])
                for state in ("BEFORE", "AFTER"):
                    self.assertEqual(re.findall(r"NOTE-BREAK-" + state + r"=(\d+)",
                                                output), ["200"])
                self.assertEqual(re.findall(r"NOTE-BREAK-RESTORED=(\d+)", output), ["50"])

    def test_text_notes_outside_songs_and_before_numbered_first_lines(self):
        source = document(r"""
\attachednote{Introductory note}
\begin{ulSongs}{}\beginsong{Notes}
\beginverse
\attachednote{Before first line}
FIRST
\endverse
\textnotefornext{Attached note}
\beginverse
NEXT
\endverse\endsong\end{ulSongs}
""", r"\renewcommand\ulPrintVerseNumber[1]{V#1\space}\setlength\ulVerseNumberWidth{20pt}")
        self.compile_source(source)
        text = self.pdf_text()
        for value in ("Introductory note", "Before first line", "Attached note", "V1", "V2"):
            self.assertIn(value, text)

    def test_long_song_splits_without_losing_lines_or_shipping_a_giant_box(self):
        verses = "\n".join(r"\beginverse*" + "\n" +
                           "\n".join(f"Line {verse:02d}-{line:02d}" for line in range(6)) +
                           "\n" + r"\endverse" for verse in range(16))
        output = self.compile_source(document(
            r"\begin{ulSongs}{titleidx}\beginsong{Long song}[id={long}]" +
            "\n" + verses + "\n" + r"\endsong\end{ulSongs}",
            r"\setlength{\ulSongNumberWidth}{0pt}"), passes=2)
        text = self.pdf_text()
        for verse in range(16):
            for line in range(6):
                self.assertEqual(text.count(f"Line {verse:02d}-{line:02d}"), 1)
        self.assertGreater(self.pages(), 2)
        self.assertNotIn("Overfull \\vbox", output)
        self.assertFalse((self.book / "book.sxc").exists())

    def test_mixed_prose_translation_passage_explanation_and_hidden_blocks(self):
        output = self.compile_source(document(r"""
\begin{ulSongs}{titleidx}
\beginsong{Mixed blocks}[id={mixed}]
\beginverse
First lyric line.
Second lyric line.
\endverse
Ordinary prose between stanzas with \textbf{formatting}.
\begin{translation}[EN]
Translated first line.
Translated second line.
\nextverse
Translated next stanza.
\end{translation}
\begin{passage}[EN]{Passage title}
Passage prose with a \passagenote{short note}.
\end{passage}
\begin{explanation}[EN]
Explanation prose.
\end{explanation}
\ulShowTranslation{false}
\begin{translation}
Hidden translation unique.
\end{translation}
\endsong
\beginsong{Reset blocks}
\beginverse
Fresh lyric line.
\endverse
\endsong
\end{ulSongs}
""", r"\setlength{\ulSongNumberWidth}{0pt}"), passes=2)
        text = self.pdf_text()
        for value in ("First lyric", "Translated first", "Translated next",
                      "Passage title", "short note", "Explanation prose", "Fresh lyric"):
            self.assertIn(value, text)
        self.assertNotIn("Hidden translation unique", text)
        self.assertNotIn("Overfull \\vbox", output)

    def test_force_break_and_page_clear_preserve_song_order(self):
        self.compile_source(document(r"""
\begin{ulSongs}{titleidx}
\beginsong{First}
\beginverse
Before forced split.
\forcebrk
After forced split.
\endverse
\endsong
\sclearpage
\beginsong{Second}
\beginverse
Second song line.
\endverse
\endsong
\end{ulSongs}
"""))
        pages = self.pdf_text().split("\f")
        before = next(i for i, text in enumerate(pages) if "Before forced" in text)
        after = next(i for i, text in enumerate(pages) if "After forced" in text)
        second = next(i for i, text in enumerate(pages) if "Second song" in text)
        self.assertLess(before, after)
        self.assertLess(after, second)

    def test_song_clear_survives_an_include_clearpage_override(self):
        included = r"""
\beginsong{Before song clear}
\beginverse*
\ClearEffect Beforelyric.
\endverse\endsong
\sclearpage
\beginsong{After song clear}
\beginverse*
\ClearEffect Afterlyric.
\endverse\endsong
"""
        source = document(r"""
\let\SavedClearpage\clearpage
\let\clearpage\relax
\ClearEffect Ordinarybefore.\par
\clearpage
\ClearEffect Ordinaryafter.\par
\SavedClearpage
\begin{ulSongs}{}
\include{suppressed-include}
\ifx\clearpage\relax\typeout{CLEAR-OVERRIDE-PRESERVED}\fi
\end{ulSongs}
\ifx\clearpage\relax\typeout{CLEAR-END-OVERRIDE-PRESERVED}\fi
\let\clearpage\SavedClearpage
\typeout{CLEAR-EFFECTS=\the\ClearEffects}
""", r"\newcount\ClearEffects\def\ClearEffect{\global\advance\ClearEffects1 }")
        for edition in ("chorded", "lyric"):
            variant = source
            if edition == "lyric":
                variant = r"\def\ulSongbookType{lyric}" + "\n" + variant.replace(
                    r"\begin{document}", r"\input{ulsbs-internal-lyricbook-postsetup.tex}"
                    + "\n" + r"\begin{document}")
            with self.subTest(edition=edition):
                output = self.compile_source(variant, label=edition, passes=2,
                    files={"suppressed-include.tex": included.encode()})
                pages = self.positioned_words()
                self.assertEqual(len(pages), 3)
                self.assertIn("Ordinarybefore.", [text for text, _ in pages[0]])
                self.assertIn("Ordinaryafter.", [text for text, _ in pages[0]])
                self.assertIn("Afterlyric.", [text for text, _ in pages[2]])
                self.assertEqual(re.findall(r"CLEAR-EFFECTS=(\d+)", output), ["4", "4"])
                self.assertEqual(output.count("CLEAR-OVERRIDE-PRESERVED"), 2)
                self.assertEqual(output.count("CLEAR-END-OVERRIDE-PRESERVED"), 2)

    def test_standalone_intersong_owns_its_page_top_skip(self):
        body = r"""
\begin{intersong}
\centering\Large
\vfill
\InterEffect Opening.\par
\vspace{20pt}
\InterEffect Closing.\par
\vfill
\end{intersong}
\sclearpage
\InterEffect Ordinarytop.\par
\vfill
\InterEffect Ordinarybottom.\par
\clearpage
\typeout{INTER-EFFECTS=\the\InterEffects}
"""
        for edition in ("chorded", "lyric"):
            preamble = r"\newcount\InterEffects\def\InterEffect{\global\advance\InterEffects1 }"
            if edition == "lyric":
                preamble += r"\input{ulsbs-internal-lyricbook-postsetup.tex}"
            source = (r"\def\ulSongbookType{" + edition + "}\n" + document(body, preamble))
            output = self.compile_source(source, label=edition)
            self.assertEqual(re.findall(r"INTER-EFFECTS=(\d+)", output), ["4"])
            words = {text: box for page in self.positioned_words() for text, box in page}
            self.assertLess(float(words["Opening."]["yMin"]), float(words["Closing."]["yMin"]))
            self.assertLess(float(words["Ordinarytop."]["yMin"]),
                            float(words["Ordinarybottom."]["yMin"]))

    def test_outer_fill_before_intersong_does_not_repack_song_contents(self):
        body = r"""
\begin{ulSongs}{}
\beginsong{Packing ownership}
\beginverse*
\InterEffect \[C]First lyric.
\InterEffect \[G]Second lyric.
\InterEffect \[C]Third lyric.
\endverse
\begin{translation}[EN]
\InterEffect First translation.
\InterEffect Second translation.
\end{translation}
\endsong
\vfill
\begin{intersong}
\begin{explanation}[EN]
\InterEffect Explanatory prose.
\end{explanation}
\end{intersong}
\end{ulSongs}
\typeout{INTER-EFFECTS=\the\InterEffects}
"""
        for mode in ("chorded", "lyric", "two-column", "hidden-intersong"):
            preamble = (r"\newcount\InterEffects\def\InterEffect{\global\advance\InterEffects1 }"
                        r"\setlength\textheight{300pt}")
            if mode == "lyric":
                preamble += r"\input{ulsbs-internal-lyricbook-postsetup.tex}"
            if mode == "two-column":
                preamble += r"\ulSongColumns{2}"
            edition = "lyric" if mode == "lyric" else "chorded"
            source = (r"\def\ulSongbookType{" + edition + "}\n" + document(body, preamble))
            if mode == "two-column":
                source = source.replace("\\vfill\n\\begin{intersong}",
                                        "\\vfil\\vfill\\vfill\n\\begin{intersong}")
            if mode == "hidden-intersong":
                source = source.replace("\\vfill\n\\begin{intersong}", r"""
\vfill\ulScripture{false}
\begin{intersong}\InterEffect Hiddenone.\end{intersong}
\vfill
\begin{intersong}\InterEffect Hiddentwo.\end{intersong}
\ulScripture{true}\vfill
\begin{intersong}""")
                source = source.replace(r"\end{ulSongs}", r"""\directlua{
  if ulsbs_layout then
    assert(node.length(ulsbs_layout.outer_glue)==3, 'Repeated outer glue')
  end
}\end{ulSongs}""")
            output = self.compile_source(source, label=mode)
            self.assertEqual(re.findall(r"INTER-EFFECTS=(\d+)", output),
                             ["8" if mode == "hidden-intersong" else "6"])

    def test_flowing_intersong_fill_stays_with_the_outer_page(self):
        source = document(r"""
{\ulSongColumns{0}
\begin{ulSongs}{}
\beginsong{Flowing}
\beginverse*
\InterEffect First lyric.
\InterEffect Second lyric.
\endverse\endsong
\vfill
\begin{intersong}\InterEffect Firstnote.\par\end{intersong}
\vfill
\begin{intersong}\InterEffect Secondnote.\par\end{intersong}
\directlua{if ulsbs_layout then
  assert(ulsbs_layout.outer_glue==nil, 'Flowing fill was buffered') end}
\end{ulSongs}}
\clearpage
\begin{ulSongs}{}
\beginsong{After flowing}
\beginverse*
\InterEffect Following lyric.
\endverse\endsong
\end{ulSongs}
\typeout{INTER-EFFECTS=\the\InterEffects}
""", r"\newcount\InterEffects\def\InterEffect{\global\advance\InterEffects1 }")
        output = self.compile_source(source)
        self.assertEqual(re.findall(r"INTER-EFFECTS=(\d+)", output), ["5"])
        text = self.pdf_text()
        self.assertLess(text.index("Firstnote."), text.index("Secondnote."))

    def test_outer_prose_fill_is_not_buffered_as_song_fill(self):
        output = self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Before ordinary prose}
\beginverse*
\InterEffect Lyric.
\endverse\endsong
\InterEffect Ordinaryprose.\par
\vfill
\begin{intersong}
\directlua{texio.write_nl('term and log', 'PROSE-FILL-PRESERVED=' ..
  tostring(ulsbs_layout.outer_glue==nil))}
\InterEffect Followingnote.\par
\end{intersong}
\end{ulSongs}
\typeout{INTER-EFFECTS=\the\InterEffects}
""", r"\newcount\InterEffects\def\InterEffect{\global\advance\InterEffects1 }"))
        self.assertIn("PROSE-FILL-PRESERVED=true", output)
        self.assertEqual(re.findall(r"INTER-EFFECTS=(\d+)", output), ["3"])
        words = {text: box for page in self.positioned_words() for text, box in page}
        self.assertGreater(float(words["Followingnote."]["yMin"])
                           - float(words["Ordinaryprose."]["yMin"]), 100)

    def test_song_spread_clear_does_not_flush_ordinary_even_page_prose(self):
        source = document(r"""
\begin{ulSongs}{}
\beginsong{Previous song}
\beginverse*
\ClearEffect Previouslyric.
\endverse\endsong
\end{ulSongs}
\section{Instructions}
\sclearpage
\scleardpage
\ClearEffect Firstinstructions.\par
\clearpage
\ClearEffect Secondinstructions.\par
\clearpage
\ClearEffect Thirdinstructions.\par
\scleardpage
\ulSongSection{Following songs}
\begin{ulSongs}{}
\beginsong{Following song}
\beginverse*
\ClearEffect Followinglyric.
\endverse\endsong
\end{ulSongs}
\typeout{CLEAR-EFFECTS=\the\ClearEffects}
""", r"\newcount\ClearEffects\def\ClearEffect{\global\advance\ClearEffects1 }")
        source = source.replace("[oneside,openany,", "[twoside,openany,")
        output = self.compile_source(source, label="spread-clear", passes=2)
        self.assertEqual(re.findall(r"CLEAR-EFFECTS=(\d+)", output), ["5", "5"])

    def test_spread_clear_drains_the_continuation_of_a_multipage_song(self):
        source = document(r"""
\setcounter{page}{2}
\begin{ulSongs}{titleidx}
\beginsong{Two-page song}[id={two-page}]
\beginverse*
\ClearEffect First page lyric.
\endverse
\beginverse*
\ClearEffect Continuation lyric.
\endverse\endsong

\scleardpage
\beginsong{Following song}[id={following}]
\beginverse*
\ClearEffect Following lyric.
\endverse\endsong
\end{ulSongs}
\typeout{CLEAR-EFFECTS=\the\ClearEffects}
""", r"\newcount\ClearEffects\def\ClearEffect{\global\advance\ClearEffects1 }")
        for marker in ("First page lyric.", "Continuation lyric."):
            source = source.replace(r"\ClearEffect " + marker, "\n".join(
                r"\ClearEffect " + marker + f" Line {number}." for number in range(13)))
        source = source.replace("[oneside,openany,", "[twoside,openany,")
        output = self.compile_source(source, passes=2)
        self.assertEqual(re.findall(r"CLEAR-EFFECTS=(\d+)", output), ["27", "27"])
        self.assertEqual(self.pages(), 3)

    def test_two_page_song_reserves_a_spread_on_an_empty_odd_page(self):
        lines = "\n".join(r"\EmptyEffect Lyric line " + str(n) + "." for n in range(13))
        source = document(r"""
\setcounter{page}{3}
\begin{ulSongs}{titleidx}
\beginsong{Two-page song}[id={two-page}]
\beginverse*
LINES
\endverse
\beginverse*
LINES
\endverse\endsong
\end{ulSongs}
\typeout{EMPTY-EFFECTS=\the\EmptyEffects}
""".replace("LINES", lines),
            r"\newcount\EmptyEffects\def\EmptyEffect{\global\advance\EmptyEffects1 }")
        source = source.replace("[oneside,openany,", "[twoside,openany,")
        for position in (1, 2, 3):
            with self.subTest(position=position):
                positioned = source.replace(r"\begin{ulSongs}", rf"\ulSongPosition{{{position}}}\begin{{ulSongs}}")
                output = self.compile_source(positioned, label=f"position-{position}", passes=2)
                self.assertEqual(re.findall(r"EMPTY-EFFECTS=(\d+)", output), ["26", "26"])
                self.assertEqual(self.pages(), 3)

    def test_spread_clear_blank_can_share_shrinkable_ordinary_page(self):
        source = document(r"""
\setcounter{page}{3}
\section{Ordinary instructions}
\ClearEffect First paragraph.\par
\vspace{300pt plus 12pt minus 12pt}
\ClearEffect Last paragraph.\par
\begin{center}\rule{30pt}{60pt}\end{center}
\scleardpage
\section{After clear}
\ClearEffect Aftermarker.\par
\typeout{CLEAR-EFFECTS=\the\ClearEffects}
""", r"\newcount\ClearEffects\def\ClearEffect{\global\advance\ClearEffects1 }")
        source = source.replace("[oneside,openany,", "[twoside,openany,")
        output = self.compile_source(source, passes=2)
        self.assertEqual(re.findall(r"CLEAR-EFFECTS=(\d+)", output), ["3", "3"])
        self.assertEqual(self.pages(), 2)

    def test_spread_clear_reserves_blank_without_stretching_ordinary_prose(self):
        cases = [(3, "empty", 2), (3, "paragraph", 3), (3, "hmode", 3), (3, "owned", 2),
                 (4, "empty", 1), (4, "paragraph", 1), (4, "hmode", 1), (4, "owned", 3),
                 (2, "instructions", 4)]
        for page, kind, expected_pages in cases:
            with self.subTest(page=page, kind=kind):
                body = r"\setcounter{page}{" + str(page) + "}\n"
                if kind in ("paragraph", "hmode"):
                    body += (r"\section{Ordinary heading}\ClearEffect Ordinary first paragraph.\par"
                             r"\ClearEffect Ordinary second paragraph.")
                    if kind == "paragraph":
                        body += r"\par"
                elif kind == "owned":
                    body += r"""\begin{ulSongs}{}\beginsong{Owned material}\beginverse*
\ClearEffect First lyric.
\ClearEffect Second lyric.
\endverse\endsong
"""
                elif kind == "instructions":
                    body += r"""
\section{Instructions}\sclearpage\scleardpage
\ClearEffect Firstinstructions.\par\clearpage
\ClearEffect Secondinstructions.\par
"""
                body += "\\scleardpage\n"
                if kind == "owned":
                    body += "\\end{ulSongs}\n"
                if kind == "instructions":
                    body += r"""
\ulSongSection{Following songs}\begin{ulSongs}{}\beginsong{Following song}
\beginverse*
\ClearEffect Followinglyric.
\endverse\endsong\end{ulSongs}
"""
                else:
                    body += r"\section{After clear}\ClearEffect Aftermarker.\par"
                body += r"\typeout{CLEAR-EFFECTS=\the\ClearEffects}"
                source = document(body, r"\newcount\ClearEffects"
                                  r"\def\ClearEffect{\global\advance\ClearEffects1 }")
                source = source.replace("[oneside,openany,", "[twoside,openany,")
                output = self.compile_source(source, label=f"{page}-{kind}", passes=2)
                self.assertEqual(re.findall(r"CLEAR-EFFECTS=(\d+)", output),
                                 ["1" if kind == "empty" else "3"] * 2)
                self.assertEqual(self.pages(), expected_pages)

    def test_two_columns_use_standard_latex_and_restore_single_column(self):
        songs = "\n".join(r"\beginsong{Column song " + str(i) + "}\n" +
                           r"\beginverse*" + "\n" +
                           "\n".join(f"Column lyric {i}-{j}" for j in range(8)) +
                           "\n" + r"\endverse\endsong" for i in range(8))
        output = self.compile_source(document(
            r"\ulSongColumns{2}\ulSongPosition{3}\begin{ulSongs}{}" + "\n" + songs +
            "\n" + r"\end{ulSongs}\ulSongColumns{1}Single column afterwards.",
            r"\setlength{\ulSongNumberWidth}{0pt}"))
        text = self.pdf_text()
        for i in range(8):
            self.assertIn(f"Column song {i}", text)
        self.assertIn("Single column afterwards", text)
        self.assertNotIn("Overfull \\vbox", output)

    def test_layout_does_not_call_vendor_layout_or_block_helpers(self):
        poison = r"""
\makeatletter
\def\SB@stype{\errmessage{VENDOR LAYOUT CALLED}}
\def\SB@breakpoint#1{\errmessage{VENDOR BREAK CALLED}}
\def\SB@boxup#1{\errmessage{VENDOR NOTE CALLED}}
\def\SB@chordsoff{\errmessage{VENDOR CHORD TOGGLE CALLED}}
\makeatother
"""
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Owned layout}
\beginverse
Owned stanza.
\endverse
\begin{translation}[EN]
Owned translation.
\end{translation}
\begin{explanation}
Owned explanation.
\end{explanation}
\endsong
\end{ulSongs}
""", poison))

    def test_song_position_arguments_are_validated(self):
        self.compile_source(document("", r"\ulSongPosition{4}"),
                            failure="be 0, 1, 2 or 3")

    def test_lyrics_only_uses_its_baseline_without_full_page_line_stretch(self):
        source = document(r"""
\begin{ulSongs}{}
\beginsong{Lyric metrics}
\beginverse*
Lyric first line.
Lyric second line.
Lyric third line.
\endverse
\endsong
\end{ulSongs}
""", r"\input{ulsbs-internal-lyricbook-postsetup.tex}")
        self.compile_source(source)
        bbox = subprocess.run(["pdftotext", "-bbox", str(self.book / "book.pdf"), "-"],
                              check=True, capture_output=True, text=True).stdout
        rows = [float(y) for y in re.findall(r'<word xMin="[^"]+" yMin="([^"]+)"[^>]*>Lyric</word>', bbox)]
        self.assertEqual(len(rows), 4)
        steps = [b - a for a, b in zip(rows[1:], rows[2:], strict=False)]
        self.assertTrue(all(10 < step < 25 for step in steps), rows)

    def test_selected_song_boxes_can_be_repeated_without_reexecuting_source(self):
        output = self.compile_source(document(r"""
\ulIncludeOnlySongs{1,brk,1}
\begin{ulSongs}{}
\beginsong{Repeated selected song}
\beginverse*
\global\advance\SelectionEffects1 Repeatedlyric
\endverse
\endsong
\end{ulSongs}
\typeout{SELECTION-EFFECTS=\the\SelectionEffects}
""", r"\newcount\SelectionEffects"))
        self.assertIn("SELECTION-EFFECTS=1", output)
        self.assertEqual(self.pdf_text().count("Repeatedlyric"), 2)
        self.assertEqual(self.pages(), 2)

    def test_zero_column_flow_and_nested_song_blocks_do_not_force_inner_pages(self):
        self.compile_source(document(r"""
\ulSongColumns{0}
\vbox{\begin{ulSongs}{}
\beginsong{Nested flow}
\beginverse*
Nested lyric.
\endverse
\endsong
\end{ulSongs}}
Following prose.
"""))
        self.assertIn("Nested lyric", self.pdf_text())
        self.assertIn("Following prose", self.pdf_text())
        self.assertEqual(self.pages(), 1)


if __name__ == "__main__":
    unittest.main()
