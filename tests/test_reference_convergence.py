# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bound reference retries and qualify an ordinary public synthetic songbook."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from ulsbs import pipeline
from ulsbs.config import Config
from ulsbs.jobs import Job


LABEL_REQUEST = "LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.\n"


class ReferenceConvergenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.log = self.root / "06_lualatex-pass3.log"
        self.log.write_text("settled", encoding="utf-8")
        self.job = Job(self.root / "public.tex", "public", "default", self.root)
        self.ui = Mock()
        self.cfg = Config()

    def converge(self, job=None):
        return pipeline.step_lualatex_convergence(
            self.ui, self.cfg, job or self.job, "public", {}, self.log, 7,
        )

    def test_completed_pass_records_engine_wall_time_in_its_log(self):
        def typeset(_command, **kwargs):
            kwargs["stdout_path"].write_text("Synthetic TeX output\n", encoding="utf-8")

        with patch.object(pipeline, "run_cmd", side_effect=typeset), \
                patch.object(pipeline.time, "perf_counter", side_effect=(10.0, 11.25)):
            log, step = pipeline.step_lualatex_pass(
                self.ui, self.cfg, self.job, "public", {}, 5, 3, False,
            )
        self.assertEqual((log.name, step), ("05_lualatex-pass3.log", 6))
        self.assertIn("Synthetic TeX output", log.read_text())
        self.assertIn("ULSBS wall time: 1.250 seconds (LuaLaTeX pass 3, full)", log.read_text())

    def test_explicit_requests_retry_once_and_return_latest_log(self):
        requests = (
            LABEL_REQUEST,
            "LaTeX Warning: Label(s) may have\n changed.\n",
            "LaTeX Warning: Rerun to get cross-\nreferences right.\n",
            "Package rerunfilecheck Warning: File `a-long-public-name\n.out' has changed.\n"
            "(rerunfilecheck) Rerun to get outlines right.\n",
            "Package hyperref Warning: Rerun to get /PageLabels right.\n",
            "Package hyperref Warning: Rerun to get /PageLabels entry.\n",
            "Package hyperref Warning: Rerun to get /Page\n(hyperref) Labels right.\n",
            "Package lastpage Warning: Rerun to get the references right.\n",
            "Package lastpage Warning: Rerun to get the\n(lastpage) references right.\n",
        )
        for request in requests:
            with self.subTest(request=request):
                self.log.write_text(request, encoding="utf-8")
                latest = self.root / "07_lualatex-pass4.log"
                latest.write_text("settled", encoding="utf-8")
                with patch.object(pipeline, "step_lualatex_pass", return_value=(latest, 8)) as latex, \
                        patch("ulsbs.multikey_ranges.check_pdf_property_resources") as resources:
                    self.assertEqual(self.converge(), (latest, 8))
                latex.assert_called_once_with(
                    self.ui, self.cfg, self.job, "public", {}, 7, 4, False,
                )
                resources.assert_not_called()

    def test_benign_warnings_undefined_references_and_package_names_do_not_retry(self):
        self.log.write_text(
            "(/tex/latex/rerunfilecheck/rerunfilecheck.sty)\n"
            "Package: rerunfilecheck\n"
            "Rerun to get cross-references right.\n\n"
            "LaTeX Warning: There were undefined references.\n\n"
            "LaTeX Warning: Reference `missing' on page 1 undefined on input line 9.\n\n"
            "Package hyperref Warning: Token not allowed in a PDF string.\n\n"
            "Package rerunfilecheck Info: File `public.out' has changed.\n\n"
            "Package rerunfilecheck Warning: File `public.bcf' has changed.\n\n"
            "Package unrelated Warning: Rerun to get cross-references right.\n\n"
            "warning: barcheck failed\n",
            encoding="utf-8",
        )
        with patch.object(pipeline, "step_lualatex_pass") as latex, \
                patch("ulsbs.multikey_ranges.check_pdf_property_resources") as resources:
            self.assertEqual(self.converge(), (self.log, 7))
        latex.assert_not_called()
        resources.assert_not_called()

    def test_persistent_requests_fail_after_two_extra_passes(self):
        self.log.write_text(LABEL_REQUEST, encoding="utf-8")
        with patch.object(pipeline, "step_lualatex_pass",
                          side_effect=[(self.log, 8), (self.log, 9)]) as latex:
            with self.assertRaisesRegex(pipeline.CompileError, "did not settle") as caught:
                self.converge()
        self.assertEqual([call.args[-2:] for call in latex.call_args_list], [(4, False), (5, False)])
        self.assertEqual(caught.exception.log_path.name, "09_lualatex-convergence.log")
        diagnostic = caught.exception.log_path.read_text()
        self.assertIn(str(self.log), diagnostic)
        self.assertIn("Label(s) may have changed", diagnostic)

    def test_retry_budget_uses_shared_build_policy(self):
        for budget in (0, 1):
            with self.subTest(budget=budget):
                self.log.write_text(LABEL_REQUEST, encoding="utf-8")
                with patch.object(pipeline, "LUALATEX_MAX_EXTRA_PASSES", budget), \
                        patch.object(pipeline, "step_lualatex_pass", return_value=(self.log, 8)) as latex:
                    with self.assertRaisesRegex(pipeline.CompileError, f"after {budget} extra passes"):
                        self.converge()
                self.assertEqual(latex.call_count, budget)

    def test_multikey_resources_and_reference_requests_share_retry_budget(self):
        latest = self.root / "07_lualatex-pass4.log"
        latest.write_text(LABEL_REQUEST, encoding="utf-8")
        job = replace(self.job, multikey=True)
        with patch("ulsbs.multikey_ranges.check_pdf_property_resources",
                   side_effect=[ValueError("stale property"), None, None]) as resources, \
                patch.object(pipeline, "step_lualatex_pass",
                             side_effect=[(latest, 8), (latest, 9)]) as latex:
            with self.assertRaisesRegex(pipeline.CompileError, "did not settle"):
                self.converge(job)
        self.assertEqual(resources.call_count, 3)
        self.assertEqual(latex.call_count, 2)

    def test_unreadable_initial_or_retry_log_fails_without_speculative_passes(self):
        self.log.unlink()
        with patch.object(pipeline, "step_lualatex_pass") as latex, \
                patch("ulsbs.multikey_ranges.check_pdf_property_resources") as resources:
            with self.assertRaisesRegex(pipeline.CompileError, "Cannot inspect") as caught:
                self.converge(replace(self.job, multikey=True))
        latex.assert_not_called()
        resources.assert_not_called()
        self.assertIsInstance(caught.exception.__cause__, FileNotFoundError)
        self.assertEqual(caught.exception.log_path.name, "07_lualatex-convergence.log")
        self.log.write_text(LABEL_REQUEST, encoding="utf-8")
        with patch.object(pipeline, "step_lualatex_pass",
                          return_value=(self.root / "missing.log", 8)) as latex:
            with self.assertRaisesRegex(pipeline.CompileError, "Cannot inspect"):
                self.converge()
        latex.assert_called_once()

    def test_compiler_failure_is_not_retried_or_rewrapped(self):
        self.log.write_text(LABEL_REQUEST, encoding="utf-8")
        error = pipeline.CompileError("compiler failed", self.log)
        with patch.object(pipeline, "step_lualatex_pass", side_effect=error) as latex:
            with self.assertRaises(pipeline.CompileError) as caught:
                self.converge()
        self.assertIs(caught.exception, error)
        latex.assert_called_once()


@unittest.skipUnless(all(shutil.which(tool) for tool in ("lualatex", "texlua", "pdftotext")),
                     "ordinary songbook PDF tools unavailable")
class OrdinaryReferenceIntegrationTests(unittest.TestCase):
    def test_toc_song_index_and_named_page_references_settle_by_pass_three(self):
        import pikepdf

        from test_tex_integration import TEX_ASSETS
        from ulsbs.multikey_ranges import _destinations

        source = r"""\newcommand{\ulPdfTranspositionLayers}{false}
\documentclass[oneside,openany,paper={a5paper},maintitle={Public Reference Test}]{ulsbs-songbook}
\begin{document}
\tableofcontents
\clearpage
\showindex{Song Title Index}{titleidx}
\clearpage
\chapter{Public Alpha}\hypertarget{public-alpha-target}{}\label{alpha}
Alpha target page \pageref{alpha}. Beta target page \pageref{beta}.\par
\begin{songs}{titleidx}
\beginsong{Public Alpha Song}[id={public-alpha},key={C}]
\beginverse
\[C]Public synthetic line.
\endverse
\endsong
\end{songs}
\clearpage
\chapter{Public Beta}\hypertarget{public-beta-target}{}\label{beta}
Alpha target page \pageref{alpha}. Beta target page \pageref{beta}.\par
\begin{songs}{titleidx}
\beginsong{Public Beta Song}[id={public-beta},key={G}]
\beginverse
\[G]Another public synthetic line.
\endverse
\endsong
\end{songs}
\end{document}
"""
        with tempfile.TemporaryDirectory(prefix="ulsbs-test-ordinary-refs-") as directory:
            root = Path(directory)
            tex = root / "public.tex"
            tex.write_text(source, encoding="utf-8")
            cache = root / "texmf-cache"
            cache.mkdir()
            env = dict(os.environ, TEXINPUTS=f"{TEX_ASSETS}//{os.pathsep}",
                       TEXMFVAR=str(cache), TEXMFCACHE=str(cache))
            job = Job(tex, "public", "default", root)
            ui, cfg = Mock(), Config()
            try:
                last, step = pipeline.step_lualatex_pass(ui, cfg, job, "public", env, 1, 1, True)
            except pipeline.CompileError as error:
                self.fail(error.log_path.read_text())
            subprocess.run(
                ["texlua", str(TEX_ASSETS / "ext_packages/songs/songidx.lua"),
                 "idx_title.sxd", "idx_title.sbx"],
                cwd=root, env=env, check=True, capture_output=True, text=True,
            )
            self.assertIn("Public Alpha Song", (root / "idx_title.sbx").read_text())
            for pass_no in (2, 3):
                last, step = pipeline.step_lualatex_pass(
                    ui, cfg, job, "public", env, step, pass_no, False,
                )
            self.assertNotIn("undefined references", last.read_text())
            with patch.object(pipeline, "step_lualatex_pass") as retry, \
                    patch("ulsbs.multikey_ranges.check_pdf_property_resources") as resources:
                self.assertEqual(pipeline.step_lualatex_convergence(
                    ui, cfg, job, "public", env, last, step,
                ), (last, step))
            retry.assert_not_called()
            resources.assert_not_called()

            def snapshot():
                """Compare destinations and visible text geometry, not volatile PDF bytes."""
                with pikepdf.open(root / "public.pdf") as pdf:
                    self.assertNotIn("/OCProperties", pdf.Root)
                    targets = _destinations(pdf)
                xml = subprocess.run(
                    ["pdftotext", "-bbox", str(root / "public.pdf"), "-"],
                    check=True, capture_output=True, text=True,
                ).stdout
                pages = ET.fromstring(xml).findall(".//{http://www.w3.org/1999/xhtml}page")
                geometry = [
                    (number, word.text, *(round(float(word.get(key)), 2)
                                         for key in ("xMin", "yMin", "xMax", "yMax")))
                    for number, page in enumerate(pages)
                    for word in page.findall("{http://www.w3.org/1999/xhtml}word")
                ]
                visible = " ".join(word[1] or "" for word in geometry)
                contents = " ".join(word[1] or "" for word in geometry if word[0] == 0)
                self.assertIn("Public Alpha", contents)
                self.assertIn("Public Beta", contents)
                for name, target in (("Alpha", "public-alpha-target"), ("Beta", "public-beta-target")):
                    self.assertIn(f"{name} target page {targets[target][0] + 1}.", visible)
                self.assertNotIn("??", visible)
                self.assertGreaterEqual(visible.count("Public Alpha Song"), 2)
                self.assertGreaterEqual(visible.count("Public Beta Song"), 2)
                return targets, [(page.get("width"), page.get("height")) for page in pages], geometry

            third = snapshot()
            pipeline.step_lualatex_pass(ui, cfg, job, "public", env, step, 4, False)
            self.assertEqual(third, snapshot())


if __name__ == "__main__":
    unittest.main()
