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

from test_pdf_transposition_layers import PdfStructure, words_and_geometry
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
        cls.assets = cls.work / "vendor-absent-tex"
        shutil.copytree(TEX_ASSETS, cls.assets, ignore=shutil.ignore_patterns("songs"))
        cls.diagnostics = ROOT / "build/diagrams"
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.addCleanup(shutil.rmtree, self.work / self._testMethodName, ignore_errors=True)

    def compile_checked(self, body, preamble="", *, lyric=False, multikey=False, offsets=(None,), effects=None):
        target = self.diagnostics / self._testMethodName
        source = (r"\documentclass[oneside,openany,maintitle={Guitar diagrams}]{ulsbs-songbook}"
                  + "\n" + r"\ulShowTags{false}\ulShowPhase{false}" + "\n" + preamble
                  + "\n" + r"\begin{document}" + "\n" + body
                  + "\n" + r"\typeout{DIAGRAM-COUNTERS:\arabic{ulSongNumber}:\arabic{ulVerseNumber}:\the\ulMinFrets}"
                  + "\n" + r"\end{document}" + "\n")
        work = self.work / self._testMethodName
        work.mkdir(parents=True)
        options = r"\def\ulSongbookType{lyric}" + "\n" if lyric else ""
        if multikey:
            options += (r"\def\ulPdfTranspositionLayers{true}" + "\n"
                        + r"\def\ulPdfTranspositionLayerUi{hidden}" + "\n")
        (work / "book.tex").write_text(options + source)
        env = dict(os.environ, TEXINPUTS=f"{self.assets}//{os.pathsep}",
                   LUAINPUTS=f"{self.assets}//{os.pathsep}", TEXMFVAR=str(self.cache),
                   TEXMFCACHE=str(self.cache))
        output = []
        try:
            for _ in range(2):
                result = subprocess.run(
                    ["lualatex", "-interaction=nonstopmode", "-halt-on-error", "-recorder", "book.tex"],
                    cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, timeout=120)
                output.append(result.stdout)
                (work / "compile.stdout").write_text("\n".join(output))
                self.assertEqual(result.returncode, 0, result.stdout)
            inputs = (work / "book.fls").read_text()
            self.assertNotIn("songs.sty", inputs)
            self.assertFalse(list(work.glob("*.sxd")))
            self.assertFalse(list(work.glob("*.sxc")))
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
                             [str(effects)] * 2)

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
\ifulChorded\musicnote{\gtab{Am6}{X02212:002314} \gtab{A\symdim7}{X01212:001324}}\fi
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
