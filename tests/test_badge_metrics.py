# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Badge visibility, measurement effects and PDF font identities are contracts."""

import re
import unittest

import test_song_lifecycle as lifecycle


class BadgeMetricTests(unittest.TestCase):
    setUpClass = classmethod(lifecycle.SongLifecycleTests.setUpClass.__func__)
    setUp = lifecycle.SongLifecycleTests.setUp
    compile_source = lifecycle.SongLifecycleTests.compile_source

    def compile_checked(self, source, effects):
        import pikepdf

        output = self.compile_source(source)
        self.assertEqual(re.findall(r"BADGE-EFFECTS:(\d+)", output), [str(effects)])
        self.assertTrue(re.findall(r"BADGE-FONT:\d+:[^:\r\n]*:\d+", output))
        with pikepdf.Pdf.open(self.book / "book.pdf") as pdf:
            self.assertTrue(any(page.Resources.get("/Font", {}) for page in pdf.pages))

    def test_title_context_badge_measurements_preserve_effects_and_font_resources(self):
        self.compile_checked(lifecycle.document(r"""
\begin{ulSongs}{}
\beginsong{Badge metrics}[tags={nature},ph={I},key={Am},gk={Bm,Am--C\shrp m}]
\beginverse*
\[Am]A measured lyric.
\endverse
\endsong
\beginsong{Tag-only metrics}[tags={fire}]
\beginverse*
Another measured lyric.
\endverse
\endsong
\end{ulSongs}
\typeout{BADGE-EFFECTS:\the\BadgeEffects}
\directlua{for id,f in font.each() do
 texio.write_nl('BADGE-FONT:'..id..':'..tostring(f.fullname)..':'..tostring(f.size)) end}
""", r"""
\ulShowTags{true}\ulShowPhase{true}
\newcount\BadgeEffects
\renewcommand\ulPreludeTagStyle{\global\advance\BadgeEffects1\relax}
"""), 5)

    def test_zero_width_metadata_is_not_a_visible_badge(self):
        self.compile_checked(lifecycle.document(r"""
\begin{ulSongs}{}
\beginsong{Zero width}[tags={\ZeroText},ph={\ZeroText}]
\beginverse*
No tag or phase badge.
\endverse
\endsong
\beginsong{Visible width}[tags={fire}]
\beginverse*
A visible tag badge.
\endverse
\endsong
\end{ulSongs}
\typeout{BADGE-EFFECTS:\the\BadgeEffects}
\directlua{for id,f in font.each() do
 texio.write_nl('BADGE-FONT:'..id..':'..tostring(f.fullname)..':'..tostring(f.size)) end}
""", r"""
\ulShowTags{true}\ulShowPhase{true}
\newcommand\ZeroText{\relax}
\newcount\BadgeEffects
\renewcommand\ulPreludeTagStyle{\global\advance\BadgeEffects1\relax}
"""), 2)

    def test_author_and_offered_to_separators_match_in_both_languages_and_editions(self):
        source = lifecycle.document(r"""
\begin{ulSongs}{}
\beginsong{Author and dedication}[by={Author},off={Recipient}]
\beginverse*
A dedication with its author.
\endverse
\endsong
\beginsong{Author only}[by={Author}]
\endsong
\beginsong{Dedication only}[off={Recipient}]
\endsong
\ulShowAuthors{false}
\beginsong{Hidden author}[by={Author},off={Recipient}]
\endsong
\ulShowAuthors{true}\ulShowOfferedTo{false}
\beginsong{Hidden dedication}[by={Author},off={Recipient}]
\endsong
\end{ulSongs}
""", r"\ulShowAuthors{true}\ulShowOfferedTo{true}")
        for language in ("english", "portuguese"):
            for edition in ("chorded", "lyric"):
                name = language + "-" + edition
                selected = (r"\def\ulSongbookType{" + edition + "}\n"
                            + source.replace("oneside,openany,",
                                             "oneside,openany,language=" + language + ",", 1))
                self.compile_source(selected, label=name)
                text = lifecycle.SongLifecycleTests.pdf_text(self)
                self.assertIn("Recipient", text)
                self.assertIn("Author", text)


if __name__ == "__main__":
    unittest.main()
