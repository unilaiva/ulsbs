# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Source evaluation, lyric geometry and layer semantics of fixtures."""

import re
import shutil
import unittest

from test_pdf_transposition_layers import LAYER_NAME, PdfStructure, words_and_geometry
from test_tex_integration import compile_fixture


class FixtureBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [tool for tool in ("lualatex", "qpdf", "pdftotext") if shutil.which(tool) is None]
        if missing:
            raise unittest.SkipTest("PDF integration tools required: " + ", ".join(missing))
        cls.builds = {}
        for lyrics in (False, True):
            for multikey in (False, True):
                preamble = "\\def\\SourceEffectsLyrics{true}\n" if lyrics else ""
                cls.builds[lyrics, multikey] = compile_fixture(
                    "source-effects", preamble=preamble, multikey=multikey, passes=3)
        cls.lyric_editions = {
            multikey: compile_fixture("source-effects", preamble="\\def\\ulSongbookType{lyric}\n",
                                      multikey=multikey, passes=3)
            for multikey in (False, True)
        }

    def test_source_effects_and_song_numbers_are_not_repeated_per_layer(self):
        for mode, (output, _) in self.builds.items():
            with self.subTest(mode=mode):
                self.assertEqual(re.findall(r"SOURCE-SONG:(\d+)", output),
                                 ["1", "2", "3", "1", "2", "3"])
                self.assertEqual(re.findall(r"SOURCE-EFFECTS:(\d+)", output), ["7"])
                self.assertNotIn("Replayed chord has no matching chord", output)
                self.assertNotIn("Missing character:", output)

    def test_zero_offset_preserves_lyrics_and_geometry(self):
        for lyrics in (False, True):
            with self.subTest(lyrics=lyrics):
                expected = words_and_geometry(self.builds[lyrics, False][1])
                actual = words_and_geometry(self.builds[lyrics, True][1])
                # OCG boundaries split adjacent C/G into two Poppler words.
                adjacent = None if lyrics else next(i for i, row in enumerate(expected) if row[1] == "CG")
                if adjacent is not None:
                    first, second = actual[adjacent:adjacent + 2]
                    self.assertEqual((first[1], second[1]), ("C", "G"))
                    self.assertEqual(first[0], second[0])
                    self.assertEqual((first[3], first[5]), (second[3], second[5]))
                    actual[adjacent:adjacent + 2] = [
                        (first[0], "CG", first[2], first[3], second[4], second[5])]
                self.assertEqual(expected, actual)

    def test_twelve_offsets_per_chorded_song_and_no_chordsoff_layers(self):
        self.assertFalse(PdfStructure(self.builds[False, False][1]).layers)
        layered = PdfStructure(self.builds[False, True][1])
        expected = {f"ulsbs:transpose:v1:id:source-effects-{song}:t{offset:02d}"
                    for song in ("empty", "short", "long", "accented", "languages", "standard")
                    for offset in range(12)}
        self.assertEqual(set(layered.names.values()), expected)
        self.assertTrue(all(LAYER_NAME.fullmatch(name) for name in layered.names.values()))
        self.assertFalse(PdfStructure(self.builds[True, True][1]).layers)

    def test_real_lyric_edition_suppresses_musicnotes_and_layers(self):
        for multikey, (output, pdf) in self.lyric_editions.items():
            with self.subTest(multikey=multikey):
                self.assertEqual(re.findall(r"SOURCE-EFFECTS:(\d+)", output), ["7"])
                self.assertNotIn("Missing character:", output)
                self.assertFalse(PdfStructure(pdf).layers)
                words = {row[1] for row in words_and_geometry(pdf)}
                self.assertNotIn("MusicNoteAnchor", words)
                self.assertTrue({"OuterRepeatAnchor", "GroupedEffectAnchor", "FinalAnchor"} <= words)
        self.assertIn("MusicNoteAnchor", {row[1] for row in words_and_geometry(self.builds[True, False][1])})
        self.assertEqual(words_and_geometry(self.lyric_editions[False][1]),
                         words_and_geometry(self.lyric_editions[True][1]))

    def test_empty_melody_blocks_are_accepted(self):
        for multikey in (False, True):
            with self.subTest(multikey=multikey):
                output, pdf = compile_fixture("source-effects-empty-melody", multikey=multikey)
                self.assertTrue(pdf.startswith(b"%PDF"))
                self.assertNotIn("Undefined control sequence", output)

    def test_anchor_lyrics_survive_all_output_variants(self):
        anchors = {
            "EmptyTitleAnchor", "AdjacentAnchor", "SpaceAnchor", "IndentedStarAnchor",
            "joined:JoinedAnchor", "StoredAnchor", "ReplayAnchor", "WrappingAnchor",
            "MusicNoteAnchor", "AlternateAnchor", "OuterRepeatAnchor", "InnerRepeatAnchor",
            "RepeatTailAnchor", "AfterBreakAnchor", "MelodyAnchor", "ZeroAdvanceAnchor",
            "AdjacentMelodyAnchor", "SwappedAnchor", "HiddenNotesAnchor",
            "HiddenBeatsAnchor", "HiddenBothAnchor", "LanguageAnchor", "GroupedEffectAnchor",
            "FinalAnchor", "UnnumberedAnchor",
        }
        for mode, (_, pdf) in self.builds.items():
            with self.subTest(mode=mode):
                words = {row[1] for row in words_and_geometry(pdf)}
                self.assertTrue(anchors <= words, f"Missing anchors: {sorted(anchors - words)}")


if __name__ == "__main__":
    unittest.main()
