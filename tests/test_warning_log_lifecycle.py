# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Warm log isolation and failed companion bookkeeping without a toolchain."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
import warnings
from unittest.mock import Mock, patch

from ulsbs import pipeline, resultlist
from ulsbs.config import Config
from ulsbs.constants import (
    RESULT_TYPE_JSON,
    RESULT_TYPE_MAIN_PDF,
    RESULT_TYPE_MULTIKEY_JSON,
    RESULT_TYPE_MULTIKEY_PDF,
)
from ulsbs.diagnostics import parse_tool_warnings, strip_tex_warnings
from ulsbs.jobs import Job, build_job_basename
from ulsbs.lock import JobLock
from ulsbs.ui import UI


class WarningLogLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ulsbs-log-lifecycle-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.result_dir = self.root / "result"
        self.result_dir.mkdir()
        self.compile_dir = self.root / "compile"
        self.compile_dir.mkdir()
        self.job = Job(self.root / "book_A5.tex", "book_A5", "default", self.compile_dir)
        self.basename = build_job_basename(self.job)
        self.cfg = replace(Config(), runtime=SimpleNamespace(
            project_paths=SimpleNamespace(project_root=self.root, result_dir=self.result_dir),
            in_container=False,
        ))
        self.ui = UI(use_colors=False)
        resultlist.initialize(self.result_dir, "log-lifecycle")
        self.addCleanup(resultlist.delete)
        resultlist.write_header()

    def test_library_warnings_are_collected_per_worker_and_hook_restored(self):
        other_dir = self.root / "other"
        other_dir.mkdir()
        other = Job(self.root / "other.tex", "other", "default", other_dir)
        barrier = threading.Barrier(2)
        original_hook = warnings.showwarning

        def compile_book(ui, assets, cfg, job):
            barrier.wait(timeout=5)
            warnings.warn(f"library issue for {job.doc_stem}", UserWarning, stacklevel=1)
            return pipeline.CompilationResult(0, 2)

        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors), \
                patch.object(pipeline, "_compile_one_job", side_effect=compile_book):
            outcome = pipeline.run_jobs_parallel(
                self.ui, [self.job, other], Mock(), replace(self.cfg, max_parallel=2),
            )
        self.assertEqual(outcome.failures, [])
        self.assertEqual(outcome.total_warnings, 2)
        for result in outcome.successes:
            self.assertEqual(result.warning_count, 1)
            diagnostic, = result.diagnostics
            self.assertEqual((diagnostic.source, diagnostic.category), ("Python", "UserWarning"))
            self.assertIn(f"library issue for {result.job.doc_stem}", diagnostic.message)
        self.assertEqual(errors.getvalue(), "")
        self.assertIs(warnings.showwarning, original_hook)

    def test_media_logs_reset_once_each_run_and_keep_all_current_songs(self):
        cfg = replace(self.cfg, midifiles=True, audiofiles=True,
                      mididir_readme_file=None, audiodir_readme_file=None)
        songs = []
        for number in (1, 2):
            midi = self.compile_dir / f"song-{number}.midi"
            midi.write_bytes(b"synthetic MIDI")
            songs.append(SimpleNamespace(
                midi_compile_file_relative=midi.name, chapter_slug=None,
                number=number, order_index=number, title_slug=f"song-{number}",
                title=f"Song {number}", options={}, chapter_title=None,
                set_midi_result_file_relative=Mock(), set_audio_result_file_relative=Mock(),
            ))
        db = SimpleNamespace(songs_without_chapter=songs, chapters=[])
        midi_log = self.compile_dir / "09_grab-midi.log"
        audio_log = self.compile_dir / "10_encode-audio.log"
        for path in (midi_log, audio_log):
            path.write_text("warning: STALE prior-run warning\n", encoding="utf-8")

        for emit_warnings in (True, False):
            with self.subTest(emit_warnings=emit_warnings):
                worker = pipeline._JobUI(self.ui, self.job)

                def encode(args, emit_warnings=emit_warnings, **kwargs):
                    self.assertTrue(kwargs["append"])
                    self.assertEqual(kwargs["stdout_path"], audio_log)
                    name = Path(args[-1]).name
                    with audio_log.open("a", encoding="utf-8") as log:
                        log.write(f"Encoded CURRENT {name}\n")
                        if emit_warnings:
                            log.write(f"warning: CURRENT encoder issue for {name}\n")
                    return SimpleNamespace(returncode=0)

                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                        patch.object(pipeline, "run_cmd", side_effect=encode) as command, \
                        patch.object(pipeline, "write_text", wraps=pipeline.write_text) as write:
                    next_step = pipeline.step_midi_audio(
                        worker, Mock(), cfg, self.job,
                        self.compile_dir / f"{self.basename}.tex", db, 9,
                    )
                    count = pipeline.analyze_warnings(worker, cfg, self.job, None, None)
                self.assertEqual(next_step, 11)
                self.assertEqual(command.call_count, 2)
                for path in (midi_log, audio_log):
                    resets = [call for call in write.call_args_list if call.args == (path, "")]
                    self.assertEqual(len(resets), 1)
                    self.assertNotIn("STALE", path.read_text(encoding="utf-8"))
                midi_text = midi_log.read_text(encoding="utf-8")
                audio_text = audio_log.read_text(encoding="utf-8")
                for number in (1, 2):
                    self.assertEqual(midi_text.count(f"Copied MIDI for 'Song {number}'"), 1)
                    self.assertEqual(audio_text.count(f"Encoded CURRENT song-{number}.midi"), 1)
                self.assertEqual(count, 2 if emit_warnings else 0)
                self.assertTrue(all("CURRENT" in item.message for item in worker.diagnostics))

    def test_strip_tex_warnings_matches_parser_headers_and_continuations(self):
        warning_records = (
            "Missing character: There is no EARLY in font demo!\n",
            "Overfull \\hbox (2.0pt too wide) in paragraph at lines 2--3\n",
            "Overfull \\vbox (2.0pt too high) detected at line 4\n",
            "warning  (pdf backend): EARLY duplicate destination\n"
            "    EARLY indented backend detail\n",
            "Package demo Warning: EARLY package warning\n"
            "(demo)                EARLY package continuation.\n",
            "LaTeX Warning: EARLY reference with a very long identifier that reaches the wrap\n"
            "EARLY unindented hard-wrapped continuation.\n",
        )
        context = "book_A5.tex:17: Undefined control sequence.\nl.17 \\BrokenCommand\n"
        for warning in warning_records:
            with self.subTest(warning=warning):
                records = parse_tool_warnings(warning, "TeX")
                self.assertEqual(len(records), 1)
                self.assertEqual(strip_tex_warnings(warning + "\n" + context), "\n" + context)

    def test_preflight_failure_excerpt_omits_tex_warnings_but_preserves_error(self):
        log = self.compile_dir / "01_lilypond.log"
        log.write_text(
            "Missing character: There is no EARLY in font demo!\n"
            "Overfull \\hbox (2.0pt too wide) in paragraph at lines 2--3\n"
            "warning  (pdf backend): EARLY duplicate destination\n"
            "    EARLY backend continuation\n\n"
            "book_A5.tex:17: Undefined control sequence.\n"
            "l.17 \\BrokenCommand\n"
            "! Fatal error occurred, no output PDF file produced!\n",
            encoding="utf-8",
        )
        failure = pipeline.JobFailure(self.job, "lilypond-book failed", log_path=log)
        for verbose in (False, True):
            with self.subTest(verbose=verbose):
                output = io.StringIO()
                with redirect_stdout(output), redirect_stderr(output), \
                        patch.object(pipeline, "strip_tex_warnings", wraps=strip_tex_warnings) as strip:
                    pipeline._report_failure(
                        self.ui, replace(self.cfg, verbose=verbose, max_log_lines=50), failure, {},
                    )
                strip.assert_called_once_with(log.read_text(encoding="utf-8"))
                text = output.getvalue()
                for forbidden in ("EARLY", "Missing character:", "Overfull", "pdf backend"):
                    self.assertNotIn(forbidden, text)
                self.assertIn("book_A5.tex:17: Undefined control sequence.", text)
                self.assertIn("l.17 \\BrokenCommand", text)
                self.assertIn("Fatal error occurred", text)
                self.assertIn("compile/01_lilypond.log", text)

    def assert_metadata_rollback(self, failure_stage):
        companion_dir = self.root / "multikey-compile"
        companion_dir.mkdir()
        companion = replace(self.job, compile_dir=companion_dir, multikey=True)
        metadata_dir = self.result_dir / "json"
        metadata_dir.mkdir()
        metadata = metadata_dir / f"{self.basename}.json"
        original = b'{\n  "book_info": {"title": "Successful ordinary edition"}\n}\n'
        metadata.write_bytes(original)
        resultlist.append_line(RESULT_TYPE_MAIN_PDF, f"{self.basename}.pdf")
        resultlist.append_line(RESULT_TYPE_JSON, metadata.name)
        committed = resultlist.lines()
        index_name = build_job_basename(companion) + "_RANGES.json"
        failure = pipeline.CompileError(f"Synthetic {failure_stage} failure")

        def package(*args):
            data = json.loads(metadata.read_text(encoding="utf-8"))
            data["book_info"]["multikey_json_file"] = f"multikey/{index_name}"
            metadata.write_text(json.dumps(data), encoding="utf-8")
            resultlist.append_line(RESULT_TYPE_MULTIKEY_PDF, "provisional-range.pdf")
            resultlist.append_line(RESULT_TYPE_MULTIKEY_JSON, index_name)
            if failure_stage == "packaging":
                raise failure
            return self.result_dir / "multikey" / index_name, 10

        write_report = pipeline.write_diagnostic_report

        def report(cfg, job, diagnostics, status):
            if failure_stage == "report" and status == "success":
                raise failure
            return write_report(cfg, job, diagnostics, status)

        commit = resultlist.commit_job

        def commit_or_fail(job):
            if failure_stage == "commit":
                raise failure
            return commit(job)

        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output), \
                patch.object(pipeline, "step_multikey_ranges", side_effect=package) as step, \
                patch.object(pipeline, "write_diagnostic_report", side_effect=report), \
                patch.object(resultlist, "commit_job", side_effect=commit_or_fail):
            with self.assertRaises(pipeline.CompileError) as caught:
                pipeline.finish_multikey_job(
                    self.ui, replace(self.cfg, json=True), companion, self.job,
                    pipeline.CompilationResult(0, 9),
                )
        self.assertIs(caught.exception, failure)
        step.assert_called_once()
        self.assertEqual(metadata.read_bytes(), original)
        self.assertEqual(resultlist.lines(), committed)
        with resultlist.job_scope(companion):
            self.assertEqual(resultlist.lines(), committed)
        diagnostic_report = (self.result_dir / "diagnostics"
                             / (build_job_basename(companion) + ".json"))
        self.assertEqual(json.loads(diagnostic_report.read_text(encoding="utf-8"))["status"], "failed")
        self.assertNotIn("SUCCESS", output.getvalue())
        lock = JobLock(companion_dir)
        lock.acquire()
        lock.release()

    def test_metadata_restored_when_packaging_mutates_then_fails(self):
        self.assert_metadata_rollback("packaging")

    def test_metadata_restored_when_success_report_fails(self):
        self.assert_metadata_rollback("report")

    def test_metadata_restored_when_inventory_commit_fails(self):
        self.assert_metadata_rollback("commit")


if __name__ == "__main__":
    unittest.main()
