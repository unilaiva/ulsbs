# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Variant selection, multikey companions, filenames, and UI labels."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from ulsbs.config import Config
from ulsbs.constants import MULTIKEY_FNAMEPART, RESULT_TYPE_MULTIKEY_PDF
from ulsbs.jobs import Job, build_job_basename, build_job_queue, build_variant_basename
from ulsbs.ui import UI


class MultikeyJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.doc = self.root / "book_A5.tex"
        self.source = (
            "\\documentclass[variants={lyric,default,charango,bassclef},"
            "subtitle={A, B}]{ulsbs-songbook}\n"
        )
        self.doc.write_text(self.source, encoding="utf-8")
        self.cfg = replace(
            Config(),
            multikey_books=True,
            songbooks=(self.doc,),
            runtime=SimpleNamespace(project_paths=SimpleNamespace(project_root=self.root)),
        )

    def test_expansion_matrix_and_isolated_directories(self) -> None:
        for multikey in (False, True):
            for selection in ("all", ("default",), ("lyric",), ("bassclef", "default")):
                with self.subTest(multikey=multikey, selection=selection):
                    self.assert_queue(multikey, selection)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), self.source)

    def assert_queue(self, multikey, selection):
        """Compare selected identities and registry-supported edition expansion."""
        jobs = build_job_queue(replace(
            self.cfg, multikey_books=multikey, variants=selection,
        ))
        variants = [name for name in ("default", "lyric", "charango", "bassclef")
                    if selection == "all" or name in selection]
        expected = [(variant, False) for variant in variants]
        if multikey:
            expected.extend((variant, True) for variant in variants if variant != "lyric")
        self.assertEqual([(job.variant, job.multikey) for job in jobs], expected)
        self.assertEqual(len({job.compile_dir for job in jobs}), len(jobs))
        self.assertEqual(len({build_job_basename(job) for job in jobs}), len(jobs))
        for job in jobs:
            edition_dir = job.variant + ("-multikey" if job.multikey else "")
            self.assertEqual(
                job.compile_dir.relative_to(self.root / "temp").parts,
                (self.doc.stem, edition_dir),
            )

    def test_subsets_follow_declaration_order_without_adding_default(self) -> None:
        self.doc.write_text(
            r"\documentclass[variants={bassclef,lyric,default,charango}]{ulsbs-songbook-custom}",
            encoding="utf-8",
        )
        for selection, expected in (
            ("all", ["default", "bassclef", "lyric", "charango"]),
            (("charango", "lyric"), ["lyric", "charango"]),
            (("bassclef",), ["bassclef"]),
        ):
            jobs = build_job_queue(replace(self.cfg, variants=selection, multikey_books=False))
            self.assertEqual([job.variant for job in jobs], expected)

    def test_collection_intersections_and_unmatched_requests_fail_before_outputs(self) -> None:
        other = self.root / "other.tex"
        other.write_text(r"\documentclass{ulsbs-songbook}", encoding="utf-8")
        cfg = replace(self.cfg, songbooks=(other, self.doc), variants=("lyric", "bassclef"))
        jobs = build_job_queue(cfg)
        self.assertEqual([job.variant for job in jobs], ["lyric", "bassclef", "bassclef"])
        self.assertTrue(all(job.doc_tex_abs == self.doc for job in jobs))
        from unittest.mock import patch
        from ulsbs.cli import print_variant_selections

        ui = UI(use_colors=False)
        with patch.object(ui, "info_line") as info:
            print_variant_selections(ui, cfg, jobs)
        self.assertEqual([call.args[0] for call in info.call_args_list], [
            "other.tex: selected <none>; skipped lyric, bassclef (unavailable)",
            "book_A5.tex: selected lyric, bassclef",
        ])
        for docs in ((other,), (other, self.doc)):
            other.write_text(r"\documentclass{ulsbs-songbook}", encoding="utf-8")
            self.doc.write_text(r"\documentclass{ulsbs-songbook}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unavailable variants|available in none"):
                build_job_queue(replace(cfg, songbooks=docs))
        self.assertFalse((self.root / "temp").exists())

    def test_invalid_availability_and_selection_fail_before_outputs(self) -> None:
        for option in ("{}", "{lyric}", "{default,lyrics}", "{default,default}", r"\names"):
            self.doc.write_text(
                r"\documentclass[variants=" + option + "]{ulsbs-songbook}", encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                build_job_queue(self.cfg)
        for selection in (("lyrics",), ("default", "default"), ()):
            with self.assertRaises(ValueError):
                build_job_queue(replace(self.cfg, variants=selection))
        self.assertFalse((self.root / "temp").exists())

    def test_package_defaults_create_only_ordinary_jobs(self) -> None:
        cfg = replace(Config(), songbooks=(self.doc,), runtime=self.cfg.runtime)
        jobs = build_job_queue(cfg)
        self.assertEqual([(job.variant, job.multikey) for job in jobs], [
            ("default", False), ("lyric", False), ("charango", False), ("bassclef", False),
        ])

    def test_omission_and_legacy_markers_do_not_enable_companions(self) -> None:
        for marker in (
            "", "% ULSBS-EXTRA-VARIANTS: bassclef", "% ULSBS-EXTRA-VARIANTS: charango",
        ):
            with self.subTest(marker=marker):
                source = "\\documentclass{ulsbs-songbook}\n" + marker + "\n"
                self.doc.write_text(source, encoding="utf-8")
                jobs = build_job_queue(self.cfg)
                self.assertEqual([job.variant for job in jobs], ["default", "default"])
                self.assertEqual(self.doc.read_text(encoding="utf-8"), source)

    def test_non_songbook_does_not_gain_optional_variants(self) -> None:
        self.doc.write_text(
            "\\documentclass{article}\n% ULSBS-EXTRA-VARIANTS: charango,bassclef\n",
            encoding="utf-8",
        )
        jobs = build_job_queue(self.cfg)
        self.assertEqual([(job.variant, job.multikey) for job in jobs], [
            ("default", False),
        ])

    def test_multiple_documents_have_independent_unique_directories(self) -> None:
        other = self.root / "other_A4.tex"
        other.write_text(self.source, encoding="utf-8")
        jobs = build_job_queue(replace(self.cfg, songbooks=(self.doc, other)))
        self.assertEqual(len(jobs), 14)
        self.assertEqual(len({job.compile_dir for job in jobs}), 14)
        for doc in (self.doc, other):
            selected = [job for job in jobs if job.doc_tex_abs == doc]
            self.assertEqual([job.multikey for job in selected], [False] * 4 + [True] * 3)

    def test_multikey_stem_can_match_an_ordinary_document(self) -> None:
        """A shared stem is safe when the jobs own different publication paths."""
        other = self.root / "book_A5_MULTIKEY.tex"
        other.write_text("\\documentclass{article}\n", encoding="utf-8")
        for json in (False, True):
            with self.subTest(json=json):
                jobs = build_job_queue(replace(self.cfg, songbooks=(self.doc, other), json=json))
                self.assertEqual(sum(build_job_basename(job) == "book_A5_MULTIKEY" for job in jobs), 2)
                self.assertFalse((self.root / "temp").exists())

    def test_multikey_index_collisions_are_checked_without_json_export(self) -> None:
        # Duplicate only the multikey jobs to isolate their mandatory index path.
        from unittest.mock import patch

        job = Job(self.doc, self.doc.stem, "default", self.root / "default", multikey=True)
        for json in (False, True):
            with self.subTest(json=json):
                with patch("ulsbs.jobs.replace", return_value=job):
                    with self.assertRaisesRegex(
                        ValueError, r"Output filename collision.*multikey/book_A5_MULTIKEY_RANGES\.json"
                    ):
                        build_job_queue(replace(self.cfg, json=json))

    def test_variant_cannot_overwrite_another_selected_document(self) -> None:
        other = self.root / "book_CHARANGO_A5.tex"
        other.write_text("\\documentclass{article}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"Output filename collision.*book_CHARANGO_A5\.pdf"):
            build_job_queue(replace(
                self.cfg, songbooks=(self.doc, other), multikey_books=False,
            ))

    def test_same_stem_in_different_directories_is_rejected(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()
        other = nested / self.doc.name
        other.write_text(self.source, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"Output filename collision.*book_A5\.pdf"):
            build_job_queue(replace(self.cfg, songbooks=(self.doc, other)))

    def test_job_names_keep_standard_names_and_order_markers(self) -> None:
        markers = {
            "default": "", "lyric": "_LYRICS-ONLY",
            "charango": "_CHARANGO", "bassclef": "_BASSCLEF",
        }
        for stem in ("book", "book_A5", "book_A4", "book_NODEPLOY_A5"):
            for variant, marker in markers.items():
                with self.subTest(stem=stem, variant=variant):
                    job = Job(self.doc, stem, variant, self.root / variant)
                    self.assertFalse(job.multikey)
                    self.assertEqual(build_job_basename(job), build_variant_basename(stem, marker))
                    if variant != "lyric":
                        self.assertEqual(
                            build_job_basename(replace(job, multikey=True)),
                            build_variant_basename(stem, marker) + "_MULTIKEY",
                        )

    def test_multikey_constants_use_result_list_width(self) -> None:
        self.assertEqual(MULTIKEY_FNAMEPART, "_MULTIKEY")
        self.assertEqual(RESULT_TYPE_MULTIKEY_PDF.strip(), "MULTIKEYPDF")
        self.assertEqual(len(RESULT_TYPE_MULTIKEY_PDF), 14)

    def test_ui_labels_distinguish_companion_editions(self) -> None:
        ui = UI(use_colors=False)
        for variant in ("default", "charango", "bassclef"):
            with self.subTest(variant=variant):
                job = Job(self.doc, self.doc.stem, variant, self.root / variant)
                self.assertEqual(ui.fmt_doc(job), f"[book_A5:{variant}]")
                self.assertEqual(
                    ui.fmt_doc(replace(job, multikey=True)), f"[book_A5:{variant}:multikey]"
                )


if __name__ == "__main__":
    unittest.main()
