from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tarfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ulsbs.tools import migrate_syntax_v2 as migration


COMMANDS = {"songcolumns": "ulSongColumns", "ifshowtags": "ifulShowTags", "old": "ulOld"}
BOOLEANS = {"showtagstrue": ("ulShowTags", "true"), "showtagsfalse": ("ulShowTags", "false"),
            "adjustchordcharstrue": ("ulAdjustChordChars", "true"),
            "adjustchordcharsfalse": ("ulAdjustChordChars", "false")}
NAMES = {
    "counter": {"songnum": "ulSongNumber"},
    "color": {"songblue": "ulSongBlue", "songred": "ulSongRed"},
    "environment": {"songs": "ulSongs"},
}
LEGACY_IDENTITY_NAMES = ("ulSongbookType",) + tuple(
    name for old, new in (("chorded", "Chorded"), ("lyric", "Lyric"),
                          ("lyriconly", "LyricOnly"), ("charangobook", "CharangoBook"),
                          ("bassclefbook", "BassclefBook"))
    for name in ("if" + old, old + "true", old + "false", "iful" + new, "ul" + new))
REMOVED_MEASURE_NAMES = ("ifmeasures", "measurestrue", "measuresfalse", "ifulMeasures", "ulMeasures")
REMOVED_SPACING_NAMES = ("baselineadj", "ulBaselineAdjustment", "versesep", "ulVerseSep")
DISPLAY_NAMES = tuple("ulShow" + suffix for suffix in (
    "Chords", "Notes", "Beats", "Measures", "Lilypond", "AltChords", "Translation", "Explanation",
    "Passage", "Feeler", "Key", "GoodKeys", "MusicComments", "Authors", "OfferedTo", "ExtraInfo",
    "Tags", "Phase", "PhaseInToc", "ImageInChapterName", "ImageOnChapterFrontPage"))


def migrate(source: str, **kwargs) -> migration.Result:
    return migration.migrate_text(source, command_renames=COMMANDS,
                                  boolean_setters=BOOLEANS, name_argument_renames=NAMES, **kwargs)


class MigrateSyntaxV2Tests(unittest.TestCase):
    def assert_conversion(self, source: str, expected: str, **kwargs) -> None:
        result = migrate(source, **kwargs)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, expected)
        second = migrate(result.text, **kwargs)
        self.assertTrue(second.safe, second.diagnostics)
        self.assertEqual(second.text, expected)
        self.assertFalse(second.converted)

    def assert_unsafe(self, source: str, fragment: str) -> None:
        result = migrate(source)
        self.assertFalse(result.safe)
        self.assertEqual(result.text, source)
        self.assertTrue(any(fragment in d.message for d in result.diagnostics), result.diagnostics)

    def test_named_commands_boundaries_and_literals(self) -> None:
        self.assert_conversion(
            r"\songcolumns{2} songcolumns \songcolumnsExtra \oldish \old@tail \ifshowtags",
            r"\ulSongColumns{2} songcolumns \songcolumnsExtra \oldish \ulOld@tail \ifulShowTags")

    def test_atletter_scopes_and_class_defaults(self) -> None:
        self.assert_conversion(
            r"\old@tail {\makeatletter\old@tail \old} \old@tail",
            r"\ulOld@tail {\makeatletter\old@tail \ulOld} \ulOld@tail")
        self.assert_conversion(r"\old@tail \old", r"\old@tail \ulOld", at_letter=True)
        self.assert_conversion(
            r"\makeatletter\old@tail\makeatother\old@tail",
            r"\makeatletter\old@tail\makeatother\ulOld@tail")

    def test_expl3_boundaries_and_group_restoration(self) -> None:
        self.assert_conversion(
            r"{\ExplSyntaxOn\old_name: \old: \old}\old_name:",
            r"{\ExplSyntaxOn\old_name: \old: \ulOld}\ulOld_name:")

    def test_comment_escape_parity_and_opaque_regions(self) -> None:
        source = ("% \\old\n\\%\\old\n\\\\% \\old\n"
                  r"\verb|\old|\verb*+\old+\Verb!\old!\lstinline[language=TeX]|\old|"
                  r"\begin{verbatim}\old\end{verbatim}"
                  r"\begin{minted}{tex}\old\end{minted}"
                  r"\begin{comment}\old\end{comment}"
                  r"\old")
        expected = source.replace("\\%\\old", "\\%\\ulOld")
        expected = expected[:-4] + r"\ulOld"
        self.assert_conversion(source, expected)

    def test_lilypond_commands_and_environments_are_opaque(self) -> None:
        source = ('\\lilypond[staffsize=12]{ \\old { c } "}" % } \\old\n c }'
                  r"\begin{lilypond}\old { c }\end{lilypond}\old")
        self.assert_conversion(source, source[:-4] + r"\ulOld")

    def test_url_verbatim_commands_preserve_literal_data(self) -> None:
        for name in ("url", "nolinkurl", "path"):
            for opening, closing in (("{", "}"), ("|", "|"), ("!", "!"), ("+", "+")):
                with self.subTest(command=name, delimiter=opening):
                    literal = ("\\" + name + opening
                               + r"https://example.test/\old%20/\showtagstrue#anchor" + closing)
                    self.assert_conversion(literal + r"\relax{\showtagsfalse}\old",
                                           literal + r"\relax{\ulShowTags{false}}\ulOld")

    def test_url_percent_sign_does_not_hide_following_commands(self) -> None:
        self.assert_conversion(r"\url{https://example.test/a%20\old}\old",
                               r"\url{https://example.test/a%20\old}\ulOld")
        self.assert_conversion(r"\url{https://example.test/\old}{\showtagstrue}",
                               r"\url{https://example.test/\old}{\ulShowTags{true}}")
        source = r"\url{https://example.test/\songid}"
        result = migration.migrate_text(source)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, source)
        self.assert_conversion(r"\path|\catcode\begin{verbatim}\old|\old",
                               r"\path|\catcode\begin{verbatim}\old|\ulOld")

    def test_href_protects_url_but_migrates_displayed_text(self) -> None:
        self.assert_conversion(
            r"\href{https://example.test/a%20b#section}{\old{}\adjustchordcharstrue}",
            r"\href{https://example.test/a%20b#section}{\ulOld{}\ulAdjustChordChars{true}}")
        self.assert_conversion(
            r"\href[page=2]{https://example.test/}{\songcolumns{2}}\old",
            r"\href[page=2]{https://example.test/}{\ulSongColumns{2}}\ulOld")

    def test_computed_or_expansion_time_url_inputs_leave_file_unchanged(self) -> None:
        for source in (
            r"\href{https://example.test/\old}{\old}",
            r"\href{\baseurl/path}{\old}", r"\href{https://example.test/{part}}{\old}",
            r"\newcommand\link[1]{\url{https://example.test/#1}}\old",
            r"\expandafter\url\expandafter{\old}\old",
            r"\edef\link{\url{https://example.test/\old}}\old",
            r"\expanded{\nolinkurl{https://example.test/\old}}\old",
        ):
            with self.subTest(source=source):
                self.assert_unsafe(source, "URL")

    def test_url_definition_targets_and_references_do_not_hide_bodies(self) -> None:
        for name in ("url", "nolinkurl", "path", "href"):
            with self.subTest(command=name):
                self.assert_conversion("\\newcommand\\" + name + r"[1]{\old}",
                                       "\\newcommand\\" + name + r"[1]{\ulOld}")
                self.assert_conversion("\\renewcommand*{\\" + name + r"}[1]{\old}",
                                       "\\renewcommand*{\\" + name + r"}[1]{\ulOld}")
                self.assert_conversion("\\let\\alias=\\" + name + r"\old",
                                       "\\let\\alias=\\" + name + r"\ulOld")
                self.assert_conversion("\\string\\" + name + r"{\old}",
                                       "\\string\\" + name + r"{\ulOld}")

    def test_unsupported_or_unterminated_url_forms_are_transactional(self) -> None:
        for source in (r"\url{open", r"\url|open", r"\path\macro", r"\href|url|{text}"):
            with self.subTest(source=source):
                self.assert_unsafe(r"\old" + source, "URL")

    def test_unterminated_opaque_constructs_are_unsafe(self) -> None:
        for source in (r"\old\verb|open", r"\old\begin{verbatim}open", r"\old\lilypond{open"):
            with self.subTest(source=source):
                self.assert_unsafe(source, "unterminated")

    def test_one_to_one_definition_and_let_targets_are_renamed(self) -> None:
        self.assert_conversion(
            r"\renewcommand{\old}[1]{\songcolumns{#1}}\def\old#1{\old{#1}}\let\old=\songcolumns",
            r"\renewcommand{\ulOld}[1]{\ulSongColumns{#1}}\def\ulOld#1{\ulOld{#1}}\let\ulOld=\ulSongColumns")

    def test_boolean_execution_and_delayed_bodies(self) -> None:
        # Keep the general naming contract, using a non-display boolean: book
        # display setters have a separate, stricter preamble-only review gate.
        self.assert_conversion(
            r"\adjustchordcharstrue{}word \adjustchordcharsfalse @ \def\foo#1{\adjustchordcharstrue#1}"
            r"\newcommand*{\foo}[1][x]{\adjustchordcharsfalse #1}"
            r"\RenewDocumentCommand\foo{m}{\adjustchordcharstrue#1}"
            r"\AtBeginDocument{\adjustchordcharstrue}",
            r"\ulAdjustChordChars{true}{}word \ulAdjustChordChars{false} @ \def\foo#1{\ulAdjustChordChars{true}#1}"
            r"\newcommand*{\foo}[1][x]{\ulAdjustChordChars{false} #1}"
            r"\RenewDocumentCommand\foo{m}{\ulAdjustChordChars{true}#1}"
            r"\AtBeginDocument{\ulAdjustChordChars{true}}")

    def test_boolean_reference_uses_are_transactional(self) -> None:
        for unsafe in (
            r"\let\alias=\showtagstrue", r"\let\showtagstrue\alias",
            r"\renewcommand{\showtagstrue}{}", r"\def\showtagstrue{}",
            r"\string\showtagstrue", r"\detokenize{\showtagstrue}",
            r"\ifx\showtagstrue\foo", r"\meaning\showtagstrue",
            r"\expandafter\showtagstrue\foo", r"\edef\foo{\showtagstrue}",
            r"\unknown{\showtagstrue}", r"\newcommand\foo[1][\showtagstrue]{#1}",
            r"\unknown\showtagstrue",
            r"\unknown[\showtagstrue]", r"\aftergroup\showtagstrue",
            r"\AddToHook{\showtagstrue}{}", r"\AtBeginEnvironment{\showtagstrue}{}",
        ):
            with self.subTest(unsafe=unsafe):
                self.assert_unsafe(r"\old " + unsafe, "boolean reference")

    def test_boolean_prefixes_are_not_rewritten(self) -> None:
        self.assert_conversion(r"\showtagstrueMore \showtagstrue@private",
                               r"\showtagstrueMore \showtagstrue@private", at_letter=True)

    def test_known_zero_argument_structural_commands_before_boolean(self) -> None:
        self.assert_conversion(
            "\\sclearpage\\adjustchordcharstrue\n\\endverse\n\\adjustchordcharsfalse\n\\appendix\\adjustchordcharstrue",
            "\\sclearpage\\ulAdjustChordChars{true}\n\\endverse\n\\ulAdjustChordChars{false}\n\\appendix\\ulAdjustChordChars{true}")

    def test_standard_obeylines_preserves_active_newlines(self) -> None:
        self.assert_conversion("{\\obeylines\n\\showtagstrue\n\\old\n}",
                               "{\\obeylines\n\\ulShowTags{true}\n\\ulOld\n}")

    def test_group_after_known_zero_argument_command_is_not_an_argument(self) -> None:
        self.assert_conversion("\\appendix\n{% standalone group\n\\showtagsfalse\n}",
                               "\\appendix\n{% standalone group\n\\ulShowTags{false}\n}")
        self.assert_conversion(r"\ifshowtags{\adjustchordcharstrue}\fi",
                               r"\ifulShowTags{\ulAdjustChordChars{true}}\fi")

    def test_counters_and_parent_counter(self) -> None:
        self.assert_conversion(
            r"\newcounter{ songnum }[songnum]\setcounter{songnum}{3}"
            r"\addtocounter{songnum}{2}\value{songnum}\arabic{songnum}"
            r"\roman{songnum}\Alph{songnum}\refstepcounter{songnum}"
            r"\counterwithin*{songnum}{songnum} songnum {songnum}",
            r"\newcounter{ ulSongNumber }[ulSongNumber]\setcounter{ulSongNumber}{3}"
            r"\addtocounter{ulSongNumber}{2}\value{ulSongNumber}\arabic{ulSongNumber}"
            r"\roman{ulSongNumber}\Alph{ulSongNumber}\refstepcounter{ulSongNumber}"
            r"\counterwithin*{ulSongNumber}{ulSongNumber} songnum {songnum}")

    def test_color_definitions_expressions_and_scoped_options(self) -> None:
        self.assert_conversion(
            r"\definecolor{songblue}{rgb}{0,0,1}\colorlet{songred}{songblue!50!black}"
            r"\color{songblue!20}\textcolor{songred}{songblue prose}"
            r"\fcolorbox{songblue}{songred}{x}\color[rgb]{0,0,1}"
            r"\node[fill=songblue!30,draw={songred},label=songblue]{songblue}"
            r"\unknown[color=songblue]{songblue}",
            r"\definecolor{ulSongBlue}{rgb}{0,0,1}\colorlet{ulSongRed}{ulSongBlue!50!black}"
            r"\color{ulSongBlue!20}\textcolor{ulSongRed}{songblue prose}"
            r"\fcolorbox{ulSongBlue}{ulSongRed}{x}\color[rgb]{0,0,1}"
            r"\node[fill=ulSongBlue!30,draw={ulSongRed},label=songblue]{songblue}"
            r"\unknown[color=songblue]{songblue}")

    def test_environment_definitions_and_execution_bodies(self) -> None:
        self.assert_conversion(
            r"\newenvironment{songs}[1]{\adjustchordcharstrue#1}{\adjustchordcharsfalse}"
            r"\begin{songs}songs\end{songs}",
            r"\newenvironment{ulSongs}[1]{\ulAdjustChordChars{true}#1}{\ulAdjustChordChars{false}}"
            r"\begin{ulSongs}songs\end{ulSongs}")

    def test_computed_identifier_arguments_are_diagnosed(self) -> None:
        for source in (r"\value{\counter}", r"\color{song\suffix}", r"\begin{\env}",
                       r"\newcounter{foo}[\parent]", r"\node[fill=\shade]{x}"):
            with self.subTest(source=source):
                self.assert_unsafe(source, "computed")

    def test_dynamic_control_sequence_references(self) -> None:
        for source in (r"\csname old\endcsname", r"\csname showtags\flag\endcsname",
                       r"\ifcsname old\endcsname", r"\makeatletter\@namedef{old}{}",
                       r"\csname song\suffix\endcsname"):
            with self.subTest(source=source):
                self.assert_unsafe(source, "reference")
        self.assert_conversion(r"\csname unrelated\endcsname\old",
                               r"\csname unrelated\endcsname\ulOld")

    def test_unsupported_tokenization_is_diagnosed(self) -> None:
        for source in (r"\catcode`\@=11\old", r"^^5cold", r"\scantokens{\old}"):
            with self.subTest(source=source):
                self.assert_unsafe(source, "unsupported")

    def test_literal_control_sequence_printing_is_not_silently_changed(self) -> None:
        self.assert_unsafe(r"\detokenize{\old}", "literal/reference")
        self.assert_conversion(r"\detokenize{\color{songblue}}\old",
                               r"\detokenize{\color{songblue}}\ulOld")

    def test_opaque_command_references_do_not_hide_executable_tokens(self) -> None:
        self.assert_conversion(r"\let\alias\verb|\old|", r"\let\alias\verb|\ulOld|")
        self.assert_conversion(r"\renewcommand{\lilypond}[1]{\old}",
                               r"\renewcommand{\lilypond}[1]{\ulOld}")
        self.assert_conversion(r"\string\begin{verbatim}\old",
                               r"\string\begin{verbatim}\ulOld")

    def test_named_delayed_hooks_only_expand_boolean_in_body(self) -> None:
        self.assert_conversion(r"\AddToHook{begindocument}[mine]{\adjustchordcharstrue}",
                               r"\AddToHook{begindocument}[mine]{\ulAdjustChordChars{true}}")
        self.assert_conversion(r"\AtBeginEnvironment{songs}{\adjustchordcharstrue}",
                               r"\AtBeginEnvironment{ulSongs}{\ulAdjustChordChars{true}}")

    def test_command_reference_does_not_parse_nonexistent_arguments(self) -> None:
        self.assert_conversion(r"\let\color\old\string\value",
                               r"\let\color\ulOld\string\value")
        self.assert_conversion(r"\def\color#1{#1}\old", r"\def\color#1{#1}\ulOld")

    def test_hyperref_color_options_use_braced_key_values(self) -> None:
        self.assert_conversion(r"\hypersetup{linkcolor=songblue,urlcolor={songred!30},pdftitle=songblue}",
                               r"\hypersetup{linkcolor=ulSongBlue,urlcolor={ulSongRed!30},pdftitle=songblue}")

    def test_delayed_tokenization_switches_are_not_executed_by_scanner(self) -> None:
        self.assert_unsafe(r"\def\foo{\makeatletter\old@tail}\old", "tokenization switch")
        self.assert_unsafe(r"\string\makeatletter\old@tail", "tokenization switch")

    def test_real_public_mapping_is_loaded_without_internal_migration(self) -> None:
        source = r"\songcolumns{2}\showtagstrue\setcounter{songnum}{1}\color{chordcolor}"
        result = migration.migrate_text(source)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text,
                         r"\ulSongColumns{2}\ulShowTags{true}\setcounter{ulSongNumber}{1}\color{ulChordColor}")
        internal = r"\makeatletter\@tagsbox\UL@audio"
        self.assertEqual(migration.migrate_text(internal).text, internal)

    def test_each_public_mapping_is_converted_or_fenced_for_review(self) -> None:
        from ulsbs.tools.naming_v2 import BOOLEAN_SETTERS, COMMAND_RENAMES
        for old, new in COMMAND_RENAMES.items():
            with self.subTest(command=old):
                result = migration.migrate_text("\\" + old)
                if old in LEGACY_IDENTITY_NAMES + REMOVED_MEASURE_NAMES + REMOVED_SPACING_NAMES:
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, "\\" + old)
                    self.assertIn("requires review", result.diagnostics[0].message)
                    self.assertEqual(result.converted, {old: 1})
                    continue
                self.assertTrue(result.safe, result.diagnostics)
                self.assertEqual(result.text, "\\" + new)
        for old, (setter, value) in BOOLEAN_SETTERS.items():
            with self.subTest(boolean=old):
                result = migration.migrate_text("\\" + old)
                if old in LEGACY_IDENTITY_NAMES + REMOVED_MEASURE_NAMES:
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, "\\" + old)
                    self.assertIn("requires review", result.diagnostics[0].message)
                    self.assertEqual(result.converted, {old: 1})
                    continue
                self.assertTrue(result.safe, result.diagnostics)
                self.assertEqual(result.text, f"\\{setter}{{{value}}}")

    def test_tag_index_names_and_unchanged_title_author_contract(self) -> None:
        source = (r"\newscripindex{tagidx}{idx_tags}\ulNewScriptureIndex{tags}{other}"
                  r"\idxscripfont\ulIndexScriptureFont"
                  r"\newindex{titleidx}{idx_title}\newauthorindex{authidx}{idx_auth}"
                  r"\ulTagFile{include/tags.can}\input{arbitrary.can}")
        expected = (r"\ulNewTagIndex{tagidx}{idx_tags}\ulNewTagIndex{tags}{other}"
                    r"\ulIndexTagFont\ulIndexTagFont"
                    r"\ulNewIndex{titleidx}{idx_title}\ulNewAuthorIndex{authidx}{idx_auth}"
                    r"\ulTagFile{include/tags.can}\input{arbitrary.can}")
        result = migration.migrate_text(source)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, expected)
        second = migration.migrate_text(expected)
        self.assertTrue(second.safe, second.diagnostics)
        self.assertEqual(second.text, expected)
        self.assertFalse(second.converted)

    def test_removed_sr_metadata_including_empty_raw_and_numbered_values(self) -> None:
        for options in (
            "sr={}", "sr=", "sr", "sr={fire}", "sr={fire 1}",
            "tags={water},sr={fire},by={Author},cr={Copyright}",
            "custom={nested,{sr={safe}}}, sr = {fire; water 1}",
            "sr% before equals\n={fire}", "s% split name\nr = {}",
            "% before key\nsr % before equals\n = {fire}",
        ):
            with self.subTest(options=options):
                source = "\\songcolumns{2}\\beginsong{Title}[" + options + "]"
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                self.assertTrue(any("removed sr song metadata" in d.message
                                    for d in result.diagnostics), result.diagnostics)
                self.assertTrue(any("tags=/by=/cr=" in d.message
                                    and "no automatic sr conversion" in d.message
                                    for d in result.diagnostics))

    def test_removed_three_braced_song_metadata(self) -> None:
        for source in (
            r"\beginsong{Title}{fire}{Author}{Copyright}",
            r"\beginsong{Title}{fire 1}{Author}{Copyright}",
            r"\beginsong{Title}{}{}{}",
            "\\beginsong{Title}% refs\n{fire}% by\n{A {nested}}% cr\n{C}",
            r"\newcommand\song{\beginsong{Title}{#1}{#2}{#3}}",
        ):
            with self.subTest(source=source):
                source = r"\songcolumns{2}" + source
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                self.assertTrue(any("removed three-braced song metadata" in d.message
                                    and "tags=/by=/cr=" in d.message
                                    and "no automatic sr conversion" in d.message
                                    for d in result.diagnostics), result.diagnostics)

    def test_song_metadata_nested_literals_and_current_keys_remain_unchanged(self) -> None:
        for source in (
            r"\beginsong{Title}[tags={fire,water 1},by={Author},cr={Copyright}]",
            r"\beginsong{Title}[custom={sr={fire},nested={sr={}}},tags={water}]",
            r"\beginsong{Title}[custom={sr},by={sr={literal}},cr={sr=1}]",
            r"\beginsong{Title}[custom=[sr={fire},nested=[sr={}]],tags={water}]",
            r"\beginsong{sr={title}}[custom=sr=literal,tags={fire}]",
            r"\beginsong{Title}[custom=\,sr=literal,tags={fire}]",
            r"\beginsong{Title}[custom=\{sr=literal\},tags={fire}]",
            r"\beginsong{Title}[custom={\beginsong{Literal}[sr={text}]}]",
            "\\beginsong{Title}[tags={fire},% sr={not a key}\nby={Author}]",
            r"\beginsong{Title}[]", r"\beginsong{Title}[,tags={fire},,]",
            r"\beginsong{Title}{grouped lyrics}",
            "Prose sr={fire}, [sr={}], {references}{authors}{copyright}",
        ):
            with self.subTest(source=source):
                result = migration.migrate_text(source)
                self.assertTrue(result.safe, result.diagnostics)
                self.assertEqual(result.text, source)

    def test_song_metadata_reference_and_opaque_contexts_are_not_invocations(self) -> None:
        for source in (
            r"\string\beginsong{Title}[sr={fire}]",
            r"\let\alias=\beginsong{Title}[sr={fire}]",
            r"\newcommand{\beginsong}[1]{sr={literal}}",
            r"\def\beginsong#1{sr={literal}}",
            r"\detokenize{\beginsong{Title}[sr={fire}]}",
            r"\unknown{\beginsong{Title}[sr={fire}]}",
            r"\verb|\beginsong{Title}[sr={fire}]|",
            "% \\beginsong{Title}[sr={fire}]\n",
            r"\begin{verbatim}\beginsong{Title}[sr={fire}]\end{verbatim}",
            r"\lilypond{ \beginsong{Title}[sr={fire}] }",
            r"\begin{lilypond}\beginsong{Title}[sr={fire}]\end{lilypond}",
            r"\url{https://test/\beginsong{Title}[sr={fire}]}",
            r"\href{https://test/sr=fire}{literal sr={fire}}",
        ):
            with self.subTest(source=source):
                result = migration.migrate_text(source)
                self.assertTrue(result.safe, result.diagnostics)
                self.assertEqual(result.text, source)

    def test_removed_song_metadata_in_safe_delayed_execution_bodies(self) -> None:
        for source in (
            r"\newcommand\song{\beginsong{Title}[sr={fire}]}",
            r"\AtBeginDocument{\beginsong{Title}[sr={}]}",
            r"\href{https://test/}{\beginsong{Title}[sr={fire}]}",
        ):
            with self.subTest(source=source):
                self.assert_unsafe(source, "removed sr song metadata")

    def test_dynamic_empty_and_malformed_song_metadata_require_review(self) -> None:
        for source in (
            r"\beginsong\title[sr={fire}]",
            r"\beginsong{Title}[\metadata]",
            r"\beginsong{Title}[\key={fire}]",
            r"\beginsong{Title}[#1={fire}]",
            r"\beginsong{Title}[=value]",
            r"\beginsong{Title}[custom=x, =value]",
            r"\beginsong{Title}[sr={fire}",
        ):
            with self.subTest(source=source):
                self.assert_unsafe(r"\old" + source, "requires review")

    def test_removed_songrefs_accessors_in_references_and_definitions(self) -> None:
        from ulsbs.tools.naming_v2 import COMMAND_RENAMES, REMOVED_COMMANDS
        for name in ("songrefs", "ulSongRefs"):
            self.assertNotIn(name, COMMAND_RENAMES)
            self.assertIn(name, REMOVED_COMMANDS)
            for source in (
                "\\" + name, "\\let\\alias=\\" + name,
                "\\renewcommand{\\" + name + "}{}", "\\def\\" + name + "{}",
                "\\string\\" + name, "\\detokenize{\\" + name + "}",
            ):
                with self.subTest(name=name, source=source):
                    self.assert_unsafe(r"\old" + source, "removed song-reference accessor")

    def test_removed_song_metadata_cli_suppresses_partial_diffs_and_writes(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.tex"
            source = b"\\songcolumns{2}\r\n\\beginsong{Title}[sr={}]\r\n"
            path.write_bytes(source)
            for mode in ("--check", "--diff", "--write"):
                with self.subTest(mode=mode), redirect_stdout(StringIO()) as output:
                    with redirect_stderr(StringIO()) as errors:
                        self.assertEqual(migration.main([mode, str(path)]), 1)
                    self.assertEqual(output.getvalue(), "")
                    self.assertIn(f"{path}:2:", errors.getvalue())
                    self.assertEqual(path.read_bytes(), source)
                    self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_song_environment_uses_same_removed_metadata_diagnostics(self) -> None:
        for source, fragment in (
            (r"\begin{song}{Title}[sr={}]", "removed sr song metadata"),
            (r"\begin{song}{Title}{fire}{Author}{Copyright}", "removed three-braced"),
        ):
            with self.subTest(source=source):
                self.assert_unsafe(source, fragment)
        for source in (
            r"\begin{song}{Title}[tags={fire},by={Author},cr={Copyright}]",
            r"\begin{song}{Title}[custom={sr={literal}}]",
            r"\string\begin{song}{Title}[sr={literal}]",
            r"\beginsong{Title}[custom={\begin{song}{Nested}[sr={literal}]}]",
        ):
            with self.subTest(source=source):
                result = migration.migrate_text(source)
                self.assertTrue(result.safe, result.diagnostics)
                self.assertEqual(result.text, source)

    def test_chorus_boundaries_preserve_repeat_semantics(self) -> None:
        for source, expected in (
            (r"\beginchorus lyric\endchorus", r"\beginverse\beginrep lyric\endrep\endverse"),
            (r"\chorus lyric\endchorus", r"\beginverse\beginrep lyric\endrep\endverse"),
            (r"\begin{chorus}lyric\end{chorus}", r"\begin{verse}\beginrep lyric\endrep\end{verse}"),
            ("\\begin% start\n{chorus}% lyrics\nx\\end{chorus}",
             "\\begin% start\n{verse}\\beginrep % lyrics\nx\\endrep\\end{verse}"),
            (r"\beginchorus\beginrep x\endrep\endchorus",
             r"\beginverse\beginrep\beginrep x\endrep\endrep\endverse"),
            (r"\newcommand\refrain{\beginchorus x\endchorus}",
             r"\newcommand\refrain{\beginverse\beginrep x\endrep\endverse}"),
            (r"\AtBeginDocument{\begin{chorus}x\end{chorus}}",
             r"\AtBeginDocument{\begin{verse}\beginrep x\endrep\end{verse}}"),
        ):
            with self.subTest(source=source):
                self.assert_conversion(source, expected)

    def test_chorus_expansion_does_not_reinterpret_modifiers_as_verse_options(self) -> None:
        # The old wrapper inserted beginrep before the source's next token too.
        self.assert_conversion(r"\beginchorus*[2]x\endchorus",
                               r"\beginverse\beginrep*[2]x\endrep\endverse")

    def test_chorus_references_and_ambiguous_arguments_are_transactional(self) -> None:
        for unsafe in (
            r"\let\alias=\beginchorus", r"\let\endchorus\alias",
            r"\def\chorus{}", r"\renewcommand{\beginchorus}{}",
            r"\string\endchorus", r"\detokenize{\beginchorus}",
            r"\ifx\beginchorus\foo", r"\aftergroup\endchorus",
            r"\unknown{\beginchorus x\endchorus}", r"\unknown\beginchorus",
            r"\edef\refrain{\beginchorus x\endchorus}",
            r"\expanded{\beginchorus x\endchorus}",
            r"\newenvironment{chorus}{}{}", r"\AtBeginEnvironment{chorus}{}",
            r"\AddToHook{env/chorus/begin}{custom}",
            r"\RemoveFromHook{env/chorus/after}[custom]",
            r"\unknown{\begin{chorus}x\end{chorus}}", r"\unknown\begin{chorus}",
            r"\string\begin{chorus}", r"\detokenize{\begin{chorus}}",
            "\\begin{cho% split\nrus}",
            r"\newcommand\foo[1][\beginchorus]{#1}",
        ):
            with self.subTest(source=unsafe):
                self.assert_unsafe(r"\old " + unsafe, "chorus")

    def test_removed_configuration_is_not_mapped_to_active_settings(self) -> None:
        from ulsbs.tools.naming_v2 import REMOVED_COMMANDS
        for name in REMOVED_COMMANDS:
            with self.subTest(command=name):
                source = r"\songcolumns{2}" + "\\" + name
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                expected = ("removed song-reference accessor" if name in {"songrefs", "ulSongRefs"}
                            else "removed no-op setting")
                self.assertIn(expected, result.diagnostics[0].message)

    def test_chorus_dynamic_references_require_review(self) -> None:
        for source in (r"\csname beginchorus\endcsname", r"\ifcsname ulChorusFont\endcsname",
                       r"\makeatletter\@namedef{endchorus}{}"):
            with self.subTest(source=source):
                self.assert_unsafe(source, "reference")

    def test_chorus_comments_literals_and_lilypond_remain_opaque(self) -> None:
        source = ("% \\beginchorus \\ulChorusFont\n"
                  r"\verb|\endchorus\ccpenalty|"
                  r"\begin{verbatim}\begin{chorus}\end{chorus}\end{verbatim}"
                  r"\url{https://example.test/\chorus%20\ulRepeatChorus}"
                  r"\lilypond{ \beginchorus \chorusfont }"
                  r"\begin{lilypond}\endchorus\end{lilypond}")
        self.assert_conversion(source + r"\old", source + r"\ulOld")

    def test_chorus_cli_preserves_unsafe_files_and_writes_safe_files_atomically(self) -> None:
        with TemporaryDirectory() as directory:
            safe = Path(directory) / "safe.tex"
            unsafe = Path(directory) / "unsafe.tex"
            safe.write_bytes(b"\\begin{chorus}x\\end{chorus}\r\n")
            unsafe_source = r"\beginchorus x\endchorus\ccpenalty=5"
            unsafe.write_text(unsafe_source, encoding="utf-8")
            with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()):
                self.assertEqual(migration.main(["--diff", str(unsafe)]), 1)
            self.assertEqual(output.getvalue(), "")
            with redirect_stderr(StringIO()):
                self.assertEqual(migration.main(["--write", directory]), 1)
                self.assertEqual(migration.main(["--check", str(safe)]), 0)
            self.assertEqual(safe.read_bytes(), b"\\begin{verse}\\beginrep x\\endrep\\end{verse}\r\n")
            self.assertEqual(unsafe.read_text(), unsafe_source)

    def test_removed_settings_in_definitions_and_literals_require_review(self) -> None:
        for source in (r"\renewcommand{\chorusfont}{\bfseries}",
                       r"\let\alias=\ulChorusVersePenalty", r"\string\ulRawText",
                       r"\detokenize{\ulNoteNameA}"):
            with self.subTest(source=source):
                self.assert_unsafe(source, "removed no-op setting")

    def test_fragmented_known_counter_name_requires_review(self) -> None:
        self.assert_unsafe("\\value{song% comment\nnum}", "fragmented")

    def test_insert_delimiter_after_changed_control_symbol(self) -> None:
        result = migration.migrate_text(r"\?letters", command_renames={"?": "ulQuestion"},
                                        boolean_setters={}, name_argument_renames={})
        self.assertEqual(result.text, r"\ulQuestion letters")

    def test_cli_modes_atomicity_newlines_and_mixed_files(self) -> None:
        with TemporaryDirectory() as directory:
            safe = Path(directory) / "safe.tex"
            unsafe = Path(directory) / "unsafe.tex"
            safe.write_bytes(b"\\old\r\n")
            unsafe.write_text(r"\old\let\alias\showtagstrue", encoding="utf-8")
            safe.chmod(0o640)
            original = migration.migrate_text

            def mapped(source, **kwargs):
                return original(source, **kwargs, command_renames=COMMANDS,
                                boolean_setters=BOOLEANS, name_argument_renames=NAMES)

            with patch.object(migration, "migrate_text", side_effect=mapped):
                with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()):
                    self.assertEqual(migration.main(["--check", str(safe)]), 1)
                    self.assertEqual(migration.main(["--diff", str(safe)]), 0)
                self.assertIn("+\\ulOld", output.getvalue())
                self.assertEqual(safe.read_bytes(), b"\\old\r\n")
                with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()):
                    self.assertEqual(migration.main(["--diff", str(unsafe)]), 1)
                self.assertEqual(output.getvalue(), "")
                with redirect_stderr(StringIO()):
                    self.assertEqual(migration.main(["--write", directory]), 1)
                self.assertEqual(safe.read_bytes(), b"\\ulOld\r\n")
                self.assertEqual(stat.S_IMODE(safe.stat().st_mode), 0o640)
                self.assertEqual(unsafe.read_text(), r"\old\let\alias\showtagstrue")
                with redirect_stderr(StringIO()):
                    self.assertEqual(migration.main(["--check", str(safe)]), 0)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ["safe.tex", "unsafe.tex"])

    def test_atomic_replace_failure_preserves_original_and_removes_temp(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "song.tex"
            path.write_text("old", encoding="utf-8")
            with patch.object(os, "replace", side_effect=OSError("failure")):
                with self.assertRaises(OSError):
                    migration._atomic_write(path, "new")
            self.assertEqual(path.read_text(), "old")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_directory_traversal_filters_generated_trees_and_accepts_explicit_sources(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("song.tex", "class.cls", "style.sty", "authors.sbx", "ignore.txt", ".hidden.tex"):
                (root / name).touch()
            for name in ("build", "generated", "temp", ".git", ".hidden",
                         "result", "results", "deploy", "temp.validation.backup", "tmp.backup"):
                (root / name).mkdir()
                (root / name / "generated.tex").touch()
                (root / name / "generated.sbx").touch()
            self.assertEqual({p.name for p in migration._paths([directory])},
                             {"song.tex", "class.cls", "style.sty", "authors.sbx"})
            explicit = root / "build" / "generated.tex"
            self.assertEqual(migration._paths([str(explicit)]), [explicit])
            explicit = root / "temp.validation.backup" / "generated.sbx"
            self.assertEqual(migration._paths([str(explicit)]), [explicit])

    def test_sbx_explicit_and_directory_cli_migrate_manual_index_fragments(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "authors.sbx"
            source = r"\begin{idxblock}{A}\idxentry{Author}{1}\end{idxblock}"
            expected = r"\begin{ulIndexBlock}{A}\ulIndexDisplayEntry{Author}{1}\end{ulIndexBlock}"
            path.write_text(source, encoding="utf-8")
            self.assertEqual(migration._paths([str(path)]), [path])
            with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()):
                self.assertEqual(migration.main(["--diff", str(path)]), 0)
            self.assertIn("+" + expected, output.getvalue())
            self.assertEqual(path.read_text(), source)
            with redirect_stderr(StringIO()):
                self.assertEqual(migration.main(["--write", directory]), 0)
                self.assertEqual(migration.main(["--check", str(path)]), 0)
            self.assertEqual(path.read_text(), expected)


class LegacyIdentityReviewTests(unittest.TestCase):
    def test_all_identity_generations_reject_direct_uses_and_preserve_counts(self) -> None:
        from ulsbs.tools.naming_v2 import BOOLEAN_SETTERS, COMMAND_RENAMES

        for name in LEGACY_IDENTITY_NAMES:
            with self.subTest(name=name):
                source = r"\songcolumns{2}" + "\\" + name + r"{false}\showtagsfalse"
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                identity_diagnostics = [d for d in result.diagnostics if "legacy variant identity" in d.message]
                self.assertEqual(len(identity_diagnostics), 1, result.diagnostics)
                diagnostic = identity_diagnostics[0]
                self.assertEqual((diagnostic.line, diagnostic.column), (1, 16))
                self.assertIn("legacy variant identity \\" + name, diagnostic.message)
                self.assertIn("review", diagnostic.message)
                counts = {"songcolumns": 1, "showtagsfalse": 1}
                if name in COMMAND_RENAMES or name in BOOLEAN_SETTERS:
                    counts[name] = 1
                self.assertEqual(result.converted, counts)
                self.assertEqual(migration.migrate_text(source), result)

    def test_identity_references_definitions_and_delayed_uses_are_not_exempt(self) -> None:
        for name in LEGACY_IDENTITY_NAMES:
            for template in (
                r"\let\alias=\%s", r"\let\%s=\alias", r"\futurelet\alias\relax\%s",
                r"\string\%s", r"\meaning\%s", r"\noexpand\%s", r"\ifx\%s\other\fi",
                r"\ifdefined\%s\fi", r"\aftergroup\%s", r"\expandafter\%s\other",
                r"\def\%s{false}", r"\renewcommand{\%s}[1]{#1}",
                r"\newcommand\later{\%s{false}}", r"\edef\later{\%s}",
                r"\AtBeginDocument{\%s{false}}", r"\AddToHook{begindocument}{\%s}",
                r"\detokenize{\%s}", r"\unexpanded{\%s}", r"\unknown{\%s}",
                r"\unknown[\%s]", r"\href{https://test/}{\%s}",
            ):
                with self.subTest(name=name, template=template):
                    source = r"\songcolumns{2}" + template % name
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    self.assertTrue(any("legacy variant identity \\" + name in d.message
                                        for d in result.diagnostics), result.diagnostics)

    def test_identity_named_and_dynamic_references_require_review(self) -> None:
        for name in LEGACY_IDENTITY_NAMES:
            for template in (r"\csname %s\endcsname", r"\ifcsname %s\endcsname\fi",
                             r"\@nameuse{%s}", r"\@namedef{%s}{}", r"\@ifundefined{%s}{}{}"):
                with self.subTest(name=name, template=template):
                    source = "heading\r\n" + r"\songcolumns{2}" + template % name
                    result = migration.migrate_text(source, at_letter=True)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    self.assertTrue(any("reference requires review" in d.message
                                        for d in result.diagnostics), result.diagnostics)
                    self.assertEqual((result.diagnostics[0].line, result.diagnostics[0].column), (2, 16))
        for source in (r"\csname iful\kind\endcsname", r"\@nameuse{ul#1}"):
            result = migration.migrate_text(source, at_letter=True)
            self.assertFalse(result.safe)
            self.assertEqual(result.text, source)

    def test_identity_opaque_regions_remain_unchanged_and_do_not_trigger_review(self) -> None:
        payload = " ".join("\\" + name for name in LEGACY_IDENTITY_NAMES)
        opaque = ("% " + payload + "\r\n"
                  + "".join("\\" + command + delimiter + payload + delimiter
                            for command in ("verb", "verb*", "Verb", "lstinline")
                            for delimiter in ("|", "!", "+"))
                  + "".join("\\begin{" + env + "}" + payload + "\\end{" + env + "}"
                            for env in sorted(migration.VERBATIM_ENVS))
                  + "".join("\\" + command + "{https://test/" + payload + "}"
                            for command in ("url", "nolinkurl", "path"))
                  + "\\lilypond[staffsize=12]{ " + payload + " }")
        result = migration.migrate_text(opaque + r"\songcolumns{2}")
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, opaque + r"\ulSongColumns{2}")
        self.assertEqual(result.converted, {"songcolumns": 1})
        self.assertTrue(migration.migrate_text(result.text).safe)

    def test_identity_boundaries_and_current_feature_apis_remain_supported(self) -> None:
        for name in LEGACY_IDENTITY_NAMES:
            for suffix, prefix, at_letter in (("Extra", "", False), ("@private", "", True),
                                              ("_private:", r"\ExplSyntaxOn", False)):
                with self.subTest(name=name, suffix=suffix):
                    source = prefix + "\\" + name + suffix
                    result = migration.migrate_text(source, at_letter=at_letter)
                    self.assertTrue(result.safe, result.diagnostics)
                    self.assertEqual(result.text, source)
        source = (r"\ulIfVariant{lyric}{yes}{no}\ulIfMusical{yes}{no}"
                  r"\ifulShowChords yes\else no\fi\ulShowChords{false}"
                  r"\ulLocalShow{chords}{true}\ifulNoLyrics\fi\ulNoLyrics{false}")
        result = migration.migrate_text(source)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, source)

    def test_nested_and_unbalanced_identity_branches_are_diagnosed_without_conversion(self) -> None:
        for source in (r"\iftrue\ifulChorded A\else\ifbassclefbook B\fi\fi\fi",
                       r"\ifulLyricOnly A\else B", r"\ifchorded"):
            with self.subTest(source=source):
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                self.assertTrue(all("legacy variant identity" in d.message for d in result.diagnostics))

    def test_identity_cli_modes_reject_whole_files_but_continue_safe_files(self) -> None:
        for mode in ("--check", "--diff", "--write"):
            for name in ("ifchorded", "ifulChorded", "bassclefbooktrue", "ulBassclefBook", "ulSongbookType"):
                with self.subTest(mode=mode, name=name), TemporaryDirectory() as directory:
                    safe, unsafe = Path(directory) / "safe.tex", Path(directory) / "unsafe.cls"
                    safe.write_bytes(b"\\songcolumns{2}\r\n")
                    source = ("% heading\r\n" + r"\songcolumns{2}" + "\\" + name + "\r\n").encode()
                    unsafe.write_bytes(source)
                    safe.chmod(0o640)
                    unsafe.chmod(0o600)
                    with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()) as errors:
                        self.assertEqual(migration.main([mode, directory]), 1)
                    self.assertIn(f"{unsafe}:2:16: legacy variant identity", errors.getvalue())
                    self.assertIn("Scanned 2 files; 1 would change; 1 need review.", errors.getvalue())
                    self.assertIn("songcolumns: 2", errors.getvalue())
                    self.assertEqual("+++ " + str(safe) in output.getvalue(), mode == "--diff")
                    self.assertNotIn(str(unsafe), output.getvalue())
                    self.assertEqual(unsafe.read_bytes(), source)
                    self.assertEqual(safe.read_bytes(), b"\\ulSongColumns{2}\r\n" if mode == "--write"
                                     else b"\\songcolumns{2}\r\n")
                    self.assertEqual(stat.S_IMODE(safe.stat().st_mode), 0o640)
                    self.assertEqual(stat.S_IMODE(unsafe.stat().st_mode), 0o600)
                    self.assertEqual(set(Path(directory).iterdir()), {safe, unsafe})


class RemovedSpacingReviewTests(unittest.TestCase):
    def test_removed_spacing_uses_original_coordinates_and_rejects_all_edits(self) -> None:
        for name in REMOVED_SPACING_NAMES:
            with self.subTest(name=name):
                source = ("% heading\r\n" + r"\songcolumns{2}\begin{chorus}" + "\\" + name
                          + "=2pt\r\n" + r"\end{chorus}")
                with patch.object(migration, "_apply_edit_plans", wraps=migration._apply_edit_plans) as apply:
                    result = migration.migrate_text(source)
                apply.assert_called_once()
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                self.assertEqual(len(result.diagnostics), 1, result.diagnostics)
                diagnostic = result.diagnostics[0]
                self.assertEqual((diagnostic.line, diagnostic.column), (2, 30))
                self.assertIn("removed spacing API \\" + name + " requires review", diagnostic.message)
                self.assertIn("no automatic spacing conversion", diagnostic.message)
                counts = {"songcolumns": 1, "environment:chorus": 2,
                          "chorus:repeat-start": 1, "chorus:repeat-end": 1}
                if name in {"baselineadj", "versesep"}:
                    counts[name] = 1
                self.assertEqual(result.converted, counts)

    def test_spacing_references_assignments_length_commands_and_delayed_bodies(self) -> None:
        for name in REMOVED_SPACING_NAMES:
            for template in (
                r"\%s", r"\%s=2pt", r"\global\%s=-1pt",
                r"\setlength{\%s}{2pt}", r"\addtolength{\%s}{-1pt}", r"\newlength{\%s}",
                r"\let\alias=\%s", r"\let\%s=\alias", r"\string\%s", r"\meaning\%s",
                r"\ifx\%s\other\fi", r"\ifdefined\%s\fi", r"\aftergroup\%s",
                r"\def\%s{2pt}", r"\renewcommand{\%s}{2pt}",
                r"\newcommand\later{\%s=2pt}", r"\AtBeginDocument{\%s=2pt}",
                r"\unknown{\%s}", r"\href{https://test/}{\%s}",
            ):
                with self.subTest(name=name, template=template):
                    source = r"\songcolumns{2}" + template % name
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    self.assertTrue(any("removed spacing API \\" + name in d.message
                                        for d in result.diagnostics), result.diagnostics)
                    result = migration.migrate_text(source, command_renames={}, boolean_setters={},
                                                    name_argument_renames={})
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)

    def test_spacing_named_references_follow_existing_qualification(self) -> None:
        for name in REMOVED_SPACING_NAMES:
            for value in (name, name[:3] + " % split\r\n" + name[3:]):
                for template in (r"\csname %s\endcsname", r"\ifcsname %s\endcsname\fi",
                                 r"\@nameuse{%s}", r"\@namedef{%s}{}", r"\@ifundefined{%s}{}{}"):
                    with self.subTest(name=name, value=value, template=template):
                        source = "% heading\r\n" + r"\songcolumns{2}" + template % value
                        result = migration.migrate_text(source, at_letter=True)
                        self.assertFalse(result.safe)
                        self.assertEqual(result.text, source)
                        self.assertIn("reference requires review", result.diagnostics[0].message)
                        self.assertEqual((result.diagnostics[0].line, result.diagnostics[0].column), (2, 16))

    def test_spacing_opaque_and_recognized_protected_payloads_are_unchanged(self) -> None:
        payload = " ".join("\\" + name for name in REMOVED_SPACING_NAMES)
        for protected in (
            "% " + payload + "\r\n", "\\verb|" + payload + "|",
            "\\lstinline[language=TeX]|" + payload + "|",
            "\\url{https://test/" + payload + "}", "\\path|" + payload + "|",
            "\\lilypond{" + payload + "}",
            *("\\begin{" + env + "}" + payload + "\\end{" + env + "}"
              for env in sorted(migration.VERBATIM_ENVS)),
            *("\\" + command + "{" + payload + "}"
              for command in ("detokenize", "unexpanded", "message", "errmessage")),
            "\\beginsong{" + payload + "}[tags={" + payload + "},by={" + payload + "}]",
            "\\begin{song}{Title}[custom={" + payload + "}]",
        ):
            with self.subTest(protected=protected):
                result = migration.migrate_text(protected + r"\songcolumns{2}")
                self.assertTrue(result.safe, result.diagnostics)
                self.assertEqual(result.text, protected + r"\ulSongColumns{2}")
                self.assertEqual(result.converted, {"songcolumns": 1})

    def test_current_spacing_settings_and_token_boundaries_pass_unchanged(self) -> None:
        source = (r"\ulVerseBaseline{1.1}\ulVerseSeparation{0.3}"
                  r"\ulVerseMinimumGap{0.1}\ulVerseSpacingScale{0.9}")
        result = migration.migrate_text(source)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, source)
        self.assertFalse(result.converted)
        for name in REMOVED_SPACING_NAMES:
            for prefix, suffix, at_letter in (("", "Extra", False), ("", "@private", True),
                                               (r"\ExplSyntaxOn", "_private:", False)):
                with self.subTest(name=name, suffix=suffix):
                    source = prefix + "\\" + name + suffix
                    result = migration.migrate_text(source, at_letter=at_letter)
                    self.assertTrue(result.safe, result.diagnostics)
                    self.assertEqual(result.text, source)

    def test_spacing_cli_modes_reject_whole_files_and_continue_safe_files(self) -> None:
        for mode in ("--check", "--diff", "--write"):
            for name in REMOVED_SPACING_NAMES:
                with self.subTest(mode=mode, name=name), TemporaryDirectory() as directory:
                    safe, rejected = Path(directory) / "safe.tex", Path(directory) / "rejected.tex"
                    safe.write_bytes(b"\\songcolumns{2}\r\n")
                    source = ("% heading\r\n" + r"\songcolumns{2}" + "\\" + name + "=2pt\r\n").encode()
                    rejected.write_bytes(source)
                    with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()) as errors:
                        self.assertEqual(migration.main([mode, directory]), 1)
                    self.assertIn(f"{rejected}:2:16: removed spacing API \\" + name, errors.getvalue())
                    self.assertIn("Scanned 2 files; 1 would change; 1 need review.", errors.getvalue())
                    self.assertNotIn(str(rejected), output.getvalue())
                    self.assertEqual("+++ " + str(safe) in output.getvalue(), mode == "--diff")
                    self.assertEqual(rejected.read_bytes(), source)
                    self.assertEqual(safe.read_bytes(), b"\\ulSongColumns{2}\r\n" if mode == "--write"
                                     else b"\\songcolumns{2}\r\n")
                    self.assertEqual(set(Path(directory).iterdir()), {safe, rejected})


class RemovedMeasureReviewTests(unittest.TestCase):
    def test_removed_measure_generations_use_original_coordinates_and_counts(self) -> None:
        for name in REMOVED_MEASURE_NAMES:
            for prefix, column in ((r"\songcolumns{2}", 16), (r"\ulSongColumns{2}", 18)):
                with self.subTest(name=name, prefix=prefix):
                    source = "heading\r\n" + prefix + "\\" + name + r"{false}\showtagsfalse" + "\r\n"
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    measure_diagnostics = [d for d in result.diagnostics if "removed measure API" in d.message]
                    self.assertEqual(len(measure_diagnostics), 1, result.diagnostics)
                    diagnostic = measure_diagnostics[0]
                    self.assertEqual((diagnostic.line, diagnostic.column), (2, column))
                    self.assertIn("removed measure API \\" + name + " requires review", diagnostic.message)
                    self.assertIn(r"\ulShowMeasures", diagnostic.message)
                    self.assertIn(r"\ulLocalShow{measures}", diagnostic.message)
                    self.assertIn(r"\ifulShowMeasures", diagnostic.message)
                    counts = {"showtagsfalse": 1}
                    if prefix.startswith(r"\songcolumns"):
                        counts["songcolumns"] = 1
                    if name in {"ifmeasures", "measurestrue", "measuresfalse"}:
                        counts[name] = 1
                    self.assertEqual(result.converted, counts)
                    self.assertEqual(migration.migrate_text(source), result)

    def test_removed_measure_references_definitions_and_delayed_uses_require_review(self) -> None:
        for name in REMOVED_MEASURE_NAMES:
            for template in (
                r"\let\alias=\%s", r"\let\%s=\alias", r"\string\%s", r"\meaning\%s",
                r"\ifx\%s\other\fi", r"\ifdefined\%s\fi", r"\aftergroup\%s",
                r"\def\%s{false}", r"\renewcommand{\%s}[1]{#1}",
                r"\newcommand\later{\%s{false}}", r"\edef\later{\%s}",
                r"\AtBeginDocument{\%s{false}}", r"\AddToHook{begindocument}{\%s}",
                r"\detokenize{\%s}", r"\unexpanded{\%s}", r"\unknown{\%s}",
                r"\unknown[\%s]", r"\href{https://test/}{\%s}",
            ):
                with self.subTest(name=name, template=template):
                    source = r"\songcolumns{2}" + template % name
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    self.assertTrue(any("removed measure API \\" + name in d.message
                                        for d in result.diagnostics), result.diagnostics)

    def test_removed_measure_named_references_require_review(self) -> None:
        for name in REMOVED_MEASURE_NAMES:
            for template in (r"\csname %s\endcsname", r"\ifcsname %s\endcsname\fi",
                             r"\@nameuse{%s}", r"\@namedef{%s}{}", r"\@ifundefined{%s}{}{}"):
                with self.subTest(name=name, template=template):
                    source = "heading\r\n" + r"\songcolumns{2}" + template % name
                    result = migration.migrate_text(source, at_letter=True)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    self.assertTrue(any("reference requires review" in d.message
                                        for d in result.diagnostics), result.diagnostics)
                    self.assertEqual((result.diagnostics[0].line, result.diagnostics[0].column), (2, 16))

    def test_removed_measure_opaque_regions_and_command_boundaries_are_preserved(self) -> None:
        payload = " ".join("\\" + name for name in REMOVED_MEASURE_NAMES)
        for opaque in ("% " + payload + "\n", "\\verb|" + payload + "|",
                       "\\url{https://test/" + payload + "}", "\\lilypond{" + payload + "}",
                       *("\\begin{" + env + "}" + payload + "\\end{" + env + "}"
                         for env in sorted(migration.VERBATIM_ENVS))):
            with self.subTest(opaque=opaque):
                result = migration.migrate_text(opaque + r"\songcolumns{2}")
                self.assertTrue(result.safe, result.diagnostics)
                self.assertEqual(result.text, opaque + r"\ulSongColumns{2}")
        for name in REMOVED_MEASURE_NAMES:
            for suffix, prefix, at_letter in (("Extra", "", False), ("@private", "", True),
                                              ("_private:", r"\ExplSyntaxOn", False)):
                with self.subTest(name=name, suffix=suffix):
                    source = prefix + "\\" + name + suffix
                    result = migration.migrate_text(source, at_letter=at_letter)
                    self.assertTrue(result.safe, result.diagnostics)
                    self.assertEqual(result.text, source)

    def test_supported_measure_policy_queries_and_local_switches_are_not_removed(self) -> None:
        source = (r"\ulShowMeasures{false}\begin{document}\measuresoff{\measureson}"
                  r"\ulLocalShow{measures}{true}\ifulShowMeasures A\else B\fi"
                  r"\let\alias\measureson\newcommand\later{\measuresoff}"
                  r"\AtBeginDocument{\measuresoff}\end{document}")
        result = migration.migrate_text(source)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, source)
        self.assertFalse(result.converted)

    def test_combined_gates_reject_all_naming_edits_with_original_diagnostics(self) -> None:
        for identity, measure in (("ifchorded", "measuresfalse"), ("ifulChorded", "ulMeasures")):
            with self.subTest(identity=identity, measure=measure):
                source = ("% heading\r\n" + r"\begin{chorus}\songcolumns{2}\showtagsfalse"
                          + "\\" + identity + " A\\else " + "\\" + measure + r"{false}\fi\end{chorus}")
                with patch.object(migration, "_apply_edit_plans", wraps=migration._apply_edit_plans) as apply:
                    result = migration.migrate_text(source)
                apply.assert_called_once()
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                self.assertEqual([(d.line, d.column) for d in result.diagnostics],
                                 [(2, source.index("\\" + name) - source.index("\n"))
                                  for name in ("showtagsfalse", identity, measure)])
                self.assertIn("display setter", result.diagnostics[0].message)
                self.assertIn("legacy variant identity", result.diagnostics[1].message)
                self.assertIn("removed measure API", result.diagnostics[2].message)
                counts = {"environment:chorus": 2, "chorus:repeat-start": 1,
                          "chorus:repeat-end": 1, "songcolumns": 1, "showtagsfalse": 1}
                if identity == "ifchorded":
                    counts.update(ifchorded=1, measuresfalse=1)
                self.assertEqual(result.converted, counts)

    def test_review_gates_cannot_be_disabled_with_naming_overrides(self) -> None:
        for name in LEGACY_IDENTITY_NAMES + REMOVED_MEASURE_NAMES:
            with self.subTest(name=name):
                source = "\\" + name
                result = migration.migrate_text(source, command_renames={}, boolean_setters={},
                                                name_argument_renames={})
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                self.assertFalse(result.converted)

    def test_both_gates_reject_whitespace_fragmented_named_references(self) -> None:
        for name in LEGACY_IDENTITY_NAMES + REMOVED_MEASURE_NAMES:
            for separator in (" ", "\t", "% split name\r\n"):
                split = len(name) // 2
                fragmented = name[:split] + separator + name[split:]
                for template in (r"\csname %s\endcsname", r"\ifcsname %s\endcsname\fi",
                                 r"\@nameuse{%s}", r"\@namedef{%s}{}", r"\@ifundefined{%s}{}{}"):
                    with self.subTest(name=name, separator=separator, template=template):
                        source = "heading\r\n" + r"\songcolumns{2}" + template % fragmented
                        result = migration.migrate_text(source, at_letter=True)
                        self.assertFalse(result.safe)
                        self.assertEqual(result.text, source)
                        self.assertIn("reference requires review", result.diagnostics[0].message)
                        self.assertEqual((result.diagnostics[0].line, result.diagnostics[0].column), (2, 16))
                        self.assertEqual(result.converted, {"songcolumns": 1})

    def test_combined_cli_modes_preserve_rejected_files_and_continue_safe_source_and_tags(self) -> None:
        for mode in ("--check", "--diff", "--write"):
            for name in REMOVED_MEASURE_NAMES:
                with self.subTest(mode=mode, name=name), TemporaryDirectory() as directory:
                    root = Path(directory)
                    safe, unsafe, identity = root / "safe.tex", root / "unsafe.sty", root / "identity.cls"
                    tags = root / "tags.can"
                    safe.write_bytes(b"\\songcolumns{2}\r\n")
                    source = ("% heading\r\n" + r"\songcolumns{2}" + "\\" + name + "\r\n").encode()
                    unsafe.write_bytes(source)
                    identity.write_bytes(b"\\ulSongColumns{2}\\ifulLyricOnly\r\n")
                    tags.write_bytes(b"Fire|flame\r\n1\r\n")
                    safe.chmod(0o640)
                    unsafe.chmod(0o600)
                    with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()) as errors:
                        self.assertEqual(migration.main([mode, "--tags-file", str(tags), directory]), 1)
                    self.assertIn(f"{unsafe}:2:16: removed measure API", errors.getvalue())
                    self.assertIn(f"{identity}:1:18: legacy variant identity", errors.getvalue())
                    self.assertIn("Scanned 4 files; 2 would change; 2 need review.", errors.getvalue())
                    self.assertIn("songcolumns: 2", errors.getvalue())
                    self.assertEqual("+++ " + str(safe) in output.getvalue(), mode == "--diff")
                    self.assertNotIn(str(unsafe), output.getvalue())
                    self.assertNotIn(str(identity), output.getvalue())
                    self.assertEqual(unsafe.read_bytes(), source)
                    self.assertEqual(identity.read_bytes(), b"\\ulSongColumns{2}\\ifulLyricOnly\r\n")
                    self.assertEqual(safe.read_bytes(), b"\\ulSongColumns{2}\r\n" if mode == "--write"
                                     else b"\\songcolumns{2}\r\n")
                    self.assertEqual(stat.S_IMODE(safe.stat().st_mode), 0o640)
                    self.assertEqual(stat.S_IMODE(unsafe.stat().st_mode), 0o600)
                    destination = tags.with_suffix(".txt") if mode == "--write" else tags
                    self.assertEqual(destination.read_bytes(), b"Fire|flame\r\n" if mode == "--write"
                                     else b"Fire|flame\r\n1\r\n")
                    self.assertEqual(set(root.iterdir()), {safe, unsafe, identity, destination})


class DisplayScopeReviewTests(unittest.TestCase):
    def test_full_display_inventory_covers_old_and_current_setters_only(self) -> None:
        from ulsbs.tools.naming_v2 import BOOLEAN_SETTERS

        self.assertEqual(migration.DISPLAY_SETTERS, set(DISPLAY_NAMES))
        legacy = {old: (new, value) for old, (new, value) in BOOLEAN_SETTERS.items() if new in DISPLAY_NAMES}
        self.assertEqual(len(legacy), 36)
        for old, (new, value) in legacy.items():
            for call, expected in (("\\" + old, f"\\{new}{{{value}}}"),
                                   (f"\\{new}{{{value}}}", f"\\{new}{{{value}}}")):
                with self.subTest(call=call):
                    preamble = r"\documentclass{third-party}" + call + r"\begin{document}x"
                    result = migration.migrate_text(preamble)
                    self.assertTrue(result.safe, result.diagnostics)
                    self.assertEqual(result.text, preamble.replace(call, expected))
                    source = r"\begin{document}\songcolumns{2}" + call
                    result = migration.migrate_text(source)
                    self.assertTrue(result.safe, result.diagnostics)
                    feature = migration.DISPLAY_FEATURES[new]
                    self.assertEqual(result.text, r"\begin{document}\ulSongColumns{2}"
                                     + f"\\ulLocalShow{{{feature}}}{{{value}}}")
        for name in DISPLAY_NAMES:
            for value in ("true", "false"):
                call = f"\\{name}{{{value}}}"
                result = migration.migrate_text(call)
                self.assertTrue(result.safe, result.diagnostics)
                result = migration.migrate_text(r"\AtBeginDocument{" + call + "}")
                self.assertFalse(result.safe)
                self.assertIn("display setter", result.diagnostics[0].message)

    def test_direct_literal_preamble_settings_preserve_both_generations(self) -> None:
        for old, new in ((r"\showtagsfalse", r"\ulShowTags{false}"),
                         (r"\showbeatstrue", r"\ulShowBeats{true}"),
                         (r"\ulShowChords{false}", r"\ulShowChords{false}"),
                         ("\\ulShowNotes{tr% literal comment\r\nue}", "\\ulShowNotes{tr% literal comment\r\nue}"),
                         (r"\ulShowMusicComments{true}", r"\ulShowMusicComments{true}"),
                         (r"\ulShowMeasures{false}", r"\ulShowMeasures{false}")):
            for prefix, suffix in (("", ""), (r"\documentclass{third-party}", r"\begin{document}x\end{document}"),
                                   ("{% direct preamble group\r\n", "}"),
                                   (r"\begingroup", r"\endgroup")):
                with self.subTest(old=old, prefix=prefix):
                    source = prefix + old + suffix
                    result = migration.migrate_text(source)
                    self.assertTrue(result.safe, result.diagnostics)
                    self.assertEqual(result.text, prefix + new + suffix)
                    second = migration.migrate_text(result.text)
                    self.assertTrue(second.safe, second.diagnostics)
                    self.assertEqual(second.text, result.text)
                    self.assertFalse(second.converted)

    def test_body_definitions_delays_references_and_ambiguous_contexts_require_review(self) -> None:
        for setter in (r"\showtagsfalse", r"\ulShowTags{false}", r"\ulShowMeasures{true}",
                       r"\ulShowChords{false}", r"\ulShowMusicComments{true}"):
            for template in (
                r"\begin{ulSongs}%s",
                r"\newcommand\later{%s}", r"\def\later{%s}", r"\edef\later{%s}",
                r"\NewDocumentCommand\later{m}{%s}", r"\newenvironment{later}{%s}{}",
                r"\AtBeginDocument{%s}", r"\AtEndOfClass{%s}", r"\AddToHook{begindocument}[mine]{%s}",
                r"\textcolor{red}{%s}", r"\href{https://test/}{%s}",
                r"\unknown{%s}", r"\unknown{}{}{}{%s}", r"\unknown[%s]", r"\unknown %s",
                r"\string %s", r"\detokenize{%s}", r"\let\alias=%s", r"\aftergroup %s",
                r"\iftrue %s\else x\fi", r"\iftrue x\else %s\fi",
                r"\iftrue\iffalse x\else %s\fi\fi", r"\iftrue %s", r"\else %s",
                r"\ulIfVariant{lyric}{%s}{}", r"\ulLocalShow{tags}{%s}",
            ):
                with self.subTest(setter=setter, template=template):
                    source = "heading\r\n" + r"\songcolumns{2}" + template % setter
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    diagnostic = next(d for d in result.diagnostics if "display setter" in d.message)
                    self.assertEqual((diagnostic.line, diagnostic.column),
                                     (2, source.index(setter) - source.index("\n")))
                    self.assertIn("preamble", diagnostic.message)
                    self.assertIn("scoped", diagnostic.message)
                    self.assertIn("songcolumns", result.converted)

    def test_nonliteral_current_setter_values_require_review_without_conversion(self) -> None:
        for value in ("", "TRUE", "0", "false true", r"\flag", "#1", "{false}", " false "):
            with self.subTest(value=value):
                source = r"\songcolumns{2}\ulShowTags{" + value + "}"
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                self.assertTrue(any("display setter" in d.message for d in result.diagnostics))
        for tail in ("", " false", "{false"):
            source = r"\ulShowNotes" + tail
            result = migration.migrate_text(source)
            self.assertFalse(result.safe)
            self.assertEqual(result.text, source)

    def test_numbered_writes_registers_and_delimited_groups_are_not_direct_settings(self) -> None:
        for call in (r"\showtagsfalse", r"\ulShowTags{false}"):
            for template in (r"\write16{%s}", r"\toks0={%s}", r"\mytokens={%s}",
                             r"\toks0=\bgroup %s\egroup", r"\write16\bgroup %s\egroup",
                             r"\unknown argument {%s}", r"\unknown*[{%s}]",
                             r"\unknown{%s", r"\unknown[%s"):
                with self.subTest(call=call, template=template):
                    source = r"\songcolumns{2}" + template % call
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    self.assertTrue(any("display setter" in d.message for d in result.diagnostics))

    def test_body_markers_and_raw_branches_are_not_executed_in_stored_or_literal_contexts(self) -> None:
        for prefix in (r"\newcommand\later{\begin{document}\iftrue}",
                       r"\AtBeginDocument{\beginsong{Later}\iffalse}",
                       r"\detokenize{\beginverse\iftrue}", r"\unknown{\document\iftrue}",
                       r"\string\begin{document}", r"\let\alias=\document",
                       r"\iftrue x\else y\fi", r"\ifulShowTags x\else y\fi",
                       r"\newif\ifcustom\ifcustom\LoadClass{third-party}\else\relax\fi",
                       r"\newif\ifcustom\newif\ifsecond\ifsecond x\fi"):
            with self.subTest(prefix=prefix):
                source = prefix + r"\ulShowTags{false}"
                result = migration.migrate_text(source)
                self.assertTrue(result.safe, result.diagnostics)
                self.assertEqual(result.text, source)
        for prefix in (r"\begin{document}\end{document}", r"\beginsong{T}\endsong",
                       r"\iftrue\begin{document}\fi", r"\fi", r"\or"):
            with self.subTest(prefix=prefix):
                source = prefix + r"\ulShowTags{false}"
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)

    def test_one_argument_setters_preserve_following_standalone_preamble_groups(self) -> None:
        for source, expected in (
            (r"\showtagsfalse{\shownotestrue}", r"\ulShowTags{false}{\ulShowNotes{true}}"),
            (r"\ulShowTags{false}{\ulShowNotes{true}}", r"\ulShowTags{false}{\ulShowNotes{true}}"),
            (r"\ulShowTags{false}{\shownotestrue}{\showbeatsfalse}",
             r"\ulShowTags{false}{\ulShowNotes{true}}{\ulShowBeats{false}}"),
        ):
            with self.subTest(source=source):
                result = migration.migrate_text(source)
                self.assertTrue(result.safe, result.diagnostics)
                self.assertEqual(result.text, expected)
                second = migration.migrate_text(expected)
                self.assertTrue(second.safe, second.diagnostics)
                self.assertEqual(second.text, expected)
                self.assertFalse(second.converted)
        for marker in (r"\beginverse", r"\begin{document}", r"\beginsong{Title}"):
            source = r"\ulShowTags{false}{" + marker + r"}\ulShowNotes{false}"
            result = migration.migrate_text(source)
            self.assertTrue(result.safe, result.diagnostics)
            self.assertEqual(result.text, source.replace(r"\ulShowNotes{false}", r"\ulLocalShow{notes}{false}"))

    def test_supported_zero_argument_local_switches_preserve_standalone_preamble_settings(self) -> None:
        for switch in ("chordson", "noteson", "notesoff", "beatson", "beatsoff", "measureson",
                       "measuresoff", "translationon", "translationoff"):
            with self.subTest(switch=switch):
                source = "\\" + switch + r"{\showtagsfalse}"
                expected = "\\" + switch + r"{\ulShowTags{false}}"
                first = migration.migrate_text(source)
                second = migration.migrate_text(expected)
                self.assertTrue(first.safe, first.diagnostics)
                self.assertTrue(second.safe, second.diagnostics)
                self.assertEqual(first.text, expected)
                self.assertEqual(second.text, expected)
                self.assertFalse(second.converted)

    def test_direct_references_and_definition_targets_cover_current_setters(self) -> None:
        for name in DISPLAY_NAMES:
            for template in (r"\let\alias=\%s", r"\let\%s=\alias", r"\futurelet\alias\relax\%s",
                             r"\meaning\%s", r"\noexpand\%s", r"\ifx\%s\other\fi",
                             r"\ifdefined\%s\fi", r"\afterassignment\%s", r"\expandafter\%s\other",
                             r"\def\%s#1{#1}", r"\renewcommand{\%s}[1]{#1}",
                             r"\NewDocumentCommand\%s{m}{#1}", r"\unexpanded{\%s}",
                             r"\expanded{\%s{true}}", r"\write{\%s{true}}"):
                with self.subTest(name=name, template=template):
                    source = r"\songcolumns{2}" + template % name
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    self.assertTrue(any("display setter \\" + name in d.message for d in result.diagnostics))

    def test_display_named_references_include_fragmented_names_and_mapping_overrides(self) -> None:
        from ulsbs.tools.naming_v2 import BOOLEAN_SETTERS

        names = DISPLAY_NAMES + tuple(old for old, (new, _) in BOOLEAN_SETTERS.items() if new in DISPLAY_NAMES)
        for name in names:
            for separator in ("", " ", "\t", "% split\r\n"):
                fragmented = name[:len(name) // 2] + separator + name[len(name) // 2:]
                for template in (r"\csname %s\endcsname", r"\ifcsname %s\endcsname\fi",
                                 r"\@nameuse{%s}", r"\@namedef{%s}{}", r"\@ifundefined{%s}{}{}"):
                    with self.subTest(name=name, separator=separator, template=template):
                        source = "heading\r\n" + r"\songcolumns{2}" + template % fragmented
                        result = migration.migrate_text(source, at_letter=True)
                        self.assertFalse(result.safe)
                        self.assertEqual(result.text, source)
                        self.assertIn("reference requires review", result.diagnostics[0].message)
                        self.assertEqual((result.diagnostics[0].line, result.diagnostics[0].column), (2, 16))
            source = "\\AtBeginDocument{\\" + name + "{false}}"
            result = migration.migrate_text(source, command_renames={}, boolean_setters={}, name_argument_renames={})
            self.assertFalse(result.safe)
            self.assertEqual(result.text, source)
            self.assertFalse(result.converted)

    def test_opaque_display_settings_and_command_boundaries_remain_unchanged(self) -> None:
        payload = " ".join("\\" + name + "{false}" for name in DISPLAY_NAMES) + r"\showtagsfalse"
        opaque = ("% " + payload + "\r\n"
                  + "".join("\\" + command + delimiter + payload + delimiter
                            for command in ("verb", "verb*", "Verb", "lstinline")
                            for delimiter in ("|", "!", "+"))
                  + "".join("\\begin{" + env + "}" + payload + "\\end{" + env + "}"
                            for env in sorted(migration.VERBATIM_ENVS))
                  + "".join("\\" + command + "{https://test/" + payload + "}"
                            for command in ("url", "nolinkurl", "path"))
                  + "\\lilypond{ " + payload + " }")
        result = migration.migrate_text(opaque + r"\showtagsfalse")
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, opaque + r"\ulShowTags{false}")
        for name in DISPLAY_NAMES + ("showtagsfalse",):
            for suffix, prefix, at_letter in (("Extra", "", False), ("@private", "", True),
                                              ("_private:", r"\ExplSyntaxOn", False)):
                with self.subTest(name=name, suffix=suffix):
                    source = r"\begin{document}" + prefix + "\\" + name + suffix
                    result = migration.migrate_text(source, at_letter=at_letter)
                    self.assertTrue(result.safe, result.diagnostics)
                    self.assertEqual(result.text, source)

    def test_non_display_booleans_and_current_display_commands_are_not_blanket_gated(self) -> None:
        from ulsbs.tools.naming_v2 import BOOLEAN_SETTERS

        for old, (new, value) in BOOLEAN_SETTERS.items():
            if new in DISPLAY_NAMES or old in LEGACY_IDENTITY_NAMES + REMOVED_MEASURE_NAMES:
                continue
            with self.subTest(old=old):
                source = "\\begin{document}\\AtBeginDocument{\\" + old + "}"
                result = migration.migrate_text(source)
                self.assertTrue(result.safe, result.diagnostics)
                self.assertEqual(result.text, r"\begin{document}\AtBeginDocument{" + f"\\{new}{{{value}}}" + "}")
        source = (r"\begin{document}\ulShowIndex{Titles}{titleidx}\ulShowChordsExtra{true}"
                  r"\notesoff{\noteson}\beatsoff{\beatson}\measuresoff{\measureson}"
                  r"\translationoff{\translationon}\chordson\ulLocalShow{chords}{false}")
        result = migration.migrate_text(source)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, source)


class BroadChordsOffReviewTests(unittest.TestCase):
    def test_combined_gates_keep_original_coordinates_counts_and_single_finalization(self) -> None:
        for display, identity, measure in ((r"\showbeatsfalse", r"\ifchorded", r"\measuresfalse"),
                                           (r"\ulShowBeats{false}", r"\ifulChorded", r"\ulMeasures{false}")):
            with self.subTest(display=display):
                source = ("% heading\r\n" + r"\showtagsfalse\begin{document}" + "\r\n"
                          + r"\begin{chorus}\songcolumns{2}" + display + r"\chordsoff"
                          + identity + " A\\else " + measure + r"\fi\end{chorus}")
                with patch.object(migration, "_apply_edit_plans", wraps=migration._apply_edit_plans) as apply:
                    result = migration.migrate_text(source)
                apply.assert_called_once()
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                self.assertEqual([(d.line, d.column) for d in result.diagnostics],
                                 [(3, source.index(call) - source.rfind("\n", 0, source.index(call)))
                                  for call in (display, r"\chordsoff", identity, measure)])
                self.assertIn("display setter", result.diagnostics[0].message)
                self.assertIn("legacy broad", result.diagnostics[1].message)
                self.assertIn("legacy variant identity", result.diagnostics[2].message)
                self.assertIn("removed measure API", result.diagnostics[3].message)
                counts = {"showtagsfalse": 1, "songcolumns": 1, "environment:chorus": 2,
                          "chorus:repeat-start": 1, "chorus:repeat-end": 1}
                if display.startswith(r"\show"):
                    counts.update(showbeatsfalse=1, ifchorded=1, measuresfalse=1)
                self.assertEqual(result.converted, counts)

    def test_cli_modes_reject_scope_and_broad_intent_but_continue_safe_preamble_and_tags(self) -> None:
        for mode in ("--check", "--diff", "--write"):
            for old in (True, False):
                with self.subTest(mode=mode, old=old), TemporaryDirectory() as directory:
                    root = Path(directory)
                    safe, scope, broad, tags = (root / name for name in ("safe.cls", "scope.tex", "broad.sty", "tags.can"))
                    safe_source = b"\\ProvidesClass{third-party}\r\n\\songcolumns{2}\\showtagsfalse\r\n"
                    safe.write_bytes(safe_source)
                    scope_source = (r"\AtBeginDocument{" + (r"\showtagsfalse" if old else r"\ulShowTags{false}") + "}").encode()
                    scope.write_bytes(b"\\songcolumns{2}\r\n" + scope_source + b"\r\n")
                    broad.write_bytes(b"\\songcolumns{2}\r\n\\chordsoff\r\n")
                    tags.write_bytes(b"Fire|flame\r\n1\r\n")
                    safe.chmod(0o640)
                    scope.chmod(0o600)
                    broad.chmod(0o644)
                    rejected = {path: path.read_bytes() for path in (scope, broad)}
                    with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()) as errors:
                        self.assertEqual(migration.main([mode, "--tags-file", str(tags), directory]), 1)
                    self.assertIn(f"{scope}:2:18: display setter", errors.getvalue())
                    self.assertIn(f"{broad}:2:1: legacy broad", errors.getvalue())
                    self.assertIn("Scanned 4 files; 2 would change; 2 need review.", errors.getvalue())
                    self.assertIn("songcolumns: 3", errors.getvalue())
                    self.assertEqual("+++ " + str(safe) in output.getvalue(), mode == "--diff")
                    for path, original in rejected.items():
                        self.assertNotIn(str(path), output.getvalue())
                        self.assertEqual(path.read_bytes(), original)
                    self.assertEqual(stat.S_IMODE(scope.stat().st_mode), 0o600)
                    self.assertEqual(stat.S_IMODE(broad.stat().st_mode), 0o644)
                    self.assertEqual(stat.S_IMODE(safe.stat().st_mode), 0o640)
                    expected = safe_source.replace(b"\\songcolumns", b"\\ulSongColumns").replace(
                        b"\\showtagsfalse", b"\\ulShowTags{false}") if mode == "--write" else safe_source
                    self.assertEqual(safe.read_bytes(), expected)
                    destination = tags.with_suffix(".txt") if mode == "--write" else tags
                    self.assertEqual(destination.read_bytes(), b"Fire|flame\r\n" if mode == "--write" else b"Fire|flame\r\n1\r\n")
                    self.assertEqual(set(root.iterdir()), {safe, scope, broad, destination})
                    if mode == "--write":
                        with redirect_stderr(StringIO()):
                            self.assertEqual(migration.main(["--check", str(safe), "--tags-file", str(destination)]), 0)

    def test_broad_chordsoff_requires_review_in_every_nonopaque_context(self) -> None:
        for template in (
            "%s", r"\begin{document}%s", r"\beginsong{Title}\beginverse %s",
            r"{%s\chordson}", r"\newcommand\later{%s}", r"\AtBeginDocument{%s}",
            r"\let\alias=%s", r"\let%s=\relax", r"\string%s", r"\detokenize{%s}",
            r"\ifx%s\other\fi", r"\aftergroup%s", r"\unknown{%s}", r"\unknown%s",
            r"\newcommand{%s}{}", r"\def%s{}", r"\ulIfVariant{lyric}{%s}{}",
            r"\notesoff\beatsoff\measuresoff%s", r"\ulLocalShow{chords}{false}%s",
        ):
            for prefix in (r"\songcolumns{2}", r"\ulSongColumns{2}"):
                with self.subTest(template=template, prefix=prefix):
                    source = "heading\r\n" + prefix + template % r"\chordsoff"
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    diagnostic = next(d for d in result.diagnostics if "broad" in d.message)
                    self.assertEqual((diagnostic.line, diagnostic.column),
                                     (2, source.index(r"\chordsoff") - source.index("\n")))
                    for phrase in ("chordsoff", "review", "pitches", "beats", "measures", "no automatic"):
                        self.assertIn(phrase, diagnostic.message)
        result = migration.migrate_text(r"\chordsoff", command_renames={}, boolean_setters={}, name_argument_renames={})
        self.assertFalse(result.safe)
        self.assertFalse(result.converted)

    def test_broad_chordsoff_named_references_and_fragmented_names_require_review(self) -> None:
        for name in ("chordsoff", "chords off", "chords% split\r\noff"):
            for template in (r"\csname %s\endcsname", r"\ifcsname %s\endcsname\fi",
                             r"\@nameuse{%s}", r"\@namedef{%s}{}", r"\@ifundefined{%s}{}{}"):
                with self.subTest(name=name, template=template):
                    source = r"\songcolumns{2}" + template % name
                    result = migration.migrate_text(source, at_letter=True)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    self.assertIn("reference requires review", result.diagnostics[0].message)

    def test_broad_chordsoff_opaque_regions_and_longer_names_stay_safe(self) -> None:
        payload = r"\chordsoff"
        opaque = ("% " + payload + "\r\n" + "\\verb|" + payload + "|"
                  + "\\url{https://test/" + payload + "}"
                  + "\\lilypond{" + payload + "}"
                  + "".join("\\begin{" + env + "}" + payload + "\\end{" + env + "}"
                            for env in sorted(migration.VERBATIM_ENVS)))
        result = migration.migrate_text(opaque + r"\songcolumns{2}")
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, opaque + r"\ulSongColumns{2}")
        for source, at_letter in ((r"\chordsoffExtra", False), (r"\chordsoff@private", True),
                                  (r"\ExplSyntaxOn\chordsoff_private:", False)):
            result = migration.migrate_text(source, at_letter=at_letter)
            self.assertTrue(result.safe, result.diagnostics)
            self.assertEqual(result.text, source)


class SourceAvailabilityReviewTests(unittest.TestCase):
    def test_safe_literal_availability_and_preamble_settings_keep_bytes_and_idempotence(self) -> None:
        from ulsbs.variants import available_variants

        for options in ("", "variants={default}", "variants={bassclef,default,charango,lyric}",
                        "subtitle={variants={nonsense}, A]B},variants={default,lyric}",
                        "variants % key\r\n= {def% joined\r\nault, lyric},subtitle={A, {B]C}, \\% ok}"):
            for prefix in (r"\songcolumns{2}", r"\ulSongColumns{2}"):
                with self.subTest(options=options, prefix=prefix):
                    source = (prefix + "\r\n\\documentclass[" + options + "]{ulsbs-songbook-independent}\r\n"
                              + r"\ulShowBeats{false}{\showtagsfalse}\begin{document}Text.\end{document}")
                    result = migration.migrate_text(source)
                    self.assertTrue(result.safe, result.diagnostics)
                    self.assertEqual(result.text, source.replace(r"\songcolumns", r"\ulSongColumns").replace(
                        r"\showtagsfalse", r"\ulShowTags{false}"))
                    self.assertEqual(available_variants(result.text), available_variants(source))
                    second = migration.migrate_text(result.text)
                    self.assertTrue(second.safe, second.diagnostics)
                    self.assertEqual(second.text, result.text)
                    self.assertFalse(second.converted)

    def test_invalid_availability_uses_shared_literal_validation_and_original_coordinates(self) -> None:
        for options in ("variants", "variants=", "variants=default", r"variants=\chosen",
                        "variants={}", "variants={lyric}", "variants={default,lyrics}",
                        "variants={default,LYRIC}", "variants={default,unknown}",
                        "variants={default,default}", "variants={default,}", "variants={default,,lyric}",
                        r"variants={default,\chosen}", "variants={{default,lyric}}",
                        "variants={default}extra", "variants={default}={lyric}",
                        "variants={default},variants={default}",
                        "variants={default},variants={default,lyric}"):
            for prefix in (r"\songcolumns{2}", r"\ulSongColumns{2}"):
                with self.subTest(options=options, prefix=prefix):
                    source = "% heading\r\n" + prefix + "\\documentclass[" + options + "]{ulsbs-songbook}"
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    diagnostic = next(d for d in result.diagnostics if "source availability" in d.message)
                    self.assertEqual((diagnostic.line, diagnostic.column), (2, len(prefix) + 1))
                    self.assertIn("literal", diagnostic.message)
                    self.assertIn("no automatic", diagnostic.message)

    def test_malformed_or_computed_class_invocations_require_review(self) -> None:
        for declaration in (r"\documentclass", r"\documentclass[variants={default]",
                            r"\documentclass[subtitle=oops}]{ulsbs-songbook}",
                            r"\documentclass{\chosen}", r"\documentclass{ulsbs-songbook",
                            r"\documentclass[\options]{ulsbs-songbook}",
                            r"\documentclass[vari ants={default}]{ulsbs-songbook}",
                            r"\documentclass[\key={default}]{ulsbs-songbook}",
                            r"\documentclass[{variants={default}}]{ulsbs-songbook}"):
            with self.subTest(declaration=declaration):
                source = r"\songcolumns{2}" + declaration
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                self.assertTrue(any("source availability" in d.message for d in result.diagnostics), result.diagnostics)

    def test_availability_requires_one_direct_top_level_preamble_class(self) -> None:
        declaration = r"\documentclass[variants={default,lyric}]{ulsbs-songbook}"
        for template in (r"{%s}", r"\begingroup%s\endgroup", r"\bgroup%s\egroup",
                         r"\iftrue%s\fi", r"\iffalse\else%s\fi", r"\fi%s", r"\else%s",
                         r"\newcommand\later{%s}", r"\def\later{%s}", r"\AtBeginDocument{%s}",
                         r"\AddToHook{class/after}{%s}", r"\unknown{a}{b}{c}{%s}",
                         r"\write16{%s}", r"\toks0={%s}", r"\unknown%s", r"\string%s",
                         r"\detokenize{%s}", r"\let\alias=%s", r"\newcommand{%s}{}",
                         r"\aftergroup%s", r"\expandafter%s\relax", r"\begin{document}%s",
                         r"\beginsong{Song}%s", r"\beginverse%s", r"\begin{anything}%s"):
            with self.subTest(template=template):
                source = r"\songcolumns{2}" + template % declaration
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                self.assertTrue(any("source availability" in d.message for d in result.diagnostics), result.diagnostics)
        for second in (declaration, r"\documentclass{article}"):
            source = declaration + "\n" + second
            result = migration.migrate_text(source)
            self.assertFalse(result.safe)
            self.assertEqual(result.text, source)
            self.assertTrue(any("multiple" in d.message for d in result.diagnostics), result.diagnostics)

    def test_inherited_and_forwarded_availability_cannot_declare_main_source_policy(self) -> None:
        for source in (r"\PassOptionsToClass{variants={default,lyric}}{ulsbs-songbook}",
                       r"\LoadClass[variants={default}]{ulsbs-songbook}",
                       r"\LoadClassWithOptions[variants={default}]{ulsbs-songbook}",
                       r"\ExecuteOptions{variants={default}}",
                       r"\PassOptionsToClass{\options}{ulsbs-songbook}"):
            with self.subTest(source=source):
                result = migration.migrate_text(r"\songcolumns{2}" + source)
                self.assertFalse(result.safe)
                self.assertTrue(any("source availability" in d.message for d in result.diagnostics), result.diagnostics)
        source = (r"\LoadClass{ulsbs-songbook}\PassOptionsToClass{oneside,subtitle={variants={x}}}{ulsbs-songbook}"
                  r"\documentclass[variants={nonsense},subtitle={a,b}]{article}\ulShowNotes{false}")
        result = migration.migrate_text(source)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, source)

    def test_availability_named_references_and_mapping_overrides_require_review(self) -> None:
        for name in ("documentclass", "document class", "document% split\r\nclass",
                     "LoadClass", "Load Class", "LoadClassWithOptions", "PassOptionsToClass", "ExecuteOptions"):
            for template in (r"\csname %s\endcsname", r"\ifcsname %s\endcsname\fi",
                             r"\@nameuse{%s}", r"\@namedef{%s}{}", r"\@ifundefined{%s}{}{}"):
                with self.subTest(name=name, template=template):
                    source = template % name
                    result = migration.migrate_text(source, at_letter=True, command_renames={},
                                                    boolean_setters={}, name_argument_renames={})
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)

    def test_unbraced_data_prefixes_are_not_provably_direct_class_invocations(self) -> None:
        declaration = r"\documentclass[variants={default,lyric}]{ulsbs-songbook}"
        for prefix in (r"\write16", r"\immediate\write16", r"\unknown data ",
                       r"\toks0=", "plain data ", "}", r"\egroup"):
            with self.subTest(prefix=prefix):
                source = r"\songcolumns{2}" + prefix + declaration
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                self.assertTrue(any("source availability" in d.message for d in result.diagnostics), result.diagnostics)

    def test_standard_current_option_forwarding_is_not_an_availability_declaration(self) -> None:
        for options in (r"\CurrentOption", " % value\r\n\\CurrentOption % tail\r\n"):
            source = (r"\DeclareOption*{\PassOptionsToClass{" + options + "}{ulsbs-songbook-third-party}}"
                      + r"\LoadClass{ulsbs-songbook}\showtagsfalse")
            result = migration.migrate_text(source)
            self.assertTrue(result.safe, result.diagnostics)
            self.assertEqual(result.text, source.replace(r"\showtagsfalse", r"\ulShowTags{false}"))
        for source in (r"\PassOptionsToClass{\CurrentOption}{ulsbs-songbook}",
                       r"\DeclareOption*{\PassOptionsToClass{variants={\CurrentOption}}{ulsbs-songbook}}",
                       r"\DeclareOption*{\PassOptionsToClass{\computed}{ulsbs-songbook}}",
                       r"\DeclareOption*{\unknown\PassOptionsToClass{\CurrentOption}{ulsbs-songbook}}",
                       "\\PassOptionsToClass{vari% = ignored\r\nants={default}}{ulsbs-songbook}"):
            with self.subTest(source=source):
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)

    def test_availability_opaque_comments_literals_and_unrelated_data_remain_untouched(self) -> None:
        payload = r"\documentclass[variants={unknown}]{ulsbs-songbook}"
        opaque = ("% " + payload + "\r\n\\verb|" + payload + "|\\url{https://test/" + payload + "}"
                  + "\\lilypond{" + payload + "}"
                  + "".join("\\begin{" + env + "}" + payload + "\\end{" + env + "}"
                            for env in sorted(migration.VERBATIM_ENVS)))
        source = (opaque + r"\documentclass[subtitle={variants={unknown}},variants={default,lyric}]{ulsbs-songbook}"
                  + r"\documentclassExtra \makeatletter\documentclass@private\makeatother")
        result = migration.migrate_text(source)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, source)

    def test_legacy_markers_always_require_review_without_inferring_availability(self) -> None:
        for value in ("none", "bassclef, charango", "unknown", "", "none,charango",
                      "charango,charango", r"\chosen", "DEFAULT", "lyric", "{bassclef}"):
            for prefix in (r"\songcolumns{2}", r"\ulSongColumns{2}"):
                for comment in ("% ", "%%%", "% prose ", ""):
                    with self.subTest(value=value, prefix=prefix, comment=comment):
                        source = (prefix + "\r\n  " + comment + "ULSBS-EXTRA-VARIANTS: " + value
                                  + " % tail\r\n\\documentclass{ulsbs-songbook-independent}")
                        result = migration.migrate_text(source)
                        self.assertFalse(result.safe)
                        self.assertEqual(result.text, source)
                        diagnostic = next(d for d in result.diagnostics if "legacy availability marker" in d.message)
                        self.assertEqual((diagnostic.line, diagnostic.column), (2, 3 + len(comment)))
                        for phrase in ("ULSBS-EXTRA-VARIANTS", "none", "lyric", "review", "no automatic"):
                            self.assertIn(phrase, diagnostic.message)
                        self.assertEqual(result.converted, {"songcolumns": 1} if "\\songcolumns" in prefix else {})

    def test_repeated_conflicting_and_malformed_markers_each_reject(self) -> None:
        for first, second in (("none", "none"), ("none", "charango"), ("charango", "bassclef")):
            source = ("% ULSBS-EXTRA-VARIANTS: " + first + "\n"
                      + "% ULSBS-EXTRA-VARIANTS: " + second + "\n"
                      + r"\documentclass[variants={default,lyric,charango}]{ulsbs-songbook}")
            result = migration.migrate_text(source)
            self.assertEqual(result.text, source)
            self.assertEqual([(d.line, d.column) for d in result.diagnostics], [(1, 3), (2, 3)])
        source = "% ULSBS-EXTRA-VARIANTS = none\n% ULSBS-EXTRA-VARIANTS"
        self.assertEqual(len(migration.migrate_text(source).diagnostics), 2)
        result = migration.migrate_text(source, command_renames={}, boolean_setters={}, name_argument_renames={})
        self.assertFalse(result.safe)

    def test_marker_opaque_regions_escape_parity_and_boundaries(self) -> None:
        payload = "ULSBS-EXTRA-VARIANTS: none"
        opaque = ("\\verb|% " + payload + "|\\url{https://test/%" + payload + "}"
                  + "\\lilypond{ % " + payload + "\n c }"
                  + "".join("\\begin{" + env + "}% " + payload + "\n\\end{" + env + "}"
                            for env in sorted(migration.VERBATIM_ENVS)))
        source = opaque + "\n% NOT-ULSBS-EXTRA-VARIANTS: none\n% ULSBS-EXTRA-VARIANTS-EXAMPLE: none\n"
        result = migration.migrate_text(source + r"\songcolumns{2}")
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, source + r"\ulSongColumns{2}")
        for prefix in (r"\% ", r"\\% ", "% "):
            source = prefix + payload
            result = migration.migrate_text(source)
            self.assertFalse(result.safe)
            self.assertEqual(result.diagnostics[0].column, len(prefix) + 1)

    def test_availability_combines_all_review_gates_against_one_original_source(self) -> None:
        for old in (True, False):
            with self.subTest(old=old):
                display = r"\showbeatsfalse" if old else r"\ulShowBeats{false}"
                identity = r"\ifchorded" if old else r"\ifulChorded"
                measure = r"\measuresfalse" if old else r"\ulMeasures{false}"
                source = ("% heading\r\n" + r"\songcolumns{2}\documentclass[variants={default,unknown}]{ulsbs-songbook}"
                          + "\r\n% ULSBS-EXTRA-VARIANTS: none\r\n"
                          + r"\showtagsfalse\begin{document}\begin{chorus}" + display
                          + r"\chordsoff" + identity + " A\\else " + measure + r"\fi\end{chorus}")
                with patch.object(migration, "_apply_edit_plans", wraps=migration._apply_edit_plans) as apply:
                    result = migration.migrate_text(source)
                apply.assert_called_once()
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                for text, message in (("ULSBS-EXTRA-VARIANTS", "legacy availability marker"),
                                      (r"\documentclass", "source availability"), (display, "display setter"),
                                      (r"\chordsoff", "legacy broad"), (identity, "legacy variant identity"),
                                      (measure, "removed measure API")):
                    diagnostic = next(d for d in result.diagnostics if message in d.message)
                    pos = source.index(text)
                    self.assertEqual((diagnostic.line, diagnostic.column),
                                     (source.count("\n", 0, pos) + 1, pos - source.rfind("\n", 0, pos)))
                self.assertEqual(len(result.diagnostics), 6)
                counts = {"songcolumns": 1, "showtagsfalse": 1, "environment:chorus": 2,
                          "chorus:repeat-start": 1, "chorus:repeat-end": 1}
                if old:
                    counts.update(showbeatsfalse=1, ifchorded=1, measuresfalse=1)
                self.assertEqual(result.converted, counts)

    def test_availability_cli_modes_reject_whole_files_and_continue_safe_sources_and_tags(self) -> None:
        for mode in ("--check", "--diff", "--write"):
            for prefix in (b"\\songcolumns{2}", b"\\ulSongColumns{2}"):
                with self.subTest(mode=mode, prefix=prefix), TemporaryDirectory() as directory:
                    root = Path(directory)
                    safe, marker, invalid, structural, tags = (root / name for name in
                                                              ("safe.tex", "marker.tex", "invalid.tex", "structural.tex", "tags.can"))
                    safe_source = (b"\\documentclass[variants={default,lyric},subtitle={Independent, book}]{ulsbs-songbook-third-party}\r\n"
                                   b"\\showtagsfalse\\songcolumns{2}\r\n")
                    safe.write_bytes(safe_source)
                    marker.write_bytes(prefix + b"\r\n%% ULSBS-EXTRA-VARIANTS: none\r\n"
                                       b"\\documentclass[variants={default,lyric}]{ulsbs-songbook}\r\n")
                    invalid.write_bytes(prefix + b"\r\n\\documentclass[variants={default},variants={default}]{ulsbs-songbook}\r\n")
                    structural.write_bytes(prefix + b"\r\n\\iftrue\\documentclass[variants={default}]{ulsbs-songbook}\\fi\r\n")
                    tags.write_bytes(b"Fire|flame\r\n1\r\n")
                    safe.chmod(0o640)
                    rejected = {path: path.read_bytes() for path in (marker, invalid, structural)}
                    for path in rejected:
                        path.chmod(0o600)
                    with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()) as errors:
                        self.assertEqual(migration.main([mode, "--tags-file", str(tags), directory]), 1)
                    self.assertIn(f"{marker}:2:4: legacy availability marker", errors.getvalue())
                    self.assertIn(f"{invalid}:2:1: source availability", errors.getvalue())
                    self.assertIn(f"{structural}:2:8: source availability", errors.getvalue())
                    self.assertIn("Scanned 5 files; 2 would change; 3 need review.", errors.getvalue())
                    self.assertEqual("+++ " + str(safe) in output.getvalue(), mode == "--diff")
                    for path, original in rejected.items():
                        self.assertNotIn(str(path), output.getvalue())
                        self.assertEqual(path.read_bytes(), original)
                        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                    expected = safe_source.replace(b"\\songcolumns", b"\\ulSongColumns").replace(
                        b"\\showtagsfalse", b"\\ulShowTags{false}") if mode == "--write" else safe_source
                    self.assertEqual(safe.read_bytes(), expected)
                    self.assertEqual(stat.S_IMODE(safe.stat().st_mode), 0o640)
                    destination = tags.with_suffix(".txt") if mode == "--write" else tags
                    self.assertEqual(destination.read_bytes(), b"Fire|flame\r\n" if mode == "--write" else b"Fire|flame\r\n1\r\n")
                    self.assertEqual(set(root.iterdir()), {safe, marker, invalid, structural, destination})
                    if mode == "--write":
                        with redirect_stderr(StringIO()):
                            self.assertEqual(migration.main(["--check", str(safe), "--tags-file", str(destination)]), 0)


class SemanticSourceMigrationTests(unittest.TestCase):
    def test_class_date_storage_cannot_establish_body_scope(self) -> None:
        for command, name in (("documentclass", "article"), ("LoadClass", "book"),
                              ("LoadClassWithOptions", "book")):
            for leading in ("", "[oneside]") if command != "LoadClassWithOptions" else ("",):
                for marker in (r"\begin{document}", r"\beginverse", r"\beginsong{Title}"):
                    with self.subTest(command=command, leading=leading, marker=marker):
                        source = ("\\" + command + leading + "{" + name + "}[2020/01/01"
                                  + marker + r"]\relax\ulShowTags{false}")
                        result = migration.migrate_text(source)
                        self.assertTrue(result.safe, result.diagnostics)
                        self.assertEqual(result.text, source)
                        self.assertFalse(result.converted)
                        # A stored marker does not make a removed measure setter local.
                        rejected = source + r"\measuresfalse"
                        result = migration.migrate_text(rejected)
                        self.assertFalse(result.safe)
                        self.assertEqual(result.text, rejected)
                        self.assertNotIn("scope:measuresfalse", result.converted)

    def test_literal_class_dates_keep_real_body_and_availability_conversions(self) -> None:
        for command in ("documentclass", "LoadClass", "LoadClassWithOptions"):
            source = ("\\" + command + "{ulsbs-songbook}[2020/01/01]"
                      + r"\relax\begin{document}\showtagsfalse")
            result = migration.migrate_text(source)
            self.assertTrue(result.safe, result.diagnostics)
            self.assertEqual(result.text, source.replace(r"\showtagsfalse", r"\ulLocalShow{tags}{false}"))
            self.assertFalse(migration.migrate_text(result.text).converted)
        source = ("% ULSBS-EXTRA-VARIANTS: none\r\n"
                  + r"\documentclass{ulsbs-songbook}[2020/01/01]\ulShowTags{false}")
        result = migration.migrate_text(source)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertIn(r"\documentclass[variants={default,lyric}]{ulsbs-songbook}[2020/01/01]", result.text)

    def test_expanding_class_and_forwarding_arguments_do_not_prove_later_execution(self) -> None:
        for invocation in (r"\documentclass[subtitle={Book \number123}]{ulsbs-songbook}",
                           r"\documentclass{article}[\requesteddate]",
                           r"\LoadClass[subtitle={\titledata}]{ulsbs-songbook}",
                           r"\LoadClass{\chosenclass}", r"\LoadClassWithOptions{\chosenclass}",
                           r"\PassOptionsToClass{subtitle={\titledata}}{ulsbs-songbook}",
                           r"\PassOptionsToClass{oneside}{\chosenclass}"):
            for call in (r"\ulShowTags{false}", r"\showtagsfalse", r"\measuresfalse",
                         r"\ifbassclefbook\newpage\else\clearpage\fi"):
                with self.subTest(invocation=invocation, call=call):
                    source = invocation + r"\relax\begin{document}\songcolumns{2}" + call
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe, result.text)
                    self.assertEqual(result.text, source)
                    self.assertFalse(any(label.startswith(("scope:", "identity:")) for label in result.converted))
        for invocation in (r"\documentclass[variants={default},subtitle={Book \number123}]{ulsbs-songbook}",
                           r"\PassOptionsToClass{subtitle={Book \number123}}{ulsbs-songbook}"):
            source = invocation + r"\relax\ulShowTags{false}"
            result = migration.migrate_text(source)
            self.assertTrue(result.safe, result.diagnostics)
            self.assertEqual(result.text, source)
            self.assertFalse(result.converted)

    def test_executeoptions_dispatch_is_not_inert_storage_or_known_preamble_phase(self) -> None:
        for prefix in ("", r"\DeclareOption{body}{\begin{document}}",
                       r"\makeatletter\def\ds@body{\begin{document}}\makeatother"):
            for call in (r"\showtagsfalse", r"\measuresfalse", r"\ifbassclefbook\newpage\fi"):
                for body in ("", r"\begin{document}"):
                    with self.subTest(prefix=prefix, call=call, body=body):
                        source = prefix + r"\ExecuteOptions{body}\relax" + body + call
                        result = migration.migrate_text(source)
                        self.assertFalse(result.safe, result.text)
                        self.assertEqual(result.text, source)
                        self.assertFalse(any(label.startswith(("scope:", "identity:")) for label in result.converted))
        # No speculative rewrite/rejection of an already-current preamble setting.
        source = r"\ExecuteOptions{oneside}\relax\ulShowTags{false}"
        result = migration.migrate_text(source)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, source)

    def test_class_argument_limits_keep_literal_forwarding_and_current_preamble(self) -> None:
        for invocation in (r"\PassOptionsToClass{oneside,subtitle={A, B}}{ulsbs-songbook}",
                           r"\LoadClass[oneside]{ulsbs-songbook}",
                           r"\LoadClassWithOptions{ulsbs-songbook}"):
            source = invocation + r"\relax\showtagsfalse\begin{document}\showbeatsfalse"
            result = migration.migrate_text(source)
            self.assertTrue(result.safe, result.diagnostics)
            self.assertEqual(result.text, invocation + r"\relax\ulShowTags{false}"
                             r"\begin{document}\ulLocalShow{beats}{false}")
        for invocation in (r"\documentclass[subtitle={Book \number123}]{ulsbs-songbook}",
                           r"\LoadClass[subtitle={\titledata}]{ulsbs-songbook}",
                           r"\PassOptionsToClass{subtitle={\titledata}}{ulsbs-songbook}"):
            source = invocation + r"\relax\showtagsfalse"
            result = migration.migrate_text(source)
            self.assertTrue(result.safe, result.diagnostics)
            self.assertEqual(result.text, invocation + r"\relax\ulShowTags{false}")
        for suffix in (r"[2020/01/01\makeatletter]", "[2020/01/01"):
            source = r"\documentclass{article}" + suffix + r"\relax\showtagsfalse"
            result = migration.migrate_text(source)
            self.assertFalse(result.safe)
            self.assertEqual(result.text, source)
        source = r"\LoadClassWithOptions[oneside]{ulsbs-songbook}"
        self.assertFalse(migration.migrate_text(source).safe)

    @unittest.skipUnless(shutil.which("lualatex"), "LuaLaTeX not installed")
    def test_real_kernel_class_dates_preserve_book_permission_and_option_dispatch(self) -> None:
        assets = Path(__file__).resolve().parents[1] / "src/ulsbs/assets/tex"
        bootstrap = (r"\RequirePackage{etoolbox,xstring}\def\languagename{english}"
                     r"\makeatletter\input{ulsbs-init.code.tex}"
                     r"\input{ulsbs-utilities.code.tex}\input{ulsbs-book-defaults.code.tex}\makeatother")
        # Isolated real-kernel/real-owner probes, not a claim about full package
        # operation under another engine or an emulation of option processing.
        with TemporaryDirectory() as directory:
            root = Path(directory)
            env = dict(os.environ, TEXINPUTS=str(assets) + "//" + os.pathsep,
                       TEXMFVAR=str(root / "cache"), TEXMFCACHE=str(root / "cache"))

            def compile_source(source: str) -> str:
                (root / "probe.tex").write_text(source, encoding="utf-8")
                result = subprocess.run(
                    ["lualatex", "-halt-on-error", "-interaction=nonstopmode", "probe.tex"],
                    cwd=root, env=env, capture_output=True, text=True, timeout=60, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            for command, name in (("documentclass", "article"), ("LoadClass", "book"),
                                  ("LoadClassWithOptions", "book")):
                fragment = ("\\" + command + "{" + name + "}[2020/01/01"
                            + r"\begin{document}]\relax\ulShowTags{false}")
                migrated = migration.migrate_text(fragment)
                self.assertTrue(migrated.safe, migrated.diagnostics)
                for source in (fragment, migrated.text):
                    with self.subTest(command=command, source=source):
                        source = source.replace(r"\relax", bootstrap + r"\relax", 1)
                        if command != "documentclass":
                            (root / "independent.cls").write_text(
                                r"\ProvidesClass{independent}" + source, encoding="utf-8")
                            source = r"\documentclass{independent}"
                        output = compile_source(source + r"\begin{document}\ulLocalShow{tags}{true}"
                                                r"\ifulShowTags\typeout{ARGUMENT-TAGS=ON}"
                                                r"\else\typeout{ARGUMENT-TAGS=OFF}\fi x\end{document}")
                        self.assertIn("ARGUMENT-TAGS=OFF", output)
                        self.assertNotIn("ARGUMENT-TAGS=ON", output)
            # The handler is explicit source, not hypothetical external class code.
            fragment = r"\DeclareOption{body}{\begin{document}}\ExecuteOptions{body}\showtagsfalse"
            self.assertFalse(migration.migrate_text(fragment).safe)
            output = compile_source(r"\documentclass{article}" + bootstrap + r"\newif\ifshowtags"
                                    + fragment + r"\typeout{ARGUMENT-HANDLER=EXECUTED}x\end{document}")
            self.assertIn("ARGUMENT-HANDLER=EXECUTED", output)
            # Ordinary named handlers execute; forwarding itself only stores them.
            output = compile_source(r"\documentclass{article}"
                                    r"\DeclareOption{audit}{\typeout{ARGUMENT-NAMED=EXECUTED}}"
                                    r"\DeclareOption*{\typeout{ARGUMENT-CATCHALL=EXECUTED}}"
                                    r"\PassOptionsToClass{audit}{book}\typeout{ARGUMENT-FORWARD=STORED}"
                                    r"\ExecuteOptions{audit}\ExecuteOptions{unknown}"
                                    r"\begin{document}x\end{document}")
            self.assertLess(output.index("ARGUMENT-FORWARD=STORED"), output.index("ARGUMENT-NAMED=EXECUTED"))
            self.assertEqual(output.count("ARGUMENT-NAMED=EXECUTED"), 1)
            self.assertNotIn("ARGUMENT-CATCHALL=EXECUTED", output)
        from test_tex_integration import compile_fixture

        source = (r"\documentclass[variants={default},subtitle={Book \number123}]{ulsbs-songbook}"
                  r"\ulShowTags{false}\begin{document}Probe.\end{document}")
        current = migration.migrate_text(source)
        self.assertTrue(current.safe, current.diagnostics)
        self.assertEqual(current.text, source)
        compile_fixture("source-effects", multikey=None, files={"source-effects.tex": current.text.encode()})

    def test_argument_boundary_cli_rejection_is_one_original_coordinate_transaction(self) -> None:
        for mode in ("--check", "--diff", "--write"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                root = Path(directory)
                safe, rejected, current, config = (root / name for name in (
                    "safe.tex", "rejected.tex", "current.tex", "config.toml"))
                source = (b"% ULSBS-EXTRA-VARIANTS: none\r\n"
                          b"\\documentclass{ulsbs-songbook}[2020/01/01]\\songcolumns{2}\r\n"
                          b"\\ExecuteOptions{body}\\relax\\showtagsfalse")
                rejected.write_bytes(source)
                safe.write_bytes(b"\\begin{document}\\showtagsfalse\r\n")
                current.write_bytes(b"\\documentclass{article}[2020/01/01\\begin{document}]"
                                    b"\\relax\\ulShowTags{false}\r\n")
                config.write_bytes(b'variants = ["default", "lyric"]\r\n')
                for path in root.iterdir():
                    path.chmod(0o640)
                protected = {p: (p.read_bytes(), p.stat()) for p in (rejected, current, config)}
                with patch.object(migration, "_apply_edit_plans", wraps=migration._apply_edit_plans) as apply:
                    with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()) as errors:
                        self.assertEqual(migration.main([mode, directory, "--config-file", str(config)]), 1)
                self.assertEqual(apply.call_count, 3)
                self.assertIn("Scanned 4 files; 1 would change; 1 need review.", errors.getvalue())
                self.assertIn(f"{rejected}:3:28: display setter", errors.getvalue())
                self.assertIn("availability:declaration: 1", errors.getvalue())
                self.assertIn("songcolumns: 1", errors.getvalue())
                for path, (data, before) in protected.items():
                    self.assertNotIn("+++ " + str(path), output.getvalue())
                    self.assertEqual(path.read_bytes(), data)
                    after = path.stat()
                    self.assertEqual((after.st_ino, after.st_mtime_ns, after.st_mode),
                                     (before.st_ino, before.st_mtime_ns, before.st_mode))
                self.assertEqual("+++ " + str(safe) in output.getvalue(), mode == "--diff")
                self.assertEqual(safe.read_bytes(), b"\\begin{document}\\ulLocalShow{tags}{false}\r\n"
                                 if mode == "--write" else b"\\begin{document}\\showtagsfalse\r\n")
                self.assertEqual(set(root.iterdir()), {safe, rejected, current, config})

    def test_expanding_column_values_cannot_prove_later_semantic_execution(self) -> None:
        for columns in ("songcolumns", "ulSongColumns"):
            for value in (r'\directlua{token.set_macro("ulIfVariant","")}1', r"\computed"):
                for call in (r"\ulShowTags{false}", r"\showtagsfalse", r"\measuresfalse",
                             r"\ifbassclefbook\newpage\else\clearpage\fi"):
                    with self.subTest(columns=columns, value=value, call=call):
                        source = r"\begin{document}" + "\\" + columns + "{" + value + "}" + call
                        result = migration.migrate_text(source)
                        self.assertFalse(result.safe, result.text)
                        self.assertEqual(result.text, source)
                        self.assertFalse(any(label.startswith(("scope:", "identity:"))
                                             for label in result.converted))
            # This proof restriction must not rewrite valid current preamble
            # expressions or invent a diagnostic without any semantic proposal.
            current = r"\ulSongColumns{\computed}\ulShowTags{false}"
            result = migration.migrate_text(current)
            self.assertTrue(result.safe, result.diagnostics)
            self.assertEqual(result.text, current)

    def test_rebound_primitive_definition_parsers_cannot_skip_consumed_tokens(self) -> None:
        for primitive in ("def", "gdef", "edef", "xdef"):
            for call in (r"\ulShowTags{false}", r"\showtagsfalse", r"\measuresfalse",
                         r"\ifbassclefbook\newpage\fi"):
                with self.subTest(primitive=primitive, call=call):
                    source = (r"\begin{document}\def\eat#1#2#3{}\let" + "\\" + primitive
                              + r"\eat" + "\\" + primitive + r"\stored{}" + call)
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe, result.text)
                    self.assertEqual(result.text, source)
                    self.assertFalse(any(label.startswith(("scope:", "identity:"))
                                         for label in result.converted))

    def test_unrelated_definitions_keep_proved_bodies_and_current_preamble_bytes(self) -> None:
        for definition in (r"\newif\ifindependent", r"\def\Independent#1{#1}",
                           r"\newenvironment{independent}[1]{}{}"):
            with self.subTest(definition=definition):
                preamble = (r"\documentclass[variants={default,lyric},subtitle={A, B}]"
                            r"{ulsbs-songbook-independent}" + definition + r"\ulShowTags{false}")
                current = migration.migrate_text(preamble)
                self.assertTrue(current.safe, current.diagnostics)
                self.assertEqual(current.text, preamble)
                self.assertFalse(current.converted)
                result = migration.migrate_text(preamble + r"\begin{document}\showtagsfalse")
                self.assertTrue(result.safe, result.diagnostics)
                self.assertEqual(result.text, preamble + r"\begin{document}\ulLocalShow{tags}{false}")

    def test_rebound_identity_destination_is_not_inserted_as_a_runtime_helper(self) -> None:
        for definition in (r"\def\ulIfVariant#1#2#3{#2}", r"\let\ulIfVariant\unknown",
                           r"\newenvironment{ulIfVariant}[3]{}{}"):
            source = definition + r"\begin{document}\ifbassclefbook\newpage\else\clearpage\fi"
            with self.subTest(definition=definition):
                result = migration.migrate_text(source)
                self.assertFalse(result.safe, result.text)
                self.assertEqual(result.text, source)
                self.assertFalse(any(label.startswith("identity:") for label in result.converted))

    def test_newif_rebindings_invalidate_assumed_predicates_and_generated_setters(self) -> None:
        for predicate in ("iftrue", "ifulShowTags", "ifshowtags"):
            for call in (r"\ulShowTags{false}", r"\showtagsfalse", r"\measuresfalse",
                         r"\ifbassclefbook\newpage\fi"):
                with self.subTest(predicate=predicate, call=call):
                    source = "\\newif\\" + predicate + r"\begin{document}" + call
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe, result.text)
                    self.assertEqual(result.text, source)
                    self.assertFalse(any(label.startswith(("scope:", "identity:"))
                                         for label in result.converted))

    def test_environment_generated_controls_cannot_change_execution_assumptions(self) -> None:
        for definition in ("newenvironment", "renewenvironment", "provideenvironment"):
            for name, options, call in (("beginverse", "[1]", r"\beginverse"),
                                         ("beginsong", "[2]", r"\beginsong{Title}"),
                                         ("newpage", "[1]", r"\ifbassclefbook\newpage\fi"),
                                         ("rep", "", r"\endrep")):
                for setter in (r"\ulShowTags{false}", r"\showtagsfalse", r"\measuresfalse"):
                    with self.subTest(definition=definition, name=name, setter=setter):
                        source = ("\\" + definition + "{" + name + "}" + options + "{}{}"
                                  + r"\begin{document}" + call + setter)
                        result = migration.migrate_text(source)
                        self.assertFalse(result.safe, result.text)
                        self.assertEqual(result.text, source)
                        self.assertFalse(any(label.startswith(("scope:", "identity:"))
                                             for label in result.converted))
        source = ("% ULSBS-EXTRA-VARIANTS: none\n"
                  + r"\renewenvironment{documentclass}[1]{}{}\documentclass{ulsbs-songbook}")
        result = migration.migrate_text(source)
        self.assertFalse(result.safe, result.text)
        self.assertEqual(result.text, source)
        self.assertNotIn("availability:declaration", result.converted)

    def test_rebound_predicates_cannot_prove_execution_after_consumed_delimiters(self) -> None:
        for predicate in ("iftrue", "iffalse", "ifulShowTags", "ifshowtags"):
            for definition in ("\\def\\" + predicate + r"#1\fi#2{}",
                               "\\def\\eat#1#2{}\\let\\" + predicate + r"\eat"):
                for setter in (r"\ulShowTags{false}", r"\showtagsfalse", r"\measuresfalse",
                               r"\ifbassclefbook\newpage\fi"):
                    with self.subTest(predicate=predicate, definition=definition, setter=setter):
                        source = (definition + "\\begin{document}\\" + predicate + r"\fi" + setter)
                        result = migration.migrate_text(source)
                        self.assertFalse(result.safe, result.text)
                        self.assertEqual(result.text, source)
                        self.assertFalse(any(label.startswith(("scope:", "identity:"))
                                             for label in result.converted))
            source = ("% ULSBS-EXTRA-VARIANTS: none\n\\def\\" + predicate + "#1\\fi#2{}\\"
                      + predicate + r"\fi\documentclass{ulsbs-songbook}")
            result = migration.migrate_text(source)
            self.assertFalse(result.safe, result.text)
            self.assertEqual(result.text, source)
            self.assertNotIn("availability:declaration", result.converted)

    def test_source_redefinitions_cannot_change_assumed_execution_arities(self) -> None:
        for mutation in (r"\renewcommand\beginverse[1]{}", r"\def\beginverse#1{}",
                         r"\let\beginverse\unknown", r"\renewcommand\ulSongColumns[2]{}",
                         r"\def\newpage#1{}", r"\let\newpage\unknown",
                         r"\let\newcommand\unknown", r"\newenvironment{verse}[1]{}{}"):
            for tail in (r"\beginverse\ulShowTags{false}",
                         r"\beginverse\measuresfalse",
                         r"\beginverse\ulSongColumns{2}\ulShowTags{false}",
                         r"\beginverse\ifbassclefbook\newpage\fi"):
                with self.subTest(mutation=mutation, tail=tail):
                    source = r"\begin{document}" + mutation + tail
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    self.assertFalse(any(label.startswith(("scope:", "identity:")) for label in result.converted))
        source = ("% ULSBS-EXTRA-VARIANTS: none\n"
                  + r"\renewcommand\documentclass[2]{}\documentclass{ulsbs-songbook}")
        result = migration.migrate_text(source)
        self.assertFalse(result.safe)
        self.assertEqual(result.text, source)

    def test_executable_arguments_and_printed_metadata_cannot_prove_later_execution(self) -> None:
        prefixes = (r"\textcolor{red}{\aftergroup\eat}", r"\colorbox{red}{\unknown}",
                    r"\href{https://test/}{\unknown}", r"\AtBeginDocument{\unknown}",
                    r"\ulIfVariant{default}{\eat}{}", r"\ulIfMusical{\eat}{}",
                    r"\beginsong{\unknown}", r"\beginsong{Title}[by={\aftergroup\eat}]")
        for prefix in prefixes:
            for call in (r"\ulShowTags{false}", r"\measuresfalse", r"\ulMeasures{true}",
                         r"\ifbassclefbook\newpage\fi"):
                with self.subTest(prefix=prefix, call=call):
                    source = r"\newcommand\eat[1]{}\begin{document}" + prefix + call
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    self.assertFalse(any(label.startswith(("scope:", "identity:")) for label in result.converted))
        source = (r"\def\eat#1\fi{}\begin{document}\textcolor{red}{\aftergroup\eat}"
                  r"\ifbassclefbook\newpage\fi")
        result = migration.migrate_text(source)
        self.assertFalse(result.safe)
        self.assertEqual(result.text, source)

    def test_consumable_control_group_ends_never_restore_execution_proof(self) -> None:
        for opening, closing in ((r"\begingroup", r"\endgroup"), (r"\bgroup", r"\egroup")):
            for call in (r"\ulShowTags{false}", r"\showtagsfalse", r"\ulMeasures{false}", r"\measuresfalse",
                         r"\ifbassclefbook\newpage\fi"):
                for wrapped in (False, True):
                    with self.subTest(opening=opening, call=call, wrapped=wrapped):
                        prefix = opening + r"\unknown" + closing
                        if wrapped:
                            prefix = "{" + prefix + "}"
                        source = r"\begin{document}" + prefix + call
                        result = migration.migrate_text(source)
                        self.assertFalse(result.safe)
                        self.assertEqual(result.text, source)
                        self.assertFalse(any(label.startswith(("scope:", "identity:")) for label in result.converted))
            source = ("% ULSBS-EXTRA-VARIANTS: none\n" + opening + r"\unknown" + closing
                      + r"\documentclass{ulsbs-songbook}")
            result = migration.migrate_text(source)
            self.assertFalse(result.safe)
            self.assertEqual(result.text, source)
            self.assertNotIn("availability:declaration", result.converted)
        for prefix in (r"{\aftergroup\eat}", r"{\unknown}", r"{{\unknown}}"):
            for call in (r"\ulShowTags{false}", r"\measuresfalse", r"\ifbassclefbook\newpage\fi"):
                with self.subTest(prefix=prefix, call=call):
                    source = r"\begin{document}\newcommand\eat[1]{}" + prefix + call
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    self.assertFalse(any(label.startswith(("scope:", "identity:")) for label in result.converted))

    def test_song_metadata_is_stored_not_a_direct_display_or_identity_body(self) -> None:
        for start in (r"\beginsong{Title}", r"\begin{song}{Title}"):
            for prefix in ("", r"\begin{document}"):
                for separator in ("{}", r"\relax"):
                    for call in (r"\showtagsfalse", r"\ulShowTags{false}", r"\measuresfalse",
                                 r"\ulMeasures{false}", r"\ifbassclefbook\newpage\fi"):
                        with self.subTest(start=start, prefix=prefix, separator=separator, call=call):
                            source = prefix + start + "[by=" + separator + call + "]"
                            result = migration.migrate_text(source)
                            self.assertFalse(result.safe)
                            self.assertEqual(result.text, source)
                            self.assertFalse(any(label.startswith(("scope:", "identity:")) for label in result.converted))
            source = start + r"[by={Independent Author},id={independent}]\showtagsfalse\measuresfalse"
            result = migration.migrate_text(source)
            self.assertTrue(result.safe, result.diagnostics)
            self.assertEqual(result.text, start + r"[by={Independent Author},id={independent}]"
                             r"\ulLocalShow{tags}{false}\ulLocalShow{measures}{false}")

    def test_removed_measure_literal_assignments_convert_only_in_proved_body_scopes(self) -> None:
        for value, old in (("true", "measurestrue"), ("false", "measuresfalse")):
            for call in ("\\" + old, "\\ulMeasures{" + value + "}"):
                for start in (r"\begin{document}", r"\beginsong{Title}", r"\beginverse"):
                    with self.subTest(call=call, start=start):
                        source = start + "\r\n{" + call + "}\r\n"
                        expected = start + "\r\n{\\ulLocalShow{measures}{" + value + "}}\r\n"
                        result = migration.migrate_text(source)
                        self.assertTrue(result.safe, result.diagnostics)
                        self.assertEqual(result.text, expected)
                        self.assertEqual(result.converted, {"scope:" + call[1:].split("{")[0]: 1})
                        second = migration.migrate_text(result.text)
                        self.assertTrue(second.safe, second.diagnostics)
                        self.assertEqual(second.text, expected)
                        self.assertFalse(second.converted)

    def test_removed_measure_assignment_keeps_all_unsupported_context_fences(self) -> None:
        for call in (r"\measuresfalse", r"\measurestrue", r"\ulMeasures{false}"):
            for template in ("%s", r"\AtBeginDocument{%s}", r"\unknown{%s}", r"\unknown{}%s",
                             r"\iftrue%s\fi", r"\newcommand\later{%s}", r"\string%s",
                             r"\write16%s", r"\toks0={%s}"):
                for prefix in ("", r"\begin{document}"):
                    if prefix and template == "%s":
                        continue
                    with self.subTest(call=call, template=template, prefix=prefix):
                        source = prefix + template % call
                        result = migration.migrate_text(source)
                        self.assertFalse(result.safe)
                        self.assertEqual(result.text, source)
                        self.assertTrue(any("removed measure API" in d.message for d in result.diagnostics))
        for call in (r"\ulMeasures{\computed}", r"\ulMeasures{ false }", r"\ulMeasures", r"\ulMeasures{false",
                     r"\ifmeasures\newpage\fi", r"\ifulMeasures\newpage\fi"):
            source = r"\begin{document}" + call
            self.assertFalse(migration.migrate_text(source).safe)

    def test_combined_semantic_cli_transaction_with_tags_and_readonly_config_reviews(self) -> None:
        for mode in ("--check", "--diff", "--write"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                root = Path(directory)
                safe, rejected, tags, valid, obsolete = (root / name for name in (
                    "safe.tex", "rejected.tex", "tags.can", "valid.toml", "obsolete.toml"))
                source = ("%% ULSBS-EXTRA-VARIANTS: charango,bassclef\r\n"
                          + r"\documentclass[subtitle={Independent, book}]{ulsbs-songbook-third-party}"
                  + r"\showtagsfalse\songcolumns{2}\begin{document}\showbeatsfalse\measuresfalse"
                          + r"\ifbassclefbook\newpage\else\ifulCharangoBook\clearpage\fi\fi"
                          + r"\begin{chorus}Text\end{chorus}" + "\r\n")
                expected = migration.migrate_text(source)
                self.assertTrue(expected.safe, expected.diagnostics)
                safe.write_bytes(source.encode())
                rejected.write_bytes((source + r"\chordsoff").encode())
                tags.write_bytes(b"Water|river\r\n1\r\n")
                valid.write_bytes(b'variants = ["default", "lyric"]\r\n')
                obsolete.write_bytes(b"lyricbooks = true\r\n")
                for path in (safe, rejected, tags, valid, obsolete):
                    path.chmod(0o640)
                original_stats = {path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
                                  for path in (rejected, valid, obsolete)}
                with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()) as errors:
                    self.assertEqual(migration.main([
                        mode, directory, "--tags-file", str(tags), "--config-file", str(valid),
                        "--config-file", str(obsolete)]), 1)
                self.assertIn("Scanned 5 files; 2 would change; 2 need review.", errors.getvalue())
                self.assertIn(f"{rejected}:3:1: legacy broad", errors.getvalue())
                self.assertIn(f"{obsolete}:1:1:", errors.getvalue())
                self.assertEqual("+++ " + str(safe) in output.getvalue(), mode == "--diff")
                for path, original in original_stats.items():
                    self.assertNotIn(str(path), output.getvalue())
                    self.assertEqual((path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns), original)
                self.assertEqual(safe.read_bytes(), (expected.text if mode == "--write" else source).encode())
                destination = tags.with_suffix(".txt") if mode == "--write" else tags
                self.assertEqual(destination.read_bytes(), b"Water|river\r\n" if mode == "--write"
                                 else b"Water|river\r\n1\r\n")
                self.assertEqual(stat.S_IMODE(safe.stat().st_mode), 0o640)
                self.assertEqual(set(root.iterdir()), {safe, rejected, destination, valid, obsolete})
                if mode == "--write":
                    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                        self.assertEqual(migration.main(["--check", str(safe), "--tags-file", str(destination),
                                                         "--config-file", str(valid)]), 0)

    def test_consumed_boundaries_and_mixed_macro_arguments_never_prove_execution(self) -> None:
        for boundary in (r"\beginverse", r"\begin{document}", r"\beginsong{Title}"):
            for call in (r"\ulShowTags{false}", r"\showtagsfalse"):
                source = r"\newcommand\eat[1]{}\eat" + boundary + call
                with self.subTest(boundary=boundary, call=call):
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    self.assertNotIn("scope:" + call[1:].split("{")[0], result.converted)
        for prefix in (r"\unknown{}", r"\unknown{}{}{}", r"\unknown data ",
                       r"\newcommand\eat[2]{}\eat{}", r"\unknown\songcolumns{2}"):
            for call in (r"\ulShowTags{false}", r"\showtagsfalse",
                         r"\ifbassclefbook\newpage\fi"):
                source = r"\begin{document}" + prefix + call
                with self.subTest(prefix=prefix, call=call):
                    result = migration.migrate_text(source)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
            source = ("% ULSBS-EXTRA-VARIANTS: none\n" + prefix
                      + r"\documentclass{ulsbs-songbook}")
            result = migration.migrate_text(source)
            self.assertFalse(result.safe)
            self.assertEqual(result.text, source)
            self.assertNotIn("availability:declaration", result.converted)

    @unittest.skipUnless(shutil.which("lualatex"), "LuaLaTeX not installed")
    def test_migrated_independent_book_executes_identity_and_effective_scope_once(self) -> None:
        from test_tex_integration import compile_fixture

        source = ("%% ULSBS-EXTRA-VARIANTS: bassclef, charango\n"
                  + r"\documentclass{ulsbs-songbook}\ulShowTags{false}\ulShowMeasures{false}" + r"""
\begin{document}
\showtagstrue
\measurestrue
\ifbassclefbook % instrument pagination
  \newpage
\else
  \ifulCharangoBook\clearpage\else\newpage\clearpage\fi
\fi
{\ulShowNotes{false}
 \typeout{MIGRATION-NOTES-LOCAL:\ifulShowNotes on\else off\fi}}
\typeout{MIGRATION-NOTES-RESTORED:\ifulShowNotes on\else off\fi}
\typeout{MIGRATION-TAGS:\ifulShowTags on\else off\fi}
\typeout{MIGRATION-MEASURES:\ifulShowMeasures on\else off\fi}
\typeout{MIGRATION-PAGES:\the\PageChoice}
Probe.
\end{document}
""")
        result = migration.migrate_text(source)
        self.assertTrue(result.safe, result.diagnostics)
        # Instrument AFTER migration; source redefinitions of assumed page APIs
        # must not be mistaken for proved zero-argument pagination statements.
        instrumented = result.text.replace(r"\begin{document}", r"""
\newcount\PageChoice
\let\SavedNewPage\newpage \let\SavedClearPage\clearpage
\def\newpage{\global\advance\PageChoice1 }
\def\clearpage{\global\advance\PageChoice10 }
\begin{document}
""").replace(r"\end{document}", r"\let\newpage\SavedNewPage\let\clearpage\SavedClearPage\end{document}")
        for variant, pages, notes in (("default", 11, "on"), ("lyric", 11, "off"),
                                      ("charango", 10, "on"), ("bassclef", 1, "off")):
            with self.subTest(variant=variant):
                output, _ = compile_fixture(
                    "source-effects", multikey=None,
                    files={"source-effects.tex": (f"\\def\\ulBuildVariant{{{variant}}}\n" + instrumented).encode()},
                )
                for marker in ("MIGRATION-TAGS:off", "MIGRATION-MEASURES:off", "MIGRATION-NOTES-LOCAL:off",
                               "MIGRATION-NOTES-RESTORED:" + notes, f"MIGRATION-PAGES:{pages}"):
                    self.assertIn(marker, output)
                self.assertEqual(output.count(f"MIGRATION-PAGES:{pages}"), 1)

    def test_literal_instrument_pagination_preserves_branches_and_delimiter_whitespace(self) -> None:
        for name, variant in (("ifcharangobook", "charango"), ("ifulCharangoBook", "charango"),
                              ("ifbassclefbook", "bassclef"), ("ifulBassclefBook", "bassclef")):
            for yes, no in (("\\newpage", "\\clearpage"), (" % yes\r\n\\sclearpage", "\r\n% no\r\n"),
                            ("", "")):
                for has_else in (True, False):
                    with self.subTest(name=name, yes=yes, no=no, has_else=has_else):
                        source = "\\begin{document}\\" + name + yes + ("\\else" + no if has_else else "") + "\\fi\r\n"
                        expected = ("\\begin{document}\\ulIfVariant{" + variant + "}{\\relax" + yes
                                    + ("}{\\relax" + no if has_else else "}{") + "}\\relax\r\n")
                        result = migration.migrate_text(source)
                        self.assertTrue(result.safe, result.diagnostics)
                        self.assertEqual(result.text, expected)
                        second = migration.migrate_text(result.text)
                        self.assertTrue(second.safe, second.diagnostics)
                        self.assertEqual(second.text, result.text)
                        self.assertFalse(second.converted)

    def test_nested_instrument_pagination_is_one_original_coordinate_transaction(self) -> None:
        source = ("%% ULSBS-EXTRA-VARIANTS: bassclef, charango\r\n"
                  + r"\documentclass{ulsbs-songbook-independent}\showtagsfalse\begin{document}"
                  + r"\showbeatsfalse\ifbassclefbook\newpage\else"
                  + r"\ifulCharangoBook\clearpage\else\sclearpage\fi\fi")
        with patch.object(migration, "_apply_edit_plans", wraps=migration._apply_edit_plans) as apply:
            result = migration.migrate_text(source)
        apply.assert_called_once()
        self.assertTrue(result.safe, result.diagnostics)
        self.assertIn(r"\ulShowTags{false}\begin{document}\ulLocalShow{beats}{false}", result.text)
        self.assertIn(r"\ulIfVariant{bassclef}{\relax\newpage}{\relax"
                      r"\ulIfVariant{charango}{\relax\clearpage}{\relax\sclearpage}\relax}\relax", result.text)
        self.assertEqual(result.converted["identity:ifbassclefbook"], 1)
        self.assertEqual(result.converted["identity:ifulCharangoBook"], 1)
        self.assertEqual(result.converted["identity:fi"], 2)
        self.assertEqual(result.converted["scope:showbeatsfalse"], 1)
        second = migration.migrate_text(result.text)
        self.assertTrue(second.safe, second.diagnostics)
        self.assertFalse(second.converted)

    def test_identity_conversion_rejects_unsupported_branches_contexts_and_raw_structure(self) -> None:
        for payload in ("text", r"\unknown", r"\iftrue\newpage\fi", r"\ifchorded\newpage\fi",
                        r"\ifulLyricOnly\newpage\fi", r"\ulShowNotes{false}", r"\chordsoff",
                        r"{\newpage}", r"\pagebreak[2]", r"\verb|anything|", r"\input{missing}",
                        r"\newpage\else\clearpage\else\newpage", r"\newpage\or\clearpage"):
            source = r"\begin{document}\ifbassclefbook" + " " + payload + r"\fi"
            with self.subTest(payload=payload):
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                self.assertTrue(any("legacy variant identity" in d.message for d in result.diagnostics))
        identity = r"\ifcharangobook\newpage\else\clearpage\fi"
        for template in (r"\AtBeginDocument{%s}", r"\unknown{%s}", r"\unknown %s", r"\write16%s",
                         r"\newcommand\later{%s}", r"\string%s", r"\detokenize{%s}", r"\iftrue%s\fi",
                         r"\fi%s", r"%s\fi", r"%s\else", r"%s\iftrue"):
            with self.subTest(template=template):
                source = r"\begin{document}" + template % identity
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
        for source in (identity, r"\begin{document}\ifbassclefbook\newpage",
                       r"\begin{document}\iflyric\newpage\fi",
                       r"\begin{document}\ulSongbookType{charango}" + identity):
            self.assertFalse(migration.migrate_text(source).safe)

    def test_semantic_proposals_reject_whole_original_file_for_remaining_fences(self) -> None:
        for hazard, message in ((r"\chordsoff", "legacy broad"), (r"\ifulMeasures\fi", "removed measure"),
                                (r"\ifulChorded x\fi", "legacy variant identity"),
                                (r"\AtBeginDocument{\ulShowNotes{false}}", "display setter")):
            source = ("% ULSBS-EXTRA-VARIANTS: none\r\n"
                      + r"\documentclass{ulsbs-songbook-independent}\songcolumns{2}\begin{document}"
                      + r"\showtagsfalse\ifbassclefbook\newpage\fi" + "\r\n"
                      + r"\songcolumns{2}" + hazard)
            with self.subTest(hazard=hazard):
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                diagnostic = next(d for d in result.diagnostics if message in d.message)
                pos = source.index(hazard) if message != "display setter" else source.index(r"\ulShowNotes")
                self.assertEqual((diagnostic.line, diagnostic.column),
                                 (source.count("\n", 0, pos) + 1, pos - source.rfind("\n", 0, pos)))
                self.assertEqual(result.converted["identity:ifbassclefbook"], 1)
                self.assertEqual(result.converted["availability:declaration"], 1)
                self.assertEqual(result.converted["scope:showtagsfalse"], 1)

    def test_direct_body_display_inventory_and_grouped_restoration(self) -> None:
        from ulsbs.tools.naming_v2 import BOOLEAN_SETTERS

        self.assertEqual(set(migration.DISPLAY_FEATURES), set(DISPLAY_NAMES))
        for name in DISPLAY_NAMES:
            for value in ("true", "false"):
                for start in (r"\begin{document}", r"\beginsong{Title}", r"\beginverse"):
                    for call in (f"\\{name}{{{value}}}", *("\\" + old for old, pair in BOOLEAN_SETTERS.items()
                                                        if pair == (name, value))):
                        with self.subTest(name=name, value=value, start=start, call=call):
                            source = start + "\r\n{" + call + "}\r\n"
                            expected = start + "\r\n{\\ulLocalShow{" + migration.DISPLAY_FEATURES[name] + "}{" + value + "}}\r\n"
                            first = migration.migrate_text(source)
                            self.assertTrue(first.safe, first.diagnostics)
                            self.assertEqual(first.text, expected)
                            second = migration.migrate_text(first.text)
                            self.assertTrue(second.safe, second.diagnostics)
                            self.assertEqual(second.text, first.text)
                            self.assertFalse(second.converted)

    def test_body_literal_comments_survive_and_current_local_arity_is_idempotent(self) -> None:
        source = ("\\begin{document}\r\n\\ulShowNotes % argument\r\n{tr% literal\r\nue}"
                  + r"{\showtagsfalse}\ulLocalShow{beats}{false}{\ulShowMeasures{true}}")
        expected = ("\\begin{document}\r\n\\ulLocalShow{notes} % argument\r\n{tr% literal\r\nue}"
                    + r"{\ulLocalShow{tags}{false}}\ulLocalShow{beats}{false}{\ulLocalShow{measures}{true}}")
        result = migration.migrate_text(source)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, expected)
        second = migration.migrate_text(expected)
        self.assertTrue(second.safe, second.diagnostics)
        self.assertEqual(second.text, expected)
        self.assertFalse(second.converted)

    def test_body_conversion_does_not_exempt_unknown_delayed_or_conditional_contexts(self) -> None:
        for template in (r"\unknown{%s}", r"\unknown{}{}{}{ %s }", r"\unknown %s",
                         r"\write16{%s}", r"\write16%s", r"\toks0={%s}", r"\toks0=%s",
                         r"\newcommand\later{%s}", r"\AtBeginDocument{%s}", r"\string%s",
                         r"\iftrue%s\fi", r"\ulIfVariant{lyric}{%s}{}", r"\expanded{%s}"):
            with self.subTest(template=template):
                source = r"\begin{document}\songcolumns{2}" + template % r"\ulShowNotes{false}"
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                self.assertTrue(any("display setter" in d.message for d in result.diagnostics))

    def test_leading_literal_marker_preserves_implicit_lyric_and_explicit_instruments(self) -> None:
        from ulsbs.variants import available_variants

        for value, names in (("none", "default,lyric"), ("charango", "default,lyric,charango"),
                             ("bassclef, charango", "default,lyric,bassclef,charango")):
            for options in ("", "[]", "[subtitle={A, {B]C}},oneside]", "[% comment\r\n]"):
                with self.subTest(value=value, options=options):
                    source = ("% independent book\r\n  %% ULSBS-EXTRA-VARIANTS: " + value + "\r\n"
                              + "\\documentclass" + options + "{ulsbs-songbook-independent}\r\n"
                              + r"\showtagsfalse\songcolumns{2}\begin{document}Text.")
                    result = migration.migrate_text(source)
                    self.assertTrue(result.safe, result.diagnostics)
                    self.assertNotIn("ULSBS-EXTRA-VARIANTS", result.text)
                    self.assertIn("% independent book\r\n  %% \r\n", result.text)
                    self.assertEqual(available_variants(result.text), tuple(names.split(",")))
                    self.assertIn(r"\ulShowTags{false}\ulSongColumns{2}", result.text)
                    if "subtitle" in options:
                        self.assertIn("subtitle={A, {B]C}},oneside", result.text)
                    second = migration.migrate_text(result.text)
                    self.assertTrue(second.safe, second.diagnostics)
                    self.assertEqual(second.text, result.text)
                    self.assertFalse(second.converted)

    def test_marker_conversion_requires_explicit_unambiguous_leading_evidence(self) -> None:
        declaration = r"\documentclass{ulsbs-songbook-independent}"
        for marker in ("% ULSBS-EXTRA-VARIANTS: unknown", "% ULSBS-EXTRA-VARIANTS: none,charango",
                       "% ULSBS-EXTRA-VARIANTS: charango,charango", "% prose ULSBS-EXTRA-VARIANTS: none",
                       "% ULSBS-EXTRA-VARIANTS: none % explanation", "ULSBS-EXTRA-VARIANTS: none",
                       "% ULSBS-EXTRA-VARIANTS: ", r"% ULSBS-EXTRA-VARIANTS: \computed"):
            with self.subTest(marker=marker):
                source = marker + "\n" + declaration
                result = migration.migrate_text(source)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
        marker = "% ULSBS-EXTRA-VARIANTS: none\n"
        for body in (r"{\documentclass{ulsbs-songbook}}", r"\iftrue\documentclass{ulsbs-songbook}\fi",
                     r"\AtBeginDocument{\documentclass{ulsbs-songbook}}", r"\documentclass{article}",
                     declaration + declaration, r"\documentclass[variants={default,lyric}]{ulsbs-songbook}",
                     r"\documentclass[variants={default}]{ulsbs-songbook}",
                     r"\documentclass[\key=value]{ulsbs-songbook}"):
            with self.subTest(body=body):
                result = migration.migrate_text(marker + body)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, marker + body)
        for prefix in (r"\relax", r"\def\later{", r"\iftrue", r"\begingroup"):
            source = prefix + "\n" + marker + declaration
            self.assertFalse(migration.migrate_text(source).safe)

    def test_marker_and_naming_proposals_roll_back_at_original_diagnostic_coordinates(self) -> None:
        source = ("% ULSBS-EXTRA-VARIANTS: none\r\n"
                  + r"\documentclass{ulsbs-songbook-independent}\songcolumns{2}" + "\r\n"
                  + r"\songcolumns{2}\chordsoff")
        with patch.object(migration, "_apply_edit_plans", wraps=migration._apply_edit_plans) as apply:
            result = migration.migrate_text(source)
        apply.assert_called_once()
        self.assertFalse(result.safe)
        self.assertEqual(result.text, source)
        self.assertEqual((result.diagnostics[0].line, result.diagnostics[0].column), (3, 16))
        self.assertEqual(result.converted["availability:declaration"], 1)
        self.assertEqual(result.converted["availability:marker"], 1)
        self.assertEqual(result.converted["songcolumns"], 2)

    def test_availability_semantic_cli_modes_preserve_bytes_modes_and_config_no_write(self) -> None:
        for mode in ("--check", "--diff", "--write"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                root = Path(directory)
                safe, rejected, config = (root / name for name in ("book.tex", "review.tex", "config.toml"))
                original = (b"%% ULSBS-EXTRA-VARIANTS: none\r\n"
                            b"\\documentclass{ulsbs-songbook-independent}\\songcolumns{2}\r\n")
                safe.write_bytes(original)
                rejected.write_bytes(original + b"\\chordsoff")
                config.write_bytes(b'variants = ["default", "lyric"]\r\n')
                for path in (safe, rejected, config):
                    path.chmod(0o640)
                config_stat = config.stat()
                with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()):
                    self.assertEqual(migration.main([mode, directory, "--config-file", str(config)]), 1)
                self.assertEqual("+++ " + str(safe) in output.getvalue(), mode == "--diff")
                self.assertNotIn(str(rejected), output.getvalue())
                self.assertNotIn(str(config), output.getvalue())
                self.assertEqual(rejected.read_bytes(), original + b"\\chordsoff")
                self.assertEqual(config.read_bytes(), b'variants = ["default", "lyric"]\r\n')
                self.assertEqual((config.stat().st_ino, config.stat().st_mtime_ns),
                                 (config_stat.st_ino, config_stat.st_mtime_ns))
                expected = (b"%% \r\n\\documentclass[variants={default,lyric}]{ulsbs-songbook-independent}"
                            b"\\ulSongColumns{2}\r\n")
                self.assertEqual(safe.read_bytes(), expected if mode == "--write" else original)
                self.assertEqual(stat.S_IMODE(safe.stat().st_mode), 0o640)
                self.assertEqual(set(root.iterdir()), {safe, rejected, config})


class CompilerConfigReviewTests(unittest.TestCase):
    def run_cli(self, *args: str) -> tuple[int, str, str]:
        with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()) as errors:
            status = migration.main(list(args))
        return status, output.getvalue(), errors.getvalue()

    def review(self, source: str) -> migration.Result:
        result = migration.review_config_text(source)
        self.assertEqual(result.text, source)
        self.assertFalse(result.converted)
        self.assertEqual(migration.review_config_text(source), result)
        return result

    def test_removed_categories_in_root_and_every_profile(self) -> None:
        for key in ("lyricbooks", "extrainstrumentbooks", "no-lyricbooks", "no_lyricbooks",
                    "no-extrainstrumentbooks", "no_extrainstrumentbooks"):
            for value in ("true", "false", '"computed"', "[]"):
                with self.subTest(key=key, value=value):
                    source = f'# {key} = false\r\n  {key} = {value}\r\n[profiles.unused]\r\n{key} = false\r\n'
                    result = self.review(source)
                    self.assertEqual([(d.line, d.column) for d in result.diagnostics], [(2, 3), (4, 1)])
                    self.assertTrue(all("removed variant-category" in d.message for d in result.diagnostics))
                    self.assertTrue(all("availability" in d.message for d in result.diagnostics))

    def test_valid_selectors_and_profile_overrides_are_unchanged(self) -> None:
        for value in ('"all"', '["default"]', '["bassclef", "lyric"]',
                      '[\n "charango", # keep comment\n "default",\n]'):
            source = (f'variants = {value}\n[profiles.base]\nvariants = ["lyric"]\n'
                      '[profiles.dev]\ninherit-from = "base"\nvariants = ["default"]\n')
            self.assertTrue(self.review(source).safe)
        source = ('variants = ["default"]\n[profiles.base]\nvariants = ["lyric"]\n'
                  '[profiles.dev]\ninherit_from = "base"\nmerge-keys = ["variants"]\n'
                  'variants = ["bassclef"]\n')
        self.assertTrue(self.review(source).safe)

    def test_malformed_or_computed_selectors_are_reviewed_before_overrides(self) -> None:
        values = ('true', 'false', '0', '[]', '"default"', '"default,lyric"', '"ALL"',
                  '"${VARIANTS}"', '["all"]', '["lyrics"]', '["unknown"]',
                  '["default", "default"]', '[" default"]', '["lyric "]',
                  '["default,lyric"]', '[1]', '[true]', '{default = true}')
        for value in values:
            with self.subTest(value=value):
                source = (f'variants = {value}\n[profiles.bad]\nvariants = {value}\n'
                          '[profiles.override]\nvariants = ["default"]\n')
                result = self.review(source)
                self.assertFalse(result.safe)
                self.assertEqual([(d.line, d.column) for d in result.diagnostics], [(1, 1), (3, 1)])
                self.assertTrue(all("variants selector" in d.message for d in result.diagnostics))

    def test_conflicting_negated_selectors_and_normalized_keys(self) -> None:
        for source, position in (
            ('variants = "all"\nno-variants = true\n', (2, 1)),
            ('no_variants = false\n', (1, 1)),
            ('[profiles.dev]\nvariants = ["default"]\nno_variants = false\n', (3, 1)),
            ('[profiles.dev]\ninherit-from = "base"\ninherit_from = "other"\n', (3, 1)),
            ('[profiles.dev-one]\nvariants = "all"\n[profiles.dev_one]\nvariants = "all"\n', (3, 11)),
        ):
            with self.subTest(source=source):
                result = self.review(source)
                self.assertFalse(result.safe)
                self.assertIn(position, [(d.line, d.column) for d in result.diagnostics])

    def test_quoted_dotted_and_inline_profile_keys_keep_original_coordinates(self) -> None:
        for source, positions in (
            ('"profiles"."dev.name"."no-lyricbooks" = true\r\n', [(1, 23)]),
            ('profiles = { dev = { variants = ["lyrics"] } }\n', [(1, 22)]),
            ('profiles.dev = { "no_extrainstrumentbooks" = false }\n', [(1, 18)]),
            ('[profiles."dev.name"]\n  "varian\\u0074s" = ["bogus"]\n', [(2, 3)]),
        ):
            with self.subTest(source=source):
                result = self.review(source)
                self.assertFalse(result.safe)
                self.assertEqual([(d.line, d.column) for d in result.diagnostics], positions)

    def test_comments_strings_and_unrelated_nested_data_are_not_settings(self) -> None:
        source = '''# lyricbooks = true
songbooks = ["lyricbooks = true.tex", "variants = bogus.tex"]
variants = 'all'
common-deploy-metadata = ["missing.json"]
note = """\n[profiles.fake]\nlyricbooks = true\n"""
literal = ''' + "'''\nvariants = false\n'''\n" + '''
[unrelated]
lyricbooks = false
variants = "not a compiler selector"
[profiles.dev]
variants = ["default"]
[profiles.dev.custom]
lyricbooks = true
'''
        self.assertTrue(self.review(source).safe)

    def test_profile_shapes_and_selector_inheritance_hazards_require_review(self) -> None:
        for source in (
            'profiles = false\n', 'profiles = []\n', 'profiles.dev = "computed"\n',
            '[[profiles.dev]]\nvariants = "all"\n',
            'variants = "all"\n[profiles.dev]\nmerge-keys = ["variants"]\nvariants = ["default"]\n',
            'variants = ["default"]\n[profiles.dev]\ninherit-from = "missing"\n',
            '[profiles.a]\ninherit-from = "b"\nvariants = "all"\n[profiles.b]\ninherit-from = "a"\n',
        ):
            with self.subTest(source=source):
                self.assertFalse(self.review(source).safe)

    def test_invalid_toml_rejects_whole_file_without_tex_naming(self) -> None:
        for source in ('variants = [\n', 'variants = "all"\nvariants = ["default"]\n',
                       'profiles = { dev = { variants = "all" }\n', 'not toml'):
            with self.subTest(source=source):
                result = self.review(source)
                self.assertFalse(result.safe)
                self.assertIn("TOML", result.diagnostics[0].message)

    def test_cli_requires_mode_and_explicit_input(self) -> None:
        for args in ([], ["--check"], ["--config-file", "config.toml"],
                     ["--check", "--write", "--config-file", "config.toml"]):
            with self.subTest(args=args), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as error:
                    migration.main(args)
                self.assertEqual(error.exception.code, 2)

    def test_all_modes_are_read_only_for_safe_and_rejected_configs(self) -> None:
        for mode in ("--check", "--diff", "--write"):
            for source, status in ((b'# Current\r\nvariants = ["default", "lyric"]\r\n', 0),
                                   (b'# Legacy\r\n  lyricbooks = false\r\n', 1),
                                   (b'variants = ["lyrics"]\r\n', 1)):
                with self.subTest(mode=mode, source=source), TemporaryDirectory() as directory:
                    path = Path(directory) / "explicit.conf"
                    path.write_bytes(source)
                    path.chmod(0o440)
                    before = path.stat()
                    with patch.object(migration, "_atomic_write") as write_source:
                        with patch.object(migration, "_write_tags") as write_tags:
                            result, output, errors = self.run_cli(mode, "--config-file", str(path))
                    self.assertEqual(result, status, errors)
                    self.assertEqual(output, "")
                    self.assertIn(f"Scanned 1 files; 0 would change; {status} need review.", errors)
                    self.assertNotIn("Reminder:", errors)
                    self.assertEqual(path.read_bytes(), source)
                    self.assertEqual((path.stat().st_ino, path.stat().st_mtime_ns, path.stat().st_mode),
                                     (before.st_ino, before.st_mtime_ns, before.st_mode))
                    self.assertEqual(list(path.parent.iterdir()), [path])
                    write_source.assert_not_called()
                    write_tags.assert_not_called()

    def test_config_failures_do_not_block_safe_source_and_tag_processing(self) -> None:
        for mode in ("--check", "--diff", "--write"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                root = Path(directory)
                config, safe, rejected, tags = (root / name for name in
                                               ("config.toml", "safe.tex", "review.tex", "tags.can"))
                config.write_bytes(b'# Heading\r\n  no-lyricbooks = true\r\n[profiles.dev]\r\nvariants = ["lyrics"]\r\n')
                safe.write_bytes(b'\\documentclass[variants={default,lyric}]{ulsbs-songbook}\r\n\\songcolumns{2}\r\n')
                rejected.write_bytes(b'\\songcolumns{2}\\ifulLyricOnly yes\\fi\r\n')
                tags.write_bytes(b'Fire|flame\r\n1\r\n')
                before = {p: p.read_bytes() for p in (config, safe, rejected, tags)}
                status, output, errors = self.run_cli(
                    mode, directory, "--config-file", str(config), "--tags-file", str(tags))
                self.assertEqual(status, 1)
                self.assertIn(f"{config}:2:3: removed variant-category", errors)
                self.assertIn(f"{config}:4:1: unsafe variants selector", errors)
                self.assertIn(f"{rejected}:1:16: legacy variant identity", errors)
                self.assertIn("Scanned 4 files; 2 would change; 2 need review.", errors)
                self.assertIn("songcolumns: 2", errors)
                self.assertEqual("+++ " + str(safe) in output, mode == "--diff")
                for path in (config, rejected):
                    self.assertNotIn(str(path), output)
                    self.assertEqual(path.read_bytes(), before[path])
                self.assertEqual(safe.read_bytes(), before[safe].replace(b'\\songcolumns', b'\\ulSongColumns')
                                 if mode == "--write" else before[safe])
                destination = tags.with_suffix(".txt") if mode == "--write" else tags
                self.assertEqual(destination.read_bytes(), b'Fire|flame\r\n' if mode == "--write" else before[tags])
                self.assertEqual(set(root.iterdir()), {config, safe, rejected, destination})

    def test_directory_scans_do_not_discover_configs_or_follow_config_songbooks(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config, source = root / "config.toml", root / "book.tex"
            config.write_text('lyricbooks = true\n', encoding="utf-8")
            source.write_text(r'\ulSongColumns{2}', encoding="utf-8")
            status, output, errors = self.run_cli("--check", directory)
            self.assertEqual(status, 0, errors)
            self.assertEqual(output, "")
            self.assertIn("Scanned 1 files", errors)
            config.write_text('variants = "all"\nsongbooks = ["missing/*.tex", "../elsewhere.tex"]\n', encoding="utf-8")
            with patch("ulsbs.config.build_config") as build_config:
                with patch.object(migration, "migrate_text") as migrate_source:
                    status, _, errors = self.run_cli("--check", "--config-file", str(config))
            self.assertEqual(status, 0, errors)
            build_config.assert_not_called()
            migrate_source.assert_not_called()

    def test_multiple_explicit_configs_are_reviewed_and_duplicates_deduplicated(self) -> None:
        with TemporaryDirectory() as directory:
            safe, bad = Path(directory) / "safe.toml", Path(directory) / "bad.toml"
            safe.write_text('variants = "all"\n', encoding="utf-8")
            bad.write_text('extrainstrumentbooks = true\n', encoding="utf-8")
            status, output, errors = self.run_cli("--write", "--config-file", str(safe),
                                                 "--config-file", str(bad), "--config-file", str(bad))
            self.assertEqual(status, 1)
            self.assertEqual(output, "")
            self.assertEqual(errors.count("removed variant-category"), 1)
            self.assertIn("Scanned 2 files; 0 would change; 1 need review.", errors)

    def test_config_path_hazards_reject_without_read_and_isolate_other_sources(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            config = real / "config.toml"
            config.write_bytes(b'variants = "all"\r\n')
            link, leaf, dangling, fifo = (root / name for name in ("linked", "leaf", "dangling", "fifo"))
            link.symlink_to(real, target_is_directory=True)
            leaf.symlink_to(config)
            dangling.symlink_to(root / "absent")
            os.mkfifo(fifo)
            source = root / "safe.tex"
            source.write_text(r'\songcolumns{2}', encoding="utf-8")
            hazards = (link, leaf, dangling, link / "config.toml", link / ".." / "real/config.toml",
                       fifo, real, root / "absent")
            for path in hazards:
                for mode in ("--check", "--diff", "--write"):
                    with self.subTest(path=path, mode=mode):
                        with patch.object(os, "open") as open_file:
                            status, output, errors = self.run_cli(mode, "--config-file", str(path))
                        self.assertEqual(status, 1, errors)
                        self.assertEqual(output, "")
                        self.assertIn("0 would change; 1 need review.", errors)
                        open_file.assert_not_called()
                status, _, errors = self.run_cli("--diff", str(source), "--config-file", str(path))
                self.assertEqual(status, 1)
                self.assertIn("Scanned 2 files; 1 would change; 1 need review.", errors)
            self.assertEqual(config.read_bytes(), b'variants = "all"\r\n')

    def test_invalid_encoding_isolated_from_safe_files(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config, source = root / "bad.toml", root / "safe.tex"
            config.write_bytes(b'variants = "\xff"\r\n')
            source.write_text(r'\songcolumns{2}', encoding="utf-8")
            status, _, errors = self.run_cli("--write", "--config-file", str(config), str(source))
            self.assertEqual(status, 1)
            self.assertIn("Scanned 2 files; 1 would change; 1 need review.", errors)
            self.assertEqual(source.read_text(), r'\ulSongColumns{2}')
            self.assertEqual(config.read_bytes(), b'variants = "\xff"\r\n')

    def test_config_leaf_swapped_at_open_is_not_followed(self) -> None:
        with TemporaryDirectory() as directory:
            config, target = Path(directory) / "config.toml", Path(directory) / "target.toml"
            config.write_text('variants = "all"\n', encoding="utf-8")
            open_file = os.open

            def replace_leaf(path, flags):
                self.assertTrue(flags & os.O_NOFOLLOW)
                config.rename(target)
                config.symlink_to(target)
                return open_file(path, flags)

            with patch.object(os, "open", side_effect=replace_leaf):
                with patch.object(migration, "review_config_text") as review:
                    status, output, errors = self.run_cli("--write", "--config-file", str(config))
            self.assertEqual(status, 1, errors)
            self.assertEqual(output, "")
            review.assert_not_called()
            self.assertTrue(config.is_symlink())
            self.assertEqual(target.read_text(), 'variants = "all"\n')

    def test_selected_config_cannot_be_rewritten_through_source_or_tag_roles(self) -> None:
        for role in ("source", "tag", "hardlink-source", "hardlink-tag", "destination"):
            for mode in ("--check", "--diff", "--write"):
                with self.subTest(role=role, mode=mode), TemporaryDirectory() as directory:
                    root = Path(directory)
                    config = root / "config.tex"
                    config.write_bytes(b'variants = "all"\r\n')
                    alias = root / "alias.tex"
                    if role.startswith("hardlink"):
                        os.link(config, alias)
                    selected = alias if role.startswith("hardlink") else config
                    if role == "destination":
                        config = root / "tags.txt"
                        config.write_bytes(b'variants = "all"\r\n')
                        selected = root / "tags.can"
                        selected.write_bytes(b'Fire\r\n1\r\n')
                    inputs = (str(selected),) if "source" in role else ("--tags-file", str(selected))
                    before = {p: p.read_bytes() for p in root.iterdir()}
                    status, output, errors = self.run_cli(mode, "--config-file", str(config), *inputs)
                    self.assertEqual(status, 1)
                    self.assertEqual(output, "")
                    self.assertIn("config review input cannot also be", errors)
                    self.assertEqual({p: p.read_bytes() for p in root.iterdir()}, before)

    def test_rejected_config_symlinks_also_protect_targets_from_other_roles(self) -> None:
        for component in ("leaf", "parent"):
            for role in ("source", "hardlink-source", "tag", "destination"):
                for mode in ("--check", "--diff", "--write"):
                    with self.subTest(component=component, role=role, mode=mode), TemporaryDirectory() as directory:
                        root = Path(directory)
                        real = root / "real"
                        real.mkdir()
                        target = real / ("tags.txt" if role == "destination" else "target.tex")
                        original = b'# \\songcolumns{2}\r\nvariants = "all"\r\n'
                        target.write_bytes(original)
                        if component == "leaf":
                            config = root / "config.toml"
                            config.symlink_to(target)
                        else:
                            parent = root / "linked"
                            parent.symlink_to(real, target_is_directory=True)
                            config = parent / target.name
                        selected = target
                        if role == "hardlink-source":
                            selected = root / "alias.tex"
                            os.link(target, selected)
                        elif role == "destination":
                            selected = real / "tags.can"
                            selected.write_bytes(b'Fire\r\n1\r\n')
                        safe = root / "safe.tex"
                        safe.write_bytes(b'\\songcolumns{2}\r\n')
                        inputs = (str(selected),) if "source" in role else ("--tags-file", str(selected))
                        status, output, errors = self.run_cli(mode, "--config-file", str(config), str(safe), *inputs)
                        self.assertEqual(status, 1)
                        self.assertIn("symlink config path", errors)
                        self.assertIn("config review input cannot also be", errors)
                        self.assertIn("Scanned 3 files; 1 would change; 2 need review.", errors)
                        self.assertNotIn(str(target), output)
                        self.assertNotIn(str(selected), output)
                        self.assertEqual(target.read_bytes(), original)
                        self.assertEqual(safe.read_bytes(), b'\\ulSongColumns{2}\r\n' if mode == "--write"
                                         else b'\\songcolumns{2}\r\n')
                        if role == "destination":
                            self.assertEqual(selected.read_bytes(), b'Fire\r\n1\r\n')

    def test_config_replaced_by_fifo_at_open_rejects_without_blocking_batch(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config, moved, safe = root / "config.toml", root / "moved.toml", root / "safe.tex"
            original = b'variants = "all"\r\n'
            config.write_bytes(original)
            safe.write_bytes(b'\\songcolumns{2}\r\n')
            open_file = os.open

            def replace_leaf(path, flags):
                if Path(path) == config:
                    # Assert before the swap so the regression fails, rather than hangs.
                    self.assertTrue(flags & os.O_NONBLOCK)
                    config.rename(moved)
                    os.mkfifo(config)
                return open_file(path, flags)

            with patch.object(os, "open", side_effect=replace_leaf):
                status, output, errors = self.run_cli("--diff", "--config-file", str(config), str(safe))
            self.assertEqual(status, 1, errors)
            self.assertIn("config source must be a regular file", errors)
            self.assertIn("Scanned 2 files; 1 would change; 1 need review.", errors)
            self.assertIn("+++ " + str(safe), output)
            self.assertTrue(stat.S_ISFIFO(config.stat().st_mode))
            self.assertEqual(moved.read_bytes(), original)
            self.assertEqual(safe.read_bytes(), b'\\songcolumns{2}\r\n')


class SourcePathSafetyTests(unittest.TestCase):
    def run_cli(self, *args: str) -> tuple[int, str, str]:
        with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()) as errors:
            status = migration.main(list(args))
        return status, output.getvalue(), errors.getvalue()

    def make_engine(self, root: Path, git: str = "directory") -> list[Path]:
        """Build a renamed engine tree without depending on this checkout."""
        files = [root / "pyproject.toml", root / "src/ulsbs/tools/migrate_syntax_v2.py",
                 root / "src/ulsbs/assets/tex/ulsbs.sty", root / "tests/fixtures/historical.tex"]
        for path in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(r"\songcolumns{2}", encoding="utf-8")
        if git == "directory":
            (root / ".git").mkdir()
        elif git == "file":
            (root / ".git").write_text("gitdir: ../metadata", encoding="utf-8")
        return files

    def test_engine_boundaries_are_structural_not_directory_or_git_names(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, git in (("renamed-engine", "directory"), ("vendor/package", "file"),
                              ("copied-engine", "absent")):
                self.make_engine(root / name, git)
            sources = [root / "ulsbs/song.tex", root / "other-repository/class.cls",
                       root / "partial/src/ulsbs/assets/tex/ulsbs.sty"]
            for source in sources:
                source.parent.mkdir(parents=True, exist_ok=True)
                source.touch()
            (root / "other-repository/.git").mkdir()
            self.assertEqual(migration._paths([directory]), sorted(sources))

    def test_explicit_files_and_selected_subdirectories_bypass_engine_root_pruning(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            engine = root / "engine"
            files = self.make_engine(engine)
            self.assertEqual(migration._paths([str(engine)]), [])
            self.assertEqual(migration._paths([directory, str(files[2]), str(files[3])]),
                             sorted(files[2:]))
            self.assertEqual(migration._paths([str(engine / "tests")]), [files[3]])
            self.assertEqual(migration._paths([str(files[3]), str(files[3])]), [files[3]])

    def test_consumer_cli_modes_never_read_or_rewrite_nested_engine_sources(self) -> None:
        for mode in ("--check", "--diff", "--write"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                root = Path(directory)
                engine_files = self.make_engine(root / "vendor/renamed", "file")
                before = {path: path.read_bytes() for path in engine_files}
                source = root / "book.tex"
                source.write_bytes(b"\\songcolumns{2}\r\n")
                source.chmod(0o640)
                with patch.object(migration, "migrate_text", wraps=migration.migrate_text) as migrate:
                    status, output, errors = self.run_cli(mode, directory)
                self.assertEqual(status, int(mode == "--check"), errors)
                migrate.assert_called_once_with("\\songcolumns{2}\r\n", at_letter=False)
                self.assertIn("Scanned 1 files; 1 would change; 0 need review.", errors)
                self.assertIn("songcolumns: 1", errors)
                self.assertNotIn("historical", output)
                self.assertNotIn("ulsbs.sty", output)
                self.assertEqual(source.read_bytes(), b"\\ulSongColumns{2}\r\n" if mode == "--write"
                                 else b"\\songcolumns{2}\r\n")
                self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o640)
                self.assertEqual({path: path.read_bytes() for path in engine_files}, before)

    def test_explicit_symlink_components_reject_before_traversal_or_source_read(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            source = real / "song.tex"
            source.write_bytes(b"\\songcolumns{2}\r\n")
            link = root / "linked"
            link.symlink_to(real, target_is_directory=True)
            leaf = root / "leaf.tex"
            leaf.symlink_to(source)
            dangling = root / "dangling.tex"
            dangling.symlink_to(root / "missing")
            (root / "song.tex").write_bytes(source.read_bytes())
            # Do not normalize away a symlink followed by '..', or a relative parent.
            inputs = (leaf, dangling, link, link / "song.tex", link / "missing.tex",
                      link / ".." / "song.tex", Path(os.path.relpath(link / "song.tex")))
            for path in inputs:
                for mode in ("--check", "--diff", "--write"):
                    with self.subTest(path=path, mode=mode):
                        with patch.object(os, "walk") as walk, patch.object(os, "open") as open_file:
                            with patch.object(migration, "migrate_text") as migrate:
                                status, output, errors = self.run_cli(mode, str(path))
                        self.assertEqual(status, 1, errors)
                        self.assertEqual(output, "")
                        self.assertIn("symlink source", errors)
                        self.assertIn("0 would change; 1 need review.", errors)
                        walk.assert_not_called()
                        open_file.assert_not_called()
                        migrate.assert_not_called()
            self.assertEqual(source.read_bytes(), b"\\songcolumns{2}\r\n")
            self.assertTrue(link.is_symlink())
            self.assertTrue(leaf.is_symlink())

    def test_rejected_source_paths_do_not_block_other_safe_files(self) -> None:
        for mode in ("--check", "--diff", "--write"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                root = Path(directory)
                safe = root / "safe.tex"
                safe.write_bytes(b"\\songcolumns{2}\r\n")
                safe.chmod(0o640)
                link = root / "linked"
                link.symlink_to(root, target_is_directory=True)
                status, output, errors = self.run_cli(mode, str(link), str(safe))
                self.assertEqual(status, 1)
                self.assertIn("symlink source", errors)
                self.assertIn("Scanned 2 files; 1 would change; 1 need review.", errors)
                self.assertIn("songcolumns: 1", errors)
                self.assertEqual("+++ " + str(safe) in output, mode == "--diff")
                self.assertNotIn("+++ " + str(link), output)
                self.assertEqual(safe.read_bytes(), b"\\ulSongColumns{2}\r\n" if mode == "--write"
                                 else b"\\songcolumns{2}\r\n")
                self.assertEqual(stat.S_IMODE(safe.stat().st_mode), 0o640)

    def test_directory_discovery_skips_symlink_files_and_directories(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            source = real / "song.tex"
            source.touch()
            (root / "linked").symlink_to(real, target_is_directory=True)
            (root / "loop").symlink_to(root, target_is_directory=True)
            (root / "leaf.tex").symlink_to(source)
            (root / "dangling.tex").symlink_to(root / "missing")
            self.assertEqual(migration._paths([directory]), [source])

    def test_explicit_engine_and_generated_files_can_still_be_written(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            engine = self.make_engine(root / "engine")
            generated = root / "build" / "manual.sbx"
            generated.parent.mkdir()
            generated.write_text(r"\songcolumns{2}", encoding="utf-8")
            status, _, errors = self.run_cli("--write", directory, str(engine[3]), str(generated))
            self.assertEqual(status, 0, errors)
            self.assertIn("Scanned 2 files; 2 would change; 0 need review.", errors)
            for source in (engine[3], generated):
                self.assertEqual(source.read_text(), r"\ulSongColumns{2}")
            self.assertEqual(engine[2].read_text(), r"\songcolumns{2}")

    def test_nonregular_discovered_sources_reject_before_opening(self) -> None:
        with TemporaryDirectory() as directory:
            os.mkfifo(Path(directory) / "song.tex")
            with patch.object(os, "open") as open_file:
                status, output, errors = self.run_cli("--check", directory)
            self.assertEqual(status, 1, errors)
            self.assertEqual(output, "")
            self.assertIn("source must be a regular file", errors)
            open_file.assert_not_called()

    def test_source_replaced_by_fifo_at_open_rejects_without_blocking_batch(self) -> None:
        for mode in ("--check", "--diff", "--write"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                root = Path(directory)
                source, moved, safe = (root / name for name in ("a.tex", "moved", "z.tex"))
                original = b"\\songcolumns{2}\r\n"
                source.write_bytes(original)
                safe.write_bytes(original)
                safe.chmod(0o640)
                open_file = os.open

                def replace_leaf(path, flags, *args, source=source, moved=moved, open_file=open_file, **kwargs):
                    if Path(path) == source:
                        # Fail before opening if nonblocking protection is absent.
                        self.assertTrue(flags & os.O_NONBLOCK)
                        source.rename(moved)
                        os.mkfifo(source)
                    return open_file(path, flags, *args, **kwargs)

                with patch.object(os, "open", side_effect=replace_leaf):
                    status, output, errors = self.run_cli(mode, directory)
                self.assertEqual(status, 1, errors)
                self.assertIn("source must be a regular file", errors)
                self.assertIn("Scanned 2 files; 1 would change; 1 need review.", errors)
                self.assertEqual("+++ " + str(safe) in output, mode == "--diff")
                self.assertNotIn(str(source), output)
                self.assertTrue(stat.S_ISFIFO(source.stat().st_mode))
                self.assertEqual(moved.read_bytes(), original)
                self.assertEqual(safe.read_bytes(), b"\\ulSongColumns{2}\r\n" if mode == "--write" else original)
                self.assertEqual(stat.S_IMODE(safe.stat().st_mode), 0o640)
                self.assertEqual(set(root.iterdir()), {source, moved, safe})

    def test_directory_walk_errors_report_review_and_continue_safe_inputs(self) -> None:
        for mode in ("--check", "--diff", "--write"):
            for nested in (False, True):
                with self.subTest(mode=mode, nested=nested), TemporaryDirectory() as directory:
                    root = Path(directory)
                    selected, safe = root / "selected", root / "safe.tex"
                    selected.mkdir()
                    failed = selected / "unreadable" if nested else selected
                    failed.mkdir(exist_ok=True)
                    original = b"\\songcolumns{2}\r\n"
                    hidden = failed / "pending.tex"
                    hidden.write_bytes(original)
                    safe.write_bytes(original)
                    walk = os.walk

                    def failed_walk(path, nested=nested, selected=selected, failed=failed, **kwargs):
                        if nested:
                            yield str(selected), [failed.name], []
                        error = PermissionError(13, "Permission denied", str(failed))
                        if kwargs.get("onerror"):
                            kwargs["onerror"](error)

                    with patch.object(os, "walk", side_effect=failed_walk):
                        status, output, errors = self.run_cli(mode, str(selected), str(safe))
                    self.assertEqual(status, 1, errors)
                    self.assertIn(str(failed), errors)
                    self.assertIn("Permission denied", errors)
                    self.assertIn("Scanned 2 files; 1 would change; 1 need review.", errors)
                    self.assertEqual("+++ " + str(safe) in output, mode == "--diff")
                    self.assertNotIn(str(hidden), output)
                    self.assertEqual(hidden.read_bytes(), original)
                    self.assertEqual(safe.read_bytes(), b"\\ulSongColumns{2}\r\n" if mode == "--write" else original)
                    # Real traversal also reports unreadable roots/descendants.
                    failed.chmod(0)
                    try:
                        if not os.access(failed, os.R_OK | os.X_OK):
                            with patch.object(os, "walk", wraps=walk):
                                status, output, errors = self.run_cli(mode, str(selected))
                            self.assertEqual(status, 1, errors)
                            self.assertEqual(output, "")
                            self.assertIn("Permission denied", errors)
                            self.assertIn("0 would change; 1 need review.", errors)
                    finally:
                        failed.chmod(0o700)

    def test_leaf_swapped_at_open_is_not_followed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "song.tex", root / "target.tex"
            source.write_text(r"\songcolumns{2}", encoding="utf-8")
            open_file = os.open

            def replace_leaf(path, flags):
                self.assertTrue(flags & os.O_NOFOLLOW)
                source.rename(target)
                source.symlink_to(target)
                return open_file(path, flags)

            with patch.object(os, "open", side_effect=replace_leaf):
                with patch.object(migration, "migrate_text") as migrate:
                    status, output, errors = self.run_cli("--write", str(source))
            self.assertEqual(status, 1, errors)
            self.assertEqual(output, "")
            migrate.assert_not_called()
            self.assertTrue(source.is_symlink())
            self.assertEqual(target.read_text(), r"\songcolumns{2}")

    def test_source_parent_changed_after_discovery_is_rechecked_before_read(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "selected"
            parent.mkdir()
            source = parent / "song.tex"
            source.write_text(r"\songcolumns{2}", encoding="utf-8")
            moved = root / "moved"
            paths = migration._paths

            def replace_parent(values, **kwargs):
                selected = paths(values, **kwargs)
                parent.rename(moved)
                parent.symlink_to(moved, target_is_directory=True)
                return selected

            with patch.object(migration, "_paths", side_effect=replace_parent):
                with patch.object(migration, "migrate_text") as migrate:
                    status, output, errors = self.run_cli("--write", str(source))
            self.assertEqual(status, 1, errors)
            self.assertEqual(output, "")
            self.assertIn("symlink source", errors)
            migrate.assert_not_called()
            self.assertEqual((moved / source.name).read_text(), r"\songcolumns{2}")

    def test_symlink_introduced_after_read_is_rejected_before_write(self) -> None:
        for component in ("leaf", "parent"):
            with self.subTest(component=component), TemporaryDirectory() as directory:
                root = Path(directory)
                parent = root / "selected"
                parent.mkdir()
                source = parent / "song.tex"
                source.write_bytes(b"\\songcolumns{2}\r\n")
                migrate = migration.migrate_text
                target = root / "target"

                def replace_source(text, component=component, source=source, parent=parent,
                                   target=target, migrate=migrate, **kwargs):
                    if component == "leaf":
                        source.rename(target)
                        source.symlink_to(target)
                    else:
                        parent.rename(target)
                        parent.symlink_to(target, target_is_directory=True)
                    return migrate(text, **kwargs)

                with patch.object(migration, "migrate_text", side_effect=replace_source):
                    status, output, errors = self.run_cli("--write", str(source))
                self.assertEqual(status, 1, errors)
                self.assertEqual(output, "")
                self.assertIn("symlink source", errors)
                actual = target if component == "leaf" else target / source.name
                self.assertEqual(actual.read_bytes(), b"\\songcolumns{2}\r\n")
                self.assertEqual(list(source.parent.iterdir()), [source])

    def test_leaf_swapped_during_temp_write_rejects_publication_and_cleans_temp(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "song.tex", root / "target.tex"
            source.write_text(r"\songcolumns{2}", encoding="utf-8")
            fsync = os.fsync

            def replace_leaf(fd):
                fsync(fd)
                source.rename(target)
                source.symlink_to(target)

            with patch.object(os, "fsync", side_effect=replace_leaf):
                with patch.object(os, "replace") as replace:
                    status, output, errors = self.run_cli("--write", str(source))
            self.assertEqual(status, 1, errors)
            self.assertEqual(output, "")
            self.assertIn("symlink source", errors)
            replace.assert_not_called()
            self.assertEqual(target.read_text(), r"\songcolumns{2}")
            self.assertTrue(source.is_symlink())
            self.assertEqual(set(root.iterdir()), {source, target})


class OriginalSourceEditPlanTests(unittest.TestCase):
    def test_disjoint_plans_use_original_offsets_and_do_not_mutate_plans(self) -> None:
        source = r"\songcolumns{2} first second"
        naming = migration._plan_naming_edits(source)
        extra = migration._EditPlan(source)
        # Collect in reverse source order, with length-changing replacements.
        extra.edit(source.index("second"), len(source), "last", "test:second")
        extra.edit(source.index("first"), source.index("first") + 5, "expanded first", "test:first")
        for plans in ((naming, extra), (extra, naming)):
            with self.subTest(plans=plans):
                result = migration._apply_edit_plans(source, *plans)
                self.assertTrue(result.safe, result.diagnostics)
                self.assertEqual(result.text, r"\ulSongColumns{2} expanded first last")
                self.assertEqual(result.converted,
                                 {"songcolumns": 1, "test:first": 1, "test:second": 1})
        self.assertEqual(naming.source, source)
        self.assertEqual(naming.edits, {(0, 12): r"\ulSongColumns"})
        self.assertEqual(extra.converted, {"test:first": 1, "test:second": 1})

    def test_additional_diagnostic_rejects_all_plans_at_original_line_and_column(self) -> None:
        for prefix, column, counts in ((r"\songcolumns{2}", 16, {"songcolumns": 1}),
                                       (r"\ulSongColumns{2}", 18, {})):
            with self.subTest(prefix=prefix):
                source = "intro\r\n" + prefix + r"\reviewMarker A\else B\fi" + "\r\n"
                naming = migration._plan_naming_edits(source)
                extra = migration._EditPlan(source)
                extra.edit(0, 5, "changed\nheading", "test:heading")
                extra.issue(source.index(r"\reviewMarker"), "controlled review diagnostic")
                for plans in ((naming, extra), (extra, naming)):
                    result = migration._apply_edit_plans(source, *plans)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    self.assertEqual(result.diagnostics,
                                     [migration.Diagnostic(2, column, "controlled review diagnostic")])
                    self.assertEqual(result.converted, {**counts, "test:heading": 1})

    def test_naming_diagnostic_also_rejects_additional_edits(self) -> None:
        source = "intro\n" + r"\songcolumns{2}\songrefs"
        naming = migration._plan_naming_edits(source)
        extra = migration._EditPlan(source)
        extra.edit(0, 5, "changed\nheading", "test:heading")
        result = migration._apply_edit_plans(source, extra, naming)
        self.assertFalse(result.safe)
        self.assertEqual(result.text, source)
        self.assertEqual(result.diagnostics, naming.diagnostics)
        self.assertEqual((result.diagnostics[0].line, result.diagnostics[0].column), (2, 16))
        self.assertEqual(result.converted, {"songcolumns": 1, "test:heading": 1})

    def test_conflicts_and_overlaps_reject_without_plan_precedence(self) -> None:
        source = "prefix\nabcdef"
        for left, right in (
            ((7, 10, "X"), (7, 10, "Y")),  # Different replacements of one span.
            ((7, 10, "X"), (7, 10, "X")),  # Duplicate ownership is ambiguous too.
            ((7, 10, "X"), (9, 12, "Y")),  # Partial overlap.
            ((7, 12, "X"), (8, 10, "Y")),  # Containment.
            ((7, 10, "X"), (8, 8, "Y")),   # Insertion inside a replacement.
            ((8, 8, "X"), (8, 8, "Y")),    # Competing insertions.
            ((8, 8, "X"), (8, 8, "X")),
        ):
            with self.subTest(left=left, right=right):
                first, second = migration._EditPlan(source), migration._EditPlan(source)
                first.edit(*left, "test:first")
                second.edit(*right, "test:second")
                for plans in ((first, second), (second, first)):
                    result = migration._apply_edit_plans(source, *plans)
                    self.assertFalse(result.safe)
                    self.assertEqual(result.text, source)
                    self.assertIn("overlapping edits", result.diagnostics[0].message)
                    self.assertEqual(result.diagnostics[0].line, 2)
                    self.assertEqual(result.converted, {"test:first": 1, "test:second": 1})

    def test_collection_preserves_duplicate_counts_but_rejects_conflicting_values(self) -> None:
        plan = migration._EditPlan("abc")
        plan.edit(0, 3, "abc", "test:noop")
        plan.edit(0, 3, "X", "test:first")
        plan.edit(0, 3, "X", "test:duplicate")
        self.assertEqual(migration._apply_edit_plans("abc", plan).text, "X")
        self.assertEqual(plan.converted, {"test:first": 1})
        plan.edit(0, 3, "Y", "test:conflict")
        result = migration._apply_edit_plans("abc", plan)
        self.assertFalse(result.safe)
        self.assertEqual(result.text, "abc")
        self.assertEqual(result.diagnostics,
                         [migration.Diagnostic(1, 1, "conflicting edits to original source require review")])
        self.assertEqual(result.converted, {"test:first": 1})

    def test_conflict_with_naming_rejects_unrelated_naming_edits_too(self) -> None:
        source = "heading\n" + r"\songcolumns{2}\showtagsfalse"
        naming = migration._plan_naming_edits(source)
        extra = migration._EditPlan(source)
        extra.edit(source.index("songcolumns"), source.index("songcolumns") + 4,
                   "test", "test:overlap")
        for plans in ((naming, extra), (extra, naming)):
            result = migration._apply_edit_plans(source, *plans)
            self.assertFalse(result.safe)
            self.assertEqual(result.text, source)
            self.assertEqual(result.diagnostics,
                             [migration.Diagnostic(2, 2, "overlapping edits to original source require review")])
            self.assertEqual(result.converted,
                             {"songcolumns": 1, "showtagsfalse": 1, "test:overlap": 1})

    def test_adjacent_replacements_and_boundary_insertions_are_valid(self) -> None:
        source = "abcd"
        replacements, insertions = migration._EditPlan(source), migration._EditPlan(source)
        replacements.edit(0, 2, "L", "test:left")
        replacements.edit(2, 4, "R", "test:right")
        for pos, value in ((0, "<"), (2, "|"), (4, ">")):
            insertions.edit(pos, pos, value, "test:boundary")
        for plans in ((replacements, insertions), (insertions, replacements)):
            result = migration._apply_edit_plans(source, *plans)
            self.assertTrue(result.safe, result.diagnostics)
            self.assertEqual(result.text, "<L|R>")
            self.assertEqual(result.converted, {"test:left": 1, "test:right": 1, "test:boundary": 3})

    def test_chorus_zero_width_insertions_compose_at_command_boundaries(self) -> None:
        source = r"\begin{chorus}\songcolumns{2}\end{chorus}"
        naming = migration._plan_naming_edits(source)
        extra = migration._EditPlan(source)
        extra.edit(len(source), len(source), "% tail", "test:tail")
        result = migration._apply_edit_plans(source, extra, naming)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text,
                         r"\begin{verse}\beginrep \ulSongColumns{2}\endrep\end{verse}% tail")
        self.assertEqual(result.converted, {"environment:chorus": 2, "songcolumns": 1,
                                           "chorus:repeat-start": 1, "chorus:repeat-end": 1,
                                           "test:tail": 1})

    def test_invalid_ranges_and_changed_source_plans_are_rejected(self) -> None:
        source = r"\songcolumns{2}"
        naming = migration._plan_naming_edits(source)
        for start, end in ((-1, 1), (2, 1), (0, len(source) + 1)):
            with self.subTest(start=start, end=end):
                extra = migration._EditPlan(source)
                extra.edit(start, end, "X", "test:invalid")
                result = migration._apply_edit_plans(source, naming, extra)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, source)
                self.assertIn("edit range outside original source", result.diagnostics[0].message)
        changed = migration._EditPlan(r"\ulSongColumns{2}")
        changed.edit(0, 14, "X", "test:changed")
        result = migration._apply_edit_plans(source, naming, changed)
        self.assertFalse(result.safe)
        self.assertEqual(result.text, source)
        self.assertIn("unchanged original source", result.diagnostics[0].message)

    def test_public_migration_applies_once_and_already_v2_is_noop(self) -> None:
        source = r"\songcolumns{2}\showtagsfalse"
        with patch.object(migration, "_apply_edit_plans", wraps=migration._apply_edit_plans) as apply:
            first = migration.migrate_text(source)
            apply.assert_called_once()
        self.assertTrue(first.safe, first.diagnostics)
        self.assertEqual(first.text, r"\ulSongColumns{2}\ulShowTags{false}")
        second = migration.migrate_text(first.text)
        self.assertTrue(second.safe, second.diagnostics)
        self.assertEqual(second.text, first.text)
        self.assertFalse(second.converted)
        self.assertEqual(migration._apply_edit_plans(source), migration.Result(source))

    def test_combined_naming_plan_preserves_opaque_regions(self) -> None:
        opaque = ("% \\songcolumns{2}\n" + r"\verb|\songcolumns{2}|"
                  r"\url{https://test/\songcolumns{2}}"
                  r"\begin{verbatim}\songcolumns{2}\end{verbatim}"
                  r"\lilypond{ \songcolumns{2} }")
        source = opaque + r"\songcolumns{2} tail"
        extra = migration._EditPlan(source)
        extra.edit(len(source) - 4, len(source), "end", "test:tail")
        result = migration._apply_edit_plans(source, migration._plan_naming_edits(source), extra)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, opaque + r"\ulSongColumns{2} end")
        self.assertEqual(result.converted, {"songcolumns": 1, "test:tail": 1})

    def test_additional_plan_cli_rejection_suppresses_partial_diff_and_write(self) -> None:
        apply = migration._apply_edit_plans

        def with_controlled_review(source, *plans):
            extra = migration._EditPlan(source)
            if "REVIEW" in source:
                extra.edit(0, 0, "% inserted\n", "test:insertion")
                extra.issue(source.index("REVIEW"), "controlled review diagnostic")
            return apply(source, *plans, extra)

        for mode in ("--check", "--diff", "--write"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                safe, unsafe = Path(directory) / "safe.tex", Path(directory) / "unsafe.tex"
                safe.write_bytes(b"\\songcolumns{2}\r\n")
                unsafe_source = b"% heading\r\n\\songcolumns{2}REVIEW\r\n"
                unsafe.write_bytes(unsafe_source)
                safe.chmod(0o640)
                with patch.object(migration, "_apply_edit_plans", side_effect=with_controlled_review):
                    with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()) as errors:
                        self.assertEqual(migration.main([mode, directory]), 1)
                self.assertIn(f"{unsafe}:2:16: controlled review diagnostic", errors.getvalue())
                self.assertIn("songcolumns: 2", errors.getvalue())
                self.assertIn("test:insertion: 1", errors.getvalue())
                if mode == "--diff":
                    self.assertIn("+++ " + str(safe), output.getvalue())
                    self.assertNotIn(str(unsafe), output.getvalue())
                else:
                    self.assertEqual(output.getvalue(), "")
                self.assertEqual(unsafe.read_bytes(), unsafe_source)
                self.assertEqual(safe.read_bytes(), b"\\ulSongColumns{2}\r\n" if mode == "--write"
                                 else b"\\songcolumns{2}\r\n")
                self.assertEqual(stat.S_IMODE(safe.stat().st_mode), 0o640)
                self.assertEqual(sorted(p.name for p in Path(directory).iterdir()),
                                 ["safe.tex", "unsafe.tex"])


class TagFileMigrationTests(unittest.TestCase):
    def run_cli(self, *args: str) -> tuple[int, str, str]:
        with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()) as errors:
            status = migration.main(list(args))
        return status, output.getvalue(), errors.getvalue()

    def test_check_diff_write_default_rename_comments_newlines_and_permissions(self) -> None:
        for newline in (b"\n", b"\r\n", b"\r"):
            with self.subTest(newline=newline), TemporaryDirectory() as directory:
                path = Path(directory) / "tags.can"
                destination = path.with_suffix(".txt")
                source = newline.join([b"# ordered", b" Fire | flame ", b"% keep", b"", b"1",
                                       " Water | rivi\u00e8re ".encode(), b"1", b""])
                expected = newline.join([b"# ordered", b"Fire|flame", b"% keep", b"",
                                         "Water|rivi\u00e8re".encode(), b""])
                path.write_bytes(source)
                path.chmod(0o640)
                self.assertEqual(self.run_cli("--check", "--tags-file", str(path))[0], 1)
                status, diff, errors = self.run_cli("--diff", "--tags-file", str(path))
                self.assertEqual(status, 0)
                self.assertIn("--- " + str(path), diff)
                self.assertIn("+++ " + str(destination), diff)
                self.assertIn("-1", diff)
                self.assertIn(str(destination), errors)
                self.assertNotIn("\\ulTagFile", errors)
                self.assertEqual(path.read_bytes(), source)
                self.assertFalse(destination.exists())
                status, _, errors = self.run_cli("--write", "--tags-file", str(path))
                self.assertEqual(status, 0, errors)
                self.assertFalse(path.exists())
                self.assertEqual(destination.read_bytes(), expected)
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o640)
                self.assertEqual(self.run_cli("--check", "--tags-file", str(destination))[0], 0)
                self.assertEqual(self.run_cli("--diff", "--tags-file", str(destination))[1], "")
                with patch.object(migration, "_write_tags") as write:
                    self.assertEqual(self.run_cli("--write", "--tags-file", str(destination))[0], 0)
                    write.assert_not_called()
                self.assertEqual(destination.read_bytes(), expected)
                self.assertEqual(list(Path(directory).iterdir()), [destination])

    def test_custom_extension_notice_and_no_final_newline(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "custom.legacy"
            path.write_bytes(b"Fire|flame\n1")
            status, _, errors = self.run_cli("--write", "--tags-file", str(path))
            destination = path.with_suffix(".txt")
            self.assertEqual(status, 0, errors)
            self.assertIn("\\ulTagFile{" + str(destination) + "}", errors)
            self.assertEqual(destination.read_bytes(), b"Fire|flame")

    def test_txt_normalization_retains_definitions_comments_and_no_final_newline(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tags.txt"
            path.write_bytes(b"% retained\r\n  Fire | flame \r\n\r\nWater")
            self.assertEqual(self.run_cli("--check", "--tags-file", str(path))[0], 1)
            self.assertEqual(self.run_cli("--write", "--tags-file", str(path))[0], 0)
            self.assertEqual(path.read_bytes(), b"% retained\r\nFire|flame\r\n\r\nWater")
            self.assertEqual(self.run_cli("--check", "--tags-file", str(path))[0], 0)

    def test_malformed_definitions_never_write_or_show_partial_diff(self) -> None:
        for suffix, source in (
            (".can", b"Fire\n1\nWater\n2\n"),
            (".can", b"Fire\n1 1\n"), (".can", b"Fire\n01\n"),
            (".can", b"Fire\n"), (".can", b"Fire\n1\nWater\n% end"),
            (".can", b"Fire||flame\n1\n"), (".can", b"Fire|\n1\n"),
            (".can", b"|Fire\n1\n"), (".can", b"123\n1\n"),
            (".txt", b"Fire\n1\n"), (".txt", b"123 456\n"),
            (".txt", b"Fire|flame,burning\n"), (".can", b"Fire;flame\n1\n"),
            (".txt", b"# comments only\n\n% no definitions"), (".can", b""),
            (".txt", b"Fire|  |flame\n"), (".can", b"\xff\n1\n"),
        ):
            with self.subTest(suffix=suffix, source=source), TemporaryDirectory() as directory:
                path = Path(directory) / ("tags" + suffix)
                path.write_bytes(source)
                for mode in ("--check", "--diff", "--write"):
                    status, output, _ = self.run_cli(mode, "--tags-file", str(path))
                    self.assertEqual(status, 1)
                    self.assertEqual(output, "")
                    self.assertEqual(path.read_bytes(), source)
                    self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_digit_ending_names_and_numeric_aliases_remain_literal(self) -> None:
        source = "Phase 1|123\nFire 2\n"
        result = migration.migrate_tags_text(source, legacy=False)
        self.assertTrue(result.safe, result.diagnostics)
        self.assertEqual(result.text, source)

    def test_comments_and_blank_lines_before_final_unterminated_count_are_preserved(self) -> None:
        for source, expected in (("Fire\n# keep\n1", "Fire\n# keep\n"),
                                 ("Fire\n\n1", "Fire\n\n")):
            with self.subTest(source=source):
                result = migration.migrate_tags_text(source, legacy=True)
                self.assertTrue(result.safe, result.diagnostics)
                self.assertEqual(result.text, expected)

    def test_collision_and_symlink_destinations_are_never_clobbered(self) -> None:
        for kind in ("file", "symlink", "dangling", "directory"):
            with self.subTest(kind=kind), TemporaryDirectory() as directory:
                path = Path(directory) / "tags.can"
                path.write_bytes(b"Fire\n1\n")
                target = Path(directory) / "target"
                target.write_bytes(b"untouched")
                destination = path.with_suffix(".txt")
                if kind == "file":
                    destination.write_bytes(b"existing")
                elif kind == "directory":
                    destination.mkdir()
                else:
                    destination.symlink_to(target if kind == "symlink" else target.with_name("missing"))
                for mode in ("--check", "--diff", "--write"):
                    status, output, errors = self.run_cli(mode, "--tags-file", str(path))
                    self.assertEqual(status, 1)
                    self.assertIn("already exists", errors)
                    self.assertEqual(output, "")
                self.assertEqual(path.read_bytes(), b"Fire\n1\n")
                self.assertEqual(target.read_bytes(), b"untouched")
                if kind == "file":
                    self.assertEqual(destination.read_bytes(), b"existing")
                elif kind != "directory":
                    self.assertTrue(destination.is_symlink())

    def test_symlink_source_and_parent_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "tags.can"
            path.write_bytes(b"Fire\n1\n")
            link = root / "link.can"
            link.symlink_to(path)
            parent_link = root / "parent"
            parent_link.symlink_to(root, target_is_directory=True)
            for source in (link, parent_link / path.name):
                status, _, errors = self.run_cli("--write", "--tags-file", str(source))
                self.assertEqual(status, 1)
                self.assertIn("symlink", errors)
                self.assertEqual(path.read_bytes(), b"Fire\n1\n")
            self.assertFalse(path.with_suffix(".txt").exists())

    def test_publish_failure_and_destination_race_preserve_original(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tags.can"
            path.write_bytes(b"Fire\n1\n")
            with patch.object(os, "link", side_effect=OSError("publish failed")):
                self.assertEqual(self.run_cli("--write", "--tags-file", str(path))[0], 1)
            self.assertEqual(list(Path(directory).iterdir()), [path])
            self.assertEqual(path.read_bytes(), b"Fire\n1\n")
            original_link = os.link

            def collision(source, destination):
                destination.write_bytes(b"racing file")
                original_link(source, destination)

            with patch.object(os, "link", side_effect=collision):
                self.assertEqual(self.run_cli("--write", "--tags-file", str(path))[0], 1)
            self.assertEqual(path.read_bytes(), b"Fire\n1\n")
            self.assertEqual(path.with_suffix(".txt").read_bytes(), b"racing file")
            self.assertEqual(len(list(Path(directory).iterdir())), 2)

    def test_nonregular_tag_sources_are_rejected_before_opening(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fifo = root / "tags.can"
            os.mkfifo(fifo)
            for source in (fifo, root):
                with self.subTest(source=source), patch.object(os, "open") as open_file:
                    status, _, errors = self.run_cli("--check", "--tags-file", str(source))
                    self.assertEqual(status, 1)
                    self.assertIn("regular file", errors)
                    open_file.assert_not_called()

    def test_txt_replace_failure_preserves_original_and_cleans_temp(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tags.txt"
            path.write_bytes(b" Fire | flame \r\n")
            with patch.object(os, "replace", side_effect=OSError("replace failed")):
                self.assertEqual(self.run_cli("--write", "--tags-file", str(path))[0], 1)
            self.assertEqual(path.read_bytes(), b" Fire | flame \r\n")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_unlink_failure_leaves_original_and_successfully_published_destination(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tags.can"
            path.write_bytes(b"Fire\n1\n")
            with patch.object(Path, "unlink", side_effect=OSError("unlink failed")):
                status, _, errors = self.run_cli("--write", "--tags-file", str(path))
            self.assertEqual(status, 1)
            self.assertIn("unlink failed", errors)
            self.assertEqual(path.read_bytes(), b"Fire\n1\n")
            self.assertEqual(path.with_suffix(".txt").read_bytes(), b"Fire\n")
            self.assertEqual(len(list(Path(directory).iterdir())), 2)

    def test_missing_tag_file_and_directory_fail_safely(self) -> None:
        with TemporaryDirectory() as directory:
            for path in (Path(directory) / "missing.can", Path(directory)):
                status, _, _ = self.run_cli("--write", "--tags-file", str(path))
                self.assertEqual(status, 1)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_combined_invocation_and_source_only_reminder_without_can_scan(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            tags = root / "tags.can"
            tags.write_bytes(b"Fire\n1\n")
            source = root / "book.tex"
            source.write_text(r"\newscripindex{tagidx}{idx_tags}\ulTagFile{tags.can}")
            status, _, errors = self.run_cli("--write", directory)
            self.assertEqual(status, 0, errors)
            self.assertIn("Reminder", errors)
            self.assertIn("--tags-file", errors)
            self.assertTrue(tags.exists())
            self.assertEqual(source.read_text(), r"\ulNewTagIndex{tagidx}{idx_tags}\ulTagFile{tags.can}")
            status, _, errors = self.run_cli("--write", str(source), "--tags-file", str(tags), directory)
            self.assertEqual(status, 0, errors)
            self.assertNotIn("Reminder", errors)
            self.assertFalse(tags.exists())
            self.assertEqual(tags.with_suffix(".txt").read_bytes(), b"Fire\n")

    def test_modes_and_inputs_remain_required(self) -> None:
        for args in ([], ["--check"], ["--tags-file", "tags.can"], ["--check", "--write", "x.tex"]):
            with self.subTest(args=args), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                migration.main(args)


def installed_migration_smoke(*, container: bool = False) -> None:
    """Opt-in offline wheel/entry-point evidence; leave the checkout untouched."""
    from installer import install
    from installer.destinations import SchemeDictionaryDestination
    from installer.sources import WheelFile
    from test_modules import ModulePackagingSmoke

    check = unittest.TestCase()
    package = ModulePackagingSmoke
    try:
        package.build()
        # Check the semantic collector AND its installed dependencies against the
        # live source, rather than accidentally exercising an older local install.
        root = Path(__file__).resolve().parents[1]
        names = ("tools/migrate_syntax_v2.py", "tools/naming_v2.py", "variants.py",
                 "assets/tex/ulsbs-variants.def.tex")
        with zipfile.ZipFile(package.wheel) as wheel, tarfile.open(package.sdist) as sdist:
            prefix = sdist.getnames()[0].split("/")[0]
            for name in names:
                expected = (root / "src/ulsbs" / name).read_bytes()
                check.assertEqual(wheel.read("ulsbs/" + name), expected)
                member = sdist.extractfile(prefix + "/src/ulsbs/" + name)
                check.assertIsNotNone(member)
                check.assertEqual(member.read(), expected)
        installed = package.work / "installed"
        library = installed / "lib"
        scheme = {key: str(installed / key) for key in ("headers", "scripts", "data")}
        scheme.update(purelib=str(library), platlib=str(library))
        with WheelFile.open(package.wheel) as wheel:
            install(wheel, SchemeDictionaryDestination(scheme, sys.executable, "posix"),
                    additional_metadata={})
        launcher = installed / "scripts/ulsbs-migrate-syntax-v2"
        check.assertTrue(os.access(launcher, os.X_OK))
        # Execute the generated script in isolated Python, adding only the wheel's
        # library. -I ignores inherited PYTHONPATH and the checkout's working path.
        runner = ("import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); "
                  "from pathlib import Path; from ulsbs.tools import migrate_syntax_v2 as m; "
                  "assert Path(m.__file__).is_relative_to(sys.path[0]); "
                  "runpy.run_path(sys.argv.pop(1),run_name='__main__')")
        fixture = package.work / "independent"
        fixture.mkdir()
        source = (b"%% ULSBS-EXTRA-VARIANTS: charango,bassclef\r\n"
                  b"\\documentclass[subtitle={Independent, book}]{ulsbs-songbook-third-party}[2020/01/01]"
                  b"\\showtagsfalse\\songcolumns{2}\\begin{document}"
                  b"\\showbeatsfalse\\measuresfalse"
                  b"\\ifbassclefbook\\newpage\\else\\ifulCharangoBook\\clearpage\\fi\\fi\r\n")
        expected = (b"%% \r\n\\documentclass[variants={default,lyric,charango,bassclef},"
                    b"subtitle={Independent, book}]{ulsbs-songbook-third-party}[2020/01/01]"
                    b"\\ulShowTags{false}\\ulSongColumns{2}\\begin{document}"
                    b"\\ulLocalShow{beats}{false}\\ulLocalShow{measures}{false}"
                    b"\\ulIfVariant{bassclef}{\\relax\\newpage}{\\relax"
                    b"\\ulIfVariant{charango}{\\relax\\clearpage}{}\\relax}\\relax\r\n")
        safe, rejected, boundary, dates, dispatch, config, obsolete = (fixture / name for name in (
            "book.tex", "review.tex", "boundary.tex", "dates.tex", "dispatch.tex", "current.toml", "obsolete.toml"))
        boundary_source = (b"\\begin{document}\\songcolumns{2}"
                           b'\\ulSongColumns{\\directlua{token.set_macro("ulIfVariant","")}1}'
                           b"\\ifbassclefbook\\newpage\\else\\clearpage\\fi")
        dispatch_source = (b"\\songcolumns{2}\r\n"
                           b"\\DeclareOption{body}{\\begin{document}}\\ExecuteOptions{body}\\relax\\showtagsfalse")
        for path, data in ((safe, source), (rejected, source + b"\\chordsoff"),
                           (boundary, boundary_source),
                           (dates, b"\\documentclass{article}[2020/01/01\\begin{document}]"
                                   b"\\relax\\ulShowTags{false}\r\n"),
                           (dispatch, dispatch_source),
                           (config, b'variants = ["default", "lyric"]\r\n'),
                           (obsolete, b"lyricbooks = true\r\n")):
            path.write_bytes(data)
            path.chmod(0o640)

        def snapshot(path):
            status = path.stat()
            return path.read_bytes(), status.st_ino, status.st_mtime_ns, stat.S_IMODE(status.st_mode)

        protected = {path: snapshot(path) for path in (rejected, boundary, dates, dispatch, config, obsolete)}
        python = [sys.executable]
        if container:
            # Build/install offline on the host; the supported image needs no
            # packaging dependencies and sees no source checkout at execution.
            python = ["docker", "run", "--rm", "--read-only", "--user", f"{os.getuid()}:{os.getgid()}",
                      "--workdir", str(fixture), "--env", "HOME=/tmp", "--env", "NO_COLOR=1",
                      "--mount", f"type=bind,src={package.work},dst={package.work}",
                      "--mount", "type=tmpfs,tmpfs-size=64m,dst=/tmp",
                      "ulsbs-compiler", "python3"]

        def run(mode, *paths, status):
            result = subprocess.run(
                [*python, "-I", "-B", "-c", runner, str(library), str(launcher), mode,
                 *map(str, paths)], cwd=fixture, text=True, capture_output=True, timeout=30,
                check=False)
            check.assertEqual(result.returncode, status, result.stdout + result.stderr)
            return result

        dry = snapshot(safe)
        for mode in ("--check", "--diff", "--write"):
            result = run(mode, safe, rejected, boundary, dates, dispatch, "--config-file", config,
                         "--config-file", obsolete, status=1)
            check.assertIn("Scanned 7 files; 1 would change; 4 need review.", result.stderr)
            check.assertIn(str(rejected) + ":3:1: legacy broad", result.stderr)
            column = boundary_source.index(b"\\ifbassclefbook") + 1
            check.assertIn(f"{boundary}:1:{column}: legacy variant identity", result.stderr)
            column = dispatch_source.index(b"\\showtagsfalse") - dispatch_source.rfind(b"\n")
            check.assertIn(f"{dispatch}:2:{column}: display setter", result.stderr)
            check.assertIn(str(obsolete) + ":1:1:", result.stderr)
            check.assertEqual("+++ " + str(safe) in result.stdout, mode == "--diff")
            for path in protected:
                check.assertNotIn("+++ " + str(path), result.stdout)
                check.assertEqual(snapshot(path), protected[path])
            check.assertEqual(safe.read_bytes(), expected if mode == "--write" else source)
            check.assertEqual(stat.S_IMODE(safe.stat().st_mode), 0o640)
            if mode != "--write":
                check.assertEqual(snapshot(safe), dry)
        stable = snapshot(safe)
        for mode in ("--check", "--diff", "--write"):
            result = run(mode, safe, dates, "--config-file", config, status=0)
            check.assertEqual(result.stdout, "")
            check.assertIn("0 would change; 0 need review.", result.stderr)
            check.assertEqual(snapshot(safe), stable)
            check.assertEqual(snapshot(config), protected[config])
            check.assertEqual(snapshot(dates), protected[dates])
        # Also exercise OS shebang dispatch, not just the entry-point body. Only
        # the installed library is on PYTHONPATH; no checkout path is inherited.
        environment = dict(os.environ, PYTHONPATH=str(library), PYTHONDONTWRITEBYTECODE="1")
        environment.pop("PYTHONHOME", None)
        direct = [str(launcher), "--check", str(safe), str(dates), "--config-file", str(config)]
        if container:
            direct = [*python[:-1], "env", f"PYTHONPATH={library}", "PYTHONDONTWRITEBYTECODE=1", *direct]
        result = subprocess.run(direct, cwd=fixture, env=environment, text=True, capture_output=True,
                                check=False, timeout=30)
        check.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        check.assertEqual(result.stdout, "")
        check.assertIn("0 would change; 0 need review.", result.stderr)
        check.assertEqual(snapshot(safe), stable)
        check.assertEqual(snapshot(config), protected[config])
        check.assertEqual(snapshot(dates), protected[dates])
        check.assertEqual(set(fixture.iterdir()), {safe, rejected, boundary, dates, dispatch, config, obsolete})
        print("Offline wheel/sdist/isolated installed v2 semantic entry-point smoke passed")
    finally:
        if hasattr(package, "temporary"):
            package.temporary.cleanup()


if __name__ == "__main__":
    if sys.argv[1:] in (["--installed-smoke"], ["--installed-smoke-container"]):
        installed_migration_smoke(container=sys.argv[1] == "--installed-smoke-container")
    else:
        unittest.main()
