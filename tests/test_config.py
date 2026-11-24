# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Multikey edition configuration and pre-load pipeline integration."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ulsbs.cli import _run_cli, build_arg_parser, print_plan_summary
from ulsbs.config import Config, build_config
from ulsbs.jobs import Job, build_job_basename
from ulsbs.pipeline import make_variant_tex
from ulsbs.ui import UI


class MultikeyConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def build(
        self, text: str, profile: str = "default", args_ns: Namespace | None = None
    ) -> Config:
        path = self.root / "ulsbs-config.toml"
        path.write_text(text, encoding="utf-8")
        return build_config(
            args_ns=args_ns,
            config_path=path,
            profile=profile,
            env={},
            runtime_project_paths=SimpleNamespace(project_root=self.root),
            runtime_in_container=False,
            runtime_unique_id="test",
        )

    def test_defaults(self) -> None:
        cfg = self.build("")
        self.assertEqual(cfg.variants, "all")
        self.assertEqual(Config().variants, "all")
        self.assertIsNone(build_arg_parser(UI(use_colors=False)).parse_args([]).variants)
        self.assertFalse(cfg.multikey_books)
        self.assertFalse(Config().multikey_books)
        self.assertEqual(cfg.multikey_max_pages_per_range, 50)
        self.assertEqual(Config().multikey_max_pages_per_range, 50)
        self.assertEqual(cfg.multikey_target_max_range_bytes, 33554432)
        self.assertEqual(Config().multikey_target_max_range_bytes, 33554432)
        self.assertEqual(cfg.multikey_layer_ui, "native")
        self.assertFalse(cfg.multikey_require_song_ids)
        self.assertFalse(Config().multikey_require_song_ids)
        self.assertFalse(cfg.multikey_lilypond_scores)
        self.assertFalse(Config().multikey_lilypond_scores)
        self.assertEqual(cfg.multikey_min_chordname_scale, 0.85)
        self.assertEqual(Config().multikey_min_chordname_scale, 0.85)

    def test_range_sizes_accept_positive_integers_and_normalized_keys(self) -> None:
        """Range tuning accepts either key spelling without enabling the edition."""
        for name in ("multikey-max-pages-per-range", "multikey-target-max-range-bytes"):
            for separator in ("-", "_"):
                option = name.replace("-", separator)
                for value in (1, 30, 50, 33554432):
                    for prefix in ("", "[profiles.default]\n"):
                        with self.subTest(option=option, value=value, prefix=prefix):
                            cfg = self.build(prefix + f"{option} = {value}\n")
                            self.assertEqual(getattr(cfg, name.replace("-", "_")), value)
                            self.assertFalse(cfg.multikey_books)

    def test_pdf_deploy_requirements_default_off_and_follow_profiles(self) -> None:
        for name in ("require-multikey-for-pdf-deploy", "require-json-for-pdf-deploy"):
            field = name.replace("-", "_")
            with self.subTest(name=name):
                self.assertFalse(getattr(self.build(""), field))
                config = f'{name} = true\n[profiles.permissive]\n{field} = false\n'
                self.assertTrue(getattr(self.build(config), field))
                self.assertFalse(getattr(self.build(config, "permissive"), field))
                for value in ('"true"', "1"):
                    with self.assertRaisesRegex(ValueError, f"{name} must be a boolean"):
                        self.build(f"[profiles.default]\n{name} = {value}")

    def test_range_sizes_follow_profile_inheritance_and_overrides(self) -> None:
        for name in ("multikey-max-pages-per-range", "multikey-target-max-range-bytes"):
            with self.subTest(name=name):
                text = (
                    f'{name} = 50\n[profiles.base]\n{name} = 30\n'
                    '[profiles.inherited]\ninherit-from = "base"\n'
                    f'[profiles.child]\ninherit-from = "inherited"\n{name} = 1\n'
                )
                field = name.replace("-", "_")
                self.assertEqual(getattr(self.build(text), field), 50)
                self.assertEqual(getattr(self.build(text, "inherited"), field), 30)
                self.assertEqual(getattr(self.build(text, "child"), field), 1)

    def test_range_sizes_reject_non_integer_and_non_positive_values(self) -> None:
        """TOML booleans and integral floats are not positive-integer settings."""
        for name in ("multikey-max-pages-per-range", "multikey-target-max-range-bytes"):
            for value in ('"50"', "true", "false", "1.0", "0", "-1", "nan", "inf", "[]", "{}"):
                for prefix in ("", "[profiles.default]\n"):
                    with self.subTest(name=name, value=value, prefix=prefix):
                        with self.assertRaisesRegex(ValueError, name + " must be a positive integer"):
                            self.build(prefix + f"{name} = {value}\n")

    def test_chordname_scale_accepts_numeric_bounds_and_normalized_keys(self) -> None:
        for separator in ("-", "_"):
            option = "multikey-min-chordname-scale".replace("-", separator)
            for value in (0.5, 0.85, 1, 1.0):
                for prefix in ("", "[profiles.default]\n"):
                    with self.subTest(separator=separator, value=value, prefix=prefix):
                        cfg = self.build(prefix + f"{option} = {value}\n")
                        self.assertEqual(cfg.multikey_min_chordname_scale, value)
                        self.assertFalse(cfg.multikey_books)

    def test_chordname_scale_inherits_and_profiles_can_override_it(self) -> None:
        text = ('multikey-min-chordname-scale = 0.5\n'
                '[profiles.base]\nmultikey-min-chordname-scale = 0.7\n'
                '[profiles.inherited]\ninherit-from = "base"\n'
                '[profiles.child]\ninherit-from = "inherited"\n'
                'multikey-min-chordname-scale = 1\n')
        self.assertEqual(self.build(text).multikey_min_chordname_scale, 0.5)
        self.assertEqual(self.build(text, "inherited").multikey_min_chordname_scale, 0.7)
        self.assertEqual(self.build(text, "child").multikey_min_chordname_scale, 1)

    def test_chordname_scale_rejects_non_numeric_nonfinite_and_out_of_range_values(self) -> None:
        for value in ('"0.85"', "true", "false", "0.4999", "1.0001", "0", "-1",
                      "nan", "+nan", "inf", "+inf", "-inf", "[]", "{}"):
            for prefix in ("", "[profiles.default]\n"):
                with self.subTest(value=value, prefix=prefix):
                    with self.assertRaisesRegex(ValueError, "multikey-min-chordname-scale"):
                        self.build(prefix + f"multikey-min-chordname-scale = {value}\n")

    def test_lilypond_scores_boolean_settings(self) -> None:
        for separator in ("-", "_"):
            option = "multikey-lilypond-scores".replace("-", separator)
            for enabled in (False, True):
                for prefix in ("", "[profiles.default]\n"):
                    with self.subTest(separator=separator, enabled=enabled, prefix=prefix):
                        cfg = self.build(prefix + f"{option} = {str(enabled).lower()}\n")
                        self.assertEqual(cfg.multikey_lilypond_scores, enabled)

    def test_lilypond_scores_profile_inheritance_and_overrides(self) -> None:
        for root, parent, child in ((False, True, False), (True, False, True)):
            with self.subTest(root=root, parent=parent, child=child):
                text = (
                    f'multikey-lilypond-scores = {str(root).lower()}\n'
                    '[profiles.base]\n'
                    f'multikey-lilypond-scores = {str(parent).lower()}\n'
                    '[profiles.inherited]\ninherit-from = "base"\n'
                    '[profiles.child]\ninherit-from = "inherited"\n'
                    f'multikey-lilypond-scores = {str(child).lower()}\n'
                )
                self.assertEqual(self.build(text).multikey_lilypond_scores, root)
                self.assertEqual(
                    self.build(text, "inherited").multikey_lilypond_scores, parent
                )
                self.assertEqual(self.build(text, "child").multikey_lilypond_scores, child)

    def test_explicit_settings_and_normalized_keys(self) -> None:
        for separator in ("-", "_"):
            for enabled in (False, True):
                with self.subTest(separator=separator, enabled=enabled):
                    cfg = self.build(
                        f'multikey{separator}books = {str(enabled).lower()}\n'
                        f'multikey{separator}layer{separator}ui = "hidden"\n'
                        f'multikey{separator}require{separator}song{separator}ids = true\n'
                    )
                    self.assertEqual(cfg.multikey_books, enabled)
                    self.assertEqual(cfg.multikey_layer_ui, "hidden")
                    self.assertTrue(cfg.multikey_require_song_ids)

    def test_hidden_ui_does_not_enable_companions(self) -> None:
        cfg = self.build('multikey-layer-ui = "hidden"\n')
        self.assertFalse(cfg.multikey_books)
        cfg = self.build('multikey-books = true\nmultikey-layer-ui = "hidden"\n')
        self.assertTrue(cfg.multikey_books)

    def test_score_opt_in_does_not_enable_companions(self) -> None:
        cfg = self.build('multikey-lilypond-scores = true\n')
        self.assertTrue(cfg.multikey_lilypond_scores)
        self.assertFalse(cfg.multikey_books)

    def test_root_opt_ins_are_inherited_by_profiles(self) -> None:
        text = ('multikey-books = true\nmultikey-lilypond-scores = true\n'
                '[profiles.default]\n[profiles.astral]\n[profiles.dev]\n')
        for profile in ("default", "astral", "dev"):
            with self.subTest(profile=profile):
                cfg = self.build(text, profile)
                self.assertTrue(cfg.multikey_books)
                self.assertTrue(cfg.multikey_lilypond_scores)

    def test_profile_inheritance_and_disable(self) -> None:
        cfg = self.build(
            'multikey-books = true\n'
            '[profiles.base]\nmultikey-layer-ui = "hidden"\n'
            '[profiles.child]\ninherit-from = "base"\nmultikey-books = false\n',
            "child",
        )
        self.assertFalse(cfg.multikey_books)
        self.assertEqual(cfg.multikey_layer_ui, "hidden")

    def test_profiles_override_root_settings_in_both_directions(self) -> None:
        for setting, override in (
            ("multikey-books = false", True),
            ("no-multikey-books = true", True),
            ("no_multikey_books = true", True),
            ("multikey-books = true", False),
        ):
            with self.subTest(setting=setting):
                cfg = self.build(
                    setting + '\n[profiles.default]\n'
                    f'multikey-books = {str(override).lower()}\n',
                )
                self.assertEqual(cfg.multikey_books, override)

    def test_child_overrides_parent_settings_in_both_directions(self) -> None:
        for parent, child in ((False, True), (True, False)):
            with self.subTest(parent=parent, child=child):
                cfg = self.build(
                    '[profiles.base]\n'
                    f'multikey-books = {str(parent).lower()}\n'
                    '[profiles.child]\ninherit-from = "base"\n'
                    f'multikey-books = {str(child).lower()}\n',
                    "child",
                )
                self.assertEqual(cfg.multikey_books, child)

    def test_child_positive_settings_override_parent_negations(self) -> None:
        for option in (
            "multikey-books", "multikey-require-song-ids", "multikey-lilypond-scores",
            "create-printouts", "json"
        ):
            for separator in ("-", "_"):
                with self.subTest(option=option, separator=separator):
                    negative = ("no-" + option).replace("-", separator)
                    cfg = self.build(
                        f'[profiles.base]\n{negative} = true\n'
                        f'[profiles.child]\ninherit-from = "base"\n{option} = true\n',
                        "child",
                    )
                    self.assertTrue(getattr(cfg, option.replace("-", "_")))

    def test_grandchild_can_override_an_inherited_negation(self) -> None:
        cfg = self.build(
            '[profiles.base]\nmultikey-books = true\n'
            '[profiles.parent]\ninherit-from = "base"\nno-multikey-books = true\n'
            '[profiles.child]\ninherit-from = "parent"\nmultikey-books = true\n',
            "child",
        )
        self.assertTrue(cfg.multikey_books)

    def test_invalid_values(self) -> None:
        for setting in (
            'multikey-books = "false"',
            "multikey-books = 0",
            'multikey-require-song-ids = "false"',
            "multikey-require-song-ids = 0",
            "multikey-require-song-ids = []",
            'no-multikey-require-song-ids = "true"',
            'multikey-lilypond-scores = "false"',
            "multikey-lilypond-scores = 0",
            "multikey-lilypond-scores = 1.0",
            "multikey-lilypond-scores = []",
            "multikey-lilypond-scores = {}",
            'no-multikey-lilypond-scores = "true"',
            'multikey-layer-ui = "other"',
            "multikey-layer-ui = false",
            "multikey-layer-ui = []",
        ):
            for prefix in ("", "[profiles.default]\n"):
                with self.subTest(setting=setting, prefix=prefix):
                    with self.assertRaisesRegex(ValueError, "multikey"):
                        self.build(prefix + setting)

    def test_old_settings_are_unknown_not_aliases(self) -> None:
        for setting in (
            "pdf-transposition-layers = true",
            "pdf_transposition_layers = false",
            'pdf-transposition-layer-ui = "native"',
            'pdf_transposition_layer_ui = "hidden"',
            "no-pdf-transposition-layers = true",
        ):
            for prefix in ("", "[profiles.default]\n"):
                with self.subTest(setting=setting, prefix=prefix):
                    with self.assertRaisesRegex(ValueError, "Unknown keys"):
                        self.build(prefix + setting)

    def test_cli_disable_overrides_profile(self) -> None:
        args = build_arg_parser(UI(use_colors=False)).parse_args(["--no-multikey"])
        cfg = self.build(
            "multikey-books = true\n[profiles.default]\nmultikey-books = true\n",
            args_ns=args,
        )
        self.assertFalse(cfg.multikey_books)

    def test_strict_ids_profile_inheritance_and_overrides(self) -> None:
        for separator in ("-", "_"):
            option = "multikey-require-song-ids".replace("-", separator)
            for parent, child in ((False, True), (True, False)):
                for negative in (False, True):
                    setting = (
                        f"no{separator}{option} = true" if negative
                        else f"{option} = {str(parent).lower()}"
                    )
                    expected_parent = False if negative else parent
                    for scope in ("root", "parent"):
                        with self.subTest(
                            separator=separator, parent=parent, child=child,
                            negative=negative, scope=scope,
                        ):
                            text = (
                                setting + "\n[profiles.base]\n" if scope == "root"
                                else "[profiles.base]\n" + setting + "\n"
                            )
                            text += (
                                '[profiles.inherited]\ninherit-from = "base"\n'
                                '[profiles.child]\ninherit-from = "inherited"\n'
                                f"{option} = {str(child).lower()}\n"
                            )
                            self.assertEqual(
                                self.build(text, "inherited").multikey_require_song_ids,
                                expected_parent,
                            )
                            self.assertEqual(
                                self.build(text, "child").multikey_require_song_ids, child
                            )

    def test_strict_ids_profile_negation_overrides_root(self) -> None:
        for separator in ("-", "_"):
            negative = "no-multikey-require-song-ids".replace("-", separator)
            with self.subTest(separator=separator):
                cfg = self.build(
                    'multikey-require-song-ids = true\n'
                    f'[profiles.default]\n{negative} = true\n'
                )
                self.assertFalse(cfg.multikey_require_song_ids)

    def test_cli_require_song_ids_overrides_profile(self) -> None:
        parser = build_arg_parser(UI(use_colors=False))
        self.assertFalse(parser.parse_args([]).require_song_ids)
        for setting in (
            "multikey-require-song-ids = false",
            "no-multikey-require-song-ids = true",
        ):
            with self.subTest(setting=setting):
                args = parser.parse_args(["--require-song-ids"])
                cfg = self.build("[profiles.default]\n" + setting, args_ns=args)
                self.assertTrue(cfg.multikey_require_song_ids)
                self.assertFalse(cfg.multikey_books)
        cfg = self.build("multikey-require-song-ids = true", args_ns=parser.parse_args([]))
        self.assertTrue(cfg.multikey_require_song_ids)

    def test_strict_ids_do_not_enable_disabled_companions(self) -> None:
        for flag in ("--no-multikey", "--quick"):
            with self.subTest(flag=flag):
                args = build_arg_parser(UI(use_colors=False)).parse_args(
                    ["--require-song-ids", flag]
                )
                cfg = self.build("", args_ns=args)
                self.assertTrue(cfg.multikey_require_song_ids)
                self.assertFalse(cfg.multikey_books)

    def test_plan_shows_strict_policy_only_for_multikey(self) -> None:
        ui = UI(use_colors=False)
        cfg = self.build("")
        cfg.runtime.project_paths.host_project_root = self.root
        for enabled in (False, True):
            for strict in (False, True):
                with self.subTest(enabled=enabled, strict=strict):
                    with patch.object(ui, "plain") as plain:
                        print_plan_summary(
                            ui, replace(
                                cfg, multikey_books=enabled, multikey_require_song_ids=strict
                            ), jobs_count=1,
                        )
                    output = "\n".join(call.args[0] for call in plain.call_args_list)
                    if enabled:
                        self.assertIn(
                            "Require song IDs (strict publishing): " + ("YES" if strict else "NO"),
                            output,
                        )
                    else:
                        self.assertNotIn("Require song IDs", output)

    def test_quick_mode_disables_companions(self) -> None:
        for flag in ("-q", "--quick"):
            with self.subTest(flag=flag):
                args = build_arg_parser(UI(use_colors=False)).parse_args([flag])
                cfg = self.build("multikey-books = true\n", args_ns=args)
                self.assertTrue(cfg.quick)
                self.assertFalse(cfg.multikey_books)

    def test_definitions_precede_class_and_package_for_all_variants(self) -> None:
        source = (
            "% source comment\n\\documentclass[variants={default,lyric,charango,bassclef}]{ulsbs-songbook}\n"
            "\\usepackage{ulsbs}\n\\begin{document}\nWords\n\\end{document}\n"
        )
        doc = self.root / "book_A5.tex"
        doc.write_text(source, encoding="utf-8")
        for enabled in (True, False):
            for ui in ("native", "hidden"):
                for variant in ("default", "lyric", "charango", "bassclef"):
                    for multikey in (False, True):
                        with self.subTest(
                            enabled=enabled, ui=ui, variant=variant, multikey=multikey
                        ):
                            compile_dir = self.root / variant
                            compile_dir.mkdir(exist_ok=True)
                            cfg = replace(
                                Config(), multikey_books=enabled, multikey_layer_ui=ui
                            )
                            job = Job(doc, doc.stem, variant, compile_dir, multikey=multikey)
                            if variant == "lyric" and multikey:
                                with self.assertRaises(ValueError):
                                    make_variant_tex(job, cfg)
                                continue
                            result_path = make_variant_tex(job, cfg)
                            self.assertEqual(result_path.name, build_job_basename(job) + ".tex")
                            result = result_path.read_text(encoding="utf-8")
                            value = (
                                "true" if enabled and multikey
                                else "false"
                            )
                            definitions = (
                                f"\\newcommand{{\\ulPdfTranspositionLayers}}{{{value}}}\n"
                                 f"\\newcommand{{\\ulPdfTranspositionLayerUi}}{{{ui}}}\n"
                                   "\\newcommand{\\ulPdfTranspositionRequireSongIds}{false}\n"
                                   "\\newcommand{\\ulPdfTranspositionMinimumScale}{0.85}\n"
                                  "\\newcommand{\\ulMultikeyLilypondScores}{false}\n"
                            )
                            self.assertTrue(result.startswith(definitions))
                            self.assertNotIn("postsetup", result)
                            self.assertNotIn("\\input{ulsbs-variant-", result)
                            self.assertLess(
                                result.index("\\ulPdfTranspositionLayers"),
                                result.index("\\documentclass"),
                            )
                            self.assertLess(
                                result.index("\\ulPdfTranspositionLayerUi"),
                                result.index("\\usepackage"),
                            )
                            if variant != "default":
                                self.assertIn(f"\\def\\ulBuildVariant{{{variant}}}\n", result)
                                self.assertLess(result.index("\\ulBuildVariant"), result.index("\\documentclass"))
                            else:
                                self.assertNotIn("\\ulBuildVariant", result)
                                if value == "true":
                                    self.assertTrue(result.endswith(source))
                                    self.assertIn("\\AtBeginDocument", result)
                                else:
                                    self.assertEqual(result, definitions + source)
        self.assertEqual(doc.read_text(encoding="utf-8"), source)

    def test_chordname_scale_is_supplied_before_the_document_class(self) -> None:
        doc = self.root / "scale_A5.tex"
        doc.write_text("\\documentclass[variants={default,lyric,charango,bassclef}]{ulsbs-songbook}\n", encoding="utf-8")
        for scale in (0.5, 0.85, 1):
            cfg = replace(Config(), multikey_books=True, multikey_min_chordname_scale=scale)
            for variant in ("default", "lyric", "charango", "bassclef"):
                for multikey in (False, True):
                    with self.subTest(scale=scale, variant=variant, multikey=multikey):
                        directory = self.root / f"{scale}-{variant}-{multikey}"
                        directory.mkdir()
                        job = Job(doc, doc.stem, variant, directory, multikey=multikey)
                        if variant == "lyric" and multikey:
                            with self.assertRaises(ValueError):
                                make_variant_tex(job, cfg)
                            continue
                        text = make_variant_tex(job, cfg).read_text(encoding="utf-8")
                        macro = f"\\newcommand{{\\ulPdfTranspositionMinimumScale}}{{{scale}}}"
                        self.assertLess(text.index(macro), text.index("\\documentclass"))

    def test_variant_selection_profile_and_cli_precedence(self) -> None:
        parser = build_arg_parser(UI(use_colors=False))
        text = ('variants = ["default", "lyric"]\n'
                '[profiles.base]\nvariants = ["charango"]\n'
                '[profiles.child]\ninherit-from = "base"\n')
        self.assertEqual(self.build(text).variants, ("default", "lyric"))
        self.assertEqual(self.build(text, "child").variants, ("charango",))
        for value, expected in (("all", "all"), ("bassclef,default", ("bassclef", "default"))):
            with self.subTest(value=value):
                args = parser.parse_args(["--variants", value])
                self.assertEqual(self.build(text, "child", args).variants, expected)

    def test_variants_reject_invalid_file_values_even_when_overridden(self) -> None:
        args = build_arg_parser(UI(use_colors=False)).parse_args(["--variants", "default"])
        for value in ('"default"', '"ALL"', '""', "true", "1", "{}", "[]",
                      '["default", 1]', '["default", "default"]', '["lyrics"]',
                      '["unknown"]', '["all"]', '["default,lyric"]', '[" lyric"]'):
            for text in (f"variants = {value}\n",
                         f'variants = {value}\n[profiles.default]\nvariants = "all"\n',
                         f'[profiles.base]\nvariants = {value}\n'
                         '[profiles.default]\ninherit-from = "base"\nvariants = "all"\n'):
                with self.subTest(value=value, text=text):
                    with self.assertRaises(ValueError):
                        self.build(text, args_ns=args)

    def test_variants_reject_invalid_cli_selectors(self) -> None:
        parser = build_arg_parser(UI(use_colors=False))
        for value in ("", "ALL", "lyrics", "unknown", "all,default", "default,", ",default",
                      "default,default", "Default", "\\default"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.build('variants = "all"\n', args_ns=parser.parse_args(["--variants", value]))

    def test_removed_variant_options_have_no_aliases(self) -> None:
        parser = build_arg_parser(UI(use_colors=False))
        for flag in ("--no-lyric", "--no-extrainstr"):
            with self.subTest(flag=flag), patch("sys.stderr"):
                with self.assertRaises(SystemExit):
                    parser.parse_args([flag])
        for name in ("lyricbooks", "extrainstrumentbooks", "no-lyricbooks", "no-extrainstrumentbooks"):
            for value in ("true", "false"):
                for prefix in ("", "[profiles.default]\n"):
                    with self.subTest(name=name, value=value, prefix=prefix):
                        with self.assertRaisesRegex(ValueError, "Unknown keys"):
                            self.build(prefix + f"{name} = {value}\n")

    def test_quick_variant_selection_and_conflicts(self) -> None:
        parser = build_arg_parser(UI(use_colors=False))
        for setting in ("", 'variants = "all"\n', 'variants = ["default"]\n'):
            for selector in ([], ["--variants", "default"]):
                with self.subTest(setting=setting, selector=selector):
                    cfg = self.build(setting, args_ns=parser.parse_args(["--quick", *selector]))
                    self.assertEqual(cfg.variants, ("default",))
                    self.assertFalse(cfg.multikey_books)
        for value in ("all", "lyric", "default,lyric", "bassclef"):
            with self.subTest(cli=value):
                with self.assertRaisesRegex(ValueError, "quick conflicts"):
                    self.build("", args_ns=parser.parse_args(["--quick", "--variants", value]))
        with self.assertRaisesRegex(ValueError, "quick conflicts"):
            self.build('[profiles.default]\nvariants = ["lyric"]\n',
                       args_ns=parser.parse_args(["--quick"]))
        cfg = self.build('[profiles.default]\nvariants = ["lyric"]\n',
                         args_ns=parser.parse_args(["--quick", "--variants", "default"]))
        self.assertEqual(cfg.variants, ("default",))

    def test_plan_summary_uses_generic_variant_selection(self) -> None:
        ui = UI(use_colors=False)
        cfg = self.build('variants = ["default", "lyric"]\n')
        cfg.runtime.project_paths.host_project_root = self.root
        with patch.object(ui, "plain") as plain:
            print_plan_summary(ui, cfg, jobs_count=2)
        output = "\n".join(call.args[0] for call in plain.call_args_list)
        self.assertIn("Variants: default, lyric", output)
        self.assertNotIn("Additional lyrics", output)
        self.assertNotIn("extra instrument", output)

    def test_plan_errors_precede_setup_container_and_artifact_generation(self) -> None:
        (self.root / "ulsbs-config.toml").write_text("", encoding="utf-8")
        for flags in ([], ["--no-container"]):
            with self.subTest(flags=flags), ExitStack() as stack:
                stack.enter_context(redirect_stdout(io.StringIO()))
                errors = stack.enter_context(redirect_stderr(io.StringIO()))
                stack.enter_context(patch.dict("os.environ", {}, clear=True))
                queue = stack.enter_context(patch("ulsbs.cli.build_job_queue", side_effect=ValueError("bad selector")))
                effects = [stack.enter_context(patch("ulsbs.cli." + name)) for name in (
                    "setup_temp_dir", "run_self_in_container", "require_tools", "ensure_dir",
                    "resultlist.initialize", "resultlist.write_header", "run_jobs_parallel",
                )]
                rc = _run_cli(UI(use_colors=False), SimpleNamespace(), [*flags, str(self.root)])
                self.assertEqual(rc, 1)
                self.assertIn("Compilation plan error: bad selector", errors.getvalue())
                queue.assert_called_once()
                for effect in effects:
                    effect.assert_not_called()
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["ulsbs-config.toml"])

    def test_invalid_selectors_leave_no_build_artifacts(self) -> None:
        (self.root / "ulsbs-config.toml").write_text('songbooks = ["book.tex"]\n', encoding="utf-8")
        (self.root / "book.tex").write_text("\\documentclass{ulsbs-songbook}\n", encoding="utf-8")
        for selector, heading, message in (
            ("unknown", "Configuration error!", "Unknown variant: 'unknown'"),
            ("lyric", "Compilation plan error:", "unavailable variants: lyric"),
            ("default,default", "Configuration error!", "Duplicate variant identifiers"),
        ):
            with self.subTest(selector=selector), ExitStack() as stack:
                stack.enter_context(redirect_stdout(io.StringIO()))
                errors = stack.enter_context(redirect_stderr(io.StringIO()))
                stack.enter_context(patch.dict("os.environ", {}, clear=True))
                setup = stack.enter_context(patch("ulsbs.cli.setup_temp_dir"))
                container = stack.enter_context(patch("ulsbs.cli.run_self_in_container"))
                rc = _run_cli(UI(use_colors=False), SimpleNamespace(),
                              ["--variants", selector, str(self.root)])
                self.assertEqual(rc, 1)
                self.assertIn(heading, errors.getvalue())
                self.assertIn(message, errors.getvalue())
                setup.assert_not_called()
                container.assert_not_called()
        self.assertEqual(sorted(path.name for path in self.root.iterdir()),
                         ["book.tex", "ulsbs-config.toml"])

    def test_strict_id_policy_is_supplied_before_the_document_class(self) -> None:
        doc = self.root / "strict_A5.tex"
        doc.write_text("\\documentclass{ulsbs-songbook}\n", encoding="utf-8")
        cfg = replace(Config(), multikey_require_song_ids=True)
        for multikey in (False, True):
            compile_dir = self.root / ("strict-multikey" if multikey else "strict-standard")
            compile_dir.mkdir()
            job = Job(doc, doc.stem, "default", compile_dir, multikey=multikey)
            text = make_variant_tex(job, cfg).read_text(encoding="utf-8")
            self.assertLess(
                text.index("\\newcommand{\\ulPdfTranspositionRequireSongIds}{true}"),
                text.index("\\documentclass"),
            )


if __name__ == "__main__":
    unittest.main()
