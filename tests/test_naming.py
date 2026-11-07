# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Public naming inventory and scoped configuration in the runtime."""

import re
import unittest

from ulsbs.tools.naming_v2 import BOOLEAN_SETTERS, COMMAND_RENAMES
from ulsbs.tools.migrate_syntax_v2 import migrate_text

import test_song_lifecycle as lifecycle


class NamingTests(unittest.TestCase):
    setUp = lifecycle.SongLifecycleTests.setUp
    compile_source = lifecycle.SongLifecycleTests.compile_source

    @classmethod
    def setUpClass(cls):
        lifecycle.SongLifecycleTests.setUpClass.__func__(cls)

    def test_renamed_public_commands_exist(self):
        names = sorted(set(COMMAND_RENAMES.values())
                       | {setter for setter, _ in BOOLEAN_SETTERS.values()})
        checks = "\n".join(
            rf"\cs_if_exist:cF {{{name}}}"
            rf"{{\PackageError{{ulsbs-test}}{{Missing~public~command~{name}}}{{}}}}"
            for name in names)
        source = lifecycle.document(
            "\\begin{ulSongs}{}\n\\beginsong{Naming inventory}[id={naming}]\n"
            "\\ExplSyntaxOn\n" + checks + "\n\\ExplSyntaxOff\n"
            "\\beginverse\nNaming inventory.\n\\endverse\n\\endsong\n\\end{ulSongs}")
        self.compile_source(source)

    def test_visibility_setters_and_predicates_restore_at_group_end(self):
        # Exercise the whole flag inventory, without depending on style defaults.
        pairs = sorted({(setter, COMMAND_RENAMES["if" + old.removesuffix("true")])
                        for old, (setter, value) in BOOLEAN_SETTERS.items()
                        if value == "true"
                        and "if" + old.removesuffix("true") in COMMAND_RENAMES})
        self.assertTrue(pairs)
        probe = []
        for number, (setter, predicate) in enumerate(pairs):
            probe.append(
                rf"\{setter}{{true}}"
                rf"\{predicate}\typeout{{NAMING-{number}:outer-true}}\fi"
                "{"
                rf"\{setter}{{false}}"
                rf"\{predicate}\else\typeout{{NAMING-{number}:inner-false}}\fi"
                "}"
                rf"\{predicate}\typeout{{NAMING-{number}:restored-true}}\fi")
        output = self.compile_source(lifecycle.document("\n".join(probe) + "\nScope."))
        for number in range(len(pairs)):
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
