# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Isolated multikey adapter checks, with a deterministic music seam."""

from __future__ import annotations

import json
import re
import shutil
import unittest

import test_song_lifecycle as song_helpers
from test_pdf_transposition_layers import PdfStructure
from test_tex_integration import ROOT, TEX_ASSETS


ADAPTER = TEX_ASSETS / "ulsbs-multikey.code.tex"
PREAMBLE = r"""
\ExplSyntaxOn
\int_if_exist:NF \l__ulsbs_music_transpose_int
  {\int_new:N \l__ulsbs_music_transpose_int}
\cs_set_protected:Npn \__ulsbs_music_transpose:nN #1#2
  {\tl_set:Nn #2{#1}
   \int_compare:nNnT {\l__ulsbs_music_transpose_int}={2}
     {\tl_replace_all:Nnn #2{C}{D}}}
\cs_set_protected:Npn \__ulsbs_music_transpose_alternative:nnN #1#2#3
  {\iow_term:x {ALTERNATIVE=[#1][\tl_to_str:n {#2}]}
   \tl_set:Nn #3{WideAlternative}}
\cs_set_protected:Npn \notrans #1 {#1}
\cs_if_exist:NF \__ulsbs_multikey_key_badge:
  {\file_input:n {ulsbs-multikey.code.tex}}
\ExplSyntaxOff
\makeatletter
\ExplSyntaxOn
\cs_set_eq:NN \__ulsbs_song_multikey: \__ulsbs_multikey_song_begin:
\NewDocumentCommand\AdapterChord{m}
  {\group_begin:\ulsbs@pdfchordtrue\transposehere{#1}\group_end:}
\NewDocumentCommand\AdapterBadge{}
  {\__ulsbs_multikey_key_badge:}
\NewDocumentCommand\AdapterOffset{m}
  {\int_set:Nn \l__ulsbs_music_transpose_int {#1}}
\box_new:N \l__ulsbs_test_plain_box
\box_new:N \l__ulsbs_test_layer_box
\NewDocumentCommand\AdapterMetrics{}
  {\hbox_set:Nn \l__ulsbs_test_plain_box{C}
   \hbox_set:Nn \l__ulsbs_test_layer_box{\AdapterChord{C}}
   \iow_term:x {PLAIN=\dim_eval:n {\box_wd:N \l__ulsbs_test_plain_box},
     \dim_eval:n {\box_ht:N \l__ulsbs_test_plain_box},
     \dim_eval:n {\box_dp:N \l__ulsbs_test_plain_box}}
   \iow_term:x {LAYER=\dim_eval:n {\box_wd:N \l__ulsbs_test_layer_box},
     \dim_eval:n {\box_ht:N \l__ulsbs_test_layer_box},
     \dim_eval:n {\box_dp:N \l__ulsbs_test_layer_box}}
   \box_use_drop:N \l__ulsbs_test_layer_box}
\ExplSyntaxOff
\makeatother
\newcount\AdapterEffects
\newcommand\AdapterEffect{\global\advance\AdapterEffects1 EFFECT}
"""


def document(body: str, extra: str = "", *, multikey: bool = True) -> str:
    options = r"\providecommand\ulPdfTranspositionLayers{true}" if multikey else ""
    return options + song_helpers.document(body, PREAMBLE + r"\ulShowKey{false}" + extra)


class MultikeyTests(unittest.TestCase):
    compile_source = song_helpers.SongLifecycleTests.compile_source
    pdf_text = song_helpers.SongLifecycleTests.pdf_text
    setUp = song_helpers.SongLifecycleTests.setUp

    @classmethod
    def setUpClass(cls):
        if shutil.which("qpdf") is None:
            raise unittest.SkipTest("qpdf is required")
        song_helpers.SongLifecycleTests.setUpClass.__func__(cls)
        cls.diagnostics = ROOT / "build/multikey"
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def metadata(self):
        return json.loads((self.book / "book.ulsbs-multikey.json").read_text())["multikey_info"]

    def test_adapter_has_no_vendor_private_consumers(self):
        self.assertNotIn("SB@", ADAPTER.read_text())

    def test_alternate_geometry_and_original_once(self):
        output = self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Geometry}[id={geometry},key={C}]
\AdapterMetrics
\AdapterChord{C\notrans{\AdapterEffect}G}
\AdapterChord{C\AdapterEffect}
\typeout{EFFECTS=\the\AdapterEffects}
\endsong
\end{ulSongs}
"""), passes=2)
        plain = re.findall(r"PLAIN=([^\r\n]+)", output)
        layer = re.findall(r"LAYER=([^\r\n]+)", output)
        self.assertEqual(plain, layer)
        self.assertIn("EFFECTS=2", output)
        self.assertNotIn("EFFECTS=3", output)
        self.assertEqual(output.count("ALTERNATIVE="), 2 * 3 * 11)
        structure = PdfStructure((self.book / "book.pdf").read_bytes())
        self.assertEqual(len(structure.layers), 12)

    def test_occurrences_radio_print_and_effective_key_badge(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{First}[id={same},key={Dm}]
\AdapterOffset{2}\AdapterBadge\AdapterChord{C}
\endsong
\beginsong{Second}[id={same},key={F}]
\AdapterBadge\AdapterChord{C}
\endsong
\end{ulSongs}
"""), passes=2)
        structure = PdfStructure((self.book / "book.pdf").read_bytes())
        self.assertEqual(len(structure.layers), 24)
        self.assertEqual(set(structure.names.values()), {
            f"ulsbs:transpose:v1:id:same{occurrence}:t{offset:02}"
            for occurrence in ("", ":o02") for offset in range(12)})
        self.assertEqual(len(structure.resolve(structure.config["/RBGroups"])), 2)
        on = structure.resolve(structure.config.get("/ON", []))
        if structure.config.get("/BaseState", "/ON") == "/ON":
            on = set(on) | (set(structure.layers)
                            - set(structure.resolve(structure.config.get("/OFF", []))))
        self.assertEqual({structure.names[ref].rsplit(":", 1)[1] for ref in on}, {"t00"})
        for reference, layer in structure.layers.items():
            usage = structure.resolve(layer["/Usage"])
            printing = structure.resolve(usage["/Print"])
            self.assertEqual(printing["/PrintState"],
                             "/ON" if structure.names[reference].endswith(":t00") else "/OFF")
        data = self.metadata()
        self.assertEqual([song["original_key"] for song in data["songs"]], ["Dm", "F"])
        self.assertEqual([song["occurrence"] for song in data["songs"]], [1, 2])
        self.assertTrue(all(song["has_transposable_content"] for song in data["songs"]))
        self.assertEqual(data["songs"][0]["key_labels"][0], "Dm")
        self.assertEqual(data["songs"][0]["key_labels"][1], "D♯m")

    def test_discarded_visual_does_not_mark_song_used(self):
        self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Discarded}[id={discarded},key={C}]
\setbox0=\hbox{\AdapterChord{C}}
Plain
\endsong
\beginsong{Empty}[id={empty}]
Plain
\endsong
\end{ulSongs}
"""), passes=2)
        # The existing protocol omits occurrences with no shipped notation.
        self.assertEqual(self.metadata()["songs"], [])

    def test_draft_builds_only_original(self):
        output = self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Draft}[id={draft},key={C}]
\AdapterChord{C}\AdapterBadge
\endsong
\end{ulSongs}
""", r"\makeatletter\ulsbs@pdfdraftpasstrue\makeatother"))
        self.assertNotIn("ALTERNATIVE=", output)

    def test_source_offset_is_applied_once_and_shared_state_is_retained(self):
        output = self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Source offset}[id={source},key={D}]
\AdapterOffset{2}\AdapterChord{C\notrans{\AdapterShared}}
\endsong
\end{ulSongs}
""", r"""
\renewcommand\ulTransposedChordFormat[2]{\typeout{FORMAT-ORIGINAL=[\detokenize{#1}]}#2}
\ExplSyntaxOn
\NewDocumentCommand\AdapterShared{}
  {\iow_term:x {SHARED-OFFSET=\int_use:N \l__ulsbs_music_transpose_int}}
\ExplSyntaxOff
"""))
        self.assertIn(r"FORMAT-ORIGINAL=[C\notrans {\AdapterShared }]", output)
        self.assertEqual(output.count("SHARED-OFFSET=2"), 1)
        self.assertIn("ALTERNATIVE=[1][D]", output)
        self.assertNotIn("ALTERNATIVE=[1][C]", output)

    def test_real_music_alternatives_start_from_effective_original(self):
        # Explicit loading keeps this test usable before main wires startup.
        preamble = r"""
\ExplSyntaxOn
\cs_if_exist:NF \__ulsbs_music_transpose:nN
  {\file_input:n {ulsbs-music.code.tex}}
\ExplSyntaxOn
\cs_if_exist:NF \__ulsbs_multikey_key_badge:
  {\file_input:n {ulsbs-multikey.code.tex}}
\ExplSyntaxOn
\cs_set_eq:NN \__ulsbs_song_multikey: \__ulsbs_multikey_song_begin:
\cs_new_eq:NN \AdapterRealAlternative \__ulsbs_music_transpose_alternative:nnN
\cs_set_protected:Npn \__ulsbs_music_transpose_alternative:nnN #1#2#3
  {\AdapterRealAlternative {#1}{#2}#3
   \iow_term:x {REAL-ALTERNATIVE=[#1][\tl_to_str:V #3]}}
\ExplSyntaxOff
\makeatletter
\newcommand\AdapterRealChord[1]{{\ulsbs@pdfchordtrue\transposehere{#1}}}
\makeatother
"""
        source = r"\providecommand\ulPdfTranspositionLayers{true}" + song_helpers.document(r"""
\begin{ulSongs}{}
\beginsong{Real music}[id={real},key={D}]
\transpose{2}\AdapterRealChord{C}
\endsong
\end{ulSongs}
""", preamble)
        output = self.compile_source(source, passes=2)
        alternatives = re.findall(r"REAL-ALTERNATIVE=\[(\d+)\]\[([^\]]*)\]", output)
        expected = ["E\\flt", "E", "F", "F\\shrp", "G", "A\\flt",
                    "A", "B\\flt", "B", "C", "D\\flt"]
        for offset, result in alternatives:
            self.assertEqual(result.strip(), expected[int(offset) - 1])
        self.assertEqual(len(alternatives), 22)
        self.assertEqual(self.metadata()["songs"][0]["original_key"], "D")


if __name__ == "__main__":
    unittest.main()
