# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Focused PDF font step and publication-boundary tests without PDF tooling."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ulsbs import pipeline, resultlist
from ulsbs.config import Config
from ulsbs.jobs import Job, build_job_basename
from ulsbs.lock import JobLock


class PipelinePdfFontsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.result = self.root / "result"
        self.result.mkdir()
        self.compile_dir = self.root / "compile"
        self.compile_dir.mkdir()
        self.doc = self.root / "book.tex"
        self.doc.write_text("\\documentclass{article}\n", encoding="utf-8")
        self.job = Job(self.doc, "book", "default", self.compile_dir)
        self.pdf = self.compile_dir / "book.pdf"
        self.ui = Mock()
        self.ui.fmt_doc.return_value = "[book]"
        self.ui.fmt_step.side_effect = lambda step: f"{step:02d}"
        self.cfg = replace(
            Config(), max_log_lines=0,
            runtime=SimpleNamespace(project_paths=SimpleNamespace(
                project_root=self.root, result_dir=self.result,
            ), in_container=False),
        )

    def test_step_reports_savings_and_unchanged_results(self) -> None:
        for verbose, sizes in ((False, (100, 80, 2)), (False, (100, 100, 0)),
                               (True, (100, 80, 2)), (True, (100, 100, 0))):
            with self.subTest(verbose=verbose, sizes=sizes):
                self.ui.reset_mock()
                cfg = replace(self.cfg, verbose=verbose)
                optimizer = Mock(return_value=sizes)
                with patch.dict(sys.modules, {
                    "ulsbs.pdf_fonts": SimpleNamespace(deduplicate_fonts=optimizer),
                }):
                    self.assertEqual(pipeline.step_pdf_fonts(self.ui, cfg, self.job, "book", 7), 8)
                optimizer.assert_called_once_with(self.pdf)
                original, final, removed = sizes
                summary = (self.compile_dir / "07_pdf-fonts.log").read_text(encoding="utf-8")
                self.assertIn(f"{original} -> {final} bytes", summary)
                self.assertIn(f"saved {original - final} bytes", summary)
                self.assertIn(f"removed {removed} duplicate font-program streams", summary)
                self.ui.space_line.assert_not_called()
                if verbose:
                    self.ui.debug_line.assert_called_once_with(f"[book] {summary.strip()}")
                else:
                    self.ui.debug_line.assert_not_called()
                self.ui.exec_line.assert_called_with(
                    "[book] 07 internal: deduplicate PDF fonts"
                )

    def test_step_failure_retains_traceback_and_cause(self) -> None:
        error = ValueError("semantic validation failed")
        with patch.dict(sys.modules, {
            "ulsbs.pdf_fonts": SimpleNamespace(deduplicate_fonts=Mock(side_effect=error)),
        }):
            with self.assertRaisesRegex(pipeline.CompileError, str(error)) as caught:
                pipeline.step_pdf_fonts(self.ui, self.cfg, self.job, "book", 12)
        self.assertIs(caught.exception.__cause__, error)
        self.assertEqual(caught.exception.log_path, self.compile_dir / "12_pdf-fonts.log")
        log = caught.exception.log_path.read_text(encoding="utf-8")
        self.assertIn("Traceback (most recent call last)", log)
        self.assertIn("ValueError: semantic validation failed", log)
        self.ui.space_line.assert_not_called()
        self.ui.debug_line.assert_not_called()

    def test_failed_or_missing_pdf_is_never_published_or_consumed(self) -> None:
        for multikey, produce_pdf in ((False, True), (False, False), (True, True), (True, False)):
            with self.subTest(multikey=multikey, produce_pdf=produce_pdf):
                job = replace(self.job, multikey=multikey)
                basename = build_job_basename(job)
                pdf = self.compile_dir / f"{basename}.pdf"
                pdf.unlink(missing_ok=True)
                events = []
                optimizer = Mock(side_effect=RuntimeError("font validation failed"))

                def latex(*args, pass_no, events=events, produce_pdf=produce_pdf,
                          job=job, basename=basename, pdf=pdf, **kwargs):
                    events.append(pass_no)
                    if job.multikey:
                        (self.compile_dir / f"{basename}.ulsbs-multikey.json").write_text(
                            '{"has_multikey_info": true, "multikey_info": {"songs": []}}', encoding="utf-8",
                        )
                    if pass_no == 3 and produce_pdf:
                        pdf.write_bytes(b"%PDF-original")
                    return self.compile_dir / f"pass{pass_no}.log", args[-1] + 1

                resultlist.initialize(self.result, "font-failure")
                try:
                    with ExitStack() as stack:
                        stack.enter_context(patch.dict(sys.modules, {
                            "ulsbs.pdf_fonts": SimpleNamespace(deduplicate_fonts=optimizer),
                        }))
                        stack.enter_context(patch.object(pipeline, "prepare_compile_dir"))
                        stack.enter_context(patch.object(
                            pipeline, "build_include_paths", return_value=({}, [], []),
                        ))
                        stack.enter_context(patch.object(
                            pipeline, "step_lilypond_book",
                            return_value=(self.compile_dir / f"{basename}.tex", self.doc, 2),
                        ))
                        stack.enter_context(patch.object(pipeline, "step_texlua_indices", return_value=3))
                        stack.enter_context(patch.object(pipeline, "step_lualatex_pass", side_effect=latex))
                        # This test isolates font failure with a synthetic byte
                        # string; real PDF resource convergence is tested separately.
                        stack.enter_context(patch.object(
                            pipeline, "step_lualatex_convergence", side_effect=lambda *args: args[-2:],
                        ))
                        consumers = [stack.enter_context(patch.object(pipeline, name)) for name in (
                            "step_context_printouts", "step_coverimage_extraction",
                            "step_build_song_db", "step_midi_audio", "step_write_song_db_json",
                        )]
                        message = "font validation failed" if produce_pdf else "Expected PDF not produced"
                        with self.assertRaisesRegex(pipeline.CompileError, message) as caught:
                            pipeline.compile_one_job(self.ui, Mock(), self.cfg, job)
                        for consumer in consumers:
                            consumer.assert_not_called()
                    self.assertEqual(events, [1, 2, 3])
                    output_dir = self.result / "multikey" if multikey else self.result
                    self.assertFalse((output_dir / f"{basename}.pdf").exists())
                    self.assertFalse(resultlist.exists())
                    if produce_pdf:
                        optimizer.assert_called_once_with(pdf)
                        self.assertEqual(pdf.read_bytes(), b"%PDF-original")
                        self.assertEqual(caught.exception.log_path.name, "05_pdf-fonts.log")
                        self.assertIn("RuntimeError: font validation failed",
                                      caught.exception.log_path.read_text(encoding="utf-8"))
                    else:
                        optimizer.assert_not_called()
                    lock = JobLock(self.compile_dir)
                    lock.acquire()
                    lock.release()
                finally:
                    resultlist.delete()

    def test_require_tools_checks_pikepdf_without_external_optimizer(self) -> None:
        with patch.object(pipeline, "which", return_value="/bin/tool") as which, \
                patch.object(pipeline.importlib.util, "find_spec", return_value=object()) as spec:
            pipeline.require_tools()
        self.assertEqual([call.args[0] for call in which.call_args_list],
                         ["lualatex", "texlua", "lilypond-book"])
        spec.assert_called_once_with("pikepdf")

    def test_require_tools_explains_install_and_container_rebuild(self) -> None:
        with patch.object(pipeline, "which", return_value="/bin/tool"), \
                patch.object(pipeline.importlib.util, "find_spec", return_value=None):
            with self.assertRaises(SystemExit) as caught:
                pipeline.require_tools()
        message = str(caught.exception)
        for text in ("pikepdf>=8", "python3-pikepdf", "rebuild the compiler container"):
            self.assertIn(text, message)

    def test_multikey_preflights_qpdf_without_requiring_it_for_ordinary_jobs(self) -> None:
        """Missing extraction tooling fails early only when range output is requested."""
        with patch.object(pipeline, "which", return_value="/bin/tool"), \
                patch.object(pipeline.importlib.util, "find_spec", return_value=object()), \
                patch("ulsbs.multikey_ranges.qpdf_version", return_value="12.2.0") as version:
            pipeline.require_tools()
            version.assert_not_called()
            pipeline.require_tools(multikey=True)
            version.assert_called_once()
            version.side_effect = FileNotFoundError("qpdf missing")
            with self.assertRaisesRegex(SystemExit, "qpdf is required for MULTIKEY"):
                pipeline.require_tools(multikey=True)

    def test_help_does_not_import_optimizer_or_pikepdf(self) -> None:
        code = """
import importlib.abc
import sys

class BlockOptimizer(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('pikepdf', 'ulsbs.pdf_fonts'):
            raise AssertionError('Unexpected optimizer import: ' + fullname)

sys.meta_path.insert(0, BlockOptimizer())
sys.argv = ['ulsbs-compile', '--help']
from ulsbs.cli import main
main()
"""
        completed = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage:", completed.stdout.lower())


if __name__ == "__main__":
    unittest.main()
