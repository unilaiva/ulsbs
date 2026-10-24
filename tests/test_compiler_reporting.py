# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reporting/inventory boundaries with real UI and synthetic compiler logs."""

from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import shutil
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ulsbs import pipeline, resultlist
from ulsbs.config import Config
from ulsbs.constants import RESULT_TYPE_MAIN_PDF
from ulsbs.diagnostics import Diagnostic
from ulsbs.jobs import Job, build_job_basename
from ulsbs.ui import UI


class CompilerReportingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ulsbs-reporting-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.compile_dir = self.root / "compile"
        self.compile_dir.mkdir()
        self.result_dir = self.root / "result"
        self.result_dir.mkdir()
        self.doc = self.root / "book_A5.tex"
        self.doc.write_text("\\documentclass{ulsbs-songbook}\n", encoding="utf-8")
        self.job = Job(self.doc, self.doc.stem, "default", self.compile_dir)
        self.basename = build_job_basename(self.job)
        self.cfg = replace(Config(), runtime=SimpleNamespace(
            project_paths=SimpleNamespace(project_root=self.root, result_dir=self.result_dir),
            in_container=False,
        ))
        self.ui = UI(use_colors=False)
        resultlist.initialize(self.result_dir, unique_id="reporting-test")
        self.addCleanup(resultlist.delete)
        resultlist.write_header()
        pipeline.ABORT_EVENT.clear()

    def log(self, name, text):
        path = self.compile_dir / name
        path.write_text(text, encoding="utf-8")
        return path

    @contextmanager
    def capture(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            yield stdout, stderr

    def report(self):
        path = self.result_dir / "diagnostics" / f"{self.basename}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_worker_warning_defers_output_and_retains_metadata(self):
        worker = pipeline._JobUI(self.ui, self.job)
        log = self.log("scores.log", "details\n")
        with self.capture() as (stdout, stderr):
            worker.warning_line(
                f"{self.ui.fmt_doc(self.job)} Warning: Three scores omitted",
                stderr=True, source="Scores", category="omitted-score",
                log_path=log, affected_count=3,
            )
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")
        self.assertEqual(worker.diagnostics, [Diagnostic(
            "Scores", "omitted-score", "Three scores omitted", log, affected_count=3,
        )])
        self.assertEqual(self.ui.run_diagnostics, [])

    def test_only_final_tex_pass_contributes_records_and_counts(self):
        self.log("01_lualatex-pass1.log", "LaTeX Warning: Reference `early' undefined.\n")
        self.log("02_lualatex-pass2.log", "Missing character: There is no OLD in font example!\n")
        latest = self.log("03_lualatex-pass3.log", (
            "Package demo Warning: Final issue with warning in its message\n"
            "(demo)                and a continuation.\n\n"
        ) * 2)
        worker = pipeline._JobUI(self.ui, self.job)
        worker.last_tex_log = latest
        with self.capture() as (stdout, stderr):
            count = pipeline.analyze_warnings(worker, self.cfg, self.job, None, latest)
        self.assertEqual(count, 2)
        self.assertEqual(len(worker.diagnostics), 1)
        self.assertEqual(worker.diagnostics[0].occurrences, 2)
        self.assertEqual(worker.diagnostics[0].log_path, latest)
        self.assertNotIn("early", worker.diagnostics[0].message)
        self.assertNotIn("OLD", worker.diagnostics[0].message)
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")

    def test_native_and_multiple_external_sources_count_once(self):
        worker = pipeline._JobUI(self.ui, self.job)
        native_log = self.log("scores.log", "score extraction details\n")
        worker.warning_line("Some supplemental scores omitted", source="Scores",
                            category="omitted-score", log_path=native_log, affected_count=7)
        lily = self.log("lilypond.log", "warning: barcheck failed\n" * 2)
        tex = self.log("final.log", "Missing character: There is no X in font example!\n")
        index = self.log("indices.log", "Index: warning: unknown entry\n")
        worker.tool_logs[index] = "Index"
        worker.tool_logs[lily] = "LilyPond"
        count = pipeline.analyze_warnings(worker, self.cfg, self.job, lily, tex)
        self.assertEqual(count, 5)
        self.assertEqual({item.source for item in worker.diagnostics}, {"Scores", "Index", "LilyPond", "TeX"})
        self.assertEqual(worker.diagnostics[0].affected_count, 7)
        self.assertEqual(worker.diagnostics[0].occurrences, 1)

    def test_unfamiliar_warning_messages_are_counted_and_reported_with_log_paths(self):
        self.log("early.log", "LaTeX Warning: An earlier unfamiliar diagnostic.\n")
        tex = self.log("final.log", "LaTeX Warning: An unfamiliar future diagnostic.\n" * 2)
        lily = self.log("lilypond.log", "score.ly:4:2: warning: An unfamiliar engraving issue\n")
        for verbose in (False, True):
            with self.subTest(verbose=verbose):
                worker = pipeline._JobUI(self.ui, self.job)
                cfg = replace(self.cfg, verbose=verbose)
                count = pipeline.analyze_warnings(worker, cfg, self.job, lily, tex)
                self.assertEqual(count, 3)
                self.assertEqual({item.category for item in worker.diagnostics}, {"other"})
                with self.capture() as (stdout, stderr):
                    pipeline._report_success(self.ui, cfg, self.job, worker.diagnostics)
                text = stdout.getvalue() + stderr.getvalue()
                self.assertIn("successful with 3 warnings!", text)
                self.assertIn("compile/final.log", text)
                self.assertIn("compile/lilypond.log", text)
                self.assertNotIn("earlier unfamiliar", text)
                if verbose:
                    self.assertIn("An unfamiliar future diagnostic", text)
                    self.assertIn("An unfamiliar engraving issue", text)
                else:
                    self.assertIn("TeX: 2 unclassified warnings", text)
                    self.assertIn("LilyPond: 1 unclassified warning", text)
                    self.assertNotIn("An unfamiliar future diagnostic", text)

    def test_native_readme_warning_is_not_recounted_from_media_log(self):
        worker = pipeline._JobUI(self.ui, self.job)
        log = self.log("midi.log", (
            "Warning: Readme for MIDI directories does not exist: missing.md\n"
            "warning: separate encoder warning\n"
        ))
        worker.warning_line("Readme for MIDI does not exist: missing.md", source="Media",
                            category="missing-readme", log_path=log)
        worker.tool_logs[log] = "Media"
        self.assertEqual(pipeline.analyze_warnings(worker, self.cfg, self.job, None, None), 2)
        self.assertEqual(len(worker.diagnostics), 2)

    def test_verbosity_does_not_change_analyzed_totals_or_records(self):
        tex = self.log("final.log", "LaTeX Warning: Reference `final' undefined.\n" * 2)
        lily = self.log("lilypond.log", (
            "warning: Unable to auto-detect default settings\n"
            "warning: visible LilyPond warning\n"
        ))
        records = []
        for verbose in (False, True):
            cfg = replace(self.cfg, verbose=verbose)
            worker = pipeline._JobUI(self.ui, self.job)
            worker.warning_line("Score omitted", source="Scores", category="omitted-score", affected_count=6)
            with self.capture() as (stdout, stderr):
                count = pipeline.analyze_warnings(worker, cfg, self.job, lily, tex)
                pipeline._report_success(self.ui, cfg, self.job, tuple(worker.diagnostics))
            self.assertEqual(count, 4)
            self.assertIn("successful with 4 warnings!", stdout.getvalue() + stderr.getvalue())
            self.assertNotIn("Unable to auto-detect", stdout.getvalue() + stderr.getvalue())
            records.append(tuple(worker.diagnostics))
        self.assertEqual(records[0], records[1])

    def test_missing_log_is_a_reporting_warning_not_clean_success(self):
        worker = pipeline._JobUI(self.ui, self.job)
        missing = self.compile_dir / "missing-final.log"
        self.assertEqual(pipeline.analyze_warnings(worker, self.cfg, self.job, None, missing), 1)
        self.assertEqual(worker.diagnostics[0].source, "Reporting")
        self.assertEqual(worker.diagnostics[0].category, "unreadable-log")
        self.assertEqual(worker.diagnostics[0].log_path, missing)
        with self.capture() as (stdout, stderr):
            pipeline._report_success(self.ui, self.cfg, self.job, tuple(worker.diagnostics))
        text = stdout.getvalue() + stderr.getvalue()
        self.assertIn("Cannot inspect TeX log", text)
        self.assertIn("successful with 1 warning!", text)
        self.assertNotIn("Compilation successful!", text)

    def test_warning_details_and_paths_precede_success_at_both_verbosity_levels(self):
        tex = self.log("final.log", "details\n")
        native = self.log("scores.log", "details\n")
        diagnostics = (
            Diagnostic("TeX", "fonts", "Specific final font warning", tex, occurrences=2),
            Diagnostic("Scores", "omitted-score", "Some scores omitted", native, affected_count=4),
            Diagnostic("Scores", "other", "Another score issue", native),
        )
        for verbose in (False, True):
            with self.subTest(verbose=verbose), self.capture() as (stdout, stderr):
                pipeline._report_success(self.ui, replace(self.cfg, verbose=verbose), self.job, diagnostics)
            text = stdout.getvalue() + stderr.getvalue()
            self.assertIn("4 warnings", text)
            self.assertIn("Compilation successful with 4 warnings!", text)
            self.assertLess(text.index("WARNING"), text.index("SUCCESS"))
            self.assertLess(text.index("Some scores omitted"), text.index("SUCCESS"))
            self.assertLess(text.index("SEE"), text.index("SUCCESS"))
            self.assertLess(text.index("compile/final.log"), text.index("SUCCESS"))
            self.assertEqual(text.count("compile/scores.log"), 1)
            self.assertLess(text.index("SUCCESS"), text.index(f"result/{self.basename}.pdf"))
            self.assertNotIn("Compilation successful!", text)
            self.assertEqual(self.ui.run_diagnostics, [])

    def test_clean_success_has_no_warning_qualifier(self):
        with self.capture() as (stdout, stderr):
            pipeline._report_success(self.ui, self.cfg, self.job, ())
        text = stdout.getvalue() + stderr.getvalue()
        self.assertIn("Compilation successful!", text)
        self.assertNotIn("WARNING", text)
        self.assertNotIn("0 warnings", text)

    def test_layout_summary_includes_overfull_subset_without_changing_totals(self):
        tex = self.log("final.log", (
            "Overfull \\hbox (2.0pt too wide) at line 4\n" * 2
            + "Overfull \\vbox (3.0pt too high) at line 8\n"
            + "Package geometry Warning: Unexpected layout setting.\n\n"
            + "LaTeX Font Warning: An unavailable shape.\n\n"
            + "Underfull \\hbox (badness 10000) at line 9\n"
        ))
        for verbose in (False, True):
            with self.subTest(verbose=verbose):
                worker = pipeline._JobUI(self.ui, self.job)
                cfg = replace(self.cfg, verbose=verbose)
                self.assertEqual(pipeline.analyze_warnings(worker, cfg, self.job, None, tex), 5)
                with self.capture() as (stdout, stderr):
                    pipeline._report_success(self.ui, cfg, self.job, worker.diagnostics)
                text = stdout.getvalue() + stderr.getvalue()
                self.assertIn("successful with 5 warnings!", text)
                self.assertIn("compile/final.log", text)
                if verbose:
                    self.assertIn("Overfull \\hbox", text)
                    self.assertIn("Overfull \\vbox", text)
                else:
                    self.assertIn("TeX: 4 layout (3 overfull)", text)
                    self.assertIn("TeX: 1 fonts", text)

    def test_layout_overfull_subset_is_source_local_and_zero_is_omitted(self):
        diagnostics = (
            Diagnostic("TeX", "layout", "Overfull \\hbox (2pt too wide)", occurrences=2),
            Diagnostic("LilyPond", "layout", "warning: Unexpected page break"),
        )
        with self.capture() as (stdout, stderr):
            pipeline._report_success(self.ui, self.cfg, self.job, diagnostics)
        text = stdout.getvalue() + stderr.getvalue()
        self.assertIn("TeX: 2 layout (2 overfull)", text)
        self.assertIn("LilyPond: 1 layout", text)
        self.assertNotIn("LilyPond: 1 layout (", text)
        self.assertNotIn("0 overfull", text)

    def test_convergence_does_not_echo_earlier_warning_even_when_verbose(self):
        for verbose in (False, True):
            with self.subTest(verbose=verbose):
                cfg = replace(self.cfg, verbose=verbose)
                initial = self.log("03_lualatex-pass3.log", (
                    "LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.\n"
                ))
                worker = pipeline._JobUI(self.ui, self.job)

                def typeset(_args, **kwargs):
                    kwargs["stdout_path"].write_text("Settled final pass.\n", encoding="utf-8")

                with self.capture() as (stdout, stderr), patch.object(pipeline, "run_cmd", side_effect=typeset):
                    latest, step = pipeline.step_lualatex_convergence(
                        worker, cfg, self.job, self.basename, {}, initial, 4,
                    )
                    count = pipeline.analyze_warnings(worker, cfg, self.job, None, latest)
                    pipeline._report_success(self.ui, cfg, self.job, tuple(worker.diagnostics))
                text = stdout.getvalue() + stderr.getvalue()
                self.assertEqual(step, 5)
                self.assertEqual(worker.last_tex_log, latest)
                self.assertEqual(count, 0)
                self.assertIn("Rerunning LuaLaTeX pass 4", text)
                self.assertNotIn("LaTeX Warning", text)
                self.assertNotIn("Label(s) may have changed", text)
                self.assertIn("Compilation successful!", text)

    def test_tex_log_is_tracked_before_subprocess_failure(self):
        worker = pipeline._JobUI(self.ui, self.job)
        expected = self.compile_dir / "04_lualatex-pass3.log"

        def failing_command(_args, **kwargs):
            self.assertEqual(worker.last_tex_log, expected)
            self.assertEqual(kwargs["stdout_path"], expected)
            expected.write_text("LaTeX Warning: Final failure warning.\n", encoding="utf-8")
            raise RuntimeError("synthetic subprocess failure")

        with self.capture(), patch.object(pipeline, "run_cmd", side_effect=failing_command):
            with self.assertRaises(pipeline.CompileError) as caught:
                pipeline.step_lualatex_pass(worker, self.cfg, self.job, self.basename, {}, 4, 3, False)
        self.assertEqual(caught.exception.log_path, expected)
        self.assertEqual(worker.last_tex_log, expected)

    def test_success_wrapper_keeps_diagnostics_after_compile_directory_cleanup(self):
        latest = self.log("final.log", "LaTeX Font Warning: Font shape `example' undefined.\n" * 2)

        def compile_synthetic(worker, _assets, cfg, job):
            worker.warning_line("Supplemental score omitted", source="Scores",
                                category="omitted-score", affected_count=2)
            worker.last_tex_log = latest
            count = pipeline.analyze_warnings(worker, cfg, job, None, latest)
            worker.analyzed = True
            resultlist.append_line(RESULT_TYPE_MAIN_PDF, f"{self.basename}.pdf")
            return pipeline.CompilationResult(count, 17)

        with self.capture() as (stdout, stderr), patch.object(pipeline, "_compile_one_job", side_effect=compile_synthetic):
            result = pipeline.compile_one_job(self.ui, object(), self.cfg, self.job)
        self.assertEqual((result.warning_count, result.next_step), (3, 17))
        self.assertEqual(len(result.diagnostics), 2)
        self.assertIn("successful with 3 warnings!", stdout.getvalue() + stderr.getvalue())
        self.assertTrue(any(f"{self.basename}.pdf" in line for line in resultlist.lines()))
        shutil.rmtree(self.compile_dir)
        report = self.report()
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["variant"], "default")
        self.assertEqual(report["edition"], "standard")
        self.assertEqual(sum(item["occurrences"] for item in report["warnings"]), 3)
        self.assertEqual(report["warnings"][0]["affected_count"], 2)
        self.assertEqual(report["warnings"][1]["log"], str(latest))
        self.assertIn("Font shape", report["warnings"][1]["message"])
        self.assertEqual(result.diagnostics[1].occurrences, 2)

    def test_failure_retains_final_and_tracked_diagnostics_but_discards_inventory(self):
        early = self.log("01_lualatex-pass1.log", "LaTeX Warning: EARLY reference undefined.\n")
        latest = self.log("04_lualatex-pass3.log", "LaTeX Warning: Final failure warning.\n")
        lily = self.log("lilypond.log", "warning: barcheck failed\n")
        failure = pipeline.CompileError("Synthetic compilation failure", latest)
        committed = list(resultlist.lines())

        def compile_failure(worker, _assets, _cfg, job):
            worker.warning_line("Score omitted before failure", source="Scores", category="omitted-score",
                                affected_count=5)
            worker.last_tex_log = latest
            worker.tool_logs[lily] = "LilyPond"
            resultlist.append_line(RESULT_TYPE_MAIN_PDF, "provisional.pdf")
            self.assertTrue(any("provisional.pdf" in line for line in resultlist.lines()))
            raise failure

        with self.capture() as (stdout, stderr), patch.object(pipeline, "_compile_one_job", side_effect=compile_failure):
            with self.assertRaises(pipeline.CompileError) as caught:
                pipeline.compile_one_job(self.ui, object(), self.cfg, self.job)
        self.assertIs(caught.exception, failure)
        self.assertEqual(sum(item.occurrences for item in failure.diagnostics), 3)
        self.assertTrue(all(item.log_path != early for item in failure.diagnostics))
        self.assertEqual(failure.diagnostics[0].affected_count, 5)
        self.assertEqual(resultlist.lines(), committed)
        with resultlist.job_scope(self.job):
            self.assertEqual(resultlist.lines(), committed)
        self.assertNotIn("SUCCESS", stdout.getvalue() + stderr.getvalue())
        shutil.rmtree(self.compile_dir)
        report = self.report()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(report["warnings"]), 3)
        self.assertTrue(any("Final failure warning" in item["message"] for item in report["warnings"]))

    def test_failure_with_unreadable_log_still_has_durable_reporting_diagnostic(self):
        missing = self.compile_dir / "missing.log"

        def compile_failure(worker, *_args):
            worker.last_tex_log = missing
            raise pipeline.CompileError("Failed before log could be opened", missing)

        with self.capture(), patch.object(pipeline, "_compile_one_job", side_effect=compile_failure):
            with self.assertRaises(pipeline.CompileError) as caught:
                pipeline.compile_one_job(self.ui, object(), self.cfg, self.job)
        self.assertEqual(len(caught.exception.diagnostics), 1)
        self.assertEqual(caught.exception.diagnostics[0].category, "unreadable-log")
        self.assertEqual(self.report()["warnings"][0]["log"], str(missing))

    def test_repeated_concrete_source_error_is_compacted_but_each_job_remains_visible(self):
        text = "FULL ERROR CONTEXT\nbook_A5.tex:12: Undefined control sequence.\n"
        first_log = self.log("first-failure.log", text)
        second_log = self.log("second-failure.log", text)
        other_job = replace(self.job, variant="charango")
        failures = (
            pipeline.JobFailure(self.job, "Compiler failed", log_path=first_log),
            pipeline.JobFailure(other_job, "Compiler failed", log_path=second_log),
        )
        for verbose in (False, True):
            with self.subTest(verbose=verbose), self.capture() as (stdout, stderr):
                seen = {}
                for failure in failures:
                    pipeline._report_failure(self.ui, replace(self.cfg, verbose=verbose, max_log_lines=8), failure, seen)
            output = stdout.getvalue() + stderr.getvalue()
            self.assertEqual(output.count("FAIL"), 2)
            self.assertEqual(output.count("SEE"), 2)
            self.assertIn("compile/first-failure.log", output)
            self.assertIn("compile/second-failure.log", output)
            self.assertEqual(output.count("FULL ERROR CONTEXT"), 2 if verbose else 1)
            self.assertEqual("Same source error as" in output, not verbose)

    def test_generic_same_named_failures_are_not_treated_as_same_source_error(self):
        log = self.log("generic-failure.log", "GENERIC ERROR CONTEXT\nTool failed without source location.\n")
        failures = (
            pipeline.JobFailure(self.job, "Compiler failed", log_path=log),
            pipeline.JobFailure(replace(self.job, variant="charango"), "Compiler failed", log_path=log),
        )
        with self.capture() as (stdout, stderr):
            seen = {}
            for failure in failures:
                pipeline._report_failure(self.ui, replace(self.cfg, verbose=False, max_log_lines=8), failure, seen)
        output = stdout.getvalue() + stderr.getvalue()
        self.assertEqual(output.count("GENERIC ERROR CONTEXT"), 2)
        self.assertNotIn("Same source error as", output)

    def test_output_blocks_are_reentrant_and_not_interleaved(self):
        started, finished = threading.Event(), threading.Event()
        errors = []

        def other_block():
            started.set()
            try:
                with self.ui.output_block():
                    self.ui.info_line("second-block")
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()

        thread = threading.Thread(target=other_block, daemon=True)
        with self.capture() as (stdout, stderr):
            with self.ui.output_block():
                self.ui.info_line("first-block-start")
                with self.ui.output_block():
                    self.ui.info_line("first-block-nested")
                thread.start()
                self.assertTrue(started.wait(timeout=5))
                self.assertFalse(finished.is_set())
                self.ui.info_line("first-block-end")
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        text = stdout.getvalue() + stderr.getvalue()
        self.assertLess(text.index("first-block-start"), text.index("first-block-nested"))
        self.assertLess(text.index("first-block-nested"), text.index("first-block-end"))
        self.assertLess(text.index("first-block-end"), text.index("second-block"))

    def test_ordinary_exec_line_cannot_split_warning_success_output_block(self):
        warning_ready = threading.Event()
        exec_attempted, exec_finished = threading.Event(), threading.Event()
        release_report = threading.Event()
        errors = []
        log = self.log("atomic-warning.log", "warning details\n")
        diagnostics = (Diagnostic("Scores", "other", "ATOMIC WARNING DETAIL", log),)
        report_warnings = pipeline._report_warnings

        def pause_after_warnings(*args, **kwargs):
            report_warnings(*args, **kwargs)
            # _report_success still owns output_block here, after WARNING/SEE
            # but before SUCCESS and the final artifact path.
            warning_ready.set()
            if not release_report.wait(timeout=5):
                raise AssertionError("Timed out waiting to finish warning-success block")

        def reporting_worker():
            try:
                pipeline._report_success(self.ui, self.cfg, self.job, diagnostics)
            except Exception as error:
                errors.append(error)

        def ordinary_worker():
            try:
                exec_attempted.set()
                self.ui.exec_line("COMPETING ORDINARY EXEC")
            except Exception as error:
                errors.append(error)
            finally:
                exec_finished.set()

        reporting = threading.Thread(target=reporting_worker, daemon=True)
        ordinary = threading.Thread(target=ordinary_worker, daemon=True)
        with self.capture() as (stdout, stderr), patch.object(
            pipeline, "_report_warnings", side_effect=pause_after_warnings,
        ):
            reporting.start()
            try:
                self.assertTrue(warning_ready.wait(timeout=5))
                ordinary.start()
                self.assertTrue(exec_attempted.wait(timeout=5))
                self.assertFalse(exec_finished.wait(timeout=0.1),
                                 "Ordinary exec_line escaped a held output_block")
            finally:
                release_report.set()
                reporting.join(timeout=5)
                if ordinary.ident is not None:
                    ordinary.join(timeout=5)
        self.assertFalse(reporting.is_alive())
        self.assertFalse(ordinary.is_alive())
        self.assertEqual(errors, [])
        text = stdout.getvalue() + stderr.getvalue()
        self.assertLess(text.index("WARNING"), text.index("SEE"))
        self.assertLess(text.index("SEE"), text.index("SUCCESS"))
        self.assertLess(text.index("SUCCESS"), text.index(f"result/{self.basename}.pdf"))
        self.assertLess(text.index(f"result/{self.basename}.pdf"), text.index("COMPETING ORDINARY EXEC"))

    def test_two_concurrent_success_reports_keep_each_job_block_contiguous(self):
        first_ready, release_first = threading.Event(), threading.Event()
        second_attempted, second_finished = threading.Event(), threading.Event()
        errors = []
        other = replace(self.job, variant="charango")
        first_log = self.log("first-atomic.log", "first details\n")
        second_log = self.log("second-atomic.log", "second details\n")
        first_diagnostics = (Diagnostic("Scores", "other", "FIRST JOB DETAIL", first_log),)
        second_diagnostics = (Diagnostic("Scores", "other", "SECOND JOB DETAIL", second_log),)
        report_warnings = pipeline._report_warnings

        def pause_first_report(ui, cfg, job, diagnostics):
            report_warnings(ui, cfg, job, diagnostics)
            if job == self.job:
                first_ready.set()
                if not release_first.wait(timeout=5):
                    raise AssertionError("Timed out waiting to finish first report")

        def report_worker(job, diagnostics):
            try:
                if job == other:
                    second_attempted.set()
                pipeline._report_success(self.ui, self.cfg, job, diagnostics)
            except Exception as error:
                errors.append(error)
            finally:
                if job == other:
                    second_finished.set()

        first = threading.Thread(target=report_worker, args=(self.job, first_diagnostics), daemon=True)
        second = threading.Thread(target=report_worker, args=(other, second_diagnostics), daemon=True)
        with self.capture() as (stdout, stderr), patch.object(
            pipeline, "_report_warnings", side_effect=pause_first_report,
        ):
            first.start()
            try:
                self.assertTrue(first_ready.wait(timeout=5))
                second.start()
                self.assertTrue(second_attempted.wait(timeout=5))
                self.assertFalse(second_finished.wait(timeout=0.1),
                                 "Second success report escaped the first output_block")
            finally:
                release_first.set()
                first.join(timeout=5)
                if second.ident is not None:
                    second.join(timeout=5)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        text = stdout.getvalue() + stderr.getvalue()
        first_path = f"result/{self.basename}.pdf"
        second_path = f"result/{build_job_basename(other)}.pdf"
        self.assertEqual(text.count("WARNING"), 2)
        self.assertEqual(text.count("SUCCESS"), 2)
        self.assertEqual(text.count("SEE"), 2)
        self.assertLess(text.index("FIRST JOB DETAIL"), text.index("compile/first-atomic.log"))
        self.assertLess(text.index("compile/first-atomic.log"), text.index("SUCCESS"))
        self.assertLess(text.index("SUCCESS"), text.index(first_path))
        self.assertLess(text.index(first_path), text.rindex("WARNING"))
        self.assertLess(text.rindex("WARNING"), text.index("SECOND JOB DETAIL"))
        self.assertLess(text.index("SECOND JOB DETAIL"), text.index("compile/second-atomic.log"))
        self.assertLess(text.index("compile/second-atomic.log"), text.rindex("SUCCESS"))
        self.assertLess(text.rindex("SUCCESS"), text.index(second_path))


if __name__ == "__main__":
    unittest.main()
