# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Current scoped configuration and migrated repeat-stanza behavior."""

import re
import unittest

from ulsbs.tools.migrate_syntax_v2 import migrate_text

import test_song_lifecycle as lifecycle


class NamingTests(unittest.TestCase):
    setUp = lifecycle.SongLifecycleTests.setUp
    compile_source = lifecycle.SongLifecycleTests.compile_source

    @classmethod
    def setUpClass(cls):
        lifecycle.SongLifecycleTests.setUpClass.__func__(cls)

    def test_visibility_setters_and_predicates_restore_at_group_end(self):
        # Exercise grouped book configuration in the preamble, including setters
        # that now freeze at document start, without depending on style defaults.
        settings = (
            "ShowChords", "ShowNotes", "ShowBeats", "ShowMeasures", "ShowAltChords",
            "ShowLilypond", "ShowMusicComments", "ShowAuthors", "ShowOfferedTo",
            "ShowExtraInfo", "ShowKey", "ShowGoodKeys", "ShowTags", "ShowPhase",
            "ShowPhaseInToc", "ShowTranslation", "ShowExplanation", "ShowPassage",
            "ShowFeeler", "ShowImageInChapterName", "ShowImageOnChapterFrontPage",
            "Slides", "TransposeCapos", "NoLyrics", "SongIndexes", "SeparateIndexes",
            "PagePreludesEnabled",
        )
        probe = []
        for number, name in enumerate(settings):
            setter, predicate = "ul" + name, "iful" + name
            probe.append(
                rf"\{setter}{{true}}"
                rf"\{predicate}\typeout{{NAMING-{number}:outer-true}}\fi"
                "{"
                rf"\{setter}{{false}}"
                rf"\{predicate}\else\typeout{{NAMING-{number}:inner-false}}\fi"
                "}"
                rf"\{predicate}\typeout{{NAMING-{number}:restored-true}}\fi")
        output = self.compile_source(lifecycle.document("Scope.", "\n".join(probe)))
        for number in range(len(settings)):
            self.assertEqual(re.findall(rf"NAMING-{number}:([a-z-]+)", output),
                             ["outer-true", "inner-false", "restored-true"])

    def test_boolean_values_are_validated(self):
        self.compile_source(lifecycle.document("Invalid.", r"\ulShowTags{maybe}"),
                            failure="boolean")

    def test_migrated_repeat_stanzas_use_numbered_verses(self):
        source = r"""
\begin{ulSongs}{}
\beginsong{Migrated repeat regions}
\beginchorus
\probe First.
\endchorus
\chorus
\probe Second.
\endchorus
\begin{chorus}
\probe Third.
\end{chorus}
\endsong
\end{ulSongs}
"""
        migrated = migrate_text(source)
        self.assertTrue(migrated.safe, migrated.diagnostics)
        preamble = r"""
\makeatletter
\newcommand\probe{\typeout{REPEAT-STANZA=\theulVerseNumber/\the\ulsbs@rep@level}}
\makeatother
"""
        output = self.compile_source(lifecycle.document(migrated.text, preamble))
        self.assertEqual(re.findall(r"REPEAT-STANZA=(\d+/\d+)", output), ["1/1", "2/1", "3/1"])


if __name__ == "__main__":
    unittest.main()
