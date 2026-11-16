# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Qualify wall-time aggregation, worker isolation and edition reporting."""

from __future__ import annotations

import concurrent.futures
import json
import io
import tempfile
import threading
import unittest
from dataclasses import replace
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ulsbs import cli, pipeline, timing
from ulsbs.config import Config
from ulsbs.engine_assets import EngineAssets
from ulsbs.jobs import Job
from ulsbs.ui import UI


class TimingTests(unittest.TestCase):
    def test_unscoped_measurement_is_a_noop(self):
        with patch.object(timing.time, "perf_counter") as clock:
            with timing.measure("unused"):
                pass
        clock.assert_not_called()

    def test_nested_stages_are_inclusive_and_repeated_calls_aggregate(self):
        timings = timing.Timings()
        with patch.object(timing.time, "perf_counter", side_effect=[0, 1, 3, 5, 6, 7]), \
                timing.collect(timings):
            with timing.measure("outer"):
                with timing.measure("inner"):
                    pass
            with timing.measure("inner"):
                pass
        self.assertEqual(timings.stages["outer"], {"calls": 1, "elapsed_seconds": 5, "failures": 0})
        self.assertEqual(timings.stages["inner"], {"calls": 2, "elapsed_seconds": 3, "failures": 0})

    def test_decorator_counts_exceptions_and_context_is_restored(self):
        @timing.measure("call")
        def fail():
            raise KeyboardInterrupt()

        outer, inner = timing.Timings(), timing.Timings()
        with timing.collect(outer):
            with self.assertRaises(KeyboardInterrupt), timing.collect(inner):
                fail()
            with timing.measure("after"):
                pass
        self.assertEqual(inner.stages["call"]["failures"], 1)
        self.assertEqual(set(outer.stages), {"after"})
        with timing.measure("unbound"):
            pass
        self.assertNotIn("unbound", outer.stages)

    def test_parallel_workers_do_not_share_collectors(self):
        barrier = threading.Barrier(2)

        def worker(name):
            timings = timing.Timings()
            with timing.collect(timings), timing.measure(name):
                barrier.wait(timeout=5)
            return timings

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker, name) for name in ("first", "second")]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual([set(result.stages) for result in results], [{"first"}, {"second"}])

    def test_report_is_temporary_json_and_write_failure_is_nonfatal(self):
        timings = timing.Timings()
        timings.add("job.compile", 12.3456789)
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "book.ulsbs-timings.json"
            timings.write(report, elapsed_seconds=12.3456789, kind="job", status="success")
            data = json.loads(report.read_text())
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["elapsed_seconds"], 12.345679)
            self.assertEqual(data["stages"]["job.compile"]["calls"], 1)
            self.assertEqual(data["clock"], "perf_counter")
            timings.write(Path(directory) / "missing" / "report.json", elapsed_seconds=0)

    def test_duration_formats_and_minute_carry(self):
        self.assertEqual(timing.format_seconds(123.456), "123,46 s")
        self.assertEqual(timing.format_seconds(0), "0,00 s")
        self.assertEqual(timing.format_minutes(59.6), "1 min 0 sec")
        self.assertEqual(timing.format_minutes(125.2), "2 min 5 sec")


class EditionTimingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = Job(self.root / "book.tex", "book", "default", self.root)
        self.cfg = replace(Config(), runtime=SimpleNamespace(project_paths=SimpleNamespace(
            project_root=self.root, host_project_root=self.root, result_dir=self.root / "result",
        )))
        self.ui = Mock()
        self.ui.fmt_doc.return_value = "[book]"

    def report(self, job=None):
        job = job or self.job
        return json.loads((job.compile_dir / (pipeline.build_job_basename(job)
                                              + ".ulsbs-timings.json")).read_text())

    def test_ordinary_success_reports_measured_compilation_duration(self):
        with patch.object(pipeline, "_compile_one_job", return_value=pipeline.CompilationResult(0, 5)), \
                patch.object(pipeline, "_report_success") as success, \
                patch.object(pipeline, "write_diagnostic_report"), \
                patch.object(pipeline.resultlist, "commit_job"), \
                patch.object(timing.time, "perf_counter", side_effect=[10, 22.34]):
            result = pipeline.compile_one_job(self.ui, Mock(), self.cfg, self.job)
        self.assertAlmostEqual(success.call_args.kwargs["elapsed_seconds"], 12.34)
        self.assertAlmostEqual(result.timings.seconds("job.compile"), 12.34)
        self.assertEqual(self.report()["status"], "success")

    def test_multikey_duration_sums_compilation_and_packaging_not_idle_time(self):
        job = replace(self.job, multikey=True)
        timings = timing.Timings()
        timings.add("job.compile", 12.34)
        compilation = pipeline.CompilationResult(0, 5, timings=timings)
        with patch.object(pipeline, "_finish_multikey_job", return_value=pipeline.PackagingResult(0)), \
                patch.object(pipeline, "_report_success") as success, \
                patch.object(timing.time, "perf_counter", side_effect=[100, 102.5]):
            pipeline.finish_multikey_job(self.ui, self.cfg, job, self.job, compilation)
        self.assertAlmostEqual(success.call_args.kwargs["elapsed_seconds"], 14.84)
        self.assertAlmostEqual(self.report(job)["elapsed_seconds"], 14.84)
        self.assertEqual(self.report(job)["stages"]["job.packaging"]["calls"], 1)

    def test_failed_and_interrupted_jobs_retain_stage_timings(self):
        for error, status in ((pipeline.CompileError("failed"), "failed"),
                              (KeyboardInterrupt(), "interrupted")):
            with self.subTest(status=status), \
                    patch.object(pipeline, "_compile_one_job", side_effect=error), \
                    patch.object(pipeline, "analyze_warnings"), \
                    patch.object(pipeline, "write_diagnostic_report"), \
                    patch.object(pipeline.resultlist, "discard_job"):
                with self.assertRaises(type(error)):
                    pipeline.compile_one_job(self.ui, Mock(), self.cfg, self.job)
                report = self.report()
                self.assertEqual(report["status"], status)
                self.assertEqual(report["stages"]["job.compile"]["failures"], 1)

    def test_skipped_packaging_does_not_report_success(self):
        with patch.object(pipeline, "_finish_multikey_job",
                          return_value=pipeline.PackagingResult(0, skipped=True)), \
                patch.object(pipeline, "_report_success") as success:
            pipeline.finish_multikey_job(self.ui, self.cfg, self.job, self.job,
                                         pipeline.CompilationResult(0, 5))
        success.assert_not_called()
        self.assertEqual(self.report()["status"], "skipped")


class RunTimingTests(unittest.TestCase):
    def test_run_report_summary_and_successful_cleanup(self):
        for keep_temp in (True, False):
            with self.subTest(keep_temp=keep_temp), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "ulsbs-config.toml").write_text("")
                source = root / "book.tex"
                source.write_text(r"\documentclass{article}\begin{document}Public fixture\end{document}")
                output = io.StringIO()

                def run_jobs(**kwargs):
                    return pipeline.ParallelRunResult([pipeline.JobSuccess(kwargs["jobs"][0], 0)], [])

                def setup(_ui, cfg):
                    cfg.runtime.project_paths.temp_dir.mkdir()

                args = ["--no-container", "--no-deploy", "--no-multikey", "--plain-output", str(source)]
                if keep_temp:
                    args.append("--keep-temp")
                with redirect_stdout(output), redirect_stderr(output), \
                        patch.object(cli, "require_tools"), \
                        patch.object(cli, "setup_temp_dir", side_effect=setup), \
                        patch.object(cli, "run_jobs_parallel", side_effect=run_jobs), \
                        patch.object(timing.time, "perf_counter", side_effect=[10, 11, 22, 75.2]):
                    result = cli._run_cli(UI(use_colors=False, use_spinner=False), EngineAssets(), args)
                self.assertEqual(result, 0)
                self.assertIn("Finished in 1 min 5 sec: 1 jobs; 1 succeeded", output.getvalue())
                reports = list((root / "temp").glob("*.ulsbs-timings.json"))
                if keep_temp:
                    self.assertEqual(len(reports), 1)
                    report = json.loads(reports[0].read_text())
                    self.assertEqual(report["kind"], "run")
                    self.assertEqual(report["elapsed_seconds"], 65.2)
                    self.assertEqual(report["stages"]["run.jobs"]["elapsed_seconds"], 11)
                else:
                    self.assertFalse(reports)
                    self.assertEqual(list((root / "temp").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
