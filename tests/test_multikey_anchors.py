# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Full shipout sidecars, not just layer/key labels, are publication contracts."""

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_pdf_transposition_layers import PdfStructure, words_and_geometry
from test_tex_integration import FIXTURES, ROOT, TEX_ASSETS


class MultikeyAnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [tool for tool in ("lualatex", "qpdf", "pdftotext", "pdfinfo")
                   if shutil.which(tool) is None]
        if missing:
            raise unittest.SkipTest("TeX/PDF tools required: " + ", ".join(missing))
        cls.temporary = tempfile.TemporaryDirectory(prefix="ulsbs-anchor-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.assets = cls.root / "tex"
        shutil.copytree(TEX_ASSETS, cls.assets)
        cls.diagnostics = ROOT / "build/multikey-anchors"
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def compile(self, source, *, multikey=True, label=None):
        work = self.root / self._testMethodName / (label or ("layered" if multikey else "ordinary"))
        work.mkdir(parents=True)
        source = (rf"\def\ulPdfTranspositionLayers{{{'true' if multikey else 'false'}}}" + "\n"
                  + source)
        assets = self.assets
        (work / "book.tex").write_text(source)
        env = dict(os.environ, TEXINPUTS=f"{assets}//{os.pathsep}", LUAINPUTS=f"{assets}//{os.pathsep}",
                   TEXMFVAR=str(work / "cache"), TEXMFCACHE=str(work / "cache"))
        output = []
        try:
            for _ in range(3):
                result = subprocess.run(
                    ["lualatex", "-halt-on-error", "-interaction=nonstopmode", "-recorder", "book.tex"],
                    cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, timeout=120,
                )
                output.append(result.stdout)
                (work / "compile.stdout").write_text("\n".join(output))
                self.assertEqual(result.returncode, 0, result.stdout)
            self.assertFalse(list(work.glob("*.sxd")))
            self.assertFalse(list(work.glob("*.sxc")))
        finally:
            shutil.copytree(work, self.diagnostics / self._testMethodName
                            / ("layered" if multikey else "ordinary"), dirs_exist_ok=True)
        return work, "\n".join(output)

    def manifest(self, book):
        import pikepdf

        data = json.loads((book / "book.ulsbs-multikey.json").read_text())
        songs = data["multikey_info"]["songs"]
        self.assertTrue(songs)
        names = set(PdfStructure((book / "book.pdf").read_bytes()).names.values())
        occurrences = [(song["song_id"], song["occurrence"]) for song in songs]
        self.assertEqual(len(occurrences), len(set(occurrences)))
        with pikepdf.Pdf.open(book / "book.pdf") as pdf:
            for song in songs:
                self.assertEqual(len(song["key_labels"]), 12)
                self.assertTrue({song["layer_prefix"] + f":t{offset:02d}" for offset in range(12)} <= names)
                page = song["page_index"]
                self.assertIn(page, song["layer_page_indices"])
                self.assertTrue(0 <= page < len(pdf.pages))
                left, bottom, right, top = map(float, pdf.pages[page].MediaBox)
                x, y = song["anchor"]["x"], song["anchor"]["y"]
                self.assertTrue(math.isfinite(x) and left <= x <= right)
                self.assertTrue(math.isfinite(y) and bottom <= y <= top)
        return data

    def test_full_header_sidecar_and_publication_range_manifest(self):
        from ulsbs.multikey_ranges import package_ranges, validate_index

        source = (FIXTURES / "multikey-header-layout.tex").read_text()
        book, _ = self.compile(source)
        ordinary, _ = self.compile(source, multikey=False)
        manifest = self.manifest(book)
        index = package_ranges(book / "book.pdf", ordinary / "book.pdf", manifest,
                               book / "ranges", max_pages=3)
        validate_index(json.loads(index.read_text()), index, ordinary / "book.pdf")
        shutil.copytree(index.parent, self.diagnostics / self._testMethodName / "ranges",
                        dirs_exist_ok=True)

    def test_title_width_number_badge_and_source_effect_independent_anchors(self):
        source = r"""
\documentclass[oneside,openany,maintitle={Public anchor effects}]{ulsbs-songbook}
\newcount\AnchorEffects
\DeclareRobustCommand\AnchorEffect{\global\advance\AnchorEffects1\relax}
\pdfstringdefDisableCommands{\def\AnchorEffect{}}
\newcommand\AnchorSong[3]{%
  \begin{ulSongs}{}
  \beginsong{\AnchorEffect#2}[id={#1},key={C},#3]
  \beginverse*
  \[C]One chorded line.
  \endverse
  \endsong\end{ulSongs}}
\begin{document}
\AnchorSong{same}{Short}{}
\AnchorSong{same}{A considerably longer title}{ph={II},tags={nature}}
{\ulSongNumberWidth=0pt\AnchorSong{unnumbered}{Title without song number}{}}
\AnchorSong{last}{Final heading}{}
\typeout{ANCHOR-EFFECTS:\the\AnchorEffects}
\end{document}
"""
        book, output = self.compile(source)
        manifest = self.manifest(book)
        self.assertEqual([(song["song_id"], song["occurrence"])
                          for song in manifest["multikey_info"]["songs"]],
                         [("same", 1), ("same", 2), ("unnumbered", 1), ("last", 1)])
        self.assertEqual(re.findall(r"ANCHOR-EFFECTS:(\d+)", output), ["4"] * 3)

    def test_slides_header_anchor_has_sidecar_and_layers(self):
        source = r"""
\documentclass[oneside,openany,maintitle={Public slide anchors}]{ulsbs-songbook}
\ulSlides{true}
\begin{document}
\begin{ulSongs}{}
\beginsong{First slide}[id={slide-first},key={C}]
\beginverse*
\[C]A chorded line.
\endverse
\endsong
\beginsong{Second slide}[id={slide-second},key={G}]
\beginverse*
\[G]Another chorded line.
\endverse
\endsong
\end{ulSongs}
\end{document}
"""
        book, _ = self.compile(source)
        manifest = self.manifest(book)
        first, second = manifest["multikey_info"]["songs"]
        self.assertLess((first["page_index"], -first["anchor"]["y"]),
                         (second["page_index"], -second["anchor"]["y"]))

    def test_wrapping_and_badge_lanes_preserve_first_line_ui_anchor(self):
        source = r"""
\documentclass[oneside,openany]{ulsbs-songbook}
\setlength\textwidth{200pt}
\ulShowTags{true}\ulShowPhase{true}\ulShowKey{true}\ulShowGoodKeys{true}
SETTING
\begin{document}
\begin{ulSongs}{}
\beginsong{TITLE}[id={fixed-anchor},key={C},gk={Dm},tags={nature},ph={II},by={Author},ex={Supplementary heading text}]
\beginverse*
\[C]A chorded line.
\endverse
\endsong
\end{ulSongs}
\end{document}
"""
        long_title = "Alpha Beta Gamma Delta Epsilon Zeta Eta Theta Iota Kappa"
        for numbered in (False, True):
            anchors = []
            for name, title, overlap in (("short", "Short", True),
                                          ("wrapped", long_title, True),
                                          ("reserved", long_title, False)):
                with self.subTest(numbered=numbered, mode=name):
                    setting = r"\ulTitleBadgeOverlap{" + str(overlap).lower() + "}"
                    if not numbered:
                        setting += r"\ulNoSongNumbers"
                    book, output = self.compile(source.replace("SETTING", setting).replace("TITLE", title),
                                                label=f"{numbered}-{name}")
                    self.assertNotIn("Overfull \\hbox", output)
                    song, = self.manifest(book)["multikey_info"]["songs"]
                    anchors.append(song["anchor"])
            self.assertEqual(anchors[0], anchors[1])
            self.assertEqual(anchors[0], anchors[2])

    def test_all_transposed_key_badges_share_the_ordinary_title_lane(self):
        source = r"""
\documentclass[oneside,openany]{ulsbs-songbook}
\ulNoSongNumbers\setlength\textwidth{230pt}
\ulShowKey{true}\ulShowGoodKeys{false}\ulShowTags{false}\ulShowPhase{false}
\renewcommand\ulPreludeBadgeFont{\normalfont\fontsize{13}{17}\selectfont}
\renewcommand\ulPreludeTextKey{KEYMARK}
\begin{document}
\begin{ulSongs}{}
\beginsong{Alpha Beta Gamma Delta Epsilon Zeta Eta Theta}[id={reserved-keys},key={C}]
\beginverse*
\[C]BODYMARK
\endverse
\endsong
\end{ulSongs}
\end{document}
"""
        ordinary, _ = self.compile(source, multikey=False)
        plain = (ordinary / "book.pdf").read_bytes()
        layered, output = self.compile(source)
        self.assertNotIn("Overfull \\hbox", output)
        data = (layered / "book.pdf").read_bytes()
        self.assertEqual(words_and_geometry(plain), words_and_geometry(data))
        title_words = set("Alpha Beta Gamma Delta Epsilon Zeta Eta Theta".split())
        expected_title = [row for row in words_and_geometry(plain) if row[1] in title_words]
        self.assertGreater(len({row[3] for row in expected_title}), 1)
        for offset in range(12):
            with self.subTest(offset=offset):
                selected = PdfStructure(data).selected_pdf(data, {1: offset})
                words = words_and_geometry(selected)
                self.assertEqual([row for row in words if row[1] in title_words], expected_title)
                marker, = [row for row in words if row[1] == "KEYMARK"]
                badge = [row for row in words if len(row) == 6
                         and row[1] not in title_words
                         and row[3] < marker[5] and row[5] > marker[3]]
                self.assertLess(max(row[4] for row in expected_title), min(row[2] for row in badge))
        other_key, _ = self.compile(source.replace("key={C}", r"key={B\flt m}"),
                                    multikey=False, label="ordinary-other-key")
        other_words = words_and_geometry((other_key / "book.pdf").read_bytes())
        self.assertEqual([row for row in other_words if row[1] in title_words], expected_title)


if __name__ == "__main__":
    unittest.main()
