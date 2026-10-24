# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exercise the compilation/publication boundary and pair-ready orchestration.

Mock expensive subprocess and PDF operations while retaining real step/scheduler
logic. Event-driven tests control completion order without timing sleeps; the
separate TeX/LilyPond suites qualify actual PDF output. Conventional-build tests
at the end also check the generated source-disabled fallback using real TeX.
"""

from __future__ import annotations

import shutil
import json
import signal
import sys
import tempfile
import threading
import unittest
from dataclasses import FrozenInstanceError, replace
from contextlib import contextmanager
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ulsbs import pipeline, resultlist
from ulsbs.config import Config
from ulsbs.constants import (
    RESULT_MULTIKEY_SUBDIRNAME,
    RESULT_TYPE_JSON,
    RESULT_TYPE_MAIN_PDF,
    RESULT_TYPE_MULTIKEY_PDF,
    RESULT_TYPE_MULTIKEY_JSON,
)
from ulsbs.deploy import deploy_results
from ulsbs.diagnostics import Diagnostic
from ulsbs.engine_assets import EngineAssets
from ulsbs.jobs import Job, build_job_basename
from ulsbs.lock import JobLock


class MultikeyPipelineTests(unittest.TestCase):
    """Keep parallel compilation distinct from final MULTIKEY job success."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.doc = self.root / "book_A5.tex"
        self.doc.write_text("\\documentclass{ulsbs-songbook}\n", encoding="utf-8")
        self.result = self.root / "result"
        self.result.mkdir()
        resultlist.initialize(self.result, "pipeline-test")
        self.addCleanup(lambda: resultlist.delete() if resultlist._initialized else None)
        self.deploy = self.root / "deploy"
        self.deploy.mkdir()
        self.paths = SimpleNamespace(project_root=self.root, host_project_root=self.root, result_dir=self.result)
        self.cfg = replace(
            Config(),
            multikey_books=True,
            runtime=SimpleNamespace(project_paths=self.paths, in_container=False),
            deploy_dir=self.deploy,
            midifiles_allow_for_optional_variants=True,
            audiofiles_allow_for_optional_variants=True,
        )
        self.ui = Mock()
        self.ui.fmt_doc.side_effect = lambda job: f"[{job.doc_stem}:{job.variant}:{job.multikey}]"
        self.ui.colorize.side_effect = lambda text, color: text

    def job(self, variant="default", multikey=False) -> Job:
        """Create or reuse a variant/edition's isolated synthetic compile directory."""
        directory = self.root / (variant + ("-multikey" if multikey else ""))
        directory.mkdir(exist_ok=True)
        return Job(self.doc, self.doc.stem, variant, directory, multikey=multikey)

    @contextmanager
    def packaging(self):
        """Keep pipeline publication logic real while replacing PDF-heavy helpers."""
        package, publish = Mock(), Mock()
        with patch.dict(sys.modules, {
            "ulsbs.multikey_ranges": SimpleNamespace(package_ranges=package),
            "ulsbs.multikey_publish": SimpleNamespace(
                publish_package=publish, remove_legacy_outputs=Mock(), remove_package=Mock(),
            ),
        }):
            yield package, publish

    def package_job(self, ui, cfg, job, ordinary_job, payload=None):
        """Exercise the real range step using a synthetic final-pass sidecar."""
        self.write_manifest(job, payload)
        basename = build_job_basename(job)
        return pipeline.step_multikey_ranges(ui, cfg, job, basename, ordinary_job, 5)

    def write_manifest(self, job, payload=None):
        """Write compiler status; schema/content validation is mocked where needed."""
        basename = build_job_basename(job)
        manifest = job.compile_dir / f"{basename}.ulsbs-multikey.json"
        manifest.write_text(json.dumps({
            "has_multikey_info": True,
            "multikey_info": {"songs": []} if payload is None else payload,
        }))

    def test_lilypond_score_opt_in_only_reaches_multikey_non_lyrics_jobs(self) -> None:
        for enabled, books, variant, multikey in product(
                (False, True), (False, True), ("default", "lyrics", "charango", "bassclef"), (False, True)):
            with self.subTest(enabled=enabled, books=books, variant=variant, multikey=multikey):
                cfg = replace(self.cfg, multikey_lilypond_scores=enabled, multikey_books=books)
                job = self.job(variant, multikey)
                text = pipeline.make_variant_tex(job, cfg).read_text(encoding="utf-8")
                expected = enabled and books and multikey and variant != "lyrics"
                self.assertIn(r"\newcommand{\ulMultikeyLilypondScores}{" + str(expected).lower() + "}", text)
                self.assertEqual(r"\providecommand{\ulScoreSystem}" in text, expected)

    def test_multikey_skips_all_ancillary_outputs_even_when_enabled(self) -> None:
        for variant in ("default", "charango", "bassclef"):
            with self.subTest(variant=variant):
                job = self.job(variant, multikey=True)
                basename = build_job_basename(job)
                with patch.object(pipeline, "run_cmd") as command, \
                        patch.object(pipeline, "which") as tool, \
                        patch.object(pipeline, "build_song_database") as database:
                    self.assertEqual(
                        pipeline.step_context_printouts(self.ui, self.cfg, job, basename, {}, 17), 17
                    )
                    self.assertEqual(
                        pipeline.step_coverimage_extraction(self.ui, self.cfg, job, basename, {}, 17), 17
                    )
                    self.assertEqual(
                        pipeline.step_build_song_db(self.ui, self.cfg, job, self.doc, [], 17),
                        (None, 17),
                    )
                    self.assertEqual(
                        pipeline.step_midi_audio(self.ui, Mock(), self.cfg, job, self.doc, Mock(), 17),
                        17,
                    )
                    self.assertEqual(
                        pipeline.step_write_song_db_json(self.ui, self.cfg, job, self.doc, Mock(), 17),
                        17,
                    )
                    command.assert_not_called()
                    tool.assert_not_called()
                    database.assert_not_called()
                self.assertEqual(list(self.result.iterdir()), [])

    def test_export_policy_honors_global_flags_and_optional_opt_ins(self) -> None:
        for variant in ("default", "lyrics", "charango", "bassclef"):
            for multikey, midi, audio, allow_midi, allow_audio in product((False, True), repeat=5):
                with self.subTest(variant=variant, multikey=multikey, flags=(midi, audio, allow_midi, allow_audio)):
                    cfg = replace(
                        self.cfg, midifiles=midi, audiofiles=audio,
                        midifiles_allow_for_optional_variants=allow_midi,
                        audiofiles_allow_for_optional_variants=allow_audio,
                    )
                    expected = (
                        not multikey and midi and (variant == "default" or allow_midi),
                        not multikey and audio and (variant == "default" or allow_audio),
                    )
                    self.assertEqual(pipeline._midi_audio_enabled(cfg, self.job(variant, multikey)), expected)

    def test_job_copy_suppresses_only_unneeded_intermediate_midi(self) -> None:
        assets = EngineAssets()
        cases = ((True, True, False, False), (False, True, True, True),
                 (True, False, True, False), (False, False, True, True))
        for variant in ("default", "lyrics", "charango", "bassclef"):
            for multikey in (False, True):
                for midi_export, audio_export, allow_midi, allow_audio in cases:
                    with self.subTest(variant=variant, multikey=multikey,
                                      flags=(midi_export, audio_export, allow_midi, allow_audio)):
                        job = self.job(variant, multikey)
                        cfg = replace(
                            self.cfg, midifiles=midi_export, audiofiles=audio_export,
                            midifiles_allow_for_optional_variants=allow_midi,
                            audiofiles_allow_for_optional_variants=allow_audio,
                        )
                        pipeline.prepare_compile_dir(self.ui, assets, cfg, job)
                        midi = job.compile_dir / "ulsbs-assets/ly/ulsbs-internal-score-midi.ly"
                        text = midi.read_text(encoding="utf-8")
                        needed = not multikey and (
                            variant == "default" or midi_export and allow_midi or audio_export and allow_audio
                        )
                        self.assertEqual("\\midi" in text, needed)
        with assets.ly_dir() as original:
            self.assertIn("\\midi", (original / midi.name).read_text(encoding="utf-8"))

    def test_audio_only_keeps_midi_and_metadata_without_exporting_either(self) -> None:
        job = self.job("charango")
        cfg = replace(
            self.cfg, json=False, midifiles=False, audiofiles=True,
            audiodir_readme_file=self.root / "removed-audio-readme.md",
        )
        pipeline.prepare_compile_dir(self.ui, EngineAssets(), cfg, job)
        processed = job.compile_dir / (build_job_basename(job) + ".tex")
        processed.write_text(self.doc.read_text(), encoding="utf-8")
        midi = job.compile_dir / "music.midi"
        midi.write_bytes(b"MThd-test")
        song = SimpleNamespace(
            id="song", midi_compile_file_relative=Path("music.midi"),
            chapter_slug="", number="1", order_index=1, title_slug="song", title="Song",
            options={}, chapter_title="", set_audio_result_file_relative=Mock(),
            set_midi_result_file_relative=Mock(),
        )
        db = SimpleNamespace(
            songs_without_chapter=[song], chapters=[], total_songs=1, songs_with_id=1,
            book_info=SimpleNamespace(maintitle="Test", subtitle=None, variant="charango"),
        )
        with patch.object(pipeline, "build_song_database", return_value=db) as build:
            metadata, step = pipeline.step_build_song_db(self.ui, cfg, job, processed, [], 1)
            self.assertIs(metadata, db)
            build.assert_called_once()

        def encode(args, **kwargs):
            self.assertEqual(Path(args[-1]), midi)
            self.assertTrue(midi.is_file())
            target = Path(args[args.index("--outfile-basename") + 1]).with_suffix(".mp3")
            target.write_bytes(b"audio-test")

        resultlist.initialize(self.result, "audio-only")
        try:
            with patch.object(pipeline, "run_cmd", side_effect=encode) as encoder:
                pipeline.step_midi_audio(self.ui, EngineAssets(), cfg, job, processed, db, step)
                encoder.assert_called_once()
            self.assertFalse((self.result / "midi").exists())
            self.assertFalse((self.result / "json").exists())
            self.assertEqual(len(list((self.result / "audio").rglob("*.mp3"))), 1)
            song.set_midi_result_file_relative.assert_not_called()
            song.set_audio_result_file_relative.assert_called_once()
            audio_log = job.compile_dir / f"{step:02d}_encode-audio.log"
            self.assertIn(str(cfg.audiodir_readme_file), audio_log.read_text(encoding="utf-8"))
        finally:
            resultlist.delete()

    def test_compile_publishes_only_ordinary_pdf_and_keeps_master_private(self) -> None:
        resultlist.initialize(self.result, "multikey-test")
        try:
            expected = []
            variants = ("default", "lyrics", "charango", "bassclef")
            cases = [(variant, False) for variant in variants]
            cases += [(variant, True) for variant in variants if variant != "lyrics"]
            for variant, multikey in cases:
                with self.subTest(variant=variant, multikey=multikey):
                    job = self.job(variant, multikey)
                    cfg = self.cfg if multikey else replace(
                        self.cfg, create_printouts=False, coverimage=False, json=False,
                        midifiles=False, audiofiles=False,
                    )
                    events = []
                    basename = build_job_basename(job)
                    output_dir = self.result / RESULT_MULTIKEY_SUBDIRNAME if multikey else self.result
                    output = output_dir / f"{basename}.pdf"

                    def optimize(path, job=job, basename=basename, events=events, output=output):
                        self.assertEqual(path, job.compile_dir / f"{basename}.pdf")
                        self.assertEqual(events, ["pass1", "pass2", "pass3"])
                        self.assertFalse(output.exists())
                        events.append("fonts")
                        path.write_bytes(b"%PDF-optimized\n")
                        return 100, 80, 2

                    optimizer = Mock(side_effect=optimize)

                    def consume(*args, output=output, job=job,
                                basename=basename, events=events):
                        expected_pdf = b"%PDF-optimized\n"
                        if job.multikey:
                            self.assertFalse(output.exists())
                        else:
                            self.assertEqual(output.read_bytes(), expected_pdf)
                        self.assertEqual((job.compile_dir / f"{basename}.pdf").read_bytes(), expected_pdf)
                        self.assertEqual(events[:4], ["pass1", "pass2", "pass3", "fonts"])
                        return args[-1]

                    def lilypond(**kwargs):
                        return kwargs["input_tex"], kwargs["job"].compile_dir / "lilypond.log", kwargs["step"] + 1

                    def latex(ui, cfg, job, basename, env, step, *, pass_no, draftmode, events=events):
                        events.append(f"pass{pass_no}")
                        if job.multikey:
                            (job.compile_dir / f"{basename}.ulsbs-multikey.json").write_text(
                                '{"has_multikey_info": true, "multikey_info": {"songs": []}}'
                            )
                        if not draftmode:
                            (job.compile_dir / f"{basename}.pdf").write_bytes(b"%PDF-test\n")
                        return job.compile_dir / f"pass{pass_no}.log", step + 1

                    with patch.object(pipeline, "prepare_compile_dir"), \
                            patch.object(pipeline, "build_include_paths", return_value=({}, [], [])), \
                            patch.object(pipeline, "step_lilypond_book", side_effect=lilypond) as engraving, \
                            patch.object(pipeline, "step_texlua_indices", side_effect=lambda *args: args[-1] + 1), \
                            patch.object(pipeline, "step_lualatex_pass", side_effect=latex) as passes, \
                            patch.object(pipeline, "step_lualatex_convergence", side_effect=lambda *args: args[-2:]) as convergence, \
                            patch.dict(sys.modules, {"ulsbs.pdf_fonts": SimpleNamespace(deduplicate_fonts=optimizer)}), \
                            patch.object(pipeline, "step_multikey_ranges") as range_step, \
                            patch.object(pipeline, "step_context_printouts", side_effect=consume) as printouts, \
                            patch.object(pipeline, "step_coverimage_extraction", side_effect=consume) as covers, \
                            patch.object(pipeline, "analyze_warnings", return_value=0):
                        self.ui.reset_mock()
                        compilation = pipeline.compile_one_job(self.ui, Mock(), cfg, job)
                        self.assertIsInstance(compilation, pipeline.CompilationResult)
                        self.assertEqual(compilation.warning_count, 0)
                        self.assertGreater(compilation.next_step, 1)
                        engraving.assert_called_once()
                        printouts.assert_called_once()
                        covers.assert_called_once()
                        optimizer.assert_called_once()
                        range_step.assert_not_called()
                        convergence.assert_called_once()
                        if multikey:
                            self.ui.success_line.assert_not_called()
                            self.assertIn("awaiting", self.ui.info_line.call_args.args[0])
                        else:
                            self.ui.success_line.assert_called_once()
                    self.assertEqual(
                        [(call.kwargs["pass_no"], call.kwargs["draftmode"]) for call in passes.call_args_list],
                        [(1, True), (2, False), (3, False)],
                    )
                    directory = self.result / RESULT_MULTIKEY_SUBDIRNAME if multikey else self.result
                    self.assertEqual((directory / (basename + ".pdf")).is_file(), not multikey)
                    self.assertTrue((job.compile_dir / (basename + ".pdf")).is_file())
                    if not multikey:
                        self.ui.space_line.assert_called_with(f"-> result/{basename}.pdf")
                    released = JobLock(job.compile_dir)
                    released.acquire()
                    released.release()
                    if not multikey:
                        expected.append(f"{RESULT_TYPE_MAIN_PDF}\t{basename}.pdf")

            self.assertEqual(resultlist.lines(), expected)
            self.assertFalse((self.result / "json").exists())
            self.assertFalse(list((self.result / RESULT_MULTIKEY_SUBDIRNAME).glob("*")))
        finally:
            resultlist.delete()

    def test_resource_convergence_valid_pdf_needs_no_extra_pass(self) -> None:
        job = self.job(multikey=True)
        basename = build_job_basename(job)
        last_log = job.compile_dir / "06_lualatex-pass3.log"
        last_log.write_text("settled full pass", encoding="utf-8")
        with patch("ulsbs.multikey_ranges.check_pdf_property_resources") as check, \
                patch.object(pipeline, "step_lualatex_pass") as latex:
            self.assertEqual(pipeline.step_lualatex_convergence(
                self.ui, self.cfg, job, basename, {}, last_log, 7,
            ), (last_log, 7))
        check.assert_called_once_with(job.compile_dir / f"{basename}.pdf")
        latex.assert_not_called()

    def test_resource_convergence_unreadable_pdf_fails_without_retry(self) -> None:
        job = self.job(multikey=True)
        cause = OSError("unreadable PDF")
        with patch("ulsbs.multikey_ranges.check_pdf_property_resources", side_effect=cause), \
                patch.object(pipeline, "step_lualatex_pass") as latex:
            with self.assertRaisesRegex(pipeline.CompileError, "Cannot inspect") as error:
                pipeline.step_lualatex_convergence(
                    self.ui, self.cfg, job, build_job_basename(job), {}, self.doc, 7,
                )
        latex.assert_not_called()
        self.assertIs(error.exception.__cause__, cause)
        self.assertIn("unreadable PDF", error.exception.log_path.read_text())

    def test_resource_convergence_extra_full_passes_refresh_manifest_and_logs(self) -> None:
        for retries in (1, 2):
            with self.subTest(retries=retries):
                job = self.job(multikey=True)
                basename = build_job_basename(job)
                manifest = job.compile_dir / f"{basename}.ulsbs-multikey.json"
                manifest.write_text("stale status")
                env = {"TEXINPUTS": "fixture-assets"}
                commands = []

                def latex(args, *, manifest=manifest, basename=basename, expected_env=env,
                          job=job, commands=commands, **kwargs):
                    self.assertFalse(manifest.exists(), "retry retained the old manifest")
                    self.assertEqual(args, ["lualatex", "-file-line-error", "-halt-on-error",
                                            "-interaction=nonstopmode", f"{basename}.tex"])
                    self.assertEqual(kwargs["env"], expected_env)
                    self.assertEqual(kwargs["cwd"], job.compile_dir)
                    commands.append(kwargs["stdout_path"])
                    kwargs["stdout_path"].write_text("full pass")
                    manifest.write_text(json.dumps({"pass": 3 + len(commands)}))

                with patch("ulsbs.multikey_ranges.check_pdf_property_resources",
                           side_effect=[ValueError("stale property")] * retries + [None]) as check, \
                        patch.object(pipeline, "run_cmd", side_effect=latex):
                    last_log, step = pipeline.step_lualatex_convergence(
                        self.ui, self.cfg, job, basename, env, self.doc, 7,
                    )
                self.assertEqual(check.call_count, retries + 1)
                self.assertEqual(commands, [job.compile_dir / f"{7 + i:02d}_lualatex-pass{4 + i}.log"
                                            for i in range(retries)])
                self.assertEqual((last_log, step), (commands[-1], 7 + retries))
                self.assertEqual(json.loads(manifest.read_text()), {"pass": 3 + retries})

    def test_resource_convergence_caps_retries_and_logs_final_failure(self) -> None:
        job = self.job(multikey=True)
        basename = build_job_basename(job)
        with patch("ulsbs.multikey_ranges.check_pdf_property_resources",
                   side_effect=ValueError("Invalid property /rm@oc1: stream")) as check, \
                patch.object(pipeline, "step_lualatex_pass",
                             side_effect=[(self.doc, 8), (self.doc, 9)]) as latex:
            with self.assertRaisesRegex(pipeline.CompileError, "resources did not settle") as error:
                pipeline.step_lualatex_convergence(
                    self.ui, self.cfg, job, basename, {}, self.doc, 7,
                )
        self.assertEqual(check.call_count, 3)
        self.assertEqual([call.args[-2:] for call in latex.call_args_list], [(4, False), (5, False)])
        self.assertEqual(error.exception.log_path, job.compile_dir / "09_lualatex-convergence.log")
        self.assertIn("Invalid property /rm@oc1: stream", error.exception.log_path.read_text())

    def test_compile_converges_before_fonts_and_releases_lock_on_failure(self) -> None:
        for permanent in (False, True):
            with self.subTest(permanent=permanent):
                job = self.job(multikey=True)
                events = []

                def latex(ui, cfg, job, basename, env, step, pass_no, draftmode, events=events):
                    events.append(f"pass{pass_no}")
                    (job.compile_dir / f"{basename}.pdf").write_bytes(b"%PDF-test")
                    log = job.compile_dir / f"{step:02d}_lualatex-pass{pass_no}.log"
                    log.write_text("settled full pass", encoding="utf-8")
                    return log, step + 1

                def fonts(*args, events=events):
                    self.assertEqual(events, ["pass1", "pass2", "pass3", "pass4"])
                    events.append("fonts")
                    return args[-1] + 1

                checks = ValueError("stale property") if permanent else [ValueError("stale property"), None]
                with patch.object(pipeline, "prepare_compile_dir"), \
                        patch.object(pipeline, "build_include_paths", return_value=({}, [], [])), \
                        patch.object(pipeline, "step_lilypond_book", return_value=(self.doc, self.doc, 2)), \
                        patch.object(pipeline, "step_texlua_indices", return_value=4), \
                        patch.object(pipeline, "step_lualatex_pass", side_effect=latex), \
                        patch("ulsbs.multikey_ranges.check_pdf_property_resources", side_effect=checks), \
                        patch.object(pipeline, "step_pdf_fonts", side_effect=fonts) as optimize, \
                        patch.object(pipeline, "analyze_warnings", return_value=0) as warnings:
                    if permanent:
                        with self.assertRaises(pipeline.CompileError):
                            pipeline.compile_one_job(self.ui, Mock(), self.cfg, job)
                        self.assertEqual(events, ["pass1", "pass2", "pass3", "pass4", "pass5"])
                        optimize.assert_not_called()
                        warnings.assert_called_once()
                    else:
                        compilation = pipeline.compile_one_job(self.ui, Mock(), self.cfg, job)
                        self.assertEqual(compilation.next_step, 8)
                        self.assertEqual(warnings.call_args.kwargs["last_lualatex_log"],
                                         job.compile_dir / "06_lualatex-pass4.log")
                        optimize.assert_called_once()
                released = JobLock(job.compile_dir)
                released.acquire()
                released.release()

    def test_step_reads_fresh_renderer_payload_irrespective_json_export(self) -> None:
        job = self.job(multikey=True)
        ordinary = self.job()
        basename = build_job_basename(job)
        payload = {"schema_version": 2, "layer_protocol": "ulsbs:transpose:v1",
                   "coordinate_space": "pdf-user-space", "songs": []}
        (job.compile_dir / f"{basename}.pdf").write_bytes(b"%PDF-test")
        manifest = job.compile_dir / f"{basename}.ulsbs-multikey.json"
        resultlist.initialize(self.result, "capture")
        self.addCleanup(resultlist.delete)
        canonical = self.result / (build_job_basename(ordinary) + ".pdf")
        canonical.write_bytes(b"ordinary")
        resultlist.append_line(RESULT_TYPE_MAIN_PDF, canonical.name)
        with self.packaging() as (package, publish):
            publish.return_value = []
            for export_json in (False, True):
                with self.subTest(json=export_json):
                    envelope = {"has_multikey_info": True,
                                "multikey_info": dict(payload, fresh_pass=export_json)}
                    manifest.write_text(json.dumps(envelope))
                    pipeline.step_multikey_ranges(
                        self.ui, replace(self.cfg, json=export_json), job, basename, ordinary, 5,
                    )
                    self.assertEqual(package.call_args.args[2], envelope)
                    self.assertFalse((self.result / "multikey" / f"{basename}.pdf").exists())
            manifest.unlink()
            with self.assertRaises(pipeline.CompileError):
                pipeline.step_multikey_ranges(self.ui, self.cfg, job, basename, ordinary, 5)
            manifest.write_text('{"has_multikey_info": false, "multikey_info": {}}', encoding="utf-8")
            with self.assertRaisesRegex(pipeline.CompileError, "Invalid multikey metadata envelope"):
                pipeline.step_multikey_ranges(self.ui, self.cfg, job, basename, ordinary, 5)
        self.assertFalse((self.result / "json").exists())

    def test_multikey_step_rejects_missing_or_mismatched_ordinary_job(self) -> None:
        job = self.job(multikey=True)
        ordinary = self.job()
        sources = (None, self.job("charango"), job,
                   replace(ordinary, doc_tex_abs=self.root / "another_A5.tex"))
        resultlist.initialize(self.result, "source-injection")
        self.addCleanup(resultlist.delete)
        for source in sources:
            with self.subTest(source=source), self.packaging() as (package, publish):
                with self.assertRaises(pipeline.CompileError):
                    self.package_job(self.ui, self.cfg, job, source)
                package.assert_not_called()
                publish.assert_not_called()

    def test_compile_forwards_verbose_to_score_generation(self) -> None:
        job = self.job(multikey=True)
        pipeline.prepare_compile_dir(self.ui, EngineAssets(), self.cfg, job)
        basename = build_job_basename(job)
        manifest = job.compile_dir / f"{basename}.ulsbs-multikey.json"
        (job.compile_dir / f"{basename}.ulsbs-score-results.json").write_text('{"scores": []}')

        def latex(*args, **kwargs):
            manifest.write_text('{"has_multikey_info": true, "multikey_info": {"songs": []}}')
            (job.compile_dir / f"{basename}.pdf").write_bytes(b"%PDF-test")
            return self.doc, 4

        resultlist.initialize(self.result, "score-verbosity")
        self.addCleanup(resultlist.delete)
        for verbose in (False, True):
            with self.subTest(verbose=verbose), \
                    patch.object(pipeline, "prepare_compile_dir"), \
                    patch.object(pipeline, "build_include_paths", return_value=({}, [], [])), \
                    patch.object(pipeline, "step_lilypond_book", return_value=(
                        job.compile_dir / f"{basename}.tex", self.doc, 2)), \
                    patch.object(pipeline, "step_texlua_indices", return_value=3), \
                    patch.object(pipeline, "step_lualatex_pass", side_effect=latex), \
                    patch.object(pipeline, "step_lualatex_convergence", side_effect=lambda *args: args[-2:]), \
                    patch.object(pipeline, "step_pdf_fonts", return_value=5), \
                    patch.object(pipeline, "step_multikey_ranges", return_value=(self.result / "ranges.json", 6)), \
                    patch.object(pipeline, "analyze_warnings", return_value=0), \
                    patch("ulsbs.lilypond_scores.prepare_scores", return_value={}), \
                    patch("ulsbs.lilypond_scores.generate_scores") as generate:
                cfg = replace(self.cfg, multikey_lilypond_scores=True, verbose=verbose)
                compilation = pipeline.compile_one_job(self.ui, Mock(), cfg, job)
                self.assertEqual(compilation, pipeline.CompilationResult(0, 5))
                generate.assert_called_once()
                args = generate.call_args.args
                self.assertIs(args[0].ui, self.ui)
                self.assertEqual(args[1:], (job, basename, {}, {}, []))
                self.assertEqual(generate.call_args.kwargs, {"verbose": verbose})

    def test_final_status_is_required_before_any_multikey_publication(self) -> None:
        payload = {"songs": []}
        statuses = (
            {"has_multikey_info": True, "multikey_info": payload},
            {"has_multikey_info": False, "multikey_info": None},
            {"has_multikey_info": False, "multikey_info": {}},
            {"has_multikey_info": True, "multikey_info": None},
            {"has_multikey_info": 1, "multikey_info": {}},
            {}, [], "invalid JSON", None,
        )
        for status, export_json in product(statuses, (False, True)):
            with self.subTest(status=status, json=export_json):
                job = self.job(multikey=True)
                ordinary = self.job()
                basename = build_job_basename(job)
                manifest = job.compile_dir / f"{basename}.ulsbs-multikey.json"
                output = self.result / "multikey" / f"{basename}.pdf"
                output.unlink(missing_ok=True)
                cfg = replace(self.cfg, json=export_json)
                passes = []

                def latex(args, *, manifest=manifest, passes=passes, status=status,
                          job=job, basename=basename, **kwargs):
                    self.assertFalse(manifest.exists(), "previous pass/run status was not purged")
                    passes.append(args)
                    if len(passes) < 3:
                        manifest.write_text(json.dumps(statuses[0]))
                    elif status is not None:
                        manifest.write_text(status if isinstance(status, str) else json.dumps(status))
                    (job.compile_dir / f"{basename}.pdf").write_bytes(b"%PDF-test")

                # Simulate a stale successful artifact left by an earlier run.
                manifest.write_text('{"has_multikey_info": true, "multikey_info": {}}')
                resultlist.initialize(self.result, "status")
                canonical = self.result / (build_job_basename(ordinary) + ".pdf")
                canonical.write_bytes(b"ordinary")
                resultlist.append_line(RESULT_TYPE_MAIN_PDF, canonical.name)
                self.ui.reset_mock()
                try:
                    with self.packaging() as (package, publish), \
                            patch.object(pipeline, "prepare_compile_dir"), \
                            patch.object(pipeline, "build_include_paths", return_value=({}, [], [])), \
                            patch.object(pipeline, "step_lilypond_book", return_value=(job.compile_dir / f"{basename}.tex", self.doc, 2)) as engraving, \
                            patch.object(pipeline, "step_texlua_indices", return_value=3), \
                            patch.object(pipeline, "run_cmd", side_effect=latex), \
                            patch.object(pipeline, "step_lualatex_convergence", side_effect=lambda *args: args[-2:]), \
                            patch.object(pipeline, "step_pdf_fonts", return_value=7) as fonts, \
                            patch.object(pipeline, "analyze_warnings", return_value=0):
                        publish.return_value = []
                        compilation = pipeline.compile_one_job(self.ui, Mock(), cfg, job)
                        self.assertEqual(compilation, pipeline.CompilationResult(0, 7))
                        package.assert_not_called()
                        self.ui.success_line.assert_not_called()
                        if status in statuses[:2]:
                            packaged = pipeline.finish_multikey_job(
                                self.ui, cfg, job, ordinary, compilation,
                            )
                            disabled = status == statuses[1]
                            self.assertEqual(packaged, pipeline.PackagingResult(0, (), skipped=disabled))
                            self.assertFalse(output.exists())
                            if disabled:
                                self.ui.warning_line.assert_not_called()
                                self.assertIn("skipped", self.ui.noexec_line.call_args.args[0])
                                self.ui.success_line.assert_not_called()
                                package.assert_not_called()
                                sys.modules["ulsbs.multikey_publish"].remove_package.assert_called_once_with(
                                    self.result / "multikey" / f"{basename}_RANGES.json",
                                )
                                sys.modules["ulsbs.multikey_publish"].remove_legacy_outputs.assert_called_once()
                            else:
                                package.assert_called_once()
                                self.assertEqual(package.call_args.args[2], status)
                                self.ui.success_line.assert_called_once()
                        else:
                            with self.assertRaises(pipeline.CompileError):
                                pipeline.finish_multikey_job(
                                    self.ui, cfg, job, ordinary, compilation,
                                )
                            self.assertFalse(output.exists())
                            package.assert_not_called()
                        fonts.assert_called_once()
                        self.assertEqual(resultlist.lines(), [f"{RESULT_TYPE_MAIN_PDF}\t{canonical.name}"])
                        engraving.assert_called_once()
                        self.assertEqual(len(passes), 3)
                finally:
                    resultlist.delete()

    def test_step_skips_only_explicit_disabled_payload(self) -> None:
        ordinary, multikey = self.job(), self.job(multikey=True)
        directory = self.result / "json"
        directory.mkdir()
        for disabled in (True, False):
            with self.subTest(disabled=disabled):
                companion = directory / (build_job_basename(multikey) + ".json")
                companion.write_text("stale companion")
                resultlist.initialize(self.result, "disabled-coordinator")
                try:
                    def compile_job(ui, assets, cfg, job, disabled=disabled):
                        if job.multikey:
                            basename = build_job_basename(job)
                            manifest = job.compile_dir / f"{basename}.ulsbs-multikey.json"
                            if disabled:
                                manifest.write_text('{"has_multikey_info": false, "multikey_info": null}')
                            else:
                                manifest.unlink(missing_ok=True)
                        else:
                            pdf = build_job_basename(job) + ".pdf"
                            (self.result / pdf).write_bytes(b"ordinary")
                            resultlist.append_line(RESULT_TYPE_MAIN_PDF, pdf)
                            name = build_job_basename(job) + ".json"
                            (directory / name).write_text('{"book_info": {}}')
                            resultlist.append_line(RESULT_TYPE_JSON, name)
                        return pipeline.CompilationResult(0, 5)

                    with self.packaging() as (package, publish), \
                            patch.object(pipeline, "compile_one_job", side_effect=compile_job):
                        outcome = pipeline.run_jobs_parallel(self.ui, [ordinary, multikey], Mock(), self.cfg)
                    package.assert_not_called()
                    publish.assert_not_called()
                    self.assertEqual([failure.job for failure in outcome.failures],
                                     [] if disabled else [multikey])
                    self.assertEqual(outcome.total_warnings, 0)
                    self.assertEqual([record.job for record in outcome.skipped],
                                     [multikey] if disabled else [])
                    self.assertTrue(all(record.warning_count == 0 for record in outcome.skipped))
                    self.assertEqual(companion.read_text(), "stale companion")
                    self.assertNotIn(f"{RESULT_TYPE_JSON}\t{companion.name}", resultlist.lines())
                finally:
                    resultlist.delete()

    def test_parallel_finishes_matching_pair_and_links_only_ordinary_json(self) -> None:
        for variant, enabled in product(("default", "charango", "bassclef"), (False, True)):
            with self.subTest(variant=variant, json=enabled):
                ordinary = self.job(variant)
                multikey = self.job(variant, multikey=True)
                mk_finished = threading.Event()
                ordinary_finished = threading.Event()
                canonical = self.result / (build_job_basename(ordinary) + ".pdf")
                master = multikey.compile_dir / (build_job_basename(multikey) + ".pdf")
                index_name = build_job_basename(ordinary) + "_MULTIKEY_RANGES.json"
                range_name = build_job_basename(multikey) + "_RANGE_1-2.pdf"
                staged_index = multikey.compile_dir / "ranges" / index_name
                staged_index.parent.mkdir(exist_ok=True)
                stale_range = staged_index.parent / "stale.pdf"
                stale_range.write_bytes(b"old range")
                payload = {"schema_version": 2, "layer_protocol": "ulsbs:transpose:v1",
                           "coordinate_space": "pdf-user-space", "songs": [
                               {"song_id": "song", "occurrence": 1, "original_key": "Am",
                                "key_labels": ["Am", "Bbm"], "layer_prefix": "ulsbs:transpose:v1:id:song",
                                "page_index": 3, "anchor": {"x": 12.5, "y": 300},
                                "layer_page_indices": [3, 4],
                                "has_transposable_content": True}]}
                metadata = {
                    "book_info": {"maintitle": "Full book", "variant": variant,
                                  "output_basename": build_job_basename(ordinary),
                                  "audio_links": [{"url": "https://example.org/album"}]},
                    "chapters": [{"title": "Chapter", "audio_links": [{"url": "chapter.mp3"}],
                                  "songs": [{"id": "song", "lyrics": [["Full lyrics"]],
                                             "translations": [{"language": "fi", "lyrics": [["Words"]]}],
                                             "audio_links": [{"url": "external.mp3"}],
                                             "midi_result_file_relative": "midi/ordinary/song.midi",
                                             "audio_result_file_relative": "audio/ordinary/song.mp3"}]}],
                    "songs_without_chapter": [], "total_songs": 1, "songs_with_id": 1,
                    "creation_time": "fixed", "source_file_relative": "book_A5.tex",
                    "has_multikey_info": False, "multikey_info": None,
                }

                def compile_job(ui, assets, cfg, job,
                                payload=payload, mk_finished=mk_finished, metadata=metadata,
                                master=master, canonical=canonical, ordinary=ordinary,
                                ordinary_finished=ordinary_finished):
                    if job.multikey:
                        master.write_bytes(b"private master")
                        self.write_manifest(job, payload)
                        mk_finished.set()
                        return pipeline.CompilationResult(1, 11)
                    canonical.write_bytes(b"ordinary PDF")
                    resultlist.append_line(RESULT_TYPE_MAIN_PDF, canonical.name)
                    if cfg.json:
                        directory = self.result / "json"
                        directory.mkdir(exist_ok=True)
                        name = build_job_basename(job) + ".json"
                        (directory / name).write_text(json.dumps(metadata), encoding="utf-8")
                        resultlist.append_line(RESULT_TYPE_JSON, name)
                    ordinary_finished.set()
                    return pipeline.CompilationResult(2, 9)

                def package_ranges(*args, mk_finished=mk_finished,
                                   ordinary_finished=ordinary_finished, master=master,
                                   canonical=canonical, staged_index=staged_index,
                                   stale_range=stale_range, **kwargs):
                    self.assertTrue(mk_finished.is_set())
                    self.assertTrue(ordinary_finished.is_set())
                    self.assertEqual(master.read_bytes(), b"private master")
                    self.assertEqual(canonical.read_bytes(), b"ordinary PDF")
                    self.assertFalse((self.result / "multikey" / master.name).exists())
                    self.assertFalse(stale_range.exists())
                    kwargs["warn"]("Range remains larger than requested target")
                    return staged_index

                def publish_package(*args, index_name=index_name, range_name=range_name,
                                    enabled=enabled, ordinary=ordinary):
                    self.assertNotIn(f"{RESULT_TYPE_MULTIKEY_JSON}\t{index_name}", resultlist.lines())
                    self.assertNotIn(f"{RESULT_TYPE_MULTIKEY_PDF}\t{range_name}", resultlist.lines())
                    if enabled:
                        ordinary_json = self.result / "json" / (build_job_basename(ordinary) + ".json")
                        self.assertNotIn("multikey_json_file", json.loads(ordinary_json.read_text())["book_info"])
                    output = self.result / "multikey"
                    output.mkdir(exist_ok=True)
                    (output / index_name).write_text("{}")
                    (output / range_name).write_bytes(b"range")
                    return [range_name, index_name]

                resultlist.initialize(self.result, f"parallel-{variant}-{enabled}")
                try:
                    with self.packaging() as (package, publish), \
                            patch.object(pipeline, "compile_one_job", side_effect=compile_job):
                        package.side_effect = package_ranges
                        publish.side_effect = publish_package
                        cfg = replace(self.cfg, json=enabled, max_parallel=1,
                                      multikey_max_pages_per_range=7,
                                      multikey_target_max_range_bytes=123456)
                        outcome = pipeline.run_jobs_parallel(
                            self.ui, [multikey, ordinary], Mock(), cfg,
                        )
                    package.assert_called_once_with(
                        master, canonical, {"has_multikey_info": True, "multikey_info": payload},
                        multikey.compile_dir / "ranges", max_pages=7, target_bytes=123456,
                        warn=package.call_args.kwargs["warn"],
                    )
                    self.assertTrue(callable(package.call_args.kwargs["warn"]))
                    self.assertIsNot(package.call_args.kwargs["warn"], self.ui.warning_line)
                    publish.assert_called_once_with(staged_index, self.result / "multikey", canonical)
                    self.assertEqual(outcome.failures, [])
                    self.assertEqual(outcome.total_warnings, 4)
                    packaged = next(record for record in outcome.successes if record.job == multikey)
                    self.assertFalse(packaged.skipped)
                    self.assertEqual(packaged.diagnostics[-1].source, "Packaging")
                    self.assertEqual(packaged.diagnostics[-1].category, "oversized-range")
                    self.assertIn("larger than requested", packaged.diagnostics[-1].message)
                    self.assertEqual(outcome.skipped, [])
                    self.assertEqual({success.job for success in outcome.successes}, {ordinary, multikey})
                    self.assertIn(f"{RESULT_TYPE_MULTIKEY_PDF}\t{range_name}", resultlist.lines())
                    self.assertIn(f"{RESULT_TYPE_MULTIKEY_JSON}\t{index_name}", resultlist.lines())
                    self.assertNotIn(f"{RESULT_TYPE_MULTIKEY_PDF}\t{master.name}", resultlist.lines())
                    self.assertFalse((self.result / "multikey" / master.name).exists())
                    companion = self.result / "json" / (build_job_basename(multikey) + ".json")
                    self.assertFalse(companion.exists())
                    if enabled:
                        ordinary_json = companion.parent / (build_job_basename(ordinary) + ".json")
                        data = json.loads(ordinary_json.read_text(encoding="utf-8"))
                        expected = json.loads(json.dumps(metadata))
                        expected["book_info"]["multikey_json_file"] = f"multikey/{index_name}"
                        self.assertEqual(data, expected)
                        self.assertIn(f"{RESULT_TYPE_JSON}\t{ordinary_json.name}", resultlist.lines())
                    else:
                        self.assertFalse((self.result / "json").exists())
                finally:
                    resultlist.delete()
                    if (self.result / "json").exists():
                        shutil.rmtree(self.result / "json")

    def test_single_book_compiles_concurrently_and_finishes_in_same_pool_in_either_order(self) -> None:
        for first_multikey in (False, True):
            with self.subTest(first_multikey=first_multikey):
                ordinary, multikey = self.job(), self.job(multikey=True)
                started = {job: threading.Event() for job in (ordinary, multikey)}
                first_observed = threading.Event()
                packaged = threading.Event()
                workers = set()
                first = multikey if first_multikey else ordinary
                compilation = {ordinary: pipeline.CompilationResult(2, 7),
                               multikey: pipeline.CompilationResult(3, 19)}
                real_wait = pipeline.cf.wait
                real_success = pipeline.JobSuccess

                def compile_job(ui, assets, cfg, job, workers=workers, started=started,
                                ordinary=ordinary, multikey=multikey, first=first,
                                first_observed=first_observed, compilation=compilation):
                    workers.add(threading.get_ident())
                    started[job].set()
                    other = ordinary if job.multikey else multikey
                    self.assertTrue(started[other].wait(5), "paired compilations did not overlap")
                    if job != first:
                        self.assertTrue(first_observed.wait(5), "first compilation never completed")
                    return compilation[job]

                def wait(futures, real_wait=real_wait, compilation=compilation,
                         first=first, first_observed=first_observed, **kwargs):
                    completed, pending = real_wait(futures, **kwargs)
                    if any(future.exception() is None and future.result() == compilation[first]
                           for future in completed):
                        first_observed.set()
                    return completed, pending

                def success(*args, real_success=real_success, packaged=packaged, **kwargs):
                    record = real_success(*args, **kwargs)
                    if record.job.multikey:
                        self.assertTrue(packaged.is_set(), "compiled MK counted before packaging")
                    return record

                def finish(ui, cfg, job, source, result, multikey=multikey, ordinary=ordinary,
                           compilation=compilation, workers=workers, first_observed=first_observed,
                           packaged=packaged):
                    self.assertEqual((job, source, result), (multikey, ordinary, compilation[multikey]))
                    self.assertIn(threading.get_ident(), workers, "packaging ran outside compilation pool")
                    self.assertTrue(first_observed.is_set())
                    self.assertFalse(any(call.kwargs.get("job") == multikey
                                         for call in success_record.call_args_list))
                    packaged.set()
                    return pipeline.PackagingResult(result.warning_count + 1, result.diagnostics)

                with patch.object(pipeline, "compile_one_job", side_effect=compile_job) as compile_mock, \
                        patch.object(pipeline, "finish_multikey_job", side_effect=finish) as finish_mock, \
                        patch.object(pipeline.cf, "wait", side_effect=wait), \
                        patch.object(pipeline, "JobSuccess", side_effect=success) as success_record:
                    outcome = pipeline.run_jobs_parallel(
                        self.ui, [multikey, ordinary], Mock(), replace(self.cfg, max_parallel=2),
                    )
                self.assertEqual(compile_mock.call_count, 2)
                finish_mock.assert_called_once()
                self.assertEqual(outcome.failures, [])
                self.assertEqual({record.job: record.warning_count for record in outcome.successes},
                                 {ordinary: 2, multikey: 4})
                self.assertEqual(outcome.total_warnings, 6)

    def test_failed_ordinary_blocks_running_or_completed_multikey_exactly_once(self) -> None:
        for ordinary_first, multikey_fails in product((False, True), repeat=2):
            with self.subTest(ordinary_first=ordinary_first, multikey_fails=multikey_fails):
                ordinary, multikey = self.job(), self.job(multikey=True)
                mk_started = threading.Event()
                first_observed = threading.Event()
                real_wait = pipeline.cf.wait

                def compile_job(ui, assets, cfg, job, mk_started=mk_started,
                                ordinary_first=ordinary_first, first_observed=first_observed,
                                multikey_fails=multikey_fails):
                    if job.multikey:
                        mk_started.set()
                        if ordinary_first:
                            self.assertTrue(first_observed.wait(5), "ordinary failure not observed")
                        diagnostics = (Diagnostic("TeX", "fonts", "MK font warning", occurrences=9),)
                        if multikey_fails:
                            error = pipeline.CompileError("MK compile failed")
                            error.diagnostics = diagnostics
                            raise error
                        return pipeline.CompilationResult(9, 17, diagnostics)
                    self.assertTrue(mk_started.wait(5), "MK was not submitted concurrently")
                    if not ordinary_first:
                        self.assertTrue(first_observed.wait(5), "MK completion not observed")
                    error = pipeline.CompileError("ordinary compile failed", self.doc)
                    error.diagnostics = (Diagnostic("TeX", "references", "Ordinary reference warning"),)
                    raise error

                def wait(futures, real_wait=real_wait, first_observed=first_observed, **kwargs):
                    completed, pending = real_wait(futures, **kwargs)
                    first_observed.set()
                    return completed, pending

                with self.packaging() as (package, publish), \
                        patch.object(pipeline, "compile_one_job", side_effect=compile_job), \
                        patch.object(pipeline, "finish_multikey_job") as finish, \
                        patch.object(pipeline.cf, "wait", side_effect=wait):
                    outcome = pipeline.run_jobs_parallel(
                        self.ui, [ordinary, multikey], Mock(), replace(self.cfg, max_parallel=2),
                    )
                finish.assert_not_called()
                package.assert_not_called()
                publish.assert_not_called()
                self.assertEqual(outcome.successes, [])
                self.assertCountEqual([record.job for record in outcome.failures], [ordinary, multikey])
                self.assertEqual(outcome.total_warnings, 10)
                self.assertEqual({record.job for record in outcome.errors},
                                 {ordinary, multikey} if multikey_fails else {ordinary})
                self.assertEqual([record.job for record in outcome.blocked],
                                 [] if multikey_fails else [multikey])
                for record in outcome.failures:
                    self.assertEqual(record.blocked, record.job == multikey and not multikey_fails)
                failed_ordinary = next(record for record in outcome.errors if record.job == ordinary)
                self.assertEqual(failed_ordinary.log_path, self.doc)
                self.assertEqual(failed_ordinary.warning_count, 1)

    def test_keyboard_interrupt_during_compile_or_finish_restores_signal_handler(self) -> None:
        ordinary, multikey = self.job(), self.job(multikey=True)
        for stage in ("compile", "finish", "abort"):
            with self.subTest(stage=stage):
                previous = signal.getsignal(signal.SIGINT)

                def compile_job(ui, assets, cfg, job, stage=stage):
                    if stage == "compile":
                        raise KeyboardInterrupt()
                    if stage == "abort":
                        signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
                    return pipeline.CompilationResult(0, 5)

                try:
                    with patch.object(pipeline, "compile_one_job", side_effect=compile_job), \
                            patch.object(pipeline, "finish_multikey_job", side_effect=KeyboardInterrupt) as finish:
                        with self.assertRaises(KeyboardInterrupt):
                            pipeline.run_jobs_parallel(
                                self.ui, [ordinary, multikey], Mock(), replace(self.cfg, max_parallel=1),
                            )
                    self.assertTrue(pipeline.ABORT_EVENT.is_set())
                    self.assertEqual(signal.getsignal(signal.SIGINT), previous)
                    if stage != "finish":
                        finish.assert_not_called()
                    else:
                        finish.assert_called_once()
                finally:
                    pipeline.ABORT_EVENT.clear()

    def test_finish_uses_frozen_compilation_result_and_success_only_after_index(self) -> None:
        ordinary, multikey = self.job(), self.job(multikey=True)
        diagnostics = (Diagnostic("TeX", "fonts", "Font substitution", occurrences=3),)
        compilation = pipeline.CompilationResult(warning_count=3, next_step=17,
                                                 diagnostics=diagnostics)
        with self.assertRaises(FrozenInstanceError):
            compilation.next_step = 99
        published_index = self.result / "multikey" / "book_A5_MULTIKEY_RANGES.json"
        for output in (None, published_index):
            with self.subTest(published=output is not None):
                self.ui.reset_mock()

                def ranges(ui, cfg, job, basename, source, step, output=output):
                    self.assertEqual((job, basename, source, step),
                                     (multikey, build_job_basename(multikey), ordinary, 17))
                    self.ui.success_line.assert_not_called()
                    contender = JobLock(multikey.compile_dir)
                    with self.assertRaisesRegex(RuntimeError, "Locked"):
                        contender.acquire()
                    return output, 18

                with patch.object(pipeline, "step_multikey_ranges", side_effect=ranges) as step, \
                        patch.object(pipeline, "analyze_warnings") as warnings:
                    count = pipeline.finish_multikey_job(
                        self.ui, self.cfg, multikey, ordinary, compilation,
                    )
                step.assert_called_once()
                warnings.assert_not_called()
                self.assertEqual(count, pipeline.PackagingResult(3, diagnostics, skipped=output is None))
                report = json.loads((self.result / "diagnostics" /
                                     (build_job_basename(multikey) + "_DIAGNOSTICS.json")).read_text())
                self.assertEqual(report["status"], "skipped" if output is None else "success")
                self.assertEqual(report["warnings"][0]["occurrences"], 3)
                if output is None:
                    self.ui.success_line.assert_not_called()
                    self.assertFalse(any("->" in call.args[0]
                                         for call in self.ui.space_line.call_args_list))
                else:
                    self.ui.success_line.assert_called_once()
                    self.assertIn("MULTIKEY packaging successful with 3 warnings",
                                  self.ui.success_line.call_args.args[0])
                    self.ui.space_line.assert_any_call("-> result/multikey/book_A5_MULTIKEY_RANGES.json")
                released = JobLock(multikey.compile_dir)
                released.acquire()
                released.release()

    def test_parallel_requires_successful_ordinary_pdf_inventory_from_this_run(self) -> None:
        for mode, enabled in product(("absent", "failed", "missing-inventory", "wrong-variant"),
                                     (False, True)):
            with self.subTest(ordinary=mode, json=enabled):
                ordinary = self.job("charango" if mode == "wrong-variant" else "default")
                multikey = self.job(multikey=True)
                directory = self.result / "json"
                directory.mkdir(exist_ok=True)
                stale = directory / (build_job_basename(ordinary) + ".json")
                stale.write_text("stale invalid JSON")
                canonical = self.result / (build_job_basename(ordinary) + ".pdf")
                canonical.write_bytes(b"stale PDF")
                resultlist.initialize(self.result, "stale")
                try:
                    started = []

                    def compile_job(ui, assets, cfg, job,
                                    mode=mode, canonical=canonical, started=started):
                        started.append(job)
                        if job.multikey:
                            self.write_manifest(job)
                        elif mode == "failed":
                            # Publication before a later compile failure is not success.
                            resultlist.append_line(RESULT_TYPE_MAIN_PDF, canonical.name)
                            resultlist.append_line(RESULT_TYPE_JSON, build_job_basename(job) + ".json")
                            raise pipeline.CompileError("ordinary failed")
                        elif mode == "wrong-variant":
                            resultlist.append_line(RESULT_TYPE_MAIN_PDF, canonical.name)
                        return pipeline.CompilationResult(0, 5)

                    jobs = [multikey] if mode == "absent" else [ordinary, multikey]
                    with self.packaging() as (package, publish), \
                            patch.object(pipeline, "compile_one_job", side_effect=compile_job):
                        outcome = pipeline.run_jobs_parallel(
                            self.ui, jobs, Mock(), replace(self.cfg, json=enabled),
                        )
                    package.assert_not_called()
                    publish.assert_not_called()
                    expected = {ordinary, multikey} if mode == "failed" else {multikey}
                    self.assertEqual({failure.job for failure in outcome.failures}, expected)
                    if mode in ("absent", "failed", "wrong-variant"):
                        self.assertEqual([record.job for record in outcome.blocked], [multikey])
                        self.assertTrue(next(record for record in outcome.failures
                                             if record.job == multikey).blocked)
                    if mode == "failed":
                        self.assertEqual([record.job for record in outcome.errors], [ordinary])
                        self.assertFalse(resultlist.exists())
                        for failed_job in (ordinary, multikey):
                            with resultlist.job_scope(failed_job):
                                self.assertEqual(resultlist.lines(), [])
                    if mode == "missing-inventory":
                        self.assertIn(multikey, started)
                    self.assertEqual(stale.read_text(), "stale invalid JSON")
                    self.assertFalse((directory / (build_job_basename(multikey) + ".json")).exists())
                finally:
                    resultlist.delete()

    def test_multikey_publishes_before_unrelated_ordinary_finishes(self) -> None:
        ordinary, multikey = self.job(), self.job(multikey=True)
        unrelated = self.job("charango")
        unrelated_started = threading.Event()
        unrelated_finished = threading.Event()
        published = threading.Event()
        resultlist.initialize(self.result, "job-local-publication")
        self.addCleanup(resultlist.delete)

        def compile_job(ui, assets, cfg, job):
            if job == unrelated:
                unrelated_started.set()
                self.assertTrue(published.wait(5), "publication waited for unrelated job")
                unrelated_finished.set()
            elif job.multikey:
                self.assertFalse(unrelated_finished.is_set())
                self.write_manifest(job)
                return pipeline.CompilationResult(0, 5)
            else:
                self.assertTrue(unrelated_started.wait(5), "unrelated job never started")
            canonical = self.result / (build_job_basename(job) + ".pdf")
            canonical.write_bytes(b"ordinary")
            resultlist.append_line(RESULT_TYPE_MAIN_PDF, canonical.name)
            return pipeline.CompilationResult(0, 5)

        def publish(*args):
            self.assertFalse(unrelated_finished.is_set())
            published.set()
            return []

        with self.packaging() as (_, publisher), \
                patch.object(pipeline, "compile_one_job", side_effect=compile_job):
            publisher.side_effect = publish
            outcome = pipeline.run_jobs_parallel(
                self.ui, [multikey, ordinary, unrelated], Mock(),
                replace(self.cfg, max_parallel=2),
            )
        self.assertEqual(outcome.failures, [])
        self.assertTrue(published.is_set())
        self.assertTrue(unrelated_finished.is_set())

    def test_independent_failure_does_not_block_other_multikey_variants(self) -> None:
        for failed_variant in (None, "default"):
            with self.subTest(failed_variant=failed_variant):
                ordinary = [self.job(variant) for variant in ("default", "charango")]
                multikey = [self.job(variant, multikey=True) for variant in ("default", "charango")]
                finished = set()
                started = set()
                resultlist.initialize(self.result, "variant-dependencies")
                try:
                    def compile_job(ui, assets, cfg, job,
                                    started=started, ordinary=ordinary, multikey=multikey,
                                    finished=finished, failed_variant=failed_variant):
                        started.add(job)
                        if job.multikey:
                            self.write_manifest(job)
                        else:
                            if job.variant == failed_variant:
                                raise pipeline.CompileError("independent ordinary failure")
                            canonical = self.result / (build_job_basename(job) + ".pdf")
                            canonical.write_bytes(b"ordinary")
                            resultlist.append_line(RESULT_TYPE_MAIN_PDF, canonical.name)
                            finished.add(job)
                        return pipeline.CompilationResult(0, 5)

                    with self.packaging() as (_, publish), \
                            patch.object(pipeline, "compile_one_job", side_effect=compile_job):
                        publish.return_value = []
                        outcome = pipeline.run_jobs_parallel(
                            self.ui, multikey + ordinary, Mock(), replace(self.cfg, max_parallel=1),
                        )
                    self.assertEqual({failure.job for failure in outcome.failures},
                                     {ordinary[0], multikey[0]} if failed_variant else set())
                    self.assertIn(multikey[1], started)
                    self.assertIn(multikey[0], started)
                finally:
                    resultlist.delete()

    def test_parallel_failed_multikey_never_packages_successful_ordinary(self) -> None:
        ordinary, multikey = self.job(), self.job(multikey=True)
        canonical = self.result / (build_job_basename(ordinary) + ".pdf")
        resultlist.initialize(self.result, "failed-multikey")
        self.addCleanup(resultlist.delete)

        def compile_job(ui, assets, cfg, job):
            if job.multikey:
                raise pipeline.CompileError("master failed after metadata capture")
            canonical.write_bytes(b"ordinary")
            resultlist.append_line(RESULT_TYPE_MAIN_PDF, canonical.name)
            return pipeline.CompilationResult(2, 5)

        with self.packaging() as (package, publish), \
                patch.object(pipeline, "compile_one_job", side_effect=compile_job):
            outcome = pipeline.run_jobs_parallel(self.ui, [ordinary, multikey], Mock(), self.cfg)
        package.assert_not_called()
        publish.assert_not_called()
        self.assertEqual([success.job for success in outcome.successes], [ordinary])
        self.assertEqual([failure.job for failure in outcome.failures], [multikey])
        self.assertEqual(outcome.total_warnings, 2)
        self.assertEqual(resultlist.lines(), [f"{RESULT_TYPE_MAIN_PDF}\t{canonical.name}"])

    def test_scheduler_isolates_fake_compile_inventory_until_final_success(self) -> None:
        failed, successful = self.job(), self.job("charango")
        provisional = threading.Event()
        inspected = threading.Event()
        failed_record = f"{RESULT_TYPE_MAIN_PDF}\t{build_job_basename(failed)}.pdf"
        successful_name = build_job_basename(successful) + ".pdf"

        def compile_job(ui, assets, cfg, job):
            if job == failed:
                resultlist.append_line(RESULT_TYPE_MAIN_PDF, build_job_basename(job) + ".pdf")
                self.assertIn(failed_record, resultlist.lines())
                provisional.set()
                self.assertTrue(inspected.wait(5), "other worker never inspected provisional state")
                raise pipeline.CompileError("failed after provisional publication")
            self.assertTrue(provisional.wait(5), "failed worker never staged publication")
            self.assertNotIn(failed_record, resultlist.lines())
            resultlist.append_line(RESULT_TYPE_MAIN_PDF, successful_name)
            inspected.set()
            return pipeline.CompilationResult(0, 5)

        with patch.object(pipeline, "compile_one_job", side_effect=compile_job):
            outcome = pipeline.run_jobs_parallel(
                self.ui, [failed, successful], Mock(), replace(self.cfg, max_parallel=2),
            )
        self.assertEqual([record.job for record in outcome.errors], [failed])
        self.assertEqual([record.job for record in outcome.successes], [successful])
        self.assertEqual(outcome.blocked, [])
        self.assertEqual(resultlist.lines(), [f"{RESULT_TYPE_MAIN_PDF}\t{successful_name}"])
        with resultlist.job_scope(failed):
            self.assertNotIn(failed_record, resultlist.lines())

    def test_parallel_packaging_does_not_read_uninventoried_stale_json(self) -> None:
        ordinary, multikey = self.job(), self.job(multikey=True)
        directory = self.result / "json"
        directory.mkdir()
        stale = directory / (build_job_basename(ordinary) + ".json")
        stale.write_text("stale invalid JSON")
        canonical = self.result / (build_job_basename(ordinary) + ".pdf")
        resultlist.initialize(self.result, "stale-json")
        self.addCleanup(resultlist.delete)

        def compile_job(ui, assets, cfg, job):
            if job.multikey:
                self.write_manifest(job)
            else:
                canonical.write_bytes(b"ordinary")
                resultlist.append_line(RESULT_TYPE_MAIN_PDF, canonical.name)
            return pipeline.CompilationResult(3, 5)

        with self.packaging() as (package, publish), \
                patch.object(pipeline, "compile_one_job", side_effect=compile_job):
            publish.return_value = [build_job_basename(multikey) + "_RANGES.json"]
            outcome = pipeline.run_jobs_parallel(self.ui, [ordinary, multikey], Mock(), self.cfg)
        package.assert_called_once()
        publish.assert_called_once()
        self.assertEqual(outcome.failures, [])
        self.assertEqual(stale.read_text(), "stale invalid JSON")
        self.assertEqual(outcome.total_warnings, 6)

    def test_parallel_packaging_exceptions_remove_old_index_and_fail_only_multikey(self) -> None:
        for failure_stage in ("package", "publish"):
            with self.subTest(stage=failure_stage):
                ordinary, multikey = self.job(), self.job(multikey=True)
                canonical = self.result / (build_job_basename(ordinary) + ".pdf")
                output = self.result / "multikey"
                output.mkdir(exist_ok=True)
                old_index = output / (build_job_basename(multikey) + "_RANGES.json")
                old_index.write_text("stale index")
                directory = self.result / "json"
                directory.mkdir(exist_ok=True)
                ordinary_json = directory / (build_job_basename(ordinary) + ".json")
                original = '{"book_info": {"maintitle": "Ordinary"}}'

                def compile_job(ui, assets, cfg, job,
                                canonical=canonical, ordinary_json=ordinary_json, original=original):
                    if job.multikey:
                        self.write_manifest(job)
                    else:
                        canonical.write_bytes(b"ordinary")
                        ordinary_json.write_text(original)
                        resultlist.append_line(RESULT_TYPE_MAIN_PDF, canonical.name)
                        resultlist.append_line(RESULT_TYPE_JSON, ordinary_json.name)
                    return pipeline.CompilationResult(3, 5, (
                        Diagnostic("TeX", "fonts", "Compiler font warning", occurrences=3),))

                resultlist.initialize(self.result, "packaging-error")
                try:
                    with self.packaging() as (package, publish), \
                            patch.object(pipeline, "compile_one_job", side_effect=compile_job):
                        failing = package if failure_stage == "package" else publish
                        failing.side_effect = ValueError("invalid range package")
                        outcome = pipeline.run_jobs_parallel(self.ui, [ordinary, multikey], Mock(), self.cfg)
                    package.assert_called_once()
                    if failure_stage == "package":
                        publish.assert_not_called()
                    else:
                        publish.assert_called_once()
                    self.assertEqual([success.job for success in outcome.successes], [ordinary])
                    self.assertEqual([failure.job for failure in outcome.failures], [multikey])
                    self.assertIn("invalid range package", outcome.failures[0].reason)
                    self.assertEqual(outcome.total_warnings, 6)
                    self.assertEqual(outcome.blocked, [])
                    self.assertEqual([record.job for record in outcome.errors], [multikey])
                    self.assertEqual(outcome.errors[0].warning_count, 3)
                    self.assertIsNotNone(outcome.errors[0].log_path)
                    self.assertFalse(old_index.exists())
                    self.assertEqual(canonical.read_bytes(), b"ordinary")
                    self.assertEqual(ordinary_json.read_text(), original)
                    self.assertFalse(any(line.startswith((RESULT_TYPE_MULTIKEY_PDF + "\t",
                                                        RESULT_TYPE_MULTIKEY_JSON + "\t"))
                                         for line in resultlist.lines()))
                    released = JobLock(multikey.compile_dir)
                    released.acquire()
                    released.release()
                finally:
                    resultlist.delete()

    def test_packaging_failure_uses_compilation_next_step_and_releases_lock(self) -> None:
        ordinary, multikey = self.job(), self.job(multikey=True)
        basename = build_job_basename(multikey)
        manifest = multikey.compile_dir / f"{basename}.ulsbs-multikey.json"
        resultlist.initialize(self.result, "compile-packaging-error")
        self.addCleanup(resultlist.delete)
        canonical = self.result / (build_job_basename(ordinary) + ".pdf")
        canonical.write_bytes(b"ordinary")
        resultlist.append_line(RESULT_TYPE_MAIN_PDF, canonical.name)

        def latex(*args, **kwargs):
            manifest.write_text('{"has_multikey_info": true, "multikey_info": {"songs": []}}')
            (multikey.compile_dir / f"{basename}.pdf").write_bytes(b"%PDF-test")
            return self.doc, 4

        diagnostics = (Diagnostic("TeX", "fonts", "Font warning", occurrences=3),)

        def analyze(ui, *args, **kwargs):
            ui.diagnostics.extend(diagnostics)
            ui.analyzed = True
            return 3

        with self.packaging() as (package, publish), \
                patch.object(pipeline, "prepare_compile_dir"), \
                patch.object(pipeline, "build_include_paths", return_value=({}, [], [])), \
                patch.object(pipeline, "step_lilypond_book", return_value=(
                    multikey.compile_dir / f"{basename}.tex", self.doc, 2)), \
                patch.object(pipeline, "step_texlua_indices", return_value=3), \
                patch.object(pipeline, "step_lualatex_pass", side_effect=latex), \
                patch.object(pipeline, "step_lualatex_convergence", side_effect=lambda *args: args[-2:]), \
                patch.object(pipeline, "step_pdf_fonts", return_value=7) as fonts, \
                patch.object(pipeline, "analyze_warnings", side_effect=analyze) as warnings:
            def fail(*args, **kwargs):
                fonts.assert_called_once()
                contender = JobLock(multikey.compile_dir)
                with self.assertRaisesRegex(RuntimeError, "Locked"):
                    contender.acquire()
                raise ValueError("invalid range package")

            package.side_effect = fail
            compilation = pipeline.compile_one_job(self.ui, Mock(), self.cfg, multikey)
            self.assertEqual(compilation, pipeline.CompilationResult(3, 7, diagnostics))
            package.assert_not_called()
            self.ui.success_line.assert_not_called()
            released = JobLock(multikey.compile_dir)
            released.acquire()
            released.release()
            with self.assertRaisesRegex(pipeline.CompileError, "invalid range package") as error:
                pipeline.finish_multikey_job(self.ui, self.cfg, multikey, ordinary, compilation)
            publish.assert_not_called()
            warnings.assert_called_once()
            self.ui.success_line.assert_not_called()
        self.assertEqual(error.exception.log_path, multikey.compile_dir / "07_multikey-ranges.log")
        self.assertIn("invalid range package", error.exception.log_path.read_text())
        self.assertEqual(error.exception.diagnostics, diagnostics)
        self.assertEqual(resultlist.lines(), [f"{RESULT_TYPE_MAIN_PDF}\t{canonical.name}"])
        lock = JobLock(multikey.compile_dir)
        lock.acquire()
        lock.release()

    def test_song_id_requirement_is_defined_before_documentclass(self) -> None:
        for required in (False, True):
            job = self.job(multikey=True)
            output = pipeline.make_variant_tex(job, replace(self.cfg, multikey_require_song_ids=required))
            text = output.read_text(encoding="utf-8")
            macro = r"\newcommand{\ulPdfTranspositionRequireSongIDs}{" + str(required).lower() + "}"
            self.assertLess(text.index(macro), text.index(r"\documentclass"))

    def test_job_details_are_verbose_only_and_report_effective_outputs(self) -> None:
        for variant, multikey, verbose, enabled, optional in product(
            ("default", "lyrics", "charango", "bassclef"), (False, True),
            (False, True), (False, True), (False, True),
        ):
            with self.subTest(variant=variant, multikey=multikey, verbose=verbose,
                              enabled=enabled, optional=optional):
                job = self.job(variant, multikey)
                cfg = replace(
                    self.cfg, verbose=verbose, create_printouts=enabled, coverimage=enabled,
                    json=enabled, midifiles=enabled, audiofiles=True,
                    midifiles_allow_for_optional_variants=optional,
                    audiofiles_allow_for_optional_variants=optional,
                )
                self.ui.reset_mock()
                with patch.object(pipeline, "prepare_compile_dir"), \
                        patch.object(pipeline, "which", return_value="/bin/pdftoppm"), \
                        patch.object(pipeline, "make_variant_tex", side_effect=RuntimeError("stop")):
                    with self.assertRaisesRegex(RuntimeError, "stop"):
                        pipeline.compile_one_job(self.ui, Mock(), cfg, job)
                if not verbose:
                    self.ui.debug_line.assert_not_called()
                    continue
                self.assertEqual(self.ui.debug_line.call_count, 1)
                source, outputs = self.ui.debug_line.call_args.args[0].split("\nOutputs:", 1)
                directory = self.result / RESULT_MULTIKEY_SUBDIRNAME if multikey else self.result
                artifact = (f"Index: {directory / (build_job_basename(job) + '_RANGES.json')}"
                            if multikey else f"PDF: {directory / (build_job_basename(job) + '.pdf')}")
                for detail in (f"Source: {self.doc}", f"variant: {variant}",
                               f"edition: {'multikey' if multikey else 'standard'}",
                               f"compile: {job.compile_dir}", artifact):
                    self.assertIn(detail, source)
                midi, audio = pipeline._midi_audio_enabled(cfg, job)
                self.assertIn(f"printouts={not multikey and enabled}", outputs)
                self.assertIn(f"MIDI={midi}, audio={audio}", outputs)
                self.assertIn(f"JSON={'range index' if multikey else enabled}", outputs)
                self.assertIn(f"covers={not multikey and enabled}", outputs)
                layers = cfg.multikey_books and multikey and variant != "lyrics"
                self.assertIn(f"layers={layers}", outputs)
                self.assertEqual("strict IDs=" in outputs, layers)
                self.assertEqual("layer UI=" in outputs, layers)

    def test_startup_paths_use_host_locations_and_artifact_has_its_own_line(self) -> None:
        for in_container, multikey in product((False, True), repeat=2):
            with self.subTest(in_container=in_container, multikey=multikey):
                root = Path("/songbook-data") if in_container else self.root
                paths = SimpleNamespace(project_root=root, host_project_root=self.root,
                                        result_dir=root / "result")
                cfg = replace(self.cfg, verbose=True, use_container=in_container,
                              runtime=SimpleNamespace(project_paths=paths, in_container=in_container))
                job = Job(root / self.doc.name, self.doc.stem, "default",
                          root / "temp" / "book" / "default", multikey)
                self.ui.reset_mock()
                with patch.object(pipeline, "JobLock"), patch.object(pipeline, "prepare_compile_dir"), \
                        patch.object(pipeline, "which", return_value=None), \
                        patch.object(pipeline, "make_variant_tex", side_effect=RuntimeError("stop")):
                    with self.assertRaisesRegex(RuntimeError, "stop"):
                        pipeline._compile_one_job(self.ui, Mock(), cfg, job)
                settings, = self.ui.debug_line.call_args.args
                lines = settings.splitlines()
                self.assertEqual(len(lines), 3)
                self.assertTrue(lines[0].startswith(f"Source: {self.doc}"))
                self.assertIn(f"compile: {self.root / 'temp/book/default'}", lines[0])
                directory = self.result / RESULT_MULTIKEY_SUBDIRNAME if multikey else self.result
                artifact = directory / (build_job_basename(job) + ("_RANGES.json" if multikey else ".pdf"))
                self.assertEqual(lines[1], f"{'Index' if multikey else 'PDF'}: {artifact}")
                self.assertTrue(lines[2].startswith("Outputs:"))
                self.assertNotIn("/songbook-data/", settings)

    def test_deployment_skips_legacy_full_multikey_records_and_preserves_unowned_artifacts(self) -> None:
        resultlist.initialize(self.result, "deploy-test")
        try:
            (self.result / RESULT_MULTIKEY_SUBDIRNAME).mkdir()
            (self.result / "json").mkdir()
            old_result = self.result / "book_MULTIKEY_A5.pdf"
            old_deploy = self.deploy / old_result.name
            old_result.write_bytes(b"old result")
            old_deploy.write_bytes(b"old deploy")
            for result_type, name in (
                (RESULT_TYPE_MAIN_PDF, "book_A5.pdf"),
                (RESULT_TYPE_MULTIKEY_PDF, "book_MULTIKEY_A5.pdf"),
                (RESULT_TYPE_MULTIKEY_PDF, "book_NODEPLOY_MULTIKEY_A5.pdf"),
                (RESULT_TYPE_JSON, "book_A5.json"),
            ):
                directory = self.result
                if result_type == RESULT_TYPE_MULTIKEY_PDF:
                    directory /= RESULT_MULTIKEY_SUBDIRNAME
                elif result_type == RESULT_TYPE_JSON:
                    directory /= "json"
                data = b'{"book_info": {"maintitle": "Ordinary"}}' if result_type == RESULT_TYPE_JSON else name.encode()
                (directory / name).write_bytes(data)
                resultlist.append_line(result_type, name)
            deploy_results(self.ui, self.cfg)
            self.assertEqual(
                {path.name for path in self.deploy.iterdir()},
                {"book_A5.pdf", "book_MULTIKEY_A5.pdf", "json"},
            )
            self.assertEqual(old_result.read_bytes(), b"old result")
            self.assertEqual(old_deploy.read_bytes(), b"old deploy")
            self.assertFalse((self.deploy / "multikey").exists())
            self.assertEqual(
                (self.deploy / "json" / "book_A5.json").read_bytes(),
                (self.result / "json" / "book_A5.json").read_bytes(),
            )
        finally:
            if resultlist._initialized:
                resultlist.delete()


@unittest.skipUnless(shutil.which("lualatex") and shutil.which("qpdf"), "PDF tools unavailable")
class ConventionalManualBuildTests(unittest.TestCase):
    def test_generated_fallback_reports_source_lyrics_and_generic_class_disabled(self) -> None:
        from test_pdf_transposition_layers import PdfStructure
        from test_tex_integration import FIXTURES, compile_fixture

        for name, source_mode in (
            ("repeat-basic", "\\newcommand{\\ulSongbookType}{lyric}\n"),
            ("multikey-disabled-generic", ""),
        ):
            with self.subTest(source=name):
                original = (FIXTURES / f"{name}.tex").read_bytes()
                artifact_name = f"{name}.ulsbs-multikey.json"
                artifacts = {artifact_name: None}
                _, pdf = compile_fixture(
                    name, preamble=pipeline.MULTIKEY_DISABLED_FALLBACK_TEX + source_mode,
                    passes=3, draft_passes=1, artifacts=artifacts,
                    files={artifact_name: b'{"has_multikey_info": true, "multikey_info": {}}'},
                )
                self.assertEqual(json.loads(artifacts[artifact_name]),
                                 {"has_multikey_info": False, "multikey_info": None})
                structure = PdfStructure(pdf)
                self.assertNotIn("/OCProperties", structure.catalog)
                self.assertNotIn("/Metadata", structure.catalog)
                self.assertEqual((FIXTURES / f"{name}.tex").read_bytes(), original)

    def test_generated_fallback_leaves_enabled_style_finisher_unchanged(self) -> None:
        from test_tex_integration import compile_fixture

        artifact_name = "repeat-basic.ulsbs-multikey.json"
        artifacts = {artifact_name: None}
        compile_fixture("repeat-basic", preamble=pipeline.MULTIKEY_DISABLED_FALLBACK_TEX,
                        passes=3, draft_passes=1, artifacts=artifacts)
        envelope = json.loads(artifacts[artifact_name])
        self.assertIs(envelope["has_multikey_info"], True)
        self.assertIsInstance(envelope["multikey_info"], dict)

    def test_bare_style_defaults_to_conventional_pdf(self) -> None:
        from test_pdf_transposition_layers import PdfStructure
        from test_tex_integration import compile_fixture

        _, pdf = compile_fixture("pdf-transposition-layout", multikey=None, passes=2)
        structure = PdfStructure(pdf)
        self.assertEqual(structure.layers, {})
        self.assertNotIn("/OCProperties", structure.catalog)


if __name__ == "__main__":
    unittest.main()
