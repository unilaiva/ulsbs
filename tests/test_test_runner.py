# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The full-suite runner discovers new modules and propagates worker failures."""

from __future__ import annotations

import contextlib
import io
import os
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

import run_tests
from ulsbs import container, testing


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

    def test_container_interrupt_stops_only_the_named_test_run(self):
        root = Path("/source")
        for engine in ("docker", "podman"):
            with self.subTest(engine=engine), patch.dict(os.environ, {}, clear=True), \
                 patch.object(testing, "_find_repository_root", return_value=root), \
                 patch.object(testing, "_pick_container_engine", return_value=engine), \
                 patch.object(testing, "ensure_container_image"), \
                 patch.object(container.subprocess, "run", side_effect=[KeyboardInterrupt,
                              subprocess.CompletedProcess([], 0)]) as run, \
                 contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(testing.main(["--jobs", "12", "--container-memory-gb", "16"]), 130)
                start, stop = (item.args[0] for item in run.call_args_list)
                name = start[start.index("--name") + 1]
                self.assertTrue(name.startswith("ulsbs-test-"))
                self.assertIn("--rm", start)
                self.assertEqual(stop, [engine, "stop", "--time", "2", name])
                self.assertEqual(error.getvalue(), "ulsbs-test: interrupted\n")

    def test_container_interrupt_falls_back_to_force_removal(self):
        name = "ulsbs-test-probe"
        command = ["docker", "run", "--name", name, "ulsbs-compiler"]
        for failure in (subprocess.CompletedProcess([], 1), subprocess.TimeoutExpired([], 5)):
            with self.subTest(failure=failure), \
                 patch.object(container.subprocess, "run", side_effect=[KeyboardInterrupt, failure,
                              subprocess.CompletedProcess([], 0)]) as run:
                with self.assertRaises(KeyboardInterrupt):
                    container._run_named_container(command, name)
                self.assertEqual(run.call_args.args[0], ["docker", "rm", "--force", name])

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_host_interrupt_terminates_and_reaps_the_process_group(self):
        process = Mock(pid=42)
        process.wait.side_effect = [KeyboardInterrupt, subprocess.TimeoutExpired([], 1)]
        with patch.object(testing, "_find_repository_root", return_value=Path("/source")), \
             patch.object(testing.subprocess, "Popen") as popen, \
             patch.object(testing.os, "killpg") as kill, contextlib.redirect_stderr(io.StringIO()):
            context = popen.return_value
            context.__enter__.return_value = process
            self.assertEqual(testing.main(["--no-container"]), 130)
            self.assertTrue(popen.call_args.kwargs["start_new_session"])
            self.assertEqual(kill.call_args_list, [call(42, signal.SIGTERM), call(42, signal.SIGKILL)])
            context.__exit__.assert_called_once()

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

    def test_long_modules_are_scheduled_first_without_skipping_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            for name in ("test_aaa", "test_layout", "test_variants", "test_zzz"):
                (root / "tests" / f"{name}.py").touch()
            with patch.object(run_tests, "ROOT", root), \
                 patch.object(run_tests, "_run", return_value=0) as run, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_tests.main(["--skip-l3build", "--jobs", "1"]), 0)
            self.assertEqual([call.args[0][-1] for call in run.call_args_list],
                             ["test_variants", "test_layout", "test_aaa", "test_zzz"])

    def test_shards_cover_each_discovered_test_once(self):
        for module, count in run_tests.MODULE_SHARDS.items():
            with self.subTest(module=module):
                suite = unittest.defaultTestLoader.loadTestsFromName(module)
                expected = [test.id() for test in run_tests._shard(suite, 0, 1)]
                self.assertGreater(len(expected), count)
                shards = [[test.id() for test in run_tests._shard(suite, index, count)]
                          for index in range(count)]
                for index, shard in enumerate(shards):
                    self.assertEqual(shard, expected[index::count])
                self.assertCountEqual([test for shard in shards for test in shard], expected)

    def test_shard_failure_is_reported_without_skipping_other_shards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            (root / "tests/test_variants.py").touch()

            def execute(command, **kwargs):
                return int(command[-3:] == ["test_variants", "1", "2"])

            with patch.object(run_tests, "ROOT", root), \
                 patch.object(run_tests, "_run", side_effect=execute) as run, \
                 contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(run_tests.main(["--skip-l3build", "--jobs", "2"]), 1)
            self.assertEqual({tuple(call.args[0][-3:]) for call in run.call_args_list},
                             {("test_variants", "0", "2"), ("test_variants", "1", "2")})
            self.assertIn("Failed: test_variants[2/2]", errors.getvalue())

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
