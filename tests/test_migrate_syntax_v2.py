from __future__ import annotations

import os
import stat
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ulsbs.tools import migrate_syntax_v2 as migration


COMMANDS = {"songcolumns": "ulSongColumns", "ifchorded": "ifulChorded", "old": "ulOld"}
BOOLEANS = {"showtagstrue": ("ulShowTags", "true"), "showtagsfalse": ("ulShowTags", "false")}
NAMES = {
    "counter": {"songnum": "ulSongNumber"},
    "color": {"songblue": "ulSongBlue", "songred": "ulSongRed"},
    "environment": {"songs": "ulSongs"},
}


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
            r"\songcolumns{2} songcolumns \songcolumnsExtra \oldish \old@tail \ifchorded",
            r"\ulSongColumns{2} songcolumns \songcolumnsExtra \oldish \ulOld@tail \ifulChorded")

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
            r"\href{https://example.test/a%20b#section}{\old{}\showtagstrue}",
            r"\href{https://example.test/a%20b#section}{\ulOld{}\ulShowTags{true}}")
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
        self.assert_conversion(
            r"\showtagstrue{}word \showtagsfalse @ \def\foo#1{\showtagstrue#1}"
            r"\newcommand*{\foo}[1][x]{\showtagsfalse #1}"
            r"\RenewDocumentCommand\foo{m}{\showtagstrue#1}"
            r"\AtBeginDocument{\showtagstrue}",
            r"\ulShowTags{true}{}word \ulShowTags{false} @ \def\foo#1{\ulShowTags{true}#1}"
            r"\newcommand*{\foo}[1][x]{\ulShowTags{false} #1}"
            r"\RenewDocumentCommand\foo{m}{\ulShowTags{true}#1}"
            r"\AtBeginDocument{\ulShowTags{true}}")

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
            "\\sclearpage\\showtagstrue\n\\endverse\n\\showtagsfalse\n\\appendix\\showtagstrue",
            "\\sclearpage\\ulShowTags{true}\n\\endverse\n\\ulShowTags{false}\n\\appendix\\ulShowTags{true}")

    def test_standard_obeylines_preserves_active_newlines(self) -> None:
        self.assert_conversion("{\\obeylines\n\\showtagstrue\n\\old\n}",
                               "{\\obeylines\n\\ulShowTags{true}\n\\ulOld\n}")

    def test_group_after_known_zero_argument_command_is_not_an_argument(self) -> None:
        self.assert_conversion("\\appendix\n{% standalone group\n\\showtagsfalse\n}",
                               "\\appendix\n{% standalone group\n\\ulShowTags{false}\n}")
        self.assert_conversion(r"\ifchorded{\showtagstrue}\fi",
                               r"\ifulChorded{\ulShowTags{true}}\fi")

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
            r"\newenvironment{songs}[1]{\showtagstrue#1}{\showtagsfalse}"
            r"\begin{songs}songs\end{songs}",
            r"\newenvironment{ulSongs}[1]{\ulShowTags{true}#1}{\ulShowTags{false}}"
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
        self.assert_conversion(r"\AddToHook{begindocument}[mine]{\showtagstrue}",
                               r"\AddToHook{begindocument}[mine]{\ulShowTags{true}}")
        self.assert_conversion(r"\AtBeginEnvironment{songs}{\showtagstrue}",
                               r"\AtBeginEnvironment{ulSongs}{\ulShowTags{true}}")

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

    def test_each_public_mapping_is_directly_migratable(self) -> None:
        from ulsbs.tools.naming_v2 import BOOLEAN_SETTERS, COMMAND_RENAMES
        for old, new in COMMAND_RENAMES.items():
            with self.subTest(command=old):
                result = migration.migrate_text("\\" + old)
                self.assertTrue(result.safe, result.diagnostics)
                self.assertEqual(result.text, "\\" + new)
        for old, (setter, value) in BOOLEAN_SETTERS.items():
            with self.subTest(boolean=old):
                result = migration.migrate_text("\\" + old)
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


if __name__ == "__main__":
    unittest.main()
