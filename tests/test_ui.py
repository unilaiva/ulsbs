# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compiler output controls on host streams and across the container boundary."""

from __future__ import annotations

from contextlib import nullcontext
import io
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ulsbs import cli, container, ui
from ulsbs.config import Config


class SpinnerOutputTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {
            "TERM": "xterm-256color", "NO_COLOR": "", "ULSBS_NOSPINNER": "",
        }))
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.enterContext(patch.object(sys, "stdout", self.stdout))
        self.enterContext(patch.object(sys, "stderr", self.stderr))
        self.isatty = self.enterContext(patch.object(self.stdout, "isatty", return_value=True))
        for name, value in {
            "_spinner_supported": None,
            "_spinner_active": False,
            "_spinner_text": None,
            "_spinner_spin": True,
            "_spinner_dots": 0,
            "_spinner_last_width": 0,
            "_spinner_thread": None,
            "_spinner_stop_event": None,
            "_spinner_saved_state": None,
            "_spinner_generation": 0,
            "_cursor_hidden": False,
            "_original_stdout": self.stdout,
            "_original_stderr": self.stderr,
            "_stdout_wrapper": None,
            "_stderr_wrapper": None,
        }.items():
            self.enterContext(patch.object(ui, name, value))
        self.thread = self.enterContext(patch.object(ui.threading, "Thread"))
        self.ui = ui.UI(use_colors=False)
        self.addCleanup(self.ui.stop_spinner)

    def test_disabled_spinner_does_not_write_wrap_streams_or_start_thread(self):
        for tty, env in (
            (False, {}),
            (True, {"TERM": "dumb"}),
            (True, {"ULSBS_NOSPINNER": "1"}),
        ):
            with self.subTest(tty=tty, env=env), patch.dict(os.environ, env):
                self.isatty.return_value = tty
                ui._spinner_supported = None
                self.ui.start_spinner("Working")
                self.ui.suspend_spinner()
                self.ui.resume_spinner()
                self.ui.stop_spinner()
                self.assertFalse(ui._spinner_active)
                self.assertIs(sys.stdout, self.stdout)
                self.assertIs(sys.stderr, self.stderr)
                self.assertEqual(self.stdout.getvalue() + self.stderr.getvalue(), "")
                self.thread.assert_not_called()

    def test_no_color_disables_colors_but_keeps_tty_spinner(self):
        self.enterContext(patch.dict(os.environ, {"NO_COLOR": "1"}))
        self.ui = ui.UI()
        self.assertFalse(self.ui.use_colors)
        self.ui.start_spinner("Working")
        self.assertTrue(ui._spinner_active)
        self.thread.return_value.start.assert_called_once()
        with ui._output_lock:
            ui._spinner_dots = 3
            ui._draw_spinner_frame_unlocked(initial=False)
        self.ui.info_line("Job finished")
        self.ui.stop_spinner()
        text = self.stdout.getvalue()
        self.assertIn("Working...", text)
        self.assertIn("INFO     Job finished\n", text)
        self.assertIn("\033[?25l", text)
        self.assertIn("\033[?25h", text)
        self.assertFalse(ui._spinner_active)

    def test_plain_output_overrides_environment_tty_and_cached_spinner_support(self):
        def run_plain_cli(**kwargs):
            output = kwargs["ui"]
            self.assertFalse(output.use_colors)
            self.assertFalse(output.use_spinner)
            output.start_spinner("Working")
            output.info_line("Plain output")
            self.assertFalse(ui._spinner_active)
            self.assertIs(sys.stdout, self.stdout)
            return 7

        ui._spinner_supported = True
        with patch.dict(os.environ, {"FORCE_COLOR": "1", "PYTHON_COLORS": "1"}), \
                patch.object(ui.UI, "_terminal_supports_colors", return_value=True), \
                patch.object(cli, "_run_cli", side_effect=run_plain_cli), \
                patch.object(sys, "argv", ["ulsbs-compile", "--plain-output"]):
            for argv in (["--plain-output"], ["--plain-out"], None):
                with self.subTest(argv=argv):
                    self.assertEqual(cli.main(argv), 7)
            self.assertEqual(os.environ["NO_COLOR"], "")
            self.assertEqual(os.environ["ULSBS_NOSPINNER"], "")
        self.assertNotIn("\033", self.stdout.getvalue() + self.stderr.getvalue())
        self.thread.assert_not_called()

    def test_plain_output_covers_help_and_argument_errors(self):
        with patch.dict(os.environ, {"FORCE_COLOR": "1", "PYTHON_COLORS": "1"}):
            for argv, status in (
                (["--plain-output", "--help"], 0),
                (["--help", "--plain-output"], 0),
                (["--plain-output", "--unknown-option"], 2),
                (["--plain-output", "--max-parallel", "not-a-number"], 2),
            ):
                with self.subTest(argv=argv), self.assertRaises(SystemExit) as caught:
                    cli.main(argv)
                self.assertEqual(caught.exception.code, status)
                self.assertNotIn("\033", self.stdout.getvalue() + self.stderr.getvalue())
        self.assertIn("--plain-output", self.stdout.getvalue())
        self.thread.assert_not_called()

    def test_plain_output_is_opt_in_and_respects_end_of_options(self):
        with patch.object(ui.UI, "_terminal_supports_colors", return_value=True), \
                patch.object(cli, "_run_cli", return_value=0) as run:
            for argv in ([], ["--", "--plain-output"]):
                with self.subTest(argv=argv):
                    self.assertEqual(cli.main(argv), 0)
                    output = run.call_args.kwargs["ui"]
                    self.assertTrue(output.use_colors)
                    self.assertTrue(output.use_spinner)

    def test_plain_output_reaches_container_as_flag_and_output_policy(self):
        root = Path(__file__).resolve().parents[1]
        project = SimpleNamespace(project_root=root, host_project_root=root,
                                  config_file=root / "ulsbs-config.toml")
        cfg = Config(deploy=False, runtime=SimpleNamespace(
            unique_id="plain-test", project_paths=project, in_container=False,
        ))
        assets = Mock()
        assets.package_mount_root.return_value = nullcontext(root / "src")
        ui._spinner_supported = True
        with patch.dict(os.environ, {"ULSBS_INTERNAL_RUNNING_IN_CONTAINER": ""}), \
                patch.object(cli.ProjectPaths, "from_docs", return_value=project), \
                patch.object(cli, "build_config", return_value=cfg), \
                patch.object(cli, "build_job_queue", return_value=[]), \
                patch.object(cli, "setup_temp_dir"), \
                patch.object(cli, "EngineAssets", return_value=assets), \
                patch.object(container, "_pick_container_engine", return_value="docker"), \
                patch.object(container, "ensure_container_image"), \
                patch.object(container.subprocess, "run", return_value=
                             subprocess.CompletedProcess([], 7)) as run:
            self.assertEqual(cli.main(["--plain-output", "--no-deploy"]), 7)
        command = run.call_args.args[0]
        self.assertIn("NO_COLOR=1", command)
        self.assertIn("ULSBS_NOSPINNER=1", command)
        self.assertIn("--plain-output", command[-1])
        self.assertIn("--no-deploy", command[-1])
        self.thread.assert_not_called()

    def test_container_carries_host_spinner_suppression_into_its_pseudo_tty(self):
        root = Path(__file__).resolve().parents[1]
        cfg = Config(songbooks=(), runtime=SimpleNamespace(
            unique_id="spinner-test",
            project_paths=SimpleNamespace(project_root=root, host_project_root=root),
        ))
        assets = Mock()
        for tty, env, suppressed in (
            (False, {}, True),
            (True, {}, False),
            (True, {"TERM": "dumb"}, True),
            (True, {"ULSBS_NOSPINNER": "1"}, True),
            (True, {"NO_COLOR": "1"}, False),
        ):
            with self.subTest(tty=tty, env=env), patch.dict(os.environ, env), \
                    patch.object(container, "_pick_container_engine", return_value="docker"), \
                    patch.object(container, "ensure_container_image"), \
                    patch.object(container.subprocess, "run", return_value=
                                 subprocess.CompletedProcess([], 7)) as run:
                self.isatty.return_value = tty
                ui._spinner_supported = None
                # Keep color capability independent of spinner capability.
                self.ui.use_colors = not bool(env.get("NO_COLOR"))
                assets.package_mount_root.return_value = nullcontext(root / "src")
                self.assertEqual(container.run_self_in_container(
                    self.ui, assets, cfg, ["--no-deploy"], root / "ulsbs-compile",
                ), 7)
                command = run.call_args.args[0]
                forwarded = dict(command[index + 1].split("=", 1)
                                 for index, arg in enumerate(command) if arg == "-e")
                self.assertEqual(forwarded.get("ULSBS_NOSPINNER"),
                                 "1" if suppressed else None)
                self.assertIn("-it", command)
                # Container stdout is a TTY regardless of the host destination.
                self.isatty.return_value = True
                ui._spinner_supported = None
                with patch.dict(os.environ, {**forwarded, "TERM": "xterm-256color"}):
                    self.assertEqual(ui._detect_spinner_supported(), not suppressed)


if __name__ == "__main__":
    unittest.main()
