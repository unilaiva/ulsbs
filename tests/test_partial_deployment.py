# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Synthetic scheduler-to-deployment tests for incomplete compilation runs."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from threading import Event, get_ident
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ulsbs import cli, pipeline, resultlist
from ulsbs.config import Config
from ulsbs.constants import (
    RESULTLIST_SEPARATOR,
    RESULT_TYPE_JSON,
    RESULT_TYPE_MAIN_PDF,
    RESULT_TYPE_MULTIKEY_JSON,
    RESULT_TYPE_MULTIKEY_PDF,
)
from ulsbs.deploy import deploy_results
from ulsbs.diagnostics import Diagnostic
from ulsbs.jobs import Job, build_job_basename
from ulsbs.ui import UI


class PartialDeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.result_dir = self.root / "result"
        self.deploy_dir = self.root / "deploy"
        self.result_dir.mkdir()
        self.deploy_dir.mkdir()
        self.paths = SimpleNamespace(
            project_root=self.root, result_dir=self.result_dir,
            config_file=self.root / "config.json",
        )
        self.cfg = replace(
            Config(), max_parallel=2, deploy_dir=self.deploy_dir,
            runtime=SimpleNamespace(project_paths=self.paths, in_container=False),
        )
        self.ui = Mock()
        self.ui.fmt_doc.side_effect = build_job_basename
        self.ui.colorize.side_effect = lambda text, *args: str(text)
        resultlist.initialize(self.result_dir, "partial")
        resultlist.write_header()
        self.addCleanup(self.cleanup_inventory)
        self.addCleanup(pipeline.ABORT_EVENT.clear)

    @staticmethod
    def cleanup_inventory() -> None:
        if resultlist._initialized:
            resultlist.delete()

    def job(self, name: str, *, multikey: bool = False) -> Job:
        directory = self.root / (name + ("-multikey" if multikey else "-ordinary"))
        directory.mkdir(exist_ok=True)
        return Job(self.root / f"{name}.tex", name, "default", directory, multikey)

    def artifact(self, kind: str, name: str, subdir: str = "") -> Path:
        path = self.result_dir / subdir / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"synthetic artifact")
        resultlist.append_line(kind, name)
        return path

    @staticmethod
    def record(kind: str, name: str) -> str:
        return f"{kind}{RESULTLIST_SEPARATOR}{name}"

    def artifact_records(self) -> list[str]:
        kinds = {RESULT_TYPE_MAIN_PDF, RESULT_TYPE_JSON,
                 RESULT_TYPE_MULTIKEY_PDF, RESULT_TYPE_MULTIKEY_JSON}
        return [line for line in resultlist.lines()
                if line.split(RESULTLIST_SEPARATOR, 1)[0] in kinds]

    def finish_and_deploy(self, outcome) -> None:
        resultlist.finalize(runresult=outcome)
        deploy_results(self.ui, self.cfg)

    def test_failed_ordinary_pdf_is_not_inventoried_or_deployed(self) -> None:
        failed, successful = self.job("failed"), self.job("successful")

        def compile_job(ui, assets, cfg, job):
            self.artifact(RESULT_TYPE_MAIN_PDF, f"{job.doc_stem}.pdf")
            if job == failed:
                raise pipeline.CompileError("failure after publishing PDF")
            return pipeline.CompilationResult(2, 8)

        with patch.object(pipeline, "compile_one_job", side_effect=compile_job):
            outcome = pipeline.run_jobs_parallel(self.ui, [failed, successful], Mock(), self.cfg)
        self.assertEqual([item.job for item in outcome.errors], [failed])
        self.assertEqual([item.job for item in outcome.successes], [successful])
        self.assertTrue((self.result_dir / "failed.pdf").exists())
        self.assertEqual(self.artifact_records(), [self.record(RESULT_TYPE_MAIN_PDF, "successful.pdf")])
        self.finish_and_deploy(outcome)
        self.assertFalse((self.deploy_dir / "failed.pdf").exists())
        self.assertEqual((self.deploy_dir / "successful.pdf").read_bytes(), b"synthetic artifact")

    def test_failed_supplemental_step_excludes_all_outputs_of_that_job(self) -> None:
        failed, successful = self.job("supplemental"), self.job("independent")

        def compile_job(ui, assets, cfg, job):
            self.artifact(RESULT_TYPE_MAIN_PDF, f"{job.doc_stem}.pdf")
            if job == failed:
                self.artifact(RESULT_TYPE_JSON, "supplemental.json", "json")
                raise pipeline.CompileError("supplemental metadata step failed")
            return pipeline.CompilationResult(0, 8)

        with patch.object(pipeline, "compile_one_job", side_effect=compile_job):
            outcome = pipeline.run_jobs_parallel(self.ui, [failed, successful], Mock(), self.cfg)
        self.assertTrue((self.result_dir / "json/supplemental.json").exists())
        self.assertTrue((self.result_dir / "supplemental.pdf").exists())
        self.assertEqual(self.artifact_records(), [self.record(RESULT_TYPE_MAIN_PDF, "independent.pdf")])
        self.finish_and_deploy(outcome)
        self.assertFalse((self.deploy_dir / "supplemental.pdf").exists())
        self.assertFalse((self.deploy_dir / "json/supplemental.json").exists())
        self.assertTrue((self.deploy_dir / "independent.pdf").exists())

    def test_packaging_failure_across_threads_discards_all_companion_records(self) -> None:
        ordinary, companion = self.job("book"), self.job("book", multikey=True)
        threads = {}
        provisional = "book-companion-provisional.pdf"
        range_name = "book_MULTIKEY_RANGE_1-2.pdf"
        index_name = "book_MULTIKEY_RANGES.json"

        def compile_job(ui, assets, cfg, job):
            threads[job] = get_ident()
            self.artifact(RESULT_TYPE_MAIN_PDF, provisional if job.multikey else "book.pdf")
            return pipeline.CompilationResult(1, 8)

        def finish_job(ui, cfg, job, source, compilation):
            threads["packaging"] = get_ident()
            self.assertNotEqual(threads[job], threads["packaging"])
            self.assertEqual(source, ordinary)
            self.assertEqual(compilation.next_step, 8)
            self.assertIn(self.record(RESULT_TYPE_MAIN_PDF, provisional), resultlist.lines())
            self.assertIn(self.record(RESULT_TYPE_MAIN_PDF, "book.pdf"), resultlist.lines())
            self.artifact(RESULT_TYPE_MULTIKEY_PDF, range_name, "multikey")
            self.artifact(RESULT_TYPE_MULTIKEY_JSON, index_name, "multikey")
            raise pipeline.CompileError("packaging failed after partial range publication")

        # Guarantee distinct worker threads without depending on pool reuse timing.
        class PhaseExecutor:
            def __init__(self, max_workers):
                self.compilation = ThreadPoolExecutor(max_workers=max_workers)
                self.packaging = ThreadPoolExecutor(max_workers=1)

            def __enter__(self):
                return self

            def submit(self, phase, function, *args):
                pool = self.packaging if function is finish_mock else self.compilation
                return pool.submit(phase, function, *args)

            def __exit__(self, *args):
                self.compilation.shutdown(wait=True)
                self.packaging.shutdown(wait=True)

        with patch.object(pipeline, "compile_one_job", side_effect=compile_job), \
                patch.object(pipeline, "finish_multikey_job", side_effect=finish_job) as finish_mock, \
                patch.object(pipeline.cf, "ThreadPoolExecutor", PhaseExecutor):
            outcome = pipeline.run_jobs_parallel(self.ui, [companion, ordinary], Mock(), self.cfg)
        finish_mock.assert_called_once()
        self.assertEqual([item.job for item in outcome.successes], [ordinary])
        self.assertEqual([item.job for item in outcome.errors], [companion])
        self.assertEqual(self.artifact_records(), [self.record(RESULT_TYPE_MAIN_PDF, "book.pdf")])
        for name in (range_name, index_name):
            self.assertTrue((self.result_dir / "multikey" / name).exists())
        self.finish_and_deploy(outcome)
        self.assertTrue((self.deploy_dir / "book.pdf").exists())
        self.assertFalse((self.deploy_dir / provisional).exists())
        self.assertFalse((self.deploy_dir / "multikey" / range_name).exists())
        self.assertFalse((self.deploy_dir / "multikey" / index_name).exists())

    def test_successful_packaging_uses_packaging_result_and_commits_pending(self) -> None:
        ordinary, companion = self.job("book"), self.job("book", multikey=True)

        def compile_job(ui, assets, cfg, job):
            self.artifact(RESULT_TYPE_MAIN_PDF, "companion.pdf" if job.multikey else "book.pdf")
            return pipeline.CompilationResult(1, 8)

        def finish_job(ui, cfg, job, source, compilation):
            self.assertIn(self.record(RESULT_TYPE_MAIN_PDF, "companion.pdf"), resultlist.lines())
            return pipeline.PackagingResult(2)

        with patch.object(pipeline, "compile_one_job", side_effect=compile_job), \
                patch.object(pipeline, "finish_multikey_job", side_effect=finish_job):
            outcome = pipeline.run_jobs_parallel(self.ui, [companion, ordinary], Mock(), self.cfg)
        self.assertEqual(outcome.failures, [])
        self.assertEqual({item.job: item.warning_count for item in outcome.successes},
                         {ordinary: 1, companion: 2})
        self.assertEqual(outcome.total_warnings, 3)
        self.assertEqual(set(self.artifact_records()), {
            self.record(RESULT_TYPE_MAIN_PDF, "book.pdf"),
            self.record(RESULT_TYPE_MAIN_PDF, "companion.pdf"),
        })
        self.finish_and_deploy(outcome)
        self.assertTrue((self.deploy_dir / "book.pdf").exists())
        self.assertTrue((self.deploy_dir / "companion.pdf").exists())

    def test_blocked_companion_never_deploys_or_double_counts_failure(self) -> None:
        ordinary, companion = self.job("book"), self.job("book", multikey=True)
        independent = self.job("independent")
        for companion_first in (True, False):
            with self.subTest(companion_first=companion_first):
                resultlist.initialize(self.result_dir, f"blocked-{companion_first}")
                resultlist.write_header()

                def compile_job(ui, assets, cfg, job):
                    self.artifact(RESULT_TYPE_MAIN_PDF, build_job_basename(job) + ".pdf")
                    if job == ordinary:
                        raise pipeline.CompileError("ordinary failed")
                    return pipeline.CompilationResult(0, 8)

                pair = [companion, ordinary] if companion_first else [ordinary, companion]
                with patch.object(pipeline, "compile_one_job", side_effect=compile_job), \
                        patch.object(pipeline, "finish_multikey_job") as finish:
                    outcome = pipeline.run_jobs_parallel(
                        self.ui, pair + [independent], Mock(), replace(self.cfg, max_parallel=1),
                    )
                finish.assert_not_called()
                self.assertEqual(len(outcome.failures), 2)
                self.assertEqual([item.job for item in outcome.errors], [ordinary])
                self.assertEqual([item.job for item in outcome.blocked], [companion])
                self.assertTrue(outcome.blocked[0].blocked)
                self.assertEqual([item.job for item in outcome.successes], [independent])
                self.assertEqual(self.artifact_records(), [
                    self.record(RESULT_TYPE_MAIN_PDF, "independent.pdf"),
                ])
                companion_name = build_job_basename(companion) + ".pdf"
                self.assertTrue((self.result_dir / companion_name).exists())
                resultlist.finalize(runresult=outcome)
                self.assertTrue(any(line.endswith("Jobs failed: 1") for line in resultlist.lines()))
                self.assertTrue(any(line.endswith("Jobs blocked: 1") for line in resultlist.lines()))
                deploy_results(self.ui, self.cfg)
                self.assertFalse((self.deploy_dir / "book.pdf").exists())
                self.assertFalse((self.deploy_dir / companion_name).exists())
                self.assertTrue((self.deploy_dir / "independent.pdf").exists())

    def test_scheduler_abort_serializes_and_deploys_only_already_committed_job(self) -> None:
        successful, interrupted = self.job("successful"), self.job("interrupted")
        committed = Event()
        commit_job = resultlist.commit_job

        def commit_and_signal(job):
            commit_job(job)
            if job == successful:
                committed.set()

        def compile_job(ui, assets, cfg, job):
            self.artifact(RESULT_TYPE_MAIN_PDF, job.doc_stem + ".pdf")
            if job == interrupted:
                self.assertTrue(committed.wait(timeout=5))
                raise KeyboardInterrupt()
            return pipeline.CompilationResult(0, 8)

        with patch.object(pipeline, "compile_one_job", side_effect=compile_job), \
                patch.object(resultlist, "commit_job", side_effect=commit_and_signal):
            with self.assertRaises(KeyboardInterrupt):
                pipeline.run_jobs_parallel(
                    self.ui, [successful, interrupted], Mock(), replace(self.cfg, max_parallel=1),
                )
        resultlist.abort(self.result_dir)
        self.assertTrue(any("Compilation ABORTED" in line for line in resultlist.lines()))
        self.assertEqual(self.artifact_records(), [self.record(RESULT_TYPE_MAIN_PDF, "successful.pdf")])
        self.assertTrue((self.result_dir / "interrupted.pdf").exists())
        deploy_results(self.ui, self.cfg)
        self.assertTrue((self.deploy_dir / "successful.pdf").exists())
        self.assertFalse((self.deploy_dir / "interrupted.pdf").exists())

    def test_deploy_last_selects_only_newest_mtime_and_reports_partial_deployment(self) -> None:
        resultlist.delete()
        resultlist.initialize(self.result_dir, "z-older")
        self.artifact(RESULT_TYPE_MAIN_PDF, "older.pdf")
        resultlist.finalize()
        older = resultlist._resultlist_file
        resultlist.initialize(self.result_dir, "a-newer")
        self.artifact(RESULT_TYPE_MAIN_PDF, "newer.pdf")
        resultlist.finalize(runresult=pipeline.ParallelRunResult(
            successes=[], failures=[pipeline.JobFailure(self.job("failed"), "failed")],
        ))
        newer = resultlist._resultlist_file
        os.utime(older, ns=(1_000_000_000, 1_000_000_000))
        os.utime(newer, ns=(2_000_000_000, 2_000_000_000))
        cfg = replace(self.cfg, deploy_last=True)
        with patch.object(cli.ProjectPaths, "from_docs", return_value=self.paths), \
                patch.object(cli, "build_config", return_value=cfg), \
                patch.object(cli, "deploy_results", wraps=deploy_results) as deploy:
            status = cli._run_cli(self.ui, Mock(), ["--deploy-last"])
        self.assertEqual(status, 0)
        deploy.assert_called_once()
        notices = "\n".join(str(call.args[0]) for call in self.ui.info_line.call_args_list)
        self.assertIn("Explicit partial deployment", notices)
        self.assertIn("successful jobs", notices)
        self.assertTrue((self.deploy_dir / "newer.pdf").exists())
        self.assertFalse((self.deploy_dir / "older.pdf").exists())
        self.assertFalse(older.exists())
        self.assertFalse(newer.exists())
        self.assertEqual(resultlist.resultfiles_in_dir(self.result_dir), [])

    def test_summary_distinguishes_warned_success_failures_blocked_and_advisories(self) -> None:
        successful, clean = self.job("successful"), self.job("clean")
        failed, blocked = self.job("failed"), self.job("failed", multikey=True)
        result = pipeline.ParallelRunResult(
            successes=[pipeline.JobSuccess(successful, 2), pipeline.JobSuccess(clean, 0)],
            failures=[
                pipeline.JobFailure(failed, "compile failed", (
                    Diagnostic("LuaLaTeX", "fonts", "failed-job warning"),
                )),
                pipeline.JobFailure(blocked, "ordinary unavailable", blocked=True),
            ],
            total_warnings=3,
        )
        ui = UI(use_colors=False)
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            ui.warning_line("Optional tool unavailable", source="Environment")
            cli.print_run_summary(ui, self.cfg, result, jobs_count=4)
        text = output.getvalue()
        self.assertIn("2 succeeded (1 with warnings), 1 failed, 1 blocked, 0 skipped", text)
        self.assertIn("3 warning diagnostics across all job outcomes", text)
        self.assertIn("2 warnings", text)
        self.assertIn("FAILED", text)
        self.assertIn("compile failed", text)
        self.assertIn("BLOCKED", text)
        self.assertIn("ordinary unavailable", text)
        self.assertIn("Run-level advisories: 1 (separate from job warnings)", text)
        self.assertEqual(len(ui.run_diagnostics), 1)


if __name__ == "__main__":
    unittest.main()
