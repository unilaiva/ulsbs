# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real charango TAB tuning, repeatability and multikey score coverage."""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from test_pdf_transposition_layers import pdf_command
from test_tex_integration import FIXTURES
from ulsbs import lilypond_scores, pipeline
from ulsbs.config import Config
from ulsbs.engine_assets import EngineAssets
from ulsbs.jobs import Job


@unittest.skipUnless(all(shutil.which(tool) for tool in
                         ("lilypond-book", "lilypond", "lualatex", "gs", "qpdf",
                           "pdftotext")), "LilyPond/PDF tools unavailable")
class CharangoTests(unittest.TestCase):
    def words(self, pdf):
        xml = pdf_command(pdf, ["pdftotext", "-bbox", "{pdf}", "-"]).decode()
        # Emmentaler clefs/time signatures can extract as XML-illegal controls.
        # Keep Poppler's numeric TAB text and coordinates, not those music codes.
        xml = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", xml)
        root = ET.fromstring(xml)
        return [(word.text or "", *(round(float(word.get(key)), 2)
                 for key in ("xMin", "yMin", "xMax", "yMax")))
                for word in root.iter("{http://www.w3.org/1999/xhtml}word")]

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ulsbs-charango-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for child in ("content", "include", "result", "texmf-cache"):
            (self.root / child).mkdir()
        self.doc = self.root / "charango.tex"
        self.fixture = (FIXTURES / self.doc.name).read_text()
        self.assertIn('"ulsbs-include-tail.ly"', self.fixture)
        self.assertNotIn("tail-notab", self.fixture)
        self.doc.write_text(self.fixture)
        paths = SimpleNamespace(project_root=self.root, host_project_root=self.root,
                                result_dir=self.root / "result",
                                content_dir=self.root / "content", include_dir=self.root / "include")
        self.cfg = replace(Config(), runtime=SimpleNamespace(project_paths=paths, in_container=False))
        self.ui = Mock()

    def prepare(self, variant, name):
        job = Job(self.doc, self.doc.stem, variant, self.root / name)
        pipeline.prepare_compile_dir(self.ui, EngineAssets(), self.cfg, job)
        source = pipeline.make_variant_tex(job, self.cfg)
        env, includes, _ = pipeline.build_include_paths(self.cfg, job)
        env.update(TEXMFVAR=str(self.root / "texmf-cache"),
                   TEXMFCACHE=str(self.root / "texmf-cache"))
        return job, source, env, includes

    def compile(self, prepared):
        job, source, env, includes = prepared
        source = pipeline.make_variant_tex(job, self.cfg)
        try:
            processed, _, _ = pipeline.step_lilypond_book(self.ui, job, source, env, includes, 1)
        except pipeline.CompileError as error:
            self.fail(f"{error}\n{error.log_path.read_text()}")
        scores = lilypond_scores.prepare_scores(job.compile_dir, processed.stem)
        self.assertEqual(len(scores), 1)
        score = next(iter(scores.values()))
        self.assertIsNone(score.unsupported)
        self.assertEqual(len(score.graphics), 1)
        pdf = (job.compile_dir / (score.graphics[0] + ".pdf")).read_bytes()
        words = self.words(pdf)
        digits = [row[0] for row in words if re.fullmatch(r"\d+", row[0])]
        self.assertTrue(words)
        return score, words, digits

    def test_positive_charango_tab_fresh_repeat_controls_and_multikey_alternative(self):
        charango = self.prepare("charango", "charango")
        score, evidence, digits = self.compile(charango)
        self.assertEqual(len(digits), 4, "each real TabNoteHead must render a fret number")
        self.assertEqual(digits, ["0", "3", "5", "3"], "charango tuning/fret positions")
        # A no-op charango injection must not silently pass as guitar tablature.
        _, guitar, guitar_digits = self.compile(self.prepare("default", "guitar"))
        self.assertEqual(len(guitar_digits), 4)
        self.assertEqual(guitar_digits, ["0", "0", "3", "2"], "guitar tuning/fret positions")
        self.assertNotEqual(digits, guitar_digits)
        self.assertNotEqual(evidence, guitar)
        _, bass, bass_digits = self.compile(self.prepare("bassclef", "bass"))
        self.assertEqual(bass_digits, [])  # The production bass-clef tail omits TAB.
        self.assertNotEqual(bass, guitar)

        _, repeated, repeated_digits = self.compile(charango)
        self.assertEqual((repeated, repeated_digits), (evidence, digits))
        _, fresh, fresh_digits = self.compile(self.prepare("charango", "charango-fresh"))
        self.assertEqual((fresh, fresh_digits), (evidence, digits))

        # The staff-only production tail deliberately omits tablature.
        self.doc.write_text(self.fixture.replace("ulsbs-include-tail.ly", "ulsbs-include-tail-notab.ly"))
        _, staff_only, staff_digits = self.compile(self.prepare("charango", "staff-only"))
        self.assertEqual(staff_digits, [])
        self.assertNotEqual(staff_only, evidence)

        # Use the production multikey score assembler, not synthetic PDF shapes.
        job, _, env, includes = charango
        dimensions = tuple(lilypond_scores._dimensions(job.compile_dir / (graphic + ".pdf"))
                           for graphic in score.graphics)
        alternatives = []
        for interval, target in ((0, {"letter": 0, "pitch": 0}),
                                 (2, {"letter": 1, "pitch": 2})):
            with self.subTest(interval=interval):
                graphic, reason, log = lilypond_scores._engrave(
                    score, {"letter": 0, "pitch": 0, "minor": 0}, target,
                    interval, interval, dimensions, job.compile_dir, env, includes,
                )
                self.assertIsNotNone(graphic, (reason, (job.compile_dir / log).read_text()))
                pdf = (job.compile_dir / (graphic + "-1.pdf")).read_bytes()
                numbers = [row[0] for row in self.words(pdf)
                           if re.fullmatch(r"\d+", row[0])]
                self.assertEqual(len(numbers), 4)
                alternatives.append((self.words(pdf), numbers))
        self.assertEqual(alternatives[0], (evidence, digits))
        self.assertNotEqual(alternatives[1][0], alternatives[0][0])
        self.assertNotEqual(alternatives[1][1], alternatives[0][1])


if __name__ == "__main__":
    unittest.main()
