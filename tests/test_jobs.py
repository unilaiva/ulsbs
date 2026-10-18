# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Variant selection, multikey companions, filenames, and UI labels."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from itertools import product
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
            "\\documentclass{ulsbs-songbook}\n"
            "%%%ULSBS-EXTRA-VARIANTS:charango, bassclef % unchanged comment\n"
        )
        self.doc.write_text(self.source, encoding="utf-8")
        self.cfg = replace(
            Config(),
            multikey_books=True,
            songbooks=(self.doc,),
            runtime=SimpleNamespace(project_paths=SimpleNamespace(project_root=self.root)),
        )

    def test_expansion_matrix_and_isolated_directories(self) -> None:
        for multikey, lyrics, extra in product((False, True), repeat=3):
            with self.subTest(multikey=multikey, lyrics=lyrics, extra=extra):
                jobs = build_job_queue(replace(
                    self.cfg, multikey_books=multikey, lyricbooks=lyrics,
                    extrainstrumentbooks=extra,
                ))
                variants = ["default"]
                if lyrics:
                    variants.append("lyrics")
                if extra:
                    variants.extend(("charango", "bassclef"))
                expected = [(variant, False) for variant in variants]
                if multikey:
                    expected.extend((variant, True) for variant in variants if variant != "lyrics")
                self.assertEqual([(job.variant, job.multikey) for job in jobs], expected)
                self.assertEqual(len({job.compile_dir for job in jobs}), len(jobs))
                self.assertEqual(len({build_job_basename(job) for job in jobs}), len(jobs))
                for job in jobs:
                    edition_dir = job.variant + ("-multikey" if job.multikey else "")
                    self.assertEqual(
                        job.compile_dir.relative_to(self.root / "temp").parts,
                        (self.doc.stem, edition_dir),
                    )
        self.assertEqual(self.doc.read_text(encoding="utf-8"), self.source)

    def test_package_defaults_create_only_ordinary_jobs(self) -> None:
        cfg = replace(Config(), songbooks=(self.doc,), runtime=self.cfg.runtime)
        jobs = build_job_queue(cfg)
        self.assertEqual([(job.variant, job.multikey) for job in jobs], [
            ("default", False), ("lyrics", False), ("charango", False), ("bassclef", False),
        ])

    def test_companions_follow_selection_without_new_variant_comments(self) -> None:
        for marker, variants in (
            ("", ["default", "lyrics"]),
            ("% ULSBS-EXTRA-VARIANTS: bassclef", ["default", "lyrics", "bassclef"]),
            ("% ULSBS-EXTRA-VARIANTS: multikey", ["default", "lyrics"]),
            ("% ULSBS-EXTRA-VARIANTS: CHARANGO % bassclef", ["default", "lyrics", "charango"]),
        ):
            with self.subTest(marker=marker):
                source = "\\documentclass{ulsbs-songbook}\n" + marker + "\n"
                self.doc.write_text(source, encoding="utf-8")
                jobs = build_job_queue(self.cfg)
                self.assertEqual([job.variant for job in jobs if not job.multikey], variants)
                self.assertEqual(
                    [job.variant for job in jobs if job.multikey],
                    [variant for variant in variants if variant != "lyrics"],
                )
                self.assertEqual(self.doc.read_text(encoding="utf-8"), source)

    def test_non_songbook_does_not_gain_optional_variants(self) -> None:
        self.doc.write_text(
            "\\documentclass{article}\n% ULSBS-EXTRA-VARIANTS: charango,bassclef\n",
            encoding="utf-8",
        )
        jobs = build_job_queue(self.cfg)
        self.assertEqual([(job.variant, job.multikey) for job in jobs], [
            ("default", False), ("default", True),
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

    def test_companion_cannot_overwrite_another_selected_document(self) -> None:
        other = self.root / "book_MULTIKEY_A5.tex"
        other.write_text("\\documentclass{article}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"Output filename collision.*book_MULTIKEY_A5\.json"):
            build_job_queue(replace(self.cfg, songbooks=(self.doc, other)))
        self.assertFalse((self.root / "temp").exists())

        jobs = build_job_queue(replace(
            self.cfg, songbooks=(self.doc, other), multikey_books=False,
        ))
        self.assertEqual(len({build_job_basename(job) for job in jobs}), len(jobs))

        # With JSON disabled these identical PDF basenames occupy different
        # directories, so there is no publication collision to reject.
        jobs = build_job_queue(replace(self.cfg, songbooks=(self.doc, other), json=False))
        self.assertEqual(sum(build_job_basename(job) == "book_MULTIKEY_A5" for job in jobs), 2)

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
            "default": "", "lyrics": "_LYRICS-ONLY",
            "charango": "_CHARANGO", "bassclef": "_BASSCLEF",
        }
        for stem in ("book", "book_A5", "book_A4", "book_NODEPLOY_A5"):
            for variant, marker in markers.items():
                with self.subTest(stem=stem, variant=variant):
                    job = Job(self.doc, stem, variant, self.root / variant)
                    self.assertFalse(job.multikey)
                    self.assertEqual(build_job_basename(job), build_variant_basename(stem, marker))
                    if variant != "lyrics":
                        suffix = "_A5" if stem.endswith("_A5") else "_A4" if stem.endswith("_A4") else ""
                        base = stem[:-len(suffix)] if suffix else stem
                        self.assertEqual(
                            build_job_basename(replace(job, multikey=True)),
                            base + "_MULTIKEY" + marker + suffix,
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
