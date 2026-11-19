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

    def test_short_song_number_panels_fit_without_changing_geometry(self):
        songs = []
        for number in (414, 211, 148, 153, 306):
            songs.append(r"""
\setcounter{ulSongNumber}{NUMBER}
\beginsong{Short}[id={panel-NUMBER}]
\beginverse*
BODYMARK
\endverse
\endsong
""".replace("NUMBER", str(number)))
        songs.append(r"""
\renewcommand\theulSongNumber{\Roman{ulSongNumber}}
\setcounter{ulSongNumber}{1}
\beginsong{Short}[id={panel-roman}]
\beginverse*
BODYMARK
\endverse
\endsong
""")
        body = (r"\begin{ulSongs}{}" + "".join(songs)
                + r"\end{ulSongs}\typeout{PANEL-PRINTS:\the\PanelPrints}")
        preamble = r"""
\ulSongPosition{0}
\newcount\PanelPrints
\let\OriginalPrintSongNumber\ulPrintSongNumber
\renewcommand\ulPrintSongNumber[1]{\global\advance\PanelPrints1\relax\OriginalPrintSongNumber{#1}}
\makeatletter\ExplSyntaxOn
PATCH
\cs_new_eq:NN \OriginalMakePrelude \ulMakePrelude
\renewcommand\ulMakePrelude
  {\vbox_set:Nn \l_tmpa_box {\OriginalMakePrelude}
   \iow_term:x {PANEL-DIMS:\theulSongNumber/
     \dim_eval:n {\box_wd:N \l_tmpa_box}/
     \dim_eval:n {\box_ht:N \l_tmpa_box}/
     \dim_eval:n {\box_dp:N \l_tmpa_box}}
   \box_use_drop:N \l_tmpa_box}
\ExplSyntaxOff\makeatother
"""
        snapshots = []
        legacy_patch = (r"\exp_args:Nc\patchcmd{ulMakePrelude~code}{\vss}{\vfil}{}"
                        r"{\errmessage{Number panel glue not found}}")
        for label, patch in (("current", ""), ("legacy", legacy_patch)):
            output = self.compile_source(document(body, preamble.replace("PATCH", patch)), label=label)
            if label == "current":
                self.assertNotIn("Overfull \\vbox", output)
            else:
                self.assertEqual(output.count("Overfull \\vbox"), 6)
            self.assertEqual(re.findall(r"PANEL-PRINTS:(\d+)", output), ["6"])
            dimensions = re.findall(r"PANEL-DIMS:([^\n]+)", output)
            self.assertEqual(len(dimensions), 6)
            anchors = [line for line in (self.book / "book.ulsbs.psv").read_text().splitlines()
                       if line.startswith("ID-NR-PAGE-Y|")]
            self.assertEqual(len(anchors), 6)
            snapshots.append((dimensions, self.positioned_words(), anchors))
        self.assertEqual(*snapshots)

    def test_song_titles_wrap_without_replaying_display_source(self):
        body = r"""
\begin{ulSongs}{}
\beginsong{\TitleEffect Alpha Beta Gamma Delta Epsilon Zeta Eta Theta Iota Kappa Lambda Mu Nu Xi Omicron Pi Rho Sigma Tau Upsilon Phi Chi Psi Omega\\\TitleEffect Alternate heading with several ordinary words}
\beginverse*
BODYMARK
\endverse
\endsong
\end{ulSongs}
\typeout{TITLE-EFFECTS:\the\TitleEffects}
"""
        settings = (
            ("one-column", r"\setlength\textwidth{220pt}"),
            ("two-columns", r"\ulSongColumns{2}"),
            ("centered", r"\setlength\textwidth{220pt}\ulPagePreludes"),
            ("slides", r"\ulSlides{true}"),
        )
        for label, setting in settings:
            with self.subTest(layout=label):
                preamble = setting + r"""
\newcount\TitleEffects
\DeclareRobustCommand\TitleEffect{\global\advance\TitleEffects1\relax}
\pdfstringdefDisableCommands{\def\TitleEffect{}}
"""
                output = self.compile_source(document(body, preamble), label=label)
                self.assertNotIn("Overfull \\hbox", output)
                self.assertEqual(re.findall(r"TITLE-EFFECTS:(\d+)", output),
                                 ["1" if label == "slides" else "2"])
                words = {text: box for page in self.positioned_words() for text, box in page}
                self.assertGreater(float(words["Omega"]["yMin"]),
                                   float(words["Alpha"]["yMin"]))
                self.assertGreater(float(words["BODYMARK"]["yMin"]),
                                   float(words["Omega"]["yMax"]))

    def test_title_badges_keep_first_baseline_with_optional_reserved_lane(self):
        body = r"""
\begin{ulSongs}{}
\beginsong{Alpha Beta Gamma Delta}[key={C},gk={Dm},tags={nature},ph={I},by={ATTRIBUTION}]
\beginverse*
BODYMARK
\endverse
\endsong
\end{ulSongs}
"""
        preamble = r"""
\ulNoSongNumbers\setlength\textwidth{180pt}
\ulShowTags{true}\ulShowPhase{true}\ulShowKey{true}\ulShowGoodKeys{true}
\renewcommand\ulPreludeTextKey{KEYMARK}
\renewcommand\ulPreludeTextGoodKeysAlone{GOODMARK}
"""
        snapshots = {}
        for mode, setting in (("reserved", ""), ("overlap", r"\ulTitleBadgeOverlap{true}"),
                              ("hidden", r"\ulShowTags{false}\ulShowPhase{false}\ulShowKey{false}\ulShowGoodKeys{false}")):
            with self.subTest(mode=mode):
                output = self.compile_source(document(body, preamble + setting), label=mode)
                self.assertNotIn("Overfull \\hbox", output)
                snapshots[mode] = {text: {key: float(value) for key, value in box.items()}
                                   for page in self.positioned_words() for text, box in page}
        reserved, overlap, hidden = (snapshots[mode] for mode in ("reserved", "overlap", "hidden"))
        self.assertGreater(reserved["Delta"]["yMin"], reserved["Alpha"]["yMin"])
        self.assertEqual(overlap["Delta"]["yMin"], overlap["Alpha"]["yMin"])
        self.assertEqual(hidden["Delta"]["yMin"], hidden["Alpha"]["yMin"])
        for word in ("Alpha", "KEYMARK", "GOODMARK"):
            self.assertEqual(reserved[word], overlap[word])
        title_right = max(reserved[word]["xMax"] for word in ("Alpha", "Beta", "Gamma", "Delta"))
        badge_left = min(reserved[word]["xMin"] for word in ("KEYMARK", "GOODMARK", "nature"))
        self.assertLess(title_right, badge_left)
        self.assertGreater(reserved["ATTRIBUTION"]["yMin"], reserved["Delta"]["yMax"])

    def test_badge_rows_do_not_push_prelude_text_or_verses_down(self):
        body = r"""
\begin{ulSongs}{}
\beginsong{Short}[key={C},gk={Dm},tags={nature},ph={I},ex={EXMARK}]
\beginverse*
BODYMARK
\endverse
\endsong
\end{ulSongs}
"""
        preamble = r"""
\ulNoSongNumbers\setlength\textwidth{230pt}
\renewcommand\ulPreludeTextGoodKeysAlone{GOODMARK}
"""
        snapshots = []
        modes = (("hidden", False, False, False), ("one-row", False, True, False),
                 ("two-rows", True, True, False), ("three-rows", True, True, True))
        for label, tags, key, good in modes:
            with self.subTest(mode=label):
                settings = (r"\ulShowTags{" + str(tags).lower() + "}"
                            + r"\ulShowPhase{" + str(tags).lower() + "}"
                            + r"\ulShowKey{" + str(key).lower() + "}"
                            + r"\ulShowGoodKeys{" + str(good).lower() + "}")
                output = self.compile_source(document(body, preamble + settings), label=label)
                self.assertNotIn("Overfull \\hbox", output)
                words = {text: box for page in self.positioned_words() for text, box in page}
                snapshots.append({word: words[word] for word in ("Short", "EXMARK", "BODYMARK")})
                if good:
                    self.assertLess(float(words["EXMARK"]["yMin"]), float(words["GOODMARK"]["yMax"]))
                    self.assertLess(float(words["EXMARK"]["xMax"]), float(words["GOODMARK"]["xMin"]))
        for snapshot in snapshots[1:]:
            self.assertEqual(snapshot, snapshots[0])

    def test_all_prelude_text_uses_left_lane_and_retains_caller_font(self):
        body = r"""
\begin{ulSongs}{}
\beginsong{Short}[key={C},gk={Dm},tags={nature},ph={I},by={AUTHORFIRST several author words across the left lane AUTHORLAST},off={RECIPIENT},ex={EXFIRST extra text across multiple lines in the left lane EXLAST}]
\beginverse*
BODYMARK
\endverse
\endsong
\end{ulSongs}
\typeout{PRELUDE-EFFECTS:\the\TitleFontEffects/\the\PreludeEffects}
"""
        preamble = r"""
\ulNoSongNumbers\setlength\textwidth{200pt}
\ulShowTags{true}\ulShowPhase{true}\ulShowKey{true}\ulShowGoodKeys{true}
\renewcommand\ulPreludeTextGoodKeysAlone{GOODMARK}
\newcount\TitleFontEffects\newcount\PreludeEffects
\renewcommand\ulSongTitleFont{\sffamily\bfseries\Large\global\advance\TitleFontEffects1\relax}
\makeatletter
\let\OriginalMakePrelude\ulMakePrelude
\renewcommand\ulMakePrelude{\edef\ExpectedPreludeFamily{\f@family}\OriginalMakePrelude}
\let\OriginalExtendPrelude\ulExtendPrelude
\renewcommand\ulExtendPrelude{%
 \ifx\f@family\ExpectedPreludeFamily\else\errmessage{Prelude inherited title font}\fi
 \ifdim\linewidth=\hsize\else\errmessage{Prelude widths differ}\fi
 \global\advance\PreludeEffects1\relax\OriginalExtendPrelude}
\makeatother
"""
        output = self.compile_source(document(body, preamble))
        self.assertNotIn("Overfull \\hbox", output)
        self.assertEqual(re.findall(r"PRELUDE-EFFECTS:(\d+/\d+)", output), ["1/1"])
        words = [(text.strip("()"), {key: float(value) for key, value in box.items()})
                 for page in self.positioned_words() for text, box in page]
        positions = dict(words)
        left_edge = positions["GOODMARK"]["xMin"]
        prelude_words = [box for text, box in words
                         if box["yMin"] >= positions["AUTHORFIRST"]["yMin"]
                         and box["yMax"] <= positions["EXLAST"]["yMax"]
                         and text not in {"GOODMARK", "Dm", "Key:", "C", "nature", "I"}]
        self.assertTrue(prelude_words)
        self.assertLess(max(box["xMax"] for box in prelude_words), left_edge)
        self.assertGreater(positions["AUTHORLAST"]["yMin"], positions["AUTHORFIRST"]["yMin"])
        self.assertGreater(positions["EXLAST"]["yMin"], positions["EXFIRST"]["yMin"])

    def test_wrapped_title_uses_active_language_hyphenation(self):
        body = r"""
\begin{LANGUAGE}
\hyphenation{EXCEPTION}
\begin{ulSongs}{}
\beginsong{interoperability}
\beginverse*
x
\endverse
\endsong
\end{ulSongs}
\end{LANGUAGE}
"""
        preamble = r"""
\ulNoSongNumbers\setlength\textwidth{70pt}
\renewcommand\ulSongTitleFont{\normalfont\fontsize{14}{18}\selectfont}
"""
        for language, exception in (("english", "interoperability"),
                                    ("finnish", "inter-oper-ability")):
            with self.subTest(language=language):
                source = body.replace("LANGUAGE", language).replace("EXCEPTION", exception)
                output = self.compile_source(document(source, preamble), label=language)
                if language == "english":
                    self.assertIn("Overfull \\hbox", output)
                else:
                    self.assertNotIn("Overfull \\hbox", output)
                    self.assertIn("interoper-", self.pdf_text())

    def test_wrapped_alternate_titles_and_attribution_clear_all_heading_ink(self):
        body = r"""
\begin{ulSongs}{}
\beginsong{MAINSTART ordinary words across several lines MAINEND\\ALTSTART another heading across several lines ALTEND\\THIRDSTART more words across several lines \mbox{THIRDEND}}[key={C},gk={Dm},tags={nature},ph={I},by={ATTRIBUTION}]
\beginverse*
BODYMARK
\endverse
\endsong
\end{ulSongs}
"""
        preamble = r"""
\ulNoSongNumbers\setlength\textwidth{260pt}
\renewcommand\ulSongTitleFont{\normalfont\fontsize{16}{23}\selectfont}
\ulShowTags{true}\ulShowPhase{true}\ulShowKey{true}\ulShowGoodKeys{true}
"""
        output = self.compile_source(document(body, preamble))
        self.assertNotIn("Overfull \\hbox", output)
        words = {text.strip("()"): box for page in self.positioned_words() for text, box in page}
        for start, end in (("MAINSTART", "MAINEND"), ("ALTSTART", "ALTEND"),
                           ("THIRDSTART", "THIRDEND")):
            self.assertGreater(float(words[end]["yMin"]), float(words[start]["yMin"]))
        for before, after in (("MAINEND", "ALTSTART"), ("ALTEND", "THIRDSTART"),
                              ("THIRDEND", "ATTRIBUTION"), ("ATTRIBUTION", "BODYMARK")):
            self.assertGreater(float(words[after]["yMin"]), float(words[before]["yMax"]))

    def test_exhausted_title_lane_reports_a_diagnostic(self):
        source = document(r"""
\begin{ulSongs}{}
\beginsong{Heading}[key={C}]
\beginverse*
x
\endverse
\endsong
\end{ulSongs}
""", r"""
\ulNoSongNumbers\setlength\textwidth{80pt}
\ulShowKey{true}
\renewcommand\ulPreludeTextKey{An intentionally oversized badge label}
""")
        output = self.compile_source(source)
        self.assertIn("leave no room for the title", " ".join(output.split()))
        numbered = source.replace(r"\ulNoSongNumbers\setlength\textwidth{80pt}",
                                  r"\setlength\ulSongNumberWidth{90pt}\setlength\textwidth{80pt}")
        output = self.compile_source(numbered, label="numbered")
        self.assertIn("number panel leaves no room", " ".join(output.split()))

    def test_title_wrapping_also_works_with_direct_package_loading(self):
        source = r"""
\documentclass{book}
\usepackage{ulsbs}
\setlength\textwidth{200pt}
\begin{document}
\begin{ulSongs}{}
\beginsong{A title with enough ordinary words to require multiple lines}
\beginverse*
BODYMARK
\endverse
\endsong
\end{ulSongs}
\end{document}
"""
        output = self.compile_source(source)
        self.assertNotIn("Overfull \\hbox", output)
        self.assertIn("BODYMARK", self.pdf_text())

    def test_fitting_title_preserves_legacy_geometry(self):
        body = r"""
\begin{ulSongs}{}
\beginsong{Short\\Alternate}[tags={nature},ph={I},by={ATTRIBUTION}]
\beginverse*
BODYMARK
\endverse
\endsong
\end{ulSongs}
"""
        preamble = r"\ulNoSongNumbers\ulShowTags{true}\ulShowPhase{true}"
        legacy = r"""
\ExplSyntaxOn
\renewcommand\ulMakePrelude{
 \ulResetTitles
 \vbox{\raggedright\offinterlineskip\lineskip=1pt
  {\ulSongTitleFont\raisebox{0pt}[\ulSongTitleDefaultHeight]{\ulSongTitle}
   \hfill\__ulsbs_song_badges:\par
   \ulNextTitle\ulForEachTitle{(\ulSongTitle)\par}}
  \ifdim\prevdepth=0pt\kern1pt\fi
  \tiny\parskip=1pt\ulExtendPrelude\kern0pt}
 \ulResetTitles}
\ExplSyntaxOff
"""
        snapshots = []
        for label, extra in (("legacy", legacy), ("current", "")):
            self.compile_source(document(body, preamble + extra), label=label)
            snapshots.append(self.positioned_words())
        self.assertEqual(*snapshots)

    def test_key_badge_envelope_preserves_legacy_visible_geometry(self):
        body = r"""
\begin{ulSongs}{}
\beginsong{Short}[key={C}]
\beginverse*
BODYMARK
\endverse
\endsong
\end{ulSongs}
"""
        legacy = r"""
\makeatletter\ExplSyntaxOn
\cs_set_protected:Npn \__ulsbs_multikey_badge:n #1
 {\ulsbs@mainkeybox[ulChordColor]
   {\textit{\ulPreludeTextKey}~\textbf{\color{ulChordColor}#1\ulsbs@vphantommaxtext}}}
\ExplSyntaxOff\makeatother
"""
        snapshots = []
        for label, extra in (("legacy", legacy), ("current", "")):
            self.compile_source(document(body, r"\ulShowKey{true}" + extra), label=label)
            snapshots.append(self.positioned_words())
        self.assertEqual(*snapshots)

    def test_toc_three_digit_page_numbers_fit(self):
        body = r"""
\ulToc
\setcounter{page}{102}
\begin{ulSongs}{}
\beginsong{First TOC entry}
\beginverse*
First lyric.
\endverse
\endsong
\end{ulSongs}
\clearpage
\setcounter{page}{999}
\begin{ulSongs}{}
\beginsong{Second TOC entry}
\beginverse*
Second lyric.
\endverse
\endsong
\end{ulSongs}
"""
        for variant in ("default", "lyric"):
            with self.subTest(variant=variant):
                output = self.compile_source(document(body, variant=variant),
                                             label=variant, passes=2)
                self.assertNotIn("Overfull \\hbox", output)
                toc = (self.book / "book.toc").read_text()
                for page in ("102", "999"):
                    self.assertIn("}{" + page + "}{", toc)
                    self.assertIn(page, self.pdf_text())

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
                    source = document(body, preamble,
                                      variant="lyric" if edition == "lyric" else "default")
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
        # Exercise overflow deliberately, without relying on phantom chord height
        # in plain lyric lines. These fixtures have explicit authored leading.
        body = r"\begin{ulSongs}{}" + "\n"
        for name, lines in (("Alpha", 15), ("Beta", 27)):
            body += r"\beginsong{" + name + "}\n" + r"\beginverse*" + "\n"
            body += "\n".join(f"{name}{i}" for i in range(lines))
            body += "\n" + r"\endverse\endsong" + "\n"
        body += r"\end{ulSongs}"
        for position in (1, 2, 3):
            with self.subTest(songpos=position):
                self.compile_source(document(body,
                    r"\ulVerseBaseline{\fpeval{\ulVerseSpacingScale{baseline}{natural}+10*65536/(\number\fontcharht\font`A)}}{\ulVerseSpacingScale{baseline}{stretch}}{\ulVerseSpacingScale{baseline}{shrink}}\setlength\textheight{450pt}\ulSongColumns{2}\ulSongPosition{" +
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
            source = document(body, preamble,
                              variant="lyric" if edition == "lyric" else "default")
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

    def test_prelude_stays_with_first_body_content_across_pages_and_columns(self):
        # Explicit heading/filler dimensions leave room for only the heading.
        # A long body defeats whole-song fit policies and must still split later.
        preamble = r"""
\setlength\textheight{110pt}\setlength\textwidth{320pt}
\setlength\columnsep{20pt}\setlength\ulSongBarHeight{0pt}
\setlength\ulAfterPreludeSkip{0pt}\ulVerseSeparation{0}{0}{0}
\renewcommand\ulMakePrelude{\vbox to40pt{\hbox{\ulSongTitle}\vfil}}
\newcount\Effects\newcommand\Effect{\global\advance\Effects1 }
"""
        cases = (
            ("verse", "", "FIRSTLINE"),
            ("next-star", r"\textnotefornext{\Effect INTRO}*", "INTRO"),
            ("next", r"\textnotefornext{\Effect INTRO}", "INTRO"),
            ("textnote", r"\textnote{\Effect INTRO}", "INTRO"),
            ("prose", r"\Effect INTRO\par", "INTRO"),
            ("explanation", "\\begin{explanation}\n\\Effect INTRO\n\\end{explanation}", "INTRO"),
            ("spacing", r"\vspace*{0pt}\hbox{}\kern0pt\textnotefornext{\Effect INTRO}*", "INTRO"),
            ("hidden", r"{\ulLocalShow{musiccomments}{false}\musicnote{\Effect HIDDEN}}", "FIRSTLINE"),
        )
        verses = ("\\beginverse*\n\\Effect FIRSTLINE\n" + "LATERLINE\n" * 20
                  + "\\Effect LASTLINE\n\\endverse\n")
        for columns in (1, 2):
            for edition in ("default", "lyric"):
                for label, intro, first in cases:
                    with self.subTest(columns=columns, edition=edition, intro=label):
                        body = (r"\begin{ulSongs}{}"
                                r"\vbox to65pt{\hbox{FILLER}\vfil}\penalty0"
                                + "\n" + r"\beginsong{TARGET}[id={guarded-start}]" + "\n" + intro + "\n"
                                + verses + r"\endsong\end{ulSongs}"
                                r"\typeout{START-EFFECTS:\the\Effects}")
                        # Flow tests physical column breaks; default positioning
                        # also exercises dry-fit lookahead against the same guard.
                        settings = preamble + rf"\ulSongColumns{{{columns}}}"
                        if columns == 2:
                            settings += r"\ulSongPosition{0}"
                        output = self.compile_source(document(body, settings, variant=edition),
                            label=f"{columns}-{edition}-{label}")
                        locations = {}
                        for page, words in enumerate(self.positioned_words()):
                            for text, box in words:
                                if text in ("TARGET", first, "FIRSTLINE", "LASTLINE"):
                                    self.assertNotIn(text, locations)
                                    locations[text] = (page, float(box["xMin"]))
                        self.assertEqual(locations["TARGET"][0], locations[first][0])
                        self.assertLess(abs(locations["TARGET"][1] - locations[first][1]), 50)
                        # The header moves, rather than pushing the first content
                        # forward or making the entire song unbreakable.
                        self.assertTrue(locations["TARGET"][0] > 0
                                        or locations["TARGET"][1] > 200)
                        self.assertGreater(locations["LASTLINE"], locations["FIRSTLINE"])
                        self.assertNotIn("Overfull \\vbox", output)
                        self.assertNotIn("HIDDEN", self.pdf_text())
                        self.assertEqual(re.findall(r"START-EFFECTS:(\d+)", output),
                                         ["2" if first == "FIRSTLINE" else "3"])

    def test_song_start_guard_preserves_nodes_and_explicit_breaks(self):
        # Inspect real LuaTeX nodes independently of fonts or page geometry.
        source = document(r"""
\newbox\GuardBox
\setbox\GuardBox=\vbox{\write16{DEFERRED-GUARD-WRITE}\vskip3pt
  \penalty-10000\penalty-5\hbox{}\hrule height0pt\kern2pt\vskip0pt
  \hbox{FIRST}\penalty317\vskip7pt\hbox{LAST}}
\directlua{
  local b=tex.box[\number\GuardBox]
  local originals={}
  for n in node.traverse(b.list) do table.insert(originals,n) end
  local forced
  for n in node.traverse(b.list) do
    if n.id==node.id('penalty') and n.penalty==-10000 then forced=n end
  end
  local w,h,d=b.width,b.height,b.depth
  ulsbs_layout.protect_song_start(\number\GuardBox)
  assert(b.width==w and b.height==h and b.depth==d, 'Guard changed geometry')
  local seen,content=0,false
  for n in node.traverse(b.list) do
    if n==originals[seen+1] then seen=seen+1 end
    if n.id==node.id('hlist') and n.list then content=true end
    if n.id==node.id('penalty') then
      assert(n.penalty==(content and 317 or (n.penalty==-10000 and -10000 or 10000)),
        'Guard changed forced/later breaks or missed a leading penalty')
    elseif n.id==node.id('glue') and not content then
      assert(n.prev.id==node.id('penalty') and n.prev.penalty==10000,
        'Unprotected leading glue')
    end
  end
  assert(seen==rawlen(originals), 'Guard lost or reordered source nodes')
  assert(forced.penalty==-10000, 'Guard changed explicit forced break')
}
\box\GuardBox
\setbox\GuardBox=\vbox{\write16{EMPTY-GUARD-WRITE}}
\directlua{ulsbs_layout.protect_song_start(\number\GuardBox)}
\box\GuardBox
\begin{ulSongs}{}
\beginsong{Forced}\forcebrk
\beginverse*
FORCEDBODY
\endverse\endsong
\beginsong{Empty}\endsong
\end{ulSongs}
""", r"\ulSongPosition{0}")
        output = self.compile_source(source)
        self.assertEqual(output.count("DEFERRED-GUARD-WRITE"), 1)
        self.assertEqual(output.count("EMPTY-GUARD-WRITE"), 1)
        pages = self.pdf_text().split("\f")
        heading = next(i for i, text in enumerate(pages) if "Forced" in text)
        content = next(i for i, text in enumerate(pages) if "FORCEDBODY" in text)
        self.assertLess(heading, content)

    def test_selected_repeated_song_keeps_intro_without_replaying_source(self):
        body = r"""
\begin{ulSongs}{}
\vbox to65pt{\hbox{FILLER}\vfil}\penalty0
\beginsong{TARGET}[id={guarded-selection}]
\textnotefornext{\global\advance\Effects1 INTRO\write16{SELECTED-GUARD-WRITE}}*
\beginverse*
FIRSTLINE
LATERLINE
LASTLINE
\endverse\endsong
\end{ulSongs}\typeout{SELECTED-EFFECTS:\the\Effects}
"""
        preamble = r"""
\newcount\Effects\ulIncludeOnlySongs{1,1}\ulSongPosition{0}
\setlength\textheight{110pt}\setlength\ulSongBarHeight{0pt}
\setlength\ulAfterPreludeSkip{0pt}\ulVerseSeparation{0}{0}{0}
\renewcommand\ulMakePrelude{\vbox to40pt{\hbox{\ulSongTitle}\vfil}}
"""
        output = self.compile_source(document(body, preamble))
        self.assertEqual(re.findall(r"SELECTED-EFFECTS:(\d+)", output), ["1"])
        self.assertEqual(output.count("SELECTED-GUARD-WRITE"), 2)
        for words in self.positioned_words():
            text = [word for word, _ in words]
            self.assertEqual(text.count("TARGET"), text.count("INTRO"))
        for marker in ("TARGET", "INTRO", "FIRSTLINE", "LASTLINE"):
            self.assertEqual(self.pdf_text().count(marker), 2)

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
\translationoff
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

    def test_language_blocks_use_font_leading_not_verse_spacing(self):
        preamble = r"""
\makeatletter
\ulSongColumns{1}\ulSongPosition{0}
\renewcommand\baselinestretch{1.2}
\renewcommand\ulExplanationBaselineMultiplier{1.25}
\renewcommand\ulPassageBaselineMultiplier{1.5}
\newcount\BaselineInstalls
\expandafter\pretocmd\csname __ulsbs_verse_baseline:\endcsname
  {\global\advance\BaselineInstalls1 }{}{\errmessage{Baseline patch failed}}
\newcommand\CheckFontBaseline[2]{%
  \dimen0=#2\normalbaselineskip\relax
  \ifdim\baselineskip=\dimen0\else\errmessage{Wrong font baseline: #1}\fi
  \ifdim\gluestretch\baselineskip=0pt\else\errmessage{Prose stretch: #1}\fi
  \ifdim\glueshrink\baselineskip=0pt\else\errmessage{Prose shrink: #1}\fi
  \typeout{FONT-BASELINE:#1=\the\baselineskip}}
\newcommand\CheckVerseBaseline{%
  \ifdim\baselineskip=\csname l__ulsbs_verse_nominal_skip\endcsname
  \else\errmessage{Ordinary verse baseline changed}\fi}
\AddToHook{ulsbs/stanza/start}{%
  \ifulsbs@intranslation
    \CheckFontBaseline{translation-start}{1}%
  \else\CheckVerseBaseline\fi}
\makeatother
"""
        body = r"""
\begin{ulSongs}{}
\beginsong{Independent prose leading}[id={independent-prose},key={C}]
\beginverse*
\CheckVerseBaseline \[C]First lyric line.
Second lyric line.
\endverse
\edef\InstallsBeforeBlocks{\the\BaselineInstalls}
\begin{explanation}
\CheckFontBaseline{explanation}{1.25}Explanation text with enough words to wrap
into several physical lines inside the narrow song column.
\end{explanation}
\begin{passage}{Passage title}
\CheckFontBaseline{passage}{1.5}Passage text with enough words to wrap
into several physical lines inside the narrow song column.
\end{passage}
\begin{passage}*{Starred passage title}
\CheckFontBaseline{starred}{1.5}Starred passage text.
\end{passage}
\begin{translation}
\CheckFontBaseline{translation}{1}Translated first line.
Translated second line.
\end{translation}
{%
\renewcommand\ulExplanationFont{\fontsize{12}{18}\selectfont}
\renewcommand\ulPassageFont{\fontsize{12}{18}\selectfont}
\renewcommand\ulAltPassageFont{\fontsize{12}{18}\selectfont}
\renewcommand\ulTranslationFont{\fontsize{12}{18}\selectfont}
\begin{explanation}[EN]
\CheckFontBaseline{custom-explanation}{1.25}Custom explanation.
\end{explanation}
\begin{passage}[EN]{Custom passage title}
\CheckFontBaseline{custom-passage}{1.5}Custom passage.
\end{passage}
\begin{passage}*[EN]{Custom starred title}
\CheckFontBaseline{custom-starred}{1.5}Custom starred passage.
\end{passage}
\begin{translation}[EN]
\CheckFontBaseline{custom-translation}{1}Custom translation.
\end{translation}
}%
{\renewcommand\ulVerseFont{\small}% Same size as translation's built-in selection.
\begin{translation}
\CheckFontBaseline{same-size-translation}{1}Same size translation.
\end{translation}
}%
\ifnum\BaselineInstalls=\InstallsBeforeBlocks\relax\else
  \errmessage{Prose installed the verse baseline}\fi
\beginverse*
\CheckVerseBaseline Final lyric line.
\endverse\endsong\end{ulSongs}
"""
        baselines = []
        for multikey in (False, True):
            for scale in (3, 6):
                with self.subTest(multikey=multikey, scale=scale):
                    output = self.compile_source(
                        r"\def\ulPdfTranspositionLayers{" + str(multikey).lower() + "}"
                        + document(body, preamble + rf"\ulVerseBaseline{{{scale}}}{{.2}}{{.1}}"),
                        label=f"font-baselines-{multikey}-{scale}")
                    rows = re.findall(r"FONT-BASELINE:([^=\r\n]+)=([^\r\n]+)", output)
                    self.assertEqual(len(rows), 12, rows)
                    baselines.append(rows)
        self.assertTrue(all(rows == baselines[0] for rows in baselines[1:]))

    def test_translation_skip_is_opaque_empty_and_preserves_later_visible_blocks(self):
        hidden = r"""
\begin{translation}[PT]
\global\advance\TranslationEffects100
\translationon\input{must-not-be-read.tex}
\iftrue { } } { \iffalse
\end{translation}
"""
        preamble = r"""
\makeatletter
\newcount\TranslationEffects\newcount\TranslationFonts
\newcount\BlockStarts\newcount\FillCalls
\renewcommand\ulTranslationFont{\global\advance\TranslationFonts1 }
\pretocmd\ulsbs@blockstart{\global\advance\BlockStarts1 }{}{\errmessage{Block patch failed}}
\pretocmd\ulEndSongVfill{\global\advance\FillCalls1 }{}{\errmessage{Fill patch failed}}
\newcommand\TranslationEffect{\global\advance\TranslationEffects1 }
\setotherlanguage{portuguese}
\ulSongColumns{1}\ulSongPosition{0}
\makeatother
"""
        body = r"""
\makeatletter
\begin{ulSongs}{}\beginsong{Translation source}[id={translation-source},key={C}]
\beginverse*
\[<* E>C]Beforeanchor.
\endverse
\ulEndSongVfill{false}\global\FillCalls=0
\edef\SavedLanguage{\languagename}\edef\SavedColor{\current@color}
\setbox0=\vbox{HIDDEN-SOURCE}
\typeout{HIDDEN-DIMS:\the\wd0/\the\ht0/\the\dp0}
\typeout{HIDDEN-EFFECTS:\the\TranslationEffects/\the\TranslationFonts/\the\BlockStarts/\the\FillCalls}
\ExplSyntaxOn
\bool_if:NT \g__ulsbs_layout_fill_bool {\errmessage{Hidden translation changed fill}}
\ExplSyntaxOff
\edef\AfterLanguage{\languagename}\edef\AfterColor{\current@color}
\ifx\SavedLanguage\AfterLanguage\else\errmessage{Hidden language leaked}\fi
\ifx\SavedColor\AfterColor\else\errmessage{Hidden color leaked}\fi
\ifulsbs@intranslation\errmessage{Hidden translation leaked state}\fi
\beginverse*
\[<* E>G]Afteranchor.
\endverse
VISIBLE-SOURCE
\typeout{FINAL-EFFECTS:\the\TranslationEffects/\the\TranslationFonts/\the\BlockStarts/\the\FillCalls}
\edef\AfterLanguage{\languagename}\edef\AfterColor{\current@color}
\ifx\SavedLanguage\AfterLanguage\else\errmessage{Visible language leaked}\fi
\ifx\SavedColor\AfterColor\else\errmessage{Visible color leaked}\fi
\ifulsbs@intranslation\errmessage{Visible translation leaked state}\fi
\typeout{RESTORED-MUSIC:\ifulShowChords on\else off\fi/\ifulShowNotes on\else off\fi/\ifulShowBeats on\else off\fi/\ifulShowMeasures on\else off\fi/\ifulShowLilypond on\else off\fi/\ifulShowAltChords on\else off\fi}
\endsong\end{ulSongs}
"""
        # Local-off and book-off are independently empty; controls remove source
        # entirely. Visible translations then exercise all existing language paths.
        visible = "\n".join(
            r"\begin{translation}" + (f"[{language}]" if language else "") + "\n"
            + rf"\TranslationEffect Visible{language or 'None'}." + "\n"
            + r"\nextverse" + "\nSecond translated stanza.\n"
            + r"\end{translation}" for language in ("EN", "PT", "FI", ""))
        anchors = []
        for multikey in (False, True):
            for mode in ("local-off", "book-off", "control"):
                policy = (r"\ulShowTranslation{false}" if mode == "book-off" else "")
                request = r"\translationon" if mode == "book-off" else r"\translationoff"
                content = body.replace("HIDDEN-SOURCE", "" if mode == "control" else hidden)
                content = content.replace("VISIBLE-SOURCE", "" if mode == "book-off"
                                          else r"\translationon" + "\n" + visible)
                source = (rf"\def\ulPdfTranspositionLayers{{{'true' if multikey else 'false'}}}"
                          + document(content, preamble + policy + request))
                with self.subTest(multikey=multikey, mode=mode):
                    output = self.compile_source(source, label=f"{multikey}-{mode}", passes=3)
                    self.assertIn("HIDDEN-DIMS:0.0pt/0.0pt/0.0pt", output)
                    self.assertIn("HIDDEN-EFFECTS:0/0/0/0", output)
                    self.assertIn("FINAL-EFFECTS:" + ("0/0/0/0" if mode == "book-off"
                                                    else "4/4/4/4"), output)
                    self.assertIn("RESTORED-MUSIC:on/on/on/on/on/on", output)
                    words = {text: box for page in self.positioned_words() for text, box in page}
                    anchors.append([words[key] for key in ("Beforeanchor.", "Afteranchor.")])
                    text = self.pdf_text()
                    for language in ("EN", "PT", "FI", "None"):
                        self.assertEqual(text.count(f"Visible{language}."), int(mode != "book-off"))
        self.assertTrue(all(value == anchors[0] for value in anchors[1:]))

    def test_explanation_skip_is_opaque_empty_and_preserves_prose_state(self):
        hidden = r"""
\begin{explanation}[PT]
\global\advance\ExplanationEffects100
\ulLocalShow{explanation}{true}\input{must-not-be-read.tex}
\iftrue { } } { \iffalse
\end{explanation}
"""
        preamble = r"""
\makeatletter
\newcount\ExplanationEffects\newcount\ExplanationFonts\newcount\TranslationEffects
\newcount\BlockStarts\newcount\FillCalls\newcount\CodeBoxes
\renewcommand\ulExplanationFont{\global\advance\ExplanationFonts1 \rmfamily\footnotesize}
\pretocmd\ulsbs@blockstart{\global\advance\BlockStarts1 }{}{\errmessage{Block patch failed}}
\pretocmd\ulEndSongVfill{\global\advance\FillCalls1 }{}{\errmessage{Fill patch failed}}
\pretocmd\ulsbs@langcodebox{\global\advance\CodeBoxes1 }{}{\errmessage{Code patch failed}}
\newcommand\ExplanationEffect{\global\advance\ExplanationEffects1 }
\newif\ifulsbs@hide\ulsbs@hidefalse
\setotherlanguage{portuguese}
\ulSongColumns{1}\ulSongPosition{0}
\makeatother
"""
        body = r"""
\makeatletter
\begin{ulSongs}{}\beginsong{Explanation source}[id={explanation-source},key={C}]
\beginverse*
\[<* E>C]Beforeanchor.
\endverse
\ulEndSongVfill{true}\global\FillCalls=0
\edef\SavedLanguage{\languagename}\edef\SavedColor{\current@color}
\setbox0=\vbox{HIDDEN-SOURCE}
\typeout{HIDDEN-DIMS:\the\wd0/\the\ht0/\the\dp0}
\typeout{HIDDEN-EFFECTS:\the\ExplanationEffects/\the\ExplanationFonts/\the\BlockStarts/\the\FillCalls/\arabic{ulsbs@explcounter}/\the\CodeBoxes}
\ExplSyntaxOn
\bool_if:NF \g__ulsbs_layout_fill_bool {\errmessage{Hidden explanation changed fill}}
\ExplSyntaxOff
\ifulsbs@hide\errmessage{Hidden decision leaked}\fi
\typeout{AFTER-HIDDEN:\ifulShowExplanation on\else off\fi/\ifulShowTranslation on\else off\fi}
\edef\AfterLanguage{\languagename}\edef\AfterColor{\current@color}
\ifx\SavedLanguage\AfterLanguage\else\errmessage{Hidden language leaked}\fi
\ifx\SavedColor\AfterColor\else\errmessage{Hidden color leaked}\fi
\beginverse*
\[<* E>G]Afteranchor.
\endverse
VISIBLE-SOURCE
\typeout{FINAL-EFFECTS:\the\ExplanationEffects/\the\ExplanationFonts/\the\BlockStarts/\the\FillCalls/\arabic{ulsbs@explcounter}/\the\CodeBoxes}
\ExplSyntaxOn
\bool_if:NT \g__ulsbs_layout_fill_bool {\errmessage{Visible explanation lost end-fill policy}}
\ExplSyntaxOff
\begin{translation}[EN]
\global\advance\TranslationEffects1 Later translation.
\end{translation}
\typeout{TRANSLATION-EFFECTS:\the\TranslationEffects}
\edef\AfterLanguage{\languagename}\edef\AfterColor{\current@color}
\ifx\SavedLanguage\AfterLanguage\else\errmessage{Visible language leaked}\fi
\ifx\SavedColor\AfterColor\else\errmessage{Visible color leaked}\fi
\ifulsbs@hide\errmessage{Visible decision leaked}\fi
\ifulsbs@intranslation\errmessage{Translation state leaked}\fi
\typeout{RESTORED-MUSIC:\ifulShowChords on\else off\fi/\ifulShowNotes on\else off\fi/\ifulShowBeats on\else off\fi/\ifulShowMeasures on\else off\fi/\ifulShowLilypond on\else off\fi/\ifulShowAltChords on\else off\fi}
\endsong
\typeout{COUNTER-RESET:\arabic{ulsbs@explcounter}}
\end{ulSongs}
"""
        visible = "\n".join(
            r"\begin{explanation}" + (f"[{language}]" if language else "") + "\n"
            + rf"\ExplanationEffect Visible{language or 'None'}." + "\n"
            + r"\end{explanation}" for language in ("EN", "PT", "FI", ""))
        anchors = []
        for multikey in (False, True):
            for mode in ("local-off", "book-off", "language-skip", "control"):
                policy = r"\ulShowExplanation{false}" if mode == "book-off" else ""
                request = (r"\ulLocalShow{explanation}{false}" if mode in ("local-off", "control")
                           else r"\ulLocalShow{explanation}{true}")
                skip = r"\renewcommand\ulExplanationLanguagesToSkip{PT}" if mode == "language-skip" else ""
                # Author book-off remains denied; other modes restore the request
                # and remove only the language skip, not the independent omit list.
                content = body.replace("HIDDEN-SOURCE", "" if mode == "control" else hidden)
                content = content.replace("VISIBLE-SOURCE",
                                          r"\renewcommand\ulExplanationLanguagesToSkip{}"
                                          + r"\ulLocalShow{explanation}{true}" + "\n" + visible)
                # No visible explanation can change fill when book permission is denied.
                if mode == "book-off":
                    content = content.replace(r"\bool_if:NT \g__ulsbs_layout_fill_bool",
                                              r"\bool_if:NF \g__ulsbs_layout_fill_bool")
                source = (rf"\def\ulPdfTranspositionLayers{{{'true' if multikey else 'false'}}}"
                          + document(content, preamble + policy + request + skip
                                     + r"\renewcommand\ulExplanationOmitLangCodes{PT,FI}"))
                with self.subTest(multikey=multikey, mode=mode):
                    output = self.compile_source(source, label=f"explanation-{multikey}-{mode}", passes=3)
                    self.assertIn("HIDDEN-DIMS:0.0pt/0.0pt/0.0pt", output)
                    self.assertIn("HIDDEN-EFFECTS:0/0/0/0/0/0", output)
                    state = "on" if mode == "language-skip" else "off"
                    self.assertIn(f"AFTER-HIDDEN:{state}/on", output)
                    # Only the first explanation starts a block; later ones retain
                    # their smaller gap and increment the shared song counter.
                    self.assertIn("FINAL-EFFECTS:" + ("0/0/0/0/0/0" if mode == "book-off"
                                                    else "4/4/1/4/4/1"), output)
                    self.assertIn("TRANSLATION-EFFECTS:1", output)
                    self.assertIn("COUNTER-RESET:0", output)
                    self.assertIn("RESTORED-MUSIC:on/on/on/on/on/on", output)
                    words = {text: box for page in self.positioned_words() for text, box in page}
                    anchors.append([words[key] for key in ("Beforeanchor.", "Afteranchor.")])
                    text = self.pdf_text()
                    for language in ("EN", "PT", "FI", "None"):
                        self.assertEqual(text.count(f"Visible{language}."), int(mode != "book-off"))
                    self.assertEqual(text.count("Later translation."), 1)
        self.assertTrue(all(value == anchors[0] for value in anchors[1:]))

    def test_passage_skip_is_opaque_empty_and_preserves_later_prose(self):
        hidden = r"""
\begin{passage}*[PT]{\global\advance\PassageEffects100 Hidden title}
\global\advance\PassageEffects100
\ulLocalShow{passage}{true}\input{must-not-be-read.tex}
\iftrue { } } { \iffalse
\end{passage}
"""
        preamble = r"""
\makeatletter
\newcount\PassageEffects\newcount\PassageFonts\newcount\PassageTitles
\newcount\BlockStarts\newcount\FillCalls\newcount\CodeBoxes
\newcount\ExplanationEffects\newcount\TranslationEffects
\renewcommand\ulPassageFont{\global\advance\PassageFonts1 \ulLyricFontStyle}
\renewcommand\ulAltPassageFont{\global\advance\PassageFonts1 \ulLyricFontStyle\normalsize\sffamily\itshape}
\pretocmd\ulsbs@passagestart{\global\advance\PassageTitles1 }{}{\errmessage{Title patch failed}}
\pretocmd\ulsbs@blockstart{\global\advance\BlockStarts1 }{}{\errmessage{Block patch failed}}
\pretocmd\ulEndSongVfill{\global\advance\FillCalls1 }{}{\errmessage{Fill patch failed}}
\pretocmd\ulsbs@langcodebox{\global\advance\CodeBoxes1 }{}{\errmessage{Code patch failed}}
\newcommand\PassageEffect{\global\advance\PassageEffects1
 \ifdim\rightskip=\ulPassageRightSkip\else\errmessage{Passage right skip lost}\fi
 \ifdim\leftskip<\ulPassageLeftSkipAdd\errmessage{Passage left skip lost}\fi}
\newif\ifulsbs@hide\ulsbs@hidefalse
\setotherlanguage{portuguese}
\ulSongColumns{1}\ulSongPosition{0}
\makeatother
"""
        body = r"""
\makeatletter
\edef\SavedLanguage{\languagename}\edef\SavedColor{\current@color}
\setbox0=\vbox{HIDDEN-SOURCE}
\typeout{OUTSIDE-DIMS:\the\wd0/\the\ht0/\the\dp0}
\ifulsbs@hide\errmessage{Outside hide decision leaked}\fi
\begin{ulSongs}{}\beginsong{Passage source}[id={passage-source},key={C}]
\beginverse*
\[<* E>C]Beforeanchor.
\endverse
\ulEndSongVfill{false}\global\FillCalls=0
\setbox0=\vbox{HIDDEN-SOURCE}
\typeout{HIDDEN-DIMS:\the\wd0/\the\ht0/\the\dp0}
\typeout{HIDDEN-EFFECTS:\the\PassageEffects/\the\PassageFonts/\the\PassageTitles/\the\BlockStarts/\the\FillCalls/\the\CodeBoxes}
\ExplSyntaxOn
\bool_if:NT \g__ulsbs_layout_fill_bool {\errmessage{Hidden passage changed fill}}
\ExplSyntaxOff
\ifulsbs@hide\errmessage{Inside hide decision leaked}\fi
\edef\AfterLanguage{\languagename}\edef\AfterColor{\current@color}
\ifx\SavedLanguage\AfterLanguage\else\errmessage{Hidden language leaked}\fi
\ifx\SavedColor\AfterColor\else\errmessage{Hidden color leaked}\fi
\beginverse*
\[<* E>G]Afteranchor.
\endverse
VISIBLE-INSIDE
\ExplSyntaxOn
\bool_if:NT \g__ulsbs_layout_fill_bool {\errmessage{Visible passage changed fill}}
\ExplSyntaxOff
\begin{explanation}[EN]
\global\advance\ExplanationEffects1 Later explanation.
\end{explanation}
\begin{translation}[EN]
\global\advance\TranslationEffects1 Later translation.
\end{translation}
\endsong\end{ulSongs}
VISIBLE-OUTSIDE
\typeout{FINAL-EFFECTS:\the\PassageEffects/\the\PassageFonts/\the\PassageTitles/\the\CodeBoxes}
\typeout{LATER-PROSE:\the\ExplanationEffects/\the\TranslationEffects}
\edef\AfterLanguage{\languagename}\edef\AfterColor{\current@color}
\ifx\SavedLanguage\AfterLanguage\else\errmessage{Visible language leaked}\fi
\ifx\SavedColor\AfterColor\else\errmessage{Visible color leaked}\fi
\ifulsbs@hide\errmessage{Visible hide decision leaked}\fi
\typeout{RESTORED-MUSIC:\ifulShowChords on\else off\fi/\ifulShowNotes on\else off\fi/\ifulShowBeats on\else off\fi/\ifulShowMeasures on\else off\fi/\ifulShowLilypond on\else off\fi/\ifulShowAltChords on\else off\fi}
"""
        visible = [
            r"\begin{passage}" + ("*" if star else "")
            + (f"[{language}]" if language else "") + "{Title" + (language or "None") + "}\n"
            + r"\obeylines" + "\n" + rf"\PassageEffect Visible{language or 'None'}."
            + "\nSecond passage line.\n" + r"\disobeylines" + "\nRejoined prose.\n"
            + r"\end{passage}"
            for language, star in (("PT", False), ("", True), ("EN", False), ("FI", True))]
        anchors = []
        for multikey in (False, True):
            for mode in ("local-off", "book-off", "language-skip", "control"):
                policy = r"\ulShowPassage{false}" if mode == "book-off" else ""
                request = (r"\ulLocalShow{passage}{false}" if mode in ("local-off", "control")
                           else r"\ulLocalShow{passage}{true}")
                skip = r"\renewcommand\ulPassageLanguagesToSkip{PT}" if mode == "language-skip" else ""
                restore = r"\renewcommand\ulPassageLanguagesToSkip{}\ulLocalShow{passage}{true}" + "\n"
                content = body.replace("HIDDEN-SOURCE", "" if mode == "control" else hidden)
                content = content.replace("VISIBLE-INSIDE", restore + "\n".join(visible[:2]))
                content = content.replace("VISIBLE-OUTSIDE", restore + "\n".join(visible[2:]))
                source = (rf"\def\ulPdfTranspositionLayers{{{'true' if multikey else 'false'}}}"
                          + document(content, preamble + policy + request + skip
                                     + r"\renewcommand\ulPassageOmitLangCodes{PT,FI}"))
                with self.subTest(multikey=multikey, mode=mode):
                    output = self.compile_source(source, label=f"passage-{multikey}-{mode}", passes=3)
                    self.assertIn("OUTSIDE-DIMS:0.0pt/0.0pt/0.0pt", output)
                    self.assertIn("HIDDEN-DIMS:0.0pt/0.0pt/0.0pt", output)
                    self.assertIn("HIDDEN-EFFECTS:0/0/0/0/0/0", output)
                    # EN has a code; PT/FI omit theirs; later explanation adds EN.
                    self.assertIn("FINAL-EFFECTS:" + ("0/0/0/1" if mode == "book-off"
                                                    else "4/4/4/2"), output)
                    self.assertIn("LATER-PROSE:1/1", output)
                    self.assertIn("RESTORED-MUSIC:on/on/on/on/on/on", output)
                    words = {text: box for page in self.positioned_words() for text, box in page}
                    anchors.append([words[key] for key in ("Beforeanchor.", "Afteranchor.")])
                    text = self.pdf_text()
                    for language in ("EN", "PT", "FI", "None"):
                        self.assertEqual(text.count(f"Visible{language}."), int(mode != "book-off"))
                        self.assertEqual(text.count(f"Title{language}"), int(mode != "book-off"))
                    self.assertEqual(text.count("Later explanation."), 1)
                    self.assertEqual(text.count("Later translation."), 1)
        self.assertTrue(all(value == anchors[0] for value in anchors[1:]))

    def test_feeler_capture_is_lazy_empty_and_preserves_later_blocks(self):
        # Unlike the raw-skipping prose environments, feelers capture balanced
        # braces/environment delimiters. Unmatched conditional tokens stay opaque.
        hidden = r"""
\begin{feeler}
\global\advance\FeelerEffects100
\ulLocalShow{feeler}{true}\input{must-not-be-read.tex}\iftrue

\begin{em}\iffalse\end{em}
\end{feeler}
"""
        preamble = r"""
\makeatletter
\newcount\FeelerEffects\newcount\BlockStarts\newcount\FillCalls
\newcount\PassageEffects\newcount\ExplanationEffects\newcount\TranslationEffects
\pretocmd\ulsbs@blockstart{\global\advance\BlockStarts1 }{}{\errmessage{Block patch failed}}
\pretocmd\ulEndSongVfill{\global\advance\FillCalls1 }{}{\errmessage{Fill patch failed}}
{\small\em\xdef\ExpectedSize{\f@size}\xdef\ExpectedShape{\f@shape}}
\newcommand\FeelerEffect{\global\advance\FeelerEffects1
  \ifdim\f@size pt=\ExpectedSize pt\else\errmessage{Feeler small size lost}\fi
  \edef\ActualShape{\f@shape}\ifx\ActualShape\ExpectedShape\else\errmessage{Feeler emphasis lost}\fi}
\ulSongColumns{1}\ulSongPosition{0}
\makeatother
"""
        body = r"""
\makeatletter
\edef\SavedSize{\f@size}\edef\SavedShape{\f@shape}
\begin{ulSongs}{}\beginsong{Feeler source}[id={feeler-source},key={C}]
\beginverse*
\[<* E>C]Beforeanchor.
\endverse
\ulEndSongVfill{false}\global\FillCalls=0
\setbox0=\vbox{HIDDEN-SOURCE}
\typeout{HIDDEN-DIMS:\the\wd0/\the\ht0/\the\dp0}
\typeout{HIDDEN-EFFECTS:\the\FeelerEffects/\the\BlockStarts/\the\FillCalls}
\ExplSyntaxOn
\bool_if:NT \g__ulsbs_layout_fill_bool {\errmessage{Hidden feeler changed fill}}
\ExplSyntaxOff
\beginverse*
\[<* E>G]Afteranchor.
\endverse
\global\BlockStarts=0 \global\FillCalls=0
\ulLocalShow{feeler}{true}
\begin{feeler}
\FeelerEffect Visibleinside.

Second paragraph with \emph{nested emphasis}.
\end{feeler}
\typeout{VISIBLE-HOOKS:\the\BlockStarts/\the\FillCalls}
\ExplSyntaxOn
\bool_if:NTF \g__ulsbs_layout_fill_bool
  {\typeout{VISIBLE-FILL:on}}{\typeout{VISIBLE-FILL:off}}
\ExplSyntaxOff
\begin{passage}{Later passage}
\global\advance\PassageEffects1 Later passage body.
\end{passage}
\begin{explanation}[EN]
\global\advance\ExplanationEffects1 Later explanation.
\end{explanation}
\begin{translation}[EN]
\global\advance\TranslationEffects1 Later translation.
\end{translation}
\endsong
\global\BlockStarts=0 \global\FillCalls=0
\begin{intersong}
\setbox0=\vbox{HIDDEN-SOURCE}
\typeout{INTER-HIDDEN-DIMS:\the\wd0/\the\ht0/\the\dp0}
\begin{feeler}\FeelerEffect Visibleoutside.\end{feeler}
\end{intersong}
\typeout{INTER-HOOKS:\the\BlockStarts/\the\FillCalls}
\beginsong{Following}[key={C}]
\beginverse*\[<* G>C]Followinganchor.\endverse\endsong\end{ulSongs}
\typeout{FINAL-EFFECTS:\the\FeelerEffects/\the\PassageEffects/\the\ExplanationEffects/\the\TranslationEffects}
\edef\AfterSize{\f@size}\edef\AfterShape{\f@shape}
\ifx\SavedSize\AfterSize\else\errmessage{Feeler size leaked}\fi
\ifx\SavedShape\AfterShape\else\errmessage{Feeler emphasis leaked}\fi
\typeout{RESTORED-MUSIC:\ifulShowChords on\else off\fi/\ifulShowNotes on\else off\fi/\ifulShowBeats on\else off\fi/\ifulShowMeasures on\else off\fi/\ifulShowLilypond on\else off\fi/\ifulShowAltChords on\else off\fi}
"""
        anchors = []
        for multikey in (False, True):
            for mode in ("local-off", "book-off", "control"):
                policy = r"\ulShowFeeler{false}" if mode == "book-off" else ""
                # Each hidden occurrence has its own request scope, including
                # the intersong occurrence after a visible in-song restoration.
                hidden_source = ("" if mode == "control" else
                                 r"\ulLocalShow{feeler}{false}" + hidden)
                content = body.replace("HIDDEN-SOURCE", hidden_source)
                source = (rf"\def\ulPdfTranspositionLayers{{{'true' if multikey else 'false'}}}"
                          + document(content, preamble + policy))
                with self.subTest(multikey=multikey, mode=mode):
                    output = self.compile_source(source, label=f"feeler-{multikey}-{mode}", passes=3)
                    for marker in ("HIDDEN-DIMS:0.0pt/0.0pt/0.0pt",
                                   "INTER-HIDDEN-DIMS:0.0pt/0.0pt/0.0pt", "HIDDEN-EFFECTS:0/0/0"):
                        self.assertIn(marker, output)
                    visible = int(mode != "book-off")
                    self.assertIn(f"VISIBLE-HOOKS:{visible}/{visible}", output)
                    self.assertIn(f"INTER-HOOKS:{visible}/{visible}", output)
                    self.assertIn(f"VISIBLE-FILL:{'on' if visible else 'off'}", output)
                    self.assertIn(f"FINAL-EFFECTS:{2 * visible}/1/1/1", output)
                    self.assertIn("RESTORED-MUSIC:on/on/on/on/on/on", output)
                    words = {text: box for page in self.positioned_words() for text, box in page}
                    anchors.append([words[key] for key in ("Beforeanchor.", "Afteranchor.")])
                    text = self.pdf_text()
                    for marker in ("Visibleinside.", "Visibleoutside."):
                        self.assertEqual(text.count(marker), visible)
                    for marker in ("Later passage body.", "Later explanation.", "Later translation."):
                        self.assertEqual(text.count(marker), 1)
        self.assertTrue(all(value == anchors[0] for value in anchors[1:]))

    def test_hidden_musiccomments_are_opaque_empty_and_preserve_open_verse(self):
        hidden = r"""
\musicnote{\global\advance\CommentEffects100\input{must-not-be-read.tex}\iftrue}
\musicnoteforprev{\global\advance\CommentEffects100\iffalse}
\musicnotefornext{\ulLocalShow{musiccomments}{true}\iftrue}*
\musicnotefornext{\input{must-not-be-read.tex}\iffalse}
\musicnotemiddle{\global\advance\CommentEffects100\iftrue}
"""
        preamble = r"""
\newcount\CommentEffects\newcount\DisplayEffects\newcount\GlueEffects\newcount\FillEffects
\makeatletter
\pretocmd\textnote{\global\advance\DisplayEffects1 }{}{\errmessage{Note patch failed}}
\pretocmd\attachednote{\global\advance\DisplayEffects1 }{}{\errmessage{Attached patch failed}}
\pretocmd\glueverses{\global\advance\GlueEffects1 }{}{\errmessage{Glue patch failed}}
\pretocmd\ulEndSongVfill{\global\advance\FillEffects1 }{}{\errmessage{Fill patch failed}}
\makeatother
\ulSongColumns{1}\ulSongPosition{0}
"""
        body = r"""
\begin{ulSongs}{}\beginsong{Hidden comments}[id={hidden-comments},key={C}]
\beginverse*
\[<* E>C]Beforeanchor.
\global\DisplayEffects=0 \global\GlueEffects=0 \global\FillEffects=0
\setbox0=\vbox{HIDDEN-COMMENTS}
\typeout{HIDDEN-DIMS:\the\wd0/\the\ht0/\the\dp0}
HIDDEN-COMMENTS
\typeout{HIDDEN-HOOKS:\the\CommentEffects/\the\DisplayEffects/\the\GlueEffects/\the\FillEffects}
\[<* G>G]Afteranchor.
\endverse
HIDDEN-COMMENTS
\endsong
\beginsong{Following}[id={following-comments},key={C}]
\beginverse*Followinganchor.\endverse\endsong\end{ulSongs}
"""
        anchors = []
        for multikey in (False, True):
            for mode in ("local-off", "book-off", "control"):
                policy = (r"\ulShowMusicComments{false}\ulLocalShow{musiccomments}{true}"
                          if mode == "book-off" else r"\ulLocalShow{musiccomments}{false}")
                source = (rf"\def\ulPdfTranspositionLayers{{{'true' if multikey else 'false'}}}"
                          + document(body.replace("HIDDEN-COMMENTS", "" if mode == "control" else hidden),
                                     preamble + policy))
                with self.subTest(multikey=multikey, mode=mode):
                    output = self.compile_source(source, label=f"comments-{multikey}-{mode}", passes=3)
                    self.assertIn("HIDDEN-DIMS:0.0pt/0.0pt/0.0pt", output)
                    self.assertIn("HIDDEN-HOOKS:0/0/0/0", output)
                    words = {text: box for page in self.positioned_words() for text, box in page}
                    anchors.append([words[key] for key in ("Beforeanchor.", "Afteranchor.",
                                                           "Followinganchor.")])
        self.assertTrue(all(value == anchors[0] for value in anchors[1:]))

    def test_visible_musiccomments_match_text_adapters_once_with_chords_off(self):
        # The text adapters are the spacing/attachment reference, including the
        # trailing star. Chord/pitch/score suppression must not hide musical prose.
        body = r"""
\makeatletter
\edef\SavedSize{\f@size}\edef\SavedColor{\current@color}
\begin{ulSongs}{}\beginsong{Visible comments}[id={visible-comments}]
\musicnotefornext{\CommentEffect Firstcomment.}*
\beginverse*
Beforeanchor.
\musicnote{\CommentEffect Wrappedcomment with enough prose to wrap naturally across the narrow song width without re-evaluating its source.}
Afteranchor.
\endverse
\musicnoteforprev{\CommentEffect Previouscomment.}
\musicnotefornext{\CommentEffect Nextcomment.}
\beginverse*Secondanchor.\endverse
\musicnotemiddle{\CommentEffect Middlecomment.}
\endsong
\begin{intersong}\musicnote{\CommentEffect Outsidecomment.}\end{intersong}
\beginsong{Following}\beginverse*Followinganchor.\endverse\endsong\end{ulSongs}
\edef\AfterSize{\f@size}\edef\AfterColor{\current@color}
\ifx\SavedSize\AfterSize\else\errmessage{Comment size leaked}\fi
\ifx\SavedColor\AfterColor\else\errmessage{Comment color leaked}\fi
\typeout{VISIBLE-EFFECTS:\the\CommentEffects}
"""
        preamble = r"""
\ulShowChords{false}\ulShowNotes{false}\ulShowLilypond{false}
\ulSongColumns{1}\ulSongPosition{0}\setlength\textwidth{190pt}
\makeatletter
{\ulNoteFont\xdef\ExpectedSize{\f@size}}
{\color{ulChordColor}\xdef\ExpectedColor{\current@color}}
\newcount\CommentEffects
\newcommand\CommentEffect{\global\advance\CommentEffects1
  \ifdim\f@size pt=\ExpectedSize pt\else\errmessage{Wrong comment size}\fi
  \edef\ActualColor{\current@color}
  \ifx\ActualColor\ExpectedColor\else\errmessage{Wrong comment color}\fi}
\makeatother
"""
        positions = []
        for mode in ("comments", "text-adapters"):
            content = body
            if mode == "text-adapters":
                for suffix in ("fornext", "forprev", "middle", ""):
                    content = content.replace(r"\musicnote" + suffix + "{",
                                              r"\textnote" + suffix + r"{\color{ulChordColor}")
            output = self.compile_source(document(content, preamble), label=mode, passes=2)
            self.assertEqual(re.findall(r"VISIBLE-EFFECTS:(\d+)", output), ["6", "6"])
            positions.append(self.positioned_words())
            text = self.pdf_text()
            for marker in ("Firstcomment.", "Wrappedcomment", "Previouscomment.", "Nextcomment.",
                           "Middlecomment.", "Outsidecomment.", "Followinganchor."):
                self.assertEqual(text.count(marker), 1)
        self.assertEqual(*positions)

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
                variant = r"\def\ulBuildVariant{lyric}" + "\n" + source.replace(
                    r"\documentclass[", r"\documentclass[variants={default,lyric},")
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
            source = document(body, preamble,
                              variant="lyric" if edition == "lyric" else "default")
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
            if mode == "two-column":
                preamble += r"\ulSongColumns{2}"
            source = document(body, preamble,
                              variant="lyric" if mode == "lyric" else "default")
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
            r"\ulVerseBaseline{\fpeval{\ulVerseSpacingScale{baseline}{natural}+10*65536/(\number\fontcharht\font`A)}}{\ulVerseSpacingScale{baseline}{stretch}}{\ulVerseSpacingScale{baseline}{shrink}}\newcount\EmptyEffects\def\EmptyEffect{\global\advance\EmptyEffects1 }")
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
""", variant="lyric")
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
