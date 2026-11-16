# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Guitar diagram parsing, transposition and evaluation contracts."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_pdf_transposition_layers import PdfStructure, rendered_pages, words_and_geometry
from test_tex_integration import ROOT, TEX_ASSETS


# Input census from the real technical-information catalogue and song notes.
CORPUS_DIAGRAMS = r"""
\gtab{A}{X02220:001230} \gtab{Am}{X02210:002310} \gtab{A7}{X02020:002030}
\gtab{Am7}{X02010:002010} \gtab{A6}{X02222:001111} \gtab{Am6}{X02212:002314}
\gtab{Amadd9-}{X02310:002310} \gtab{A\symdim7}{X01212:001324} \gtab{Asus2}{X02200:002300}
\gtab{Asus4}{X02230:002340} \gtab{A7sus4}{X02233:001234}
\gtab{B&}{X13331:013331} \gtab{B&7}{X13131:013141} \gtab{B&maj7}{X1323X:013240}
\gtab{B}{X24442:013331} \gtab{Bm}{X24432:013421} \gtab{B7}{X21202:021304}
\gtab{Bm7}{X24232:013121} \gtab{B\symdim7}{X20101:030102} \gtab{Bm7&5}{X2323X:013240}
\gtab{Bm11/D}{XX0200:000100}
\gtab{C}{X32010:032010} \gtab{Cm}{X35543:013421} \gtab{C7}{X32310:032410}
\gtab{Cmaj7}{X32000:032000} \gtab{Cadd9}{X3203X:032040} \gtab{C6}{X32210:043210}
\gtab{Cm6}{X35045:013024}
\gtab{C#}{X46664:013331} \gtab{C#\symdim7}{XX2323:001324} \gtab{C#m7&5}{022020:023040}
\gtab{D}{XX0232:000132} \gtab{Dm}{XX0231:000231} \gtab{Dm/F}{XX3231:003241}
\gtab{D7}{XX0212:000213} \gtab{D7sus4}{XX0213:000214} \gtab{Dm7}{XX0211:000211}
\gtab{Dmaj7}{XX0222:000111} \gtab{D6}{XX0202:000102} \gtab{Dm6}{XX0201:000201}
\gtab{D\symdim7}{XX0101:000102}
\gtab{E&}{X65343:043121} \gtab{E&maj7}{XX1333:001333}
\gtab{E}{022100:023100} \gtab{Em}{022000:023000} \gtab{E7}{022130:023140}
\gtab{Em7}{022030:023040} \gtab{E\symdim7}{XX2323:001324} \gtab{Em7&5}{XX2333:001222}
\gtab{F}{133211:134211} \gtab{Fmaj7}{XX3210:003210} \gtab{Fmaj7&5}{102200:102300}
\gtab{F6}{100211:200311}
\gtab{F#}{244322:134211} \gtab{F#m}{244222:134111} \gtab{F#7}{XX4320:003210}
\gtab{F#m7}{242222:131111} \gtab{F#\symdim7}{XX1212:001324} \gtab{F#m7&5}{XX2212:002314}
\gtab{F#m11/A}{X02102:002103}
\gtab{G}{320033:210034} \gtab{Gm}{355333:134111} \gtab{G7}{320001:320001}
\gtab{Gm7}{353333:131111} \gtab{Gmaj7}{320002:320001} \gtab{Gadd9}{XX5435:003214}
\gtab{G7sus4}{330011:340011} \gtab{G6}{XX5430:003210} \gtab{Gm6}{312030:312040}
\gtab{A&7}{464544:131222}
"""
DIAGRAM_PATTERN = r"\\gtab\{([^{}]*)\}\{([^{}]*)\}"

LEGACY_DIAGRAM_DRAW = r"""
\makeatletter\ExplSyntaxOn
\cs_set_protected:Npn \__ulsbs_diagram_draw:nn #1#2
 {\group_begin:
  \__ulsbs_diagram_parse:n {#2}\mode_leave_vertical:
  \vbox{\normalfont\normalsize
   \hbox_set:Nn \l__ulsbs_diagram_title_box
    {\thinspace{\ulPrintChord{\transposehere{#1}\strut}}\thinspace}
   \hbox_set:Nn \l__ulsbs_diagram_base_box
    {{\sffamily\fontsize{10}{10}\selectfont\l__ulsbs_diagram_base_tl}}
   \hbox_set:Nn \l__ulsbs_diagram_top_box
    {\seq_map_function:NN \l__ulsbs_diagram_strings_seq \__ulsbs_diagram_top:n}
   \dim_set:Nn \l__ulsbs_diagram_width_dim
    {\dim_max:nn {\box_wd:N \l__ulsbs_diagram_title_box}
     {\box_wd:N \l__ulsbs_diagram_base_box+\l__ulsbs_diagram_grid_dim}}
   \bool_if:NT \l__ulsbs_diagram_annotation_bool
    {\dim_gset:Nn \g__ulsbs_diagram_pending_indent_dim
      {\box_wd:N \l__ulsbs_diagram_base_box+2.5pt}
     \dim_set:Nn \l_tmpa_dim {\l__ulsbs_diagram_width_dim
      -\box_wd:N \l__ulsbs_diagram_base_box-\l__ulsbs_diagram_grid_dim}
     \tex_divide:D \l_tmpa_dim by 2\scan_stop:
     \dim_gadd:Nn \g__ulsbs_diagram_pending_indent_dim {\l_tmpa_dim}}
   \hbox_to_wd:nn {\l__ulsbs_diagram_width_dim}
    {\hfil\hbox_unpack_drop:N \l__ulsbs_diagram_title_box\hfil}
   \kern-1pt\nointerlineskip
   \hbox_to_wd:nn {\l__ulsbs_diagram_width_dim}
    {\hfil\vtop{\kern3pt\box_use_drop:N \l__ulsbs_diagram_base_box}
     \vtop{\box_use_drop:N \l__ulsbs_diagram_top_box
      \int_step_inline:nn {\l__ulsbs_diagram_rows_int}
       {\int_set:Nn \l__ulsbs_diagram_row_int {##1}
        \__ulsbs_diagram_rule:\hbox{\__ulsbs_diagram_row:}}
      \__ulsbs_diagram_rule:\kern1.5pt
      \hbox{\tl_map_inline:Nn \l__ulsbs_diagram_fingers_tl
       {\hbox_to_wd:nn {6pt}{\hfil
        \str_if_in:nnF {X0O}{##1}{\sffamily\fontsize{6}{6}\selectfont##1}\hfil}}}}
     \hfil}\kern3pt}
  \group_end:\bool_set_false:N \l__ulsbs_diagram_annotation_bool}
\ExplSyntaxOff\makeatother
"""

NUT_POSITION_PROBE = r"""
\newwrite\NutPositions\immediate\openout\NutPositions=\jobname.nut\relax
\newcount\NutIndex
\makeatletter\ExplSyntaxOn
\bool_new:N \l__probe_nut_bool
\cs_new_eq:NN \ProbeDraw \__ulsbs_diagram_draw:nn
\cs_set_protected:Npn \__ulsbs_diagram_draw:nn #1#2
 {\group_begin:\bool_set_false:N \l__probe_nut_bool
  \global\advance\NutIndex1\relax\edef\NutItem{\the\NutIndex}
  \ProbeDraw{#1}{#2}\group_end:}
\cs_new_eq:NN \ProbeRule \__ulsbs_diagram_rule:
\cs_set_protected:Npn \__ulsbs_diagram_rule:
 {\bool_if:NF \l__probe_nut_bool
   {\bool_set_true:N \l__probe_nut_bool\savepos
    \edef\NutWrite{\noexpand\write\NutPositions
     {NUT:\NutItem/\noexpand\the\noexpand\lastxpos/\noexpand\the\noexpand\lastypos}}\NutWrite}
  \ProbeRule}
\ExplSyntaxOff\makeatother
"""


class DiagramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [tool for tool in ("lualatex", "qpdf", "pdftotext", "pdfinfo")
                   if shutil.which(tool) is None]
        if missing:
            raise unittest.SkipTest("TeX/PDF tools required: " + ", ".join(missing))
        cls.temporary = tempfile.TemporaryDirectory(prefix="ulsbs-diagrams-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.work = Path(cls.temporary.name)
        cls.cache = cls.work / "cache"
        cls.cache.mkdir()
        cls.diagnostics = ROOT / "build/diagrams"
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.addCleanup(shutil.rmtree, self.work / self._testMethodName, ignore_errors=True)

    def compile_checked(self, body, preamble="", *, lyric=False, multikey=False, offsets=(None,), effects=None, label=None):
        target = self.diagnostics / self._testMethodName
        source = (r"\documentclass[variants={default,lyric},oneside,openany,maintitle={Guitar diagrams}]{ulsbs-songbook}"
                  + "\n" + r"\ulShowTags{false}\ulShowPhase{false}" + "\n" + preamble
                  + "\n" + r"\begin{document}" + "\n" + body
                  + "\n" + r"\typeout{DIAGRAM-COUNTERS:\arabic{ulSongNumber}:\arabic{ulVerseNumber}:\the\ulMinFrets}"
                  + "\n" + r"\end{document}" + "\n")
        work = self.work / self._testMethodName
        if label:
            work /= label
            target /= label
        work.mkdir(parents=True)
        options = r"\def\ulBuildVariant{lyric}" + "\n" if lyric else ""
        if multikey:
            options += (r"\def\ulPdfTranspositionLayers{true}" + "\n"
                        + r"\def\ulPdfTranspositionLayerUi{hidden}" + "\n")
        (work / "book.tex").write_text(options + source)
        env = dict(os.environ, TEXINPUTS=f"{TEX_ASSETS}//{os.pathsep}",
                   LUAINPUTS=f"{TEX_ASSETS}//{os.pathsep}", TEXMFVAR=str(self.cache),
                   TEXMFCACHE=str(self.cache))
        output = []
        # Match production reruns so ocgx2 references include the outline objects.
        passes = 3 if multikey else 2
        try:
            for _ in range(passes):
                result = subprocess.run(
                    ["lualatex", "-interaction=nonstopmode", "-halt-on-error", "book.tex"],
                    cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, timeout=120)
                output.append(result.stdout)
                (work / "compile.stdout").write_text("\n".join(output))
                self.assertEqual(result.returncode, 0, result.stdout)
        finally:
            shutil.copytree(work, target, dirs_exist_ok=True)
        pdf = (work / "book.pdf").read_bytes()
        self.assertTrue(words_and_geometry(pdf))
        if multikey:
            names = set(PdfStructure(pdf).names.values())
            for offset in offsets:
                if offset is not None:
                    self.assertTrue(any(name.endswith(f":t{offset:02d}") for name in names))
        if effects is not None:
            self.assertEqual(re.findall(r"DIAGRAM-EFFECTS:(\d+)", "\n".join(output)),
                              [str(effects)] * passes)
        return "\n".join(output), pdf

    def test_grid_wraps_at_available_width_with_uniform_columns(self):
        body = r"""
\begin{ulChordDiagramGrid}
{\gtab{C}{X32010}} \gtab{D}{XX0232} \gtab{E}{022100}
\gtab{F}{133211} \gtab{G}{320033} \gtab{A}{X02220}
\end{ulChordDiagramGrid}
\noindent Z
"""
        for width, columns in ((150, 4), (100, 2), (40, 1), (20, 1)):
            with self.subTest(width=width):
                # Check row packing exactly, retaining the legacy symbol-cell tolerance.
                preamble = rf"\setlength\textwidth{{{width}pt}}" + r"""
\ExplSyntaxOn
\cs_new_eq:NN \ProbeGridEmit \__ulsbs_diagram_grid_emit:
\cs_set_protected:Npn \__ulsbs_diagram_grid_emit: {\hfuzz=0pt\ProbeGridEmit}
\ExplSyntaxOff
"""
                output, pdf = self.compile_checked(body, preamble, label=str(width))
                self.assertNotIn("Overfull \\hbox", output)
                words = {row[1]: row for row in words_and_geometry(pdf) if len(row) == 6}
                rows = [[words[name] for name in "CDE FGA".replace(" ", "")[i:i + columns]]
                        for i in range(0, 6, columns)]
                self.assertEqual(len({row[0][3] for row in rows}), len(rows))
                for row in rows:
                    for left, right in zip(row, row[1:]):
                        self.assertLess(left[4], right[2])
                self.assertGreater(words["Z"][3], max(word[5] for row in rows for word in row))

    def test_grid_aligns_nut_rules_not_titles_markers_or_bottoms(self):
        body = r"""
\begin{ulChordDiagramGrid}
\\
\gtab{C}{X32010:032010}
\gtab{F}{133211:134211}
\gtab{\Huge D}{4:XX0987:001324}
\gtab{G}{XXXXXX}
\\\\
{\ulMinFrets=1\gtab{E}{6:111111}}
\gtab{A}{OOOOOO}
\\
\end{ulChordDiagramGrid}
\noindent Z
"""
        output, _ = self.compile_checked(body, NUT_POSITION_PROBE)
        self.assertNotIn("Overfull \\hbox", output)
        positions = [tuple(map(int, row)) for row in re.findall(
            r"NUT:(\d+)/(-?\d+)/(-?\d+)",
            (self.work / self._testMethodName / "book.nut").read_text())]
        self.assertEqual([row[0] for row in positions], list(range(1, 7)))
        self.assertEqual(len({row[2] for row in positions[:4]}), 1)
        self.assertEqual(len({row[2] for row in positions[4:]}), 1)
        self.assertLess(positions[4][2], positions[0][2])

    def test_grid_spreads_columns_consistently_without_doubling_row_gaps(self):
        entries = r"""
\gtab{C}{X32010:032010}\gtab{F}{133211:134211}\\
\gtab{A}{X02220:001230}\\
\gtab{G}{320033:210034}\gtab{Am}{X02210:002310}
"""
        body = (r"\begin{ulChordDiagramGrid}" + entries + r"\end{ulChordDiagramGrid}"
                + r"\begin{ulChordDiagramGrid}[6pt]" + entries + r"\end{ulChordDiagramGrid}")
        output, pdf = self.compile_checked(body, NUT_POSITION_PROBE + r"\setlength\textwidth{80pt}")
        self.assertNotIn("Overfull", output)
        positions = [tuple(map(int, row)) for row in re.findall(
            r"NUT:(\d+)/(-?\d+)/(-?\d+)",
            (self.work / self._testMethodName / "book.nut").read_text())]
        self.assertEqual([row[0] for row in positions], list(range(1, 11)))
        self.assertAlmostEqual((positions[1][1] - positions[0][1]) / 65536, 40.75, places=4)
        self.assertAlmostEqual((positions[6][1] - positions[5][1]) / 65536, 43, places=4)
        for first_column, second_column in (((0, 2, 3), (1, 4)), ((5, 7, 8), (6, 9))):
            self.assertEqual(len({positions[index][1] for index in first_column}), 1)
            self.assertEqual(len({positions[index][1] for index in second_column}), 1)
        default_row_distance = positions[0][2] - positions[2][2]
        custom_row_distance = positions[5][2] - positions[7][2]
        self.assertAlmostEqual((custom_row_distance - default_row_distance) / 65536, 4.5, places=4)
        words = [row for row in words_and_geometry(pdf) if len(row) == 6]
        first_c = next(row for row in words if row[1] == "C")
        first_a = next(row for row in words if row[1] == "A")
        fingers = [row for row in words if row[1].isdigit() and first_c[5] < row[3] < first_a[3]]
        visible_gap = (first_a[3] - max(row[5] for row in fingers)) * 72.27 / 72
        self.assertGreaterEqual(visible_gap, 3)
        self.assertLessEqual(visible_gap, 5)

    def test_grid_preserves_grouped_settings_catcodes_and_source_effects(self):
        body = r"""
\newcount\DiagramEffects
\newcommand\DiagramEffect{\global\advance\DiagramEffects1\relax}
\let\DiagramPrintChord\ulPrintChord
\renewcommand\ulPrintChord[1]{\global\advance\DiagramEffects1\relax\DiagramPrintChord{#1}}
\begin{ulChordDiagramGrid}
\gtab{\DiagramEffect A6}{X02222:001111}
{\ulMinFrets=7\gtab{\DiagramEffect C#sus4}{4:XX3341}}
{\transpose{2}\gtab{\DiagramEffect G}{320033:210034}}
{\renewcommand\gtabtrans[2]{\gtab{#1}{#2}}\transpose{-3}
 \gtab{\DiagramEffect F}{133211:134211}}
\end{ulChordDiagramGrid}
\begin{ulChordDiagramGrid}\gtab{B&}{X13331}\end{ulChordDiagramGrid}
{\transpose{2}\begin{ulChordDiagramGrid}[0pt]\gtab{}{}\end{ulChordDiagramGrid}}
\begin{ulChordDiagramGrid}\\\\\end{ulChordDiagramGrid}
\gtab{C}{X32010}\par
\typeout{DIAGRAM-EFFECTS:\the\DiagramEffects}
\ExplSyntaxOn
\int_compare:nNnF {\g__ulsbs_diagram_grid_item_int}={0}{\errmessage{Grid items leaked}}
\seq_if_empty:NF \g__ulsbs_diagram_grid_items_seq {\errmessage{Grid sequence leaked}}
\dim_compare:nNnF {\g__ulsbs_diagram_grid_max_dim}={0pt}{\errmessage{Grid width leaked}}
\int_step_inline:nn {4}
 {\exp_args:Nc \box_if_empty:NF {g__ulsbs_diagram_grid_item_#1_box}{\errmessage{Grid nodes leaked}}}
\ExplSyntaxOff
"""
        # The last explicit grid and standalone chord add two print-chord calls.
        output, pdf = self.compile_checked(body, effects=9)
        self.assertNotIn("Overfull \\hbox", output)
        text = " ".join(row[1] for row in words_and_geometry(pdf) if len(row) == 6)
        self.assertIn("A6", text)
        self.assertIn("sus4", text)

    def test_grid_rows_can_split_across_pages(self):
        body = (r"\begin{ulChordDiagramGrid}" + "\n"
                + "\n".join(r"\gtab{C}{X32010}\\" for _ in range(15))
                + "\n" + r"\end{ulChordDiagramGrid}\noindent Z")
        output, pdf = self.compile_checked(body, r"\setlength\textheight{160pt}")
        self.assertNotIn("Overfull", output)
        words = [row for row in words_and_geometry(pdf) if len(row) == 6]
        self.assertEqual(sum(row[1] == "C" for row in words), 15)
        self.assertGreater(len({row[0] for row in words if row[1] == "C"}), 1)

    def test_grid_reference_refactor_preserves_standalone_and_annotation_ink(self):
        if shutil.which("pdftoppm") is None:
            self.skipTest("pdftoppm is not installed")
        body = r"""
\gtab{C}{X32010:032010} \gtab{F}{133211:134211} \gtab{D}{4:XX0987}\par
{\ulMinFrets=1\gtab{Open}{OOOOOO}\gtab{Base}{6:111111}}\par
""" + self.song_body()
        snapshots = []
        for label, preamble in (("current", ""), ("legacy", LEGACY_DIAGRAM_DRAW)):
            _, pdf = self.compile_checked(body, preamble, label=label)
            snapshots.append((words_and_geometry(pdf), rendered_pages(pdf)))
        self.assertEqual(snapshots[0], snapshots[1])

    def test_grid_rejects_invalid_gap_width_and_nesting(self):
        from test_tex_integration import compile_fixture
        cases = ((r"\begin{ulChordDiagramGrid}[-1pt]\end{ulChordDiagramGrid}",
                  "gap cannot be negative"),
                 (r"\hsize=0pt\begin{ulChordDiagramGrid}\end{ulChordDiagramGrid}",
                  "available width must be positive"),
                 (r"\begin{ulChordDiagramGrid}\begin{ulChordDiagramGrid}"
                  r"\end{ulChordDiagramGrid}\end{ulChordDiagramGrid}",
                  "grids cannot be nested"))
        for body, message in cases:
            with self.subTest(message=message):
                source = r"\documentclass{ulsbs-songbook}\begin{document}" + body + r"\end{document}"
                output, _ = compile_fixture("source-effects", expect_success=False,
                                            files={"source-effects.tex": source.encode()}, multikey=False)
                diagnostic = " ".join(output.replace("(ulsbs-diagrams)", "").split())
                self.assertTrue(message in diagnostic, output[-3000:])

    def test_grid_works_with_direct_package_loading(self):
        from test_tex_integration import compile_fixture
        source = r"""
\documentclass{book}\usepackage{ulsbs}
\setlength\textwidth{100pt}
\begin{document}
\begin{ulChordDiagramGrid}
\gtab{C#}{X46664}\gtab{B&}{X13331}\gtab{F}{133211}
\end{ulChordDiagramGrid}
\noindent Z
\end{document}
"""
        output, pdf = compile_fixture("source-effects", files={"source-effects.tex": source.encode()},
                                       multikey=False, passes=2)
        self.assertNotIn("Overfull", output)
        self.assertTrue(words_and_geometry(pdf))

    def test_grid_in_songs_preserves_lyric_and_multikey_contracts(self):
        body = r"""
\newcount\DiagramEffects
\newcommand\DiagramEffect{\global\advance\DiagramEffects1\relax}
\begin{ulSongs}{}
\beginsong{Chord chart}[id={grid},key={C},by={Author}]
\beginverse*
\[C]BEFOREMARK
\endverse
\begin{ulChordDiagramGrid}
\gtab{\DiagramEffect C}{X32010:032010}
\gtab{\DiagramEffect F}{133211:134211}
\gtab{\DiagramEffect A}{X02220:001230}
\end{ulChordDiagramGrid}
\beginverse*
\[C]AFTERMARK
\endverse
\endsong\end{ulSongs}
\typeout{DIAGRAM-EFFECTS:\the\DiagramEffects}
"""
        snapshots = {}
        for mode in ("chorded", "lyric", "multikey", "two-column"):
            with self.subTest(mode=mode):
                preamble = r"\ulSongColumns{2}" if mode == "two-column" else ""
                output, pdf = self.compile_checked(body, preamble, lyric=mode == "lyric", multikey=mode == "multikey",
                                                   offsets=range(12), effects=3, label=mode)
                self.assertNotIn("Overfull", output)
                if mode == "multikey":
                    original = PdfStructure(pdf).selected_pdf(pdf, {1: 0})
                    snapshots[mode] = words_and_geometry(original)
                    chart_f, = [row for row in snapshots[mode] if len(row) == 6 and row[1] == "F"]
                    def chart_words(words):
                        return [row for row in words if len(row) == 6 and row[1] in {"C", "F", "A"}
                                and chart_f[3] - 10 <= row[3] <= chart_f[5] + 10]
                    expected = chart_words(snapshots[mode])
                    self.assertEqual(len(expected), 3)
                    for offset in range(1, 12):
                        selected = PdfStructure(pdf).selected_pdf(pdf, {1: offset})
                        self.assertEqual(chart_words(words_and_geometry(selected)), expected)
                else:
                    snapshots[mode] = words_and_geometry(pdf)
        self.assertEqual(snapshots["chorded"], snapshots["multikey"])

    def test_complete_real_corpus_diagram_catalogue(self):
        corpus = Path(os.environ.get("ULSBS_CORPUS_ROOT", ROOT.parent)) / "content"
        diagrams = set(re.findall(DIAGRAM_PATTERN, CORPUS_DIAGRAMS))
        if corpus.is_dir():
            current = set()
            for path in corpus.rglob("*.tex"):
                # Include the commented key-C alternative diagrams as well.
                current.update(re.findall(DIAGRAM_PATTERN, path.read_text()))
            self.assertEqual(current, diagrams)
        self.assertGreaterEqual(len(diagrams), 70)
        calls = [rf"\gtab{{{name}}}{{{shape}}}" for name, shape in sorted(diagrams)]
        self.compile_checked("\n".join(" ".join(calls[i:i + 6]) + r"\par\medskip"
                               for i in range(0, len(calls), 6)))

    def test_optional_fields_fret_bases_string_counts_and_macros(self):
        self.compile_checked(r"""
\gtab{A}{X02220:001230} \gtab{B&}{X13331} \gtab{C#sus4}{4:XX3341}\par
\gtab{Open}{000000} \gtab{Letters}{OOOOOO} \gtab{Muted}{XXXXXX} \gtab{Empty}{}\par
\gtab{Four}{0123:0123} \gtab{Seven}{X123450:0123410} \gtab{Nine}{9:XX1212:001324}\par
{\ulMinFrets=1 \gtab{Short}{XX0101} \gtab{Deep}{XX0987}}\par
{\ulMinFrets=6 \gtab{Tall}{X02220:XO0123}}\par
{\ulMinFrets=10 \gtab{}{(XOOX00)}}\par
\newcommand\DiagramStrings{X4412X}\newcommand\DiagramFingers{X3412X}
\gtab{C\shrp}{:\DiagramStrings:\DiagramFingers}
\gtab{F}{:133211:} \gtab{D}{XX0232:} \gtab{D}{:XX0232:000132}
""")

    def test_chordlocals_and_active_colon_catcode_scopes(self):
        self.compile_checked(r"""
\newcount\DiagramEffects
\let\DiagramChordLocals\ulChordLocals
\renewcommand\ulChordLocals{\DiagramChordLocals\global\advance\DiagramEffects1\relax}
\gtab{C#/G#}{4:XX3341:003421} \gtab{B&maj7}{X1323X:013240}\par
{\catcode`\:=13
 \def:{\textbf{COLON}}
 \gtab{A6}{X02222:001111}:\par
 \gtab{D6}{:XX0202:000102}:}
\par \gtab{F#m11/A}{X02102:002103}\par
\typeout{DIAGRAM-EFFECTS:\the\DiagramEffects}
""", effects=5)

    def test_heading_and_label_source_execute_once_with_transposition(self):
        self.compile_checked(r"""
\newcount\DiagramEffects
\newcommand\DiagramEffect{\global\advance\DiagramEffects1 }
\let\DiagramPrintChord\ulPrintChord
\renewcommand\ulPrintChord[1]{\global\advance\DiagramEffects1 \DiagramPrintChord{#1}}
\gtab{\DiagramEffect A6}{X02222:001111}
\gtab{\DiagramEffect C#sus4}{4:XX3341}\par
{\transpose{2}\gtab{\DiagramEffect G}{320033:210034}}\par
{\renewcommand\gtabtrans[2]{\gtab{#1}{#2}}\transpose{-3}
 \gtab{\DiagramEffect F}{133211:134211}}\par
\typeout{DIAGRAM-EFFECTS:\the\DiagramEffects}
""", effects=7)

    def test_public_graphic_scaling_and_custom_heading_fonts(self):
        self.compile_checked(r"""
\let\DiagramPrintChord\ulPrintChord
\renewcommand\ulPrintChord[1]{\rmfamily\bfseries\Large#1}
\gtab{F#m11/A}{X02102:002103} \gtab{Long heading}{4:XX3341:003421}\par
\resizebox{!}{30pt}{\gtab{A6}{X02222:001111}}
\scalebox{.75}{\gtab{F}{[133211]:134211}}
\raisebox{3pt}{\gtab{D6}{XX0202:000102}}\par
\let\ulPrintChord\DiagramPrintChord
\gtab{D}{XX0232:000132}
""")

    def test_barres_nested_crossing_custom_and_open_ended(self):
        self.compile_checked(r"""
\gtab{C7}{X(3535X):013140} \gtab{F}{[133211]:134211}\par
\gtab{Nested}{([133]211)} \gtab{Crossing}{(1[332)11]}\par
\gtab{Several}{(13)(32)11} \gtab{Open end}{X(3535X}\par
\ulBarreDelims<>\gtab{Custom}{X<3535X>:013140} \gtab{Mixed}{X<(353)5X>:013140}\par
\gtab{Muted end}{(X13331)} \gtab{Open string}{(013331)} \gtab{No frets}{(XOOX00)}
""")

    def test_source_transposition_and_public_override(self):
        self.compile_checked(r"""
\gtab{C}{X32010:032010}\par
{\transpose{2}\gtab{C}{X32010:032010} \gtab{F#sus4/C#}{4:XX3341}}\par
{\transpose{-3}\gtab{C}{X32010:032010}}\par
{\transpose{12}\gtab{C}{X32010:032010}}\par
{\renewcommand\gtabtrans[2]{\gtab{#1}{#2}}\transpose{2}\gtab{C}{X32010:032010}}\par
{\renewcommand\gtabtrans[2]{\gtab{\notrans{#1}}{#2}}\transpose{2}\gtab{C}{X32010:032010}}
""")

    def song_body(self):
        return r"""
\newcount\DiagramEffects
\newcommand\DiagramEffect{\global\advance\DiagramEffects1 }
\begin{ulSongs}{}
\beginsong{Real diagram notes}[id={diagram-notes},key={A}]
\beginverse*
\[A]Lyrics before the guitar note.
\endverse
\musicnote{\gtab{\DiagramEffect A6}{X02222:001111} \gtab{D6}{XX0202:000102}}
\beginverse*
\gtab{D\symdim7}{XX0101:000102} \gtab{Em7&5}{XX2333:001222}
\endverse
\chordsoff
\beginverse*
Hidden chords: \[C]still lyrics.
\endverse
\chordson
\ifulShowChords\musicnote{\gtab{Am6}{X02212:002314} \gtab{A\symdim7}{X01212:001324}}\fi
\endsong
\end{ulSongs}
\typeout{DIAGRAM-EFFECTS:\the\DiagramEffects}
"""

    def test_actual_song_notes_and_chords_off(self):
        self.compile_checked(self.song_body())

    def test_true_lyric_edition_preserves_explicit_diagrams_and_hidden_notes(self):
        self.compile_checked(self.song_body(), lyric=True)

    def test_multikey_preserves_diagrams_all_twelve_offsets_and_effects(self):
        self.compile_checked(self.song_body(), multikey=True, offsets=range(12), effects=1)

    def test_diagrams_inside_chord_annotations_and_replay(self):
        self.compile_checked(r"""
\begin{ulSongs}{}\beginsong{Diagrams over lyrics}[key={C}]
\beginverse*
\[\gtab{C}{X32010}]Word \[G]after.
\[\gtab{C#sus4}{4:XX3341}]Diagram \[D]after.
\[\gtab{A}{X02220}\gtab{D}{XX0232}]Two \[G]next- word.
\endverse
\beginverse*
^Word ^after.
^Diagram ^after.
^Two ^next- word.
\endverse
\endsong\end{ulSongs}
""")


if __name__ == "__main__":
    unittest.main()
