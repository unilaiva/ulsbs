# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Multikey edition configuration and pre-load pipeline integration."""

from __future__ import annotations

import tempfile
import unittest
from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ulsbs.cli import build_arg_parser, print_plan_summary
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
        self.assertTrue(cfg.multikey_books)
        self.assertEqual(cfg.multikey_layer_ui, "native")
        self.assertFalse(cfg.multikey_require_song_ids)
        self.assertFalse(Config().multikey_require_song_ids)

    def test_explicit_settings_and_normalized_keys(self) -> None:
        for separator in ("-", "_"):
            with self.subTest(separator=separator):
                cfg = self.build(
                    f'multikey{separator}books = false\n'
                    f'multikey{separator}layer{separator}ui = "hidden"\n'
                    f'multikey{separator}require{separator}song{separator}ids = true\n'
                )
                self.assertFalse(cfg.multikey_books)
                self.assertEqual(cfg.multikey_layer_ui, "hidden")
                self.assertTrue(cfg.multikey_require_song_ids)

    def test_hidden_ui_keeps_companions_enabled(self) -> None:
        cfg = self.build('multikey-layer-ui = "hidden"\n')
        self.assertTrue(cfg.multikey_books)

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
            "multikey-books", "multikey-require-song-ids", "create-printouts", "json"
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
                self.assertTrue(cfg.multikey_books)
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
            "% source comment\n\\documentclass{ulsbs-songbook}\n"
            "\\usepackage{ulsbs}\n\\begin{document}\nWords\n\\end{document}\n"
        )
        doc = self.root / "book_A5.tex"
        doc.write_text(source, encoding="utf-8")
        for enabled in (True, False):
            for ui in ("native", "hidden"):
                for variant in ("default", "lyrics", "charango", "bassclef"):
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
                            result_path = make_variant_tex(job, cfg)
                            self.assertEqual(result_path.name, build_job_basename(job) + ".tex")
                            result = result_path.read_text(encoding="utf-8")
                            value = (
                                "true" if enabled and multikey and variant != "lyrics"
                                else "false"
                            )
                            definitions = (
                                f"\\newcommand{{\\ulPdfTranspositionLayers}}{{{value}}}\n"
                                 f"\\newcommand{{\\ulPdfTranspositionLayerUI}}{{{ui}}}\n"
                                 "\\newcommand{\\ulPdfTranspositionRequireSongIDs}{false}\n"
                            )
                            self.assertTrue(result.startswith(definitions))
                            self.assertLess(
                                result.index("\\ulPdfTranspositionLayers"),
                                result.index("\\documentclass"),
                            )
                            self.assertLess(
                                result.index("\\ulPdfTranspositionLayerUI"),
                                result.index("\\usepackage"),
                            )
                            if variant != "default":
                                suffix = "lyric" if variant == "lyrics" else variant
                                postsetup = f"ulsbs-internal-{suffix}book-postsetup.tex"
                                self.assertIn(f"\\input{{{postsetup}}}", result)
                            else:
                                if value == "true":
                                    self.assertTrue(result.endswith(source))
                                    self.assertIn("\\AtBeginDocument", result)
                                else:
                                    self.assertEqual(result, definitions + source)
        self.assertEqual(doc.read_text(encoding="utf-8"), source)

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
                text.index("\\newcommand{\\ulPdfTranspositionRequireSongIDs}{true}"),
                text.index("\\documentclass"),
            )


if __name__ == "__main__":
    unittest.main()
