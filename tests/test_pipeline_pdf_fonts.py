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
                project_root=self.root, host_project_root=self.root, result_dir=self.result,
            ), in_container=False),
        )

    def test_step_reports_savings_and_unchanged_results(self) -> None:
        for verbose, sizes in ((False, (100, 80, 2)), (False, (100, 100, 0)),
                               (True, (100, 80, 2)), (True, (100, 100, 0))):
            with self.subTest(verbose=verbose, sizes=sizes):
                self.ui.reset_mock()
                cfg = replace(self.cfg, verbose=verbose)
                original, final, removed = sizes
                log_path = self.compile_dir / "07_pdf-fonts.log"
                log_path.write_text(
                    f"PDF fonts: {original} -> {final} bytes; saved {original - final} bytes; "
                    f"removed {removed} duplicate font-program streams\n", encoding="utf-8",
                )
                with patch.object(pipeline, "run_cmd") as worker:
                    self.assertEqual(pipeline.step_pdf_fonts(self.ui, cfg, self.job, "book", 7), 8)
                worker.assert_called_once_with(
                    [sys.executable, str(Path(pipeline.__file__).with_name("pdf_fonts.py")), "--", self.pdf.name],
                    cwd=self.compile_dir, stdout_path=log_path, stderr_to_stdout=True, check=True,
                )
                self.ui.space_line.assert_not_called()
                if verbose:
                    self.ui.debug_line.assert_called_once_with(f"[book] {log_path.read_text().strip()}")
                else:
                    self.ui.debug_line.assert_not_called()
                self.ui.exec_line.assert_called_with(
                    "[book] 07 internal: deduplicate PDF fonts"
                )

    def test_worker_exit_preserves_child_diagnostics_and_records_status(self) -> None:
        error = subprocess.CalledProcessError(1, ["pdf_fonts.py"])

        def fail(args, *, stdout_path, **kwargs):
            stdout_path.write_text("ValueError: semantic validation failed\n", encoding="utf-8")
            raise error

        with patch.object(pipeline, "run_cmd", side_effect=fail):
            with self.assertRaisesRegex(pipeline.CompileError, "PDF font deduplication failed") as caught:
                pipeline.step_pdf_fonts(self.ui, self.cfg, self.job, "book", 12)
        self.assertIs(caught.exception.__cause__, error)
        self.assertEqual(caught.exception.log_path, self.compile_dir / "12_pdf-fonts.log")
        log = caught.exception.log_path.read_text(encoding="utf-8")
        self.assertIn("ValueError: semantic validation failed", log)
        self.assertIn("non-zero exit status 1", log)
        self.ui.space_line.assert_not_called()
        self.ui.debug_line.assert_not_called()

    def test_worker_cancellation_is_not_reported_as_a_job_failure(self) -> None:
        with patch.object(pipeline, "run_cmd", side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            pipeline.step_pdf_fonts(self.ui, self.cfg, self.job, "book", 7)

    def test_failed_or_missing_pdf_is_never_published_or_consumed(self) -> None:
        for multikey, produce_pdf in ((False, True), (False, False), (True, True), (True, False)):
            with self.subTest(multikey=multikey, produce_pdf=produce_pdf):
                job = replace(self.job, multikey=multikey)
                basename = build_job_basename(job)
                pdf = self.compile_dir / f"{basename}.pdf"
                pdf.unlink(missing_ok=True)
                events = []

                def fail(args, *, cwd, stdout_path, pdf=pdf, **kwargs):
                    self.assertEqual(cwd / args[-1], pdf)
                    stdout_path.write_text("RuntimeError: font validation failed\n", encoding="utf-8")
                    raise subprocess.CalledProcessError(1, args)

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
                        optimizer = stack.enter_context(patch.object(pipeline, "run_cmd", side_effect=fail))
                        stack.enter_context(patch.object(pipeline, "prepare_compile_dir"))
                        stack.enter_context(patch.object(
                            pipeline, "build_include_paths", return_value=({}, [], []),
                        ))
                        stack.enter_context(patch.object(
                            pipeline, "step_lilypond_book",
                            return_value=(self.compile_dir / f"{basename}.tex", self.doc, 2),
                        ))
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
                        message = "PDF font deduplication failed" if produce_pdf else "Expected PDF not produced"
                        with self.assertRaisesRegex(pipeline.CompileError, message) as caught:
                            pipeline.compile_one_job(self.ui, Mock(), self.cfg, job)
                        for consumer in consumers:
                            consumer.assert_not_called()
                    self.assertEqual(events, [1, 2, 3])
                    output_dir = self.result / "multikey" if multikey else self.result
                    self.assertFalse((output_dir / f"{basename}.pdf").exists())
                    self.assertFalse(resultlist.exists())
                    if produce_pdf:
                        optimizer.assert_called_once()
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
        for installed in ("10.0.0", "10.3.0", "11.0.0"):
            with self.subTest(installed=installed), \
                    patch.object(pipeline, "which", return_value="/bin/tool") as which, \
                    patch.object(pipeline.importlib.metadata, "version",
                                 return_value=installed) as version:
                pipeline.require_tools()
                self.assertEqual([call.args[0] for call in which.call_args_list],
                                 ["lualatex", "lilypond-book"])
                version.assert_called_once_with("pikepdf")

    def test_standard_pipeline_has_no_external_index_stage_and_gates_publication(self) -> None:
        request = ("Package ulsbs-index Warning: Index data changed. "
                   "Rerun LuaLaTeX to refresh the index.\n")
        for unsettled_passes in (0, 3, 5):
            with self.subTest(unsettled_passes=unsettled_passes):
                published = self.result / "book.pdf"
                published.unlink(missing_ok=True)
                commands = []

                def typeset(args, commands=commands, unsettled_passes=unsettled_passes, **kwargs):
                    commands.append(args)
                    self.assertEqual(args[0], "lualatex")
                    self.assertFalse(any("songidx" in arg for arg in args))
                    kwargs["stdout_path"].write_text(
                        request if len(commands) <= unsettled_passes else "settled\n",
                        encoding="utf-8",
                    )
                    if "-draftmode" not in args:
                        self.pdf.write_bytes(b"%PDF-test")

                cfg = replace(self.cfg, create_printouts=False, coverimage=False,
                              json=False, midifiles=False, audiofiles=False)
                resultlist.initialize(self.result, "index-pipeline")
                try:
                    with patch.object(pipeline, "prepare_compile_dir"), \
                            patch.object(pipeline, "build_include_paths", return_value=({}, [], [])), \
                            patch.object(pipeline, "step_lilypond_book", return_value=(
                                self.compile_dir / "book.tex", self.doc, 2)), \
                            patch.object(pipeline, "run_cmd", side_effect=typeset), \
                            patch.object(pipeline, "step_pdf_fonts", side_effect=lambda *args: args[-1] + 1) as fonts, \
                            patch.object(pipeline, "analyze_warnings", return_value=0):
                        if unsettled_passes == 5:
                            with self.assertRaisesRegex(pipeline.CompileError, "did not settle"):
                                pipeline.compile_one_job(self.ui, Mock(), cfg, self.job)
                            fonts.assert_not_called()
                            self.assertFalse(published.exists())
                            self.assertFalse(resultlist.exists())
                        else:
                            pipeline.compile_one_job(self.ui, Mock(), cfg, self.job)
                            fonts.assert_called_once()
                            self.assertTrue(published.exists())
                    self.assertEqual(len(commands), {0: 3, 3: 4, 5: 5}[unsettled_passes])
                    self.assertEqual(["-draftmode" in command for command in commands],
                                     [True] + [False] * (len(commands) - 1))
                finally:
                    resultlist.delete()

    def test_require_tools_rejects_missing_or_unsupported_pikepdf(self) -> None:
        for installed in (None, "8.15.1", "9.11.0"):
            missing = pipeline.importlib.metadata.PackageNotFoundError("pikepdf")
            with self.subTest(installed=installed), \
                    patch.object(pipeline, "which", return_value="/bin/tool"), \
                    patch.object(pipeline.importlib.metadata, "version", return_value=installed,
                                 side_effect=missing if installed is None else None):
                with self.assertRaises(SystemExit) as caught:
                    pipeline.require_tools()
                message = str(caught.exception)
                for text in ("pikepdf>=10", installed or "not installed", "python3-pikepdf",
                             "rebuild the compiler container"):
                    self.assertIn(text, message)

    def test_multikey_preflights_qpdf_without_requiring_it_for_ordinary_jobs(self) -> None:
        """Missing extraction tooling fails early only when range output is requested."""
        with patch.object(pipeline, "which", return_value="/bin/tool"), \
                patch.object(pipeline.importlib.metadata, "version", return_value="10.3.0"), \
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
