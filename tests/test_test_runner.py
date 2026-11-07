# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The full-suite runner discovers new modules and propagates worker failures."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_tests
from ulsbs import testing


class TestRunnerTests(unittest.TestCase):
    def test_worker_has_source_imports_writable_cache_and_reports_status(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(run_tests, "ROOT", Path(directory)), \
             patch.object(run_tests.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 3, "worker failure")) as run, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(run_tests._run(["python3", "-m", "unittest", "test_probe"],
                                           capture=True), 3)
            env = run.call_args.kwargs["env"]
            self.assertEqual(env["PYTHONPATH"].split(os.pathsep)[:2],
                             [str(Path(directory) / "src"), str(Path(directory) / "tests")])
            self.assertTrue(Path(env["TEXMFCACHE"]).is_dir())
            self.assertEqual(env["TEXMFCACHE"], env["TEXMFVAR"])
            self.assertIn("worker failure", output.getvalue())

    def test_wrapper_forwards_parallelism_and_suite_switches(self):
        args = testing._parser().parse_args(["--jobs", "2", "--skip-l3build", "--verbose"])
        self.assertEqual(testing._runner_arguments(args), [
            "python3", "tests/run_tests.py", "--jobs", "2", "--skip-l3build", "--verbose",
        ])

    def test_all_modules_run_and_a_failure_fails_the_suite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            for name in ("test_first.py", "test_second.py", "helper.py"):
                (root / "tests" / name).touch()
            def execute(command, **kwargs):
                return int("test_first" in command)
            with patch.object(run_tests, "ROOT", root), \
                 patch.object(run_tests, "_run", side_effect=execute) as run, \
                 contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run_tests.main(["--skip-l3build", "--jobs", "2"]), 1)
            self.assertEqual({call.args[0][-1] for call in run.call_args_list},
                             {"test_first", "test_second"})

    def test_l3build_failure_stops_before_python(self):
        with patch.object(run_tests, "_run", return_value=7) as run:
            self.assertEqual(run_tests.main([]), 7)
        self.assertEqual(run.call_count, 1)

    def test_invalid_or_empty_suite_is_not_a_pass(self):
        for args in (["--jobs", "0"], ["--skip-l3build", "--skip-integration"]):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), \
                 self.assertRaises(SystemExit):
                run_tests.main(args)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(run_tests, "ROOT", Path(directory)), \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run_tests.main(["--skip-l3build"])


if __name__ == "__main__":
    unittest.main()
