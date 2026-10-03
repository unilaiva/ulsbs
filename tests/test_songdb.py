# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Focused song lyric extraction tests."""

from __future__ import annotations

import unittest

from ulsbs.songdb import _extract_lyrics_from_song_block


class VerseExtractionTests(unittest.TestCase):
    def test_canonical_beginverse_variants(self) -> None:
        for modifiers in ("", "*", "+", "*+"):
            for option in ("", "[2]"):
                with self.subTest(modifiers=modifiers, option=option):
                    source = f"\\beginverse{modifiers}{option}\nFirst line\\\\\nSecond line\n\\endverse"
                    self.assertEqual(
                        _extract_lyrics_from_song_block(source),
                        ([["First line", "Second line"]], "first line\nsecond line"),
                    )

    def test_whitespace_between_modifiers_and_option(self) -> None:
        source = "\\beginverse \n * \t + \n [2] \nWords\n\\endverse"
        self.assertEqual(_extract_lyrics_from_song_block(source), ([['Words']], 'words'))

    def test_only_endverse_closes_a_canonical_verse(self) -> None:
        source = (
            "\\beginverse+[2]\nFirst\n\\end{verse}\n\\endverseextra\nSecond\n\\endverse\n"
            "\\beginverse*\nThird\n\\endverse"
        )
        self.assertEqual(
            _extract_lyrics_from_song_block(source),
            ([["First", "Second"], ["Third"]], "first\nsecond\n\nthird"),
        )

    def test_verse_environment_and_disabled_plain_text(self) -> None:
        source = "\\begin{verse}[1]\nEnvironment\n\\end{verse}"
        self.assertEqual(
            _extract_lyrics_from_song_block(source, include_plain_lowercase=False),
            ([['Environment']], None),
        )


if __name__ == "__main__":
    unittest.main()
