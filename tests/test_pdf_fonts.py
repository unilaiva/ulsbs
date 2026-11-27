# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lossless font-program sharing and atomic replacement tests."""

from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pikepdf

from ulsbs.config import Config
from ulsbs.jobs import Job
from ulsbs.pdf_fonts import _check_equivalent, deduplicate_fonts
from ulsbs.pipeline import CompileError, step_pdf_fonts


class FontSharingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ulsbs fonts ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "book with spaces.pdf"

    def make_pdf(self, specifications=None):
        # Synthetic programs exercise object identity, not rendering. The separate
        # LilyPond integration test supplies real embedded, renderable fonts.
        data = random.Random(42).randbytes(8192)
        specifications = specifications or [(data, 8192), (data, 8192)]
        with pikepdf.Pdf.new() as pdf:
            page = pdf.add_blank_page()
            fonts = pikepdf.Dictionary()
            for index, (payload, length) in enumerate(specifications):
                stream = pdf.make_stream(payload)
                stream.Length1 = length
                descriptor = pdf.make_indirect(pikepdf.Dictionary(
                    Type=pikepdf.Name.FontDescriptor, FontName=pikepdf.Name("/ABCDEF+Test"),
                    FontFile2=stream,
                ))
                fonts[f"/F{index}"] = pdf.make_indirect(pikepdf.Dictionary(
                    Type=pikepdf.Name.Font, Subtype=pikepdf.Name.TrueType,
                    BaseFont=pikepdf.Name("/ABCDEF+Test"), FontDescriptor=descriptor,
                    FirstChar=32, LastChar=33, Widths=[200 + index, 300 + index],
                    ToUnicode=pdf.make_stream(f"distinct Unicode map {index}".encode()),
                ))
            page.Resources = pikepdf.Dictionary(Font=fonts)
            pdf.docinfo.Title = "Preserve title"
            pdf.save(self.path)

    def assert_untouched(self, original):
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_shares_programs_but_preserves_distinct_metrics_and_unicode_maps(self):
        self.make_pdf()
        baseline = self.root / "baseline.pdf"
        baseline.write_bytes(self.path.read_bytes())
        before, after, removed = deduplicate_fonts(self.path)
        self.assertEqual(before, baseline.stat().st_size)
        self.assertLess(after, before)
        self.assertEqual(removed, 1)
        with pikepdf.open(baseline) as original, pikepdf.open(self.path) as candidate:
            _check_equivalent(original, candidate)
            fonts = candidate.pages[0].Resources.Font
            self.assertNotEqual(fonts.F0.objgen, fonts.F1.objgen)
            self.assertNotEqual(fonts.F0.Widths, fonts.F1.Widths)
            self.assertNotEqual(fonts.F0.ToUnicode.read_bytes(), fonts.F1.ToUnicode.read_bytes())
            self.assertEqual(fonts.F0.FontDescriptor.FontFile2.objgen,
                             fonts.F1.FontDescriptor.FontFile2.objgen)
        optimized = self.path.read_bytes()
        self.assertEqual(deduplicate_fonts(self.path), (after, after, 0))
        self.assertEqual(self.path.read_bytes(), optimized)

    def test_different_subsets_and_incompatible_dictionaries_are_not_shared(self):
        data = random.Random(42).randbytes(8192)
        for specifications in ([(data, 8192), (data + b"another glyph", 8192)],
                               [(data, 8192), (data, 4096)]):
            with self.subTest(specifications=[len(item[0]) for item in specifications]):
                self.make_pdf(specifications)
                original = self.path.read_bytes()
                self.assertEqual(deduplicate_fonts(self.path), (len(original), len(original), 0))
                self.assert_untouched(original)

    def test_no_score_pdf_is_not_rewritten(self):
        with pikepdf.Pdf.new() as pdf:
            pdf.add_blank_page()
            pdf.save(self.path)
        original = self.path.read_bytes()
        self.assertEqual(deduplicate_fonts(self.path), (len(original), len(original), 0))
        self.assert_untouched(original)

    def test_subprocess_failure_logs_diagnostics_and_leaves_input_intact(self):
        invalid_pdf = b"%PDF-1.7\ninvalid PDF data"
        self.path.write_bytes(invalid_pdf)
        job = Job(self.root / "book.tex", "book", "default", self.root)
        with self.assertRaisesRegex(CompileError, "PDF font deduplication failed") as caught:
            step_pdf_fonts(Mock(), Config(), job, self.path.stem, 5)
        log = caught.exception.log_path
        self.assertEqual(log, self.root / "05_pdf-fonts.log")
        self.assertIn("PdfError:", log.read_text(encoding="utf-8"))
        self.assertEqual(self.path.read_bytes(), invalid_pdf)

    def test_validation_failure_preserves_original_and_cleans_candidate(self):
        self.make_pdf()
        original = self.path.read_bytes()
        with patch("ulsbs.pdf_fonts._check_equivalent", side_effect=ValueError("changed glyph")):
            with self.assertRaisesRegex(ValueError, "changed glyph"):
                deduplicate_fonts(self.path)
        self.assert_untouched(original)

    def test_syntax_failure_reports_diagnostics_and_preserves_original(self):
        diagnostic = "dictionary has duplicated key /Group"
        for stage, results in (("Input PDF", [[diagnostic]]),
                               ("Font-sharing candidate", [[], [diagnostic]])):
            with self.subTest(stage=stage):
                self.make_pdf()
                original = self.path.read_bytes()
                with patch.object(pikepdf.Pdf, "check_pdf_syntax", side_effect=results):
                    with self.assertRaises(ValueError) as caught:
                        deduplicate_fonts(self.path)
                self.assertEqual(str(caught.exception),
                                 f"{stage} failed syntax validation:\n{diagnostic}")
                self.assert_untouched(original)

    def test_corrupt_candidate_preserves_original(self):
        self.make_pdf()
        original = self.path.read_bytes()

        def corrupt(pdf, output, **kwargs):
            Path(output).write_bytes(b"not a PDF")

        with patch.object(pikepdf.Pdf, "save", autospec=True, side_effect=corrupt):
            with self.assertRaises(pikepdf.PdfError):
                deduplicate_fonts(self.path)
        self.assert_untouched(original)

    def test_larger_candidate_is_discarded(self):
        self.make_pdf()
        original = self.path.read_bytes()

        def enlarge(pdf, output, **kwargs):
            Path(output).write_bytes(original + b" " * 8192)

        with patch.object(pikepdf.Pdf, "save", autospec=True, side_effect=enlarge):
            self.assertEqual(deduplicate_fonts(self.path), (len(original), len(original), 0))
        self.assert_untouched(original)

    def test_atomic_replacement_failure_preserves_original(self):
        self.make_pdf()
        original = self.path.read_bytes()
        with patch("ulsbs.pdf_fonts.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                deduplicate_fonts(self.path)
        self.assert_untouched(original)

    def test_equivalence_rejects_semantic_changes_and_handles_reference_cycles(self):
        self.make_pdf()
        with pikepdf.open(self.path) as original, pikepdf.open(self.path) as changed:
            _check_equivalent(original, changed)
            changed.pages[0].Resources.Font.F0.Widths[0] = 999
            with self.assertRaisesRegex(ValueError, "value changed"):
                _check_equivalent(original, changed)

    def test_equivalence_rejects_changed_destinations_to_identical_pages(self):
        with pikepdf.Pdf.new() as original, pikepdf.Pdf.new() as changed:
            for pdf in (original, changed):
                pdf.add_blank_page()
                pdf.add_blank_page()
            original.Root.OpenAction = pikepdf.Array([original.pages[0].obj, pikepdf.Name.Fit])
            changed.Root.OpenAction = pikepdf.Array([changed.pages[1].obj, pikepdf.Name.Fit])
            with self.assertRaisesRegex(ValueError, "page destination changed"):
                _check_equivalent(original, changed)

    def test_rejects_signed_and_encrypted_inputs(self):
        self.make_pdf()
        with pikepdf.open(self.path) as pdf:
            pdf.Root.Perms = pdf.make_indirect(pikepdf.Dictionary(
                DocMDP=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Sig))
            ))
            signed = self.root / "signed.pdf"
            pdf.save(signed)
            encrypted = self.root / "encrypted.pdf"
            pdf.save(encrypted, encryption=pikepdf.Encryption(owner="owner", user=""))
        for path, message in ((signed, "signed"), (encrypted, "encrypted")):
            with self.subTest(kind=message):
                original = path.read_bytes()
                with self.assertRaisesRegex(ValueError, message):
                    deduplicate_fonts(path)
                self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
