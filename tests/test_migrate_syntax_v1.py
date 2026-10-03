from __future__ import annotations

import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from ulsbs.tools.migrate_syntax_v1 import main, migrate_text


class MigrateSyntaxV1Tests(unittest.TestCase):
    def test_primary_sequences_beats_offsets_and_chord_remainder(self) -> None:
        result = migrate_text(r"\[^\bmc\mnc{C}\bm\mncii{D}{E}Am]")
        self.assertTrue(result.safe)
        self.assertEqual(result.text, r"\[^<* C * D E>Am]")

    def test_replay_token_stays_with_the_chord_remainder(self) -> None:
        result = migrate_text(r"\[^\mnc{C}]")
        self.assertTrue(result.safe)
        # ^ remains the leading songs replay control before the melody block.
        self.assertEqual(result.text, r"\[^<C>]")

    def test_chord_macros_after_the_leading_layer_are_preserved(self) -> None:
        result = migrate_text(r"\[\mnc{C}\ac<1>{Am}\ac<2>{G}]")
        self.assertTrue(result.safe)
        self.assertEqual(result.text, r"\[<C>\ac{1}{Am}\ac{2}{G}]")

    def test_later_legacy_command_is_not_hoisted_or_doubly_reported(self) -> None:
        source = r"\[Am\mnc{C}]"
        result = migrate_text(source)
        self.assertFalse(result.safe)
        self.assertEqual(result.text, source)
        self.assertEqual(len(result.diagnostics), 1)
        self.assertIn("follows chord content", result.diagnostics[0].message)

    def test_slash_is_a_rendered_one_slot_marker(self) -> None:
        result = migrate_text(r"\[\mn{/}\mn{C}]")
        self.assertTrue(result.safe)
        self.assertEqual(result.text, r"\[</ C>]")

    def test_all_directly_representable_legacy_commands(self) -> None:
        cases = {
            r"\[\mn{C}]": r"\[<C>]",
            r"\[\mnc{C}Am]": r"\[<C>Am]",
            r"\[\mncadj{-.3em}{C}Am]": r"\[<C @ -.3em>Am]",
            r"\[\mncii{C}{D}]": r"\[<C D>]",
            r"\[\mnciii{C}{D}{E}]": r"\[<C D E>]",
            r"\[\mnciv{C}{D}{E}{F}]": r"\[<C D E F>]",
            r"\[\mncv{C}{D}{E}{F}{G}]": r"\[<C D E F G>]",
            r"\[\mncvi{C}{D}{E}{F}{G}{A}]": r"\[<C D E F G A>]",
            r"\[\mau{E}]": r"\[<;E>]",
            r"\[\mauc{E}Am]": r"\[<;E>Am]",
            r"\[\mauii{E}{C}]": r"\[<C;E>]",
            r"\[\mauiic{E}{C}Am]": r"\[<C;E>Am]",
            r"\[\bm]": r"\[<*>]",
            r"\[\bmc]": r"\[<*>]",
            r"\[\bmadj{-.5ex}]": r"\[<* @ -.5ex>]",
            r"\[\bmcadj{.5ex}]": r"\[<* @ .5ex>]",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                result = migrate_text(source)
                self.assertTrue(result.safe)
                self.assertEqual(result.text, expected)

    def test_balanced_arguments_and_comments_are_scanned_safely(self) -> None:
        source = "\\[\\mnc { C# } % \\mnc{D}\n Am]\n% \\[\\mnc{E}]\n\\verb|\\[\\mnc{F}]|"
        result = migrate_text(source)
        self.assertTrue(result.safe)
        self.assertIn("\\[<C#> % \\mnc{D}\n Am]", result.text)
        self.assertIn("% \\[\\mnc{E}]", result.text)
        self.assertIn("\\verb|\\[\\mnc{F}]|", result.text)

    def test_pair_is_secondary_first_and_below_is_hoisted_to_verse(self) -> None:
        source = "\\beginverse\n\\[\\madii{E}{C}Am]\n\\endverse\n"
        result = migrate_text(source)
        self.assertTrue(result.safe)
        self.assertEqual(
            result.text,
            "\\beginverse\n\\melodySecondaryPosition{below}\n\\[<C;E>Am]\n\\endverse\n",
        )

    def test_above_pair_and_style_mapping(self) -> None:
        result = migrate_text("\\usealtmnstyletrue\\[\\mauiic{E}{C}Am]")
        self.assertTrue(result.safe)
        self.assertEqual(result.text, "\\melodyStyleMapping{swapped}\\[<C;E>Am]")

    def test_beats_keep_their_order_with_a_paired_command(self) -> None:
        result = migrate_text(r"\[\bmc\mauiic{E}{C}\bm Am]")
        self.assertTrue(result.safe)
        self.assertEqual(result.text, r"\[<* C *;E> Am]")

    def test_low_requires_explicit_opt_in(self) -> None:
        self.assertFalse(migrate_text(r"\[\mnd{C}] ").safe)
        result = migrate_text("\\beginverse\n\\[\\mnd{C}]\n\\endverse", normalize_low=True)
        self.assertTrue(result.safe)
        self.assertEqual(result.text, "\\beginverse\n\\[<C>]\n\\endverse")

    def test_low_normalization_never_changes_verse_spacing(self) -> None:
        self.assertEqual(migrate_text(r"\[\mnd{C}]", normalize_low=True).text, r"\[<C>]")
        source = "\\beginverse*+[2]\n\\[\\mnd{C}]\n\\endverse"
        result = migrate_text(source, normalize_low=True)
        self.assertTrue(result.safe)
        self.assertEqual(result.text, "\\beginverse*+[2]\n\\[<C>]\n\\endverse")

    def test_unsafe_cases_leave_original_unchanged(self) -> None:
        source = r"\[\mnc{C#7}\mnc{D}]"
        result = migrate_text(source)
        self.assertFalse(result.safe)
        self.assertEqual(result.text, source)
        self.assertIn("unsupported melody marker", result.diagnostics[0].message)

    def test_baseline_alternates_use_same_position_policy(self) -> None:
        source = "\\beginverse\n\\[\\ma{E}]\\n\\[\\mac{F}Am]\\n\\endverse"
        result = migrate_text(source)
        self.assertTrue(result.safe)
        self.assertEqual(
            result.text,
            "\\beginverse\n\\melodySecondaryPosition{same}\n\\[<;E>]\\n\\[<;F>Am]\\n\\endverse",
        )

    def test_nonuniform_same_position_uses_a_local_group(self) -> None:
        source = "\\beginverse\n\\[\\ma{E}]\n\\[\\mauiic{F}{C}]\n\\endverse"
        result = migrate_text(source)
        self.assertTrue(result.safe)
        self.assertEqual(
            result.text,
            "\\beginverse\n{\\melodySecondaryPosition{same}\\[<;E>]}\n\\[<C;F>]\n\\endverse",
        )

    def test_same_position_uses_existing_melody_aware_verse_scope(self) -> None:
        source = "\\beginverse*+[2]\n\\[\\ma{E}]\n\\endverse"
        result = migrate_text(source)
        self.assertTrue(result.safe)
        self.assertEqual(
            result.text,
            "\\beginverse*+[2]\n\\melodySecondaryPosition{same}\n\\[<;E>]\n\\endverse",
        )

    def test_legacy_verse_start_variants_and_independent_endings(self) -> None:
        for suffix, expected in (("", "+"), ("*", "*+"), ("[2]", "+[2]"), ("*[2]", "*+[2]")):
            for ending in (r"\mnendverse", r"\endverse"):
                with self.subTest(suffix=suffix, ending=ending):
                    source = rf"\mnbeginverse{suffix} words {ending}"
                    result = migrate_text(source)
                    self.assertTrue(result.safe)
                    self.assertEqual(result.text, rf"\beginverse{expected} words \endverse")
                    self.assertEqual(result.converted["mnbeginverse"], 1)
                    self.assertEqual(result.converted["mnendverse"], int(ending == r"\mnendverse"))
        result = migrate_text(r"\beginverse words \mnendverse")
        self.assertTrue(result.safe)
        self.assertEqual(result.text, r"\beginverse words \endverse")

    def test_adjacent_commands_and_scope_after_verse_conversion(self) -> None:
        source = "\\mnbeginverse*[2]\\[\\ma{E}]\\mnendverse\\glueverses\\beginverse+\\[\\madii{F}{C}]\\endverse"
        result = migrate_text(source)
        self.assertTrue(result.safe)
        self.assertEqual(result.text, "\\beginverse*+[2]\n\\melodySecondaryPosition{same}\\[<;E>]\\endverse\\glueverses\\beginverse+\n\\melodySecondaryPosition{below}\\[<C;F>]\\endverse")

    def test_verse_migration_protects_comments_and_verbatim(self) -> None:
        source = ("% \\mnbeginverse \\mnendverse\n"
                  "\\verb|\\mnbeginverse*[2]\\mnendverse|\n"
                  "\\begin{verbatim}\\mnbeginverse\\mnendverse\\end{verbatim}\n"
                  "\\mnbeginverse\\mnendverse")
        result = migrate_text(source)
        self.assertTrue(result.safe)
        self.assertEqual(result.text, source.replace("\n\\mnbeginverse\\mnendverse", "\n\\beginverse+\\endverse"))
        self.assertEqual(result.converted["mnbeginverse"], 1)
        self.assertEqual(result.converted["mnendverse"], 1)

    def test_malformed_verse_modifiers_are_transactional(self) -> None:
        for source in (r"\mnbeginverse**", r"\mnbeginverse+[2]", r"\mnbeginverse[2]*",
                       r"\mnbeginverse[bad]", r"\mnbeginverse[2", r"\mnendverse[2]",
                       r"\mnendverse*"):
            with self.subTest(source=source):
                original = source + r" \[\mnc{C}] \mnendverse"
                result = migrate_text(original)
                self.assertFalse(result.safe)
                self.assertEqual(result.text, original)
                self.assertIn("malformed", result.diagnostics[0].message)

    def test_verse_migration_is_idempotent(self) -> None:
        first = migrate_text(r"\mnbeginverse*[2]\mnendverse")
        second = migrate_text(first.text)
        self.assertTrue(first.safe)
        self.assertTrue(second.safe)
        self.assertEqual(second.text, first.text)
        self.assertFalse(second.converted)

    def test_spaced_numeric_option_remains_in_verse_scope(self) -> None:
        source = "\\mnbeginverse* [2]\n\\[\\ma{E}]\n\\mnendverse"
        result = migrate_text(source)
        self.assertTrue(result.safe)
        self.assertEqual(result.text, "\\beginverse*+ [2]\n\\melodySecondaryPosition{same}\n\\[<;E>]\n\\endverse")

    def test_verse_rewrites_roll_back_on_other_migration_failure(self) -> None:
        source = r"\mnbeginverse\[\mnc{C#7}]\mnendverse"
        result = migrate_text(source)
        self.assertFalse(result.safe)
        self.assertEqual(result.text, source)

    def test_cli_verse_counts_and_second_write_is_noop(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "song.tex"
            path.write_text(r"\mnbeginverse*\mnendverse", encoding="utf-8")
            output = StringIO()
            with redirect_stderr(output):
                self.assertEqual(main(["--write", str(path)]), 0)
            self.assertEqual(path.read_text(encoding="utf-8"), r"\beginverse*+\endverse")
            self.assertIn("1 would change", output.getvalue())
            self.assertIn(r"\mnbeginverse: 1", output.getvalue())
            self.assertIn(r"\mnendverse: 1", output.getvalue())
            output = StringIO()
            with redirect_stderr(output):
                self.assertEqual(main(["--check", str(path)]), 0)
            self.assertIn("0 would change", output.getvalue())

    def test_low_secondary_requires_opt_in(self) -> None:
        self.assertFalse(migrate_text(r"\[\mad{E}]").safe)
        result = migrate_text("\\beginverse\n\\[\\mad{E}]\n\\endverse", normalize_low=True)
        self.assertTrue(result.safe)
        self.assertEqual(result.text, "\\beginverse\n\\[<;E>]\n\\endverse")

    def test_alternate_chord_selector_migration(self) -> None:
        source = r"\[\mnc{C}\ac<1>{Em}] \altchords{|\ac<2>{Am}} \[\ac<3>F#]"
        result = migrate_text(source)
        self.assertTrue(result.safe)
        self.assertEqual(
            result.text,
            r"\[<C>\ac{1}{Em}] \altchords{|\ac{2}{Am}} \[\ac{3}{F#}]",
        )
        self.assertEqual(result.converted["ac"], 3)

    def test_alternate_chord_migration_skips_comments(self) -> None:
        source = "% \\ac<1>{C}\n\\[\\ac<2>{D}]"
        result = migrate_text(source)
        self.assertTrue(result.safe)
        self.assertEqual(result.text, "% \\ac<1>{C}\n\\[\\ac{2}{D}]")

    def test_accidentals_migrate_only_in_supported_musical_contexts(self) -> None:
        source = (
            r"\beginsong{C\shrp{} title}"
            r"[by={A\&B},key={C\shrp{}m},gk={B\flt{}m, C\shrp{}--D\flt{}m}]"
            "\n"
            r"\audio[title={C\shrp{} version},key=F\shrp{}m]{https://example.test/a\&b}"
            "\n"
            r"line \altchords{\id{alt. (C\shrp{})}|F\shrp{}m "
            r"|\ac{2}{B\flt{}7} |\notrans{D\shrp{}}}"
            "\n"
            r"outside C\shrp{} and B\flt{}"
        )
        result = migrate_text(source)
        self.assertTrue(result.safe)
        self.assertEqual(
            result.text,
            r"\beginsong{C\shrp{} title}"
            r"[by={A\&B},key={C#m},gk={B&m, C#--D&m}]"
            "\n"
            r"\audio[title={C\shrp{} version},key=F#m]{https://example.test/a\&b}"
            "\n"
            r"line \altchords{\id{alt. (C#)}|F#m |\ac{2}{B&7} |\notrans{D#}}"
            "\n"
            r"outside C\shrp{} and B\flt{}",
        )
        self.assertEqual(result.converted["shrp"], 6)
        self.assertEqual(result.converted["flt"], 3)

    def test_audio_options_after_url_and_bare_accidental_macros_migrate(self) -> None:
        source = r"\audio{url}[key={E\flt m}] \altchords{|A\flt |G\shrp{m}}"
        result = migrate_text(source)
        self.assertTrue(result.safe)
        self.assertEqual(result.text, r"\audio{url}[key={E& m}] \altchords{|A& |G#{m}}")

    def test_accidental_migration_skips_comments_and_is_idempotent(self) -> None:
        source = "% \\altchords{|C\\shrp{}}\n\\altchords{|C# |B&}"
        result = migrate_text(source)
        self.assertTrue(result.safe)
        self.assertEqual(result.text, source)

    def test_already_migrated_text_is_idempotent(self) -> None:
        source = r"\[<C D;E F @ -.2em>\ac{1}{Am}]"
        result = migrate_text(source)
        self.assertTrue(result.safe)
        self.assertEqual(result.text, source)


if __name__ == "__main__":
    unittest.main()
