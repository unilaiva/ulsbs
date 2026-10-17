# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Multikey PDF publication, independent jobs, and ancillary-output guards."""

from __future__ import annotations

import shutil
import json
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ulsbs import pipeline, resultlist
from ulsbs.config import Config
from ulsbs.constants import (
    DEPLOY_MULTIKEY_SUBDIRNAME,
    RESULT_MULTIKEY_SUBDIRNAME,
    RESULT_TYPE_JSON,
    RESULT_TYPE_MAIN_PDF,
    RESULT_TYPE_MULTIKEY_PDF,
)
from ulsbs.deploy import deploy_results
from ulsbs.engine_assets import EngineAssets
from ulsbs.jobs import Job, build_job_basename
from ulsbs.lock import JobLock


class MultikeyPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.doc = self.root / "book_A5.tex"
        self.doc.write_text("\\documentclass{ulsbs-songbook}\n", encoding="utf-8")
        self.result = self.root / "result"
        self.result.mkdir()
        self.deploy = self.root / "deploy"
        self.deploy.mkdir()
        self.paths = SimpleNamespace(project_root=self.root, result_dir=self.result)
        self.cfg = replace(
            Config(),
            runtime=SimpleNamespace(project_paths=self.paths, in_container=False),
            deploy_dir=self.deploy,
            midifiles_allow_for_optional_variants=True,
            audiofiles_allow_for_optional_variants=True,
        )
        self.ui = Mock()
        self.ui.fmt_doc.side_effect = lambda job: f"[{job.doc_stem}:{job.variant}:{job.multikey}]"
        self.ui.colorize.side_effect = lambda text, color: text

    def job(self, variant="default", multikey=False) -> Job:
        directory = self.root / (variant + ("-multikey" if multikey else ""))
        directory.mkdir(exist_ok=True)
        return Job(self.doc, self.doc.stem, variant, directory, multikey=multikey)

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

    def test_compile_publishes_distinct_pdf_types_and_full_pass_counts(self) -> None:
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
                            patch.dict(sys.modules, {"ulsbs.pdf_fonts": SimpleNamespace(deduplicate_fonts=optimizer)}), \
                            patch.object(pipeline, "step_context_printouts", side_effect=consume) as printouts, \
                            patch.object(pipeline, "step_coverimage_extraction", side_effect=consume) as covers, \
                            patch.object(pipeline, "analyze_warnings", return_value=0):
                        self.assertEqual(pipeline.compile_one_job(self.ui, Mock(), cfg, job), 0)
                        engraving.assert_called_once()
                        printouts.assert_called_once()
                        covers.assert_called_once()
                        optimizer.assert_called_once()
                    self.assertEqual(
                        [(call.kwargs["pass_no"], call.kwargs["draftmode"]) for call in passes.call_args_list],
                        [(1, True), (2, False), (3, False)],
                    )
                    directory = self.result / RESULT_MULTIKEY_SUBDIRNAME if multikey else self.result
                    self.assertTrue((directory / (build_job_basename(job) + ".pdf")).is_file())
                    self.ui.space_line.assert_called_with(
                        f"-> result/{'multikey/' if multikey else ''}{build_job_basename(job)}.pdf"
                    )
                    released = JobLock(job.compile_dir)
                    released.acquire()
                    released.release()
                    result_type = RESULT_TYPE_MULTIKEY_PDF if multikey else RESULT_TYPE_MAIN_PDF
                    expected.append(f"{result_type}\t{build_job_basename(job)}.pdf")

            self.assertEqual(resultlist.lines(), expected)
            self.assertEqual(
                {path.suffix for path in self.result.iterdir()}, {".pdf", ".txt", ""}
            )
        finally:
            resultlist.delete()

    def test_compile_captures_renderer_payload_only_when_sink_requested(self) -> None:
        job = self.job(multikey=True)
        basename = build_job_basename(job)
        payload = {"schema_version": 1, "layer_protocol": "ulsbs:transpose:v1",
                   "coordinate_space": "pdf-user-space", "songs": []}
        (job.compile_dir / f"{basename}.pdf").write_bytes(b"%PDF-test")
        manifest = job.compile_dir / f"{basename}.ulsbs-multikey.json"

        def latex(*args, **kwargs):
            manifest.write_text(json.dumps({"has_multikey_info": True, "multikey_info": payload}))
            return self.doc, 4

        sink = {}
        resultlist.initialize(self.result, "capture")
        self.addCleanup(resultlist.delete)
        with patch.object(pipeline, "prepare_compile_dir"), \
                patch.object(pipeline, "build_include_paths", return_value=({}, [], [])), \
                patch.object(pipeline, "step_lilypond_book", return_value=(job.compile_dir / f"{basename}.tex", self.doc, 2)), \
                patch.object(pipeline, "step_texlua_indices", return_value=3), \
                patch.object(pipeline, "step_lualatex_pass", side_effect=latex,
                             return_value=(self.doc, 4)) as passes, \
                patch.object(pipeline, "step_pdf_fonts", return_value=5), \
                patch.object(pipeline, "analyze_warnings", return_value=2):
            self.assertEqual(pipeline.compile_one_job(
                self.ui, Mock(), self.cfg, job, multikey_payload_sink=sink
            ), 2)
            manifest.unlink()
            passes.side_effect = None
            # Direct callers must validate status too, even without JSON or a sink.
            with self.assertRaisesRegex(pipeline.CompileError, "Failed to capture multikey metadata"):
                pipeline.compile_one_job(self.ui, Mock(), replace(self.cfg, json=False), job)
            with self.assertRaisesRegex(pipeline.CompileError, "Failed to capture multikey metadata"):
                pipeline.compile_one_job(self.ui, Mock(), self.cfg, job, multikey_payload_sink={})
            manifest.write_text('{"has_multikey_info": false, "multikey_info": {}}', encoding="utf-8")
            with self.assertRaisesRegex(pipeline.CompileError, "Invalid multikey metadata envelope"):
                pipeline.compile_one_job(self.ui, Mock(), self.cfg, job, multikey_payload_sink={})
        shutil.rmtree(job.compile_dir)
        self.assertEqual(sink, {job: payload})
        self.assertFalse((self.result / "json").exists())

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
        for status, export_json, capture in product(statuses, (False, True), (False, True)):
            with self.subTest(status=status, json=export_json, capture=capture):
                job = self.job(multikey=True)
                basename = build_job_basename(job)
                manifest = job.compile_dir / f"{basename}.ulsbs-multikey.json"
                output = self.result / "multikey" / f"{basename}.pdf"
                output.unlink(missing_ok=True)
                sink = {} if capture else None
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
                self.ui.reset_mock()
                try:
                    with patch.object(pipeline, "prepare_compile_dir"), \
                            patch.object(pipeline, "build_include_paths", return_value=({}, [], [])), \
                            patch.object(pipeline, "step_lilypond_book", return_value=(job.compile_dir / f"{basename}.tex", self.doc, 2)) as engraving, \
                            patch.object(pipeline, "step_texlua_indices", return_value=3), \
                            patch.object(pipeline, "run_cmd", side_effect=latex), \
                            patch.object(pipeline, "step_pdf_fonts", return_value=7) as fonts, \
                            patch.object(pipeline, "analyze_warnings", return_value=0):
                        if status in statuses[:2]:
                            warnings = pipeline.compile_one_job(
                                self.ui, Mock(), cfg, job, multikey_payload_sink=sink
                            )
                            disabled = status == statuses[1]
                            self.assertEqual(warnings, int(disabled))
                            self.assertEqual(output.exists(), not disabled)
                            self.assertEqual(len(resultlist.lines()) if resultlist.exists() else 0,
                                             int(not disabled))
                            if capture:
                                self.assertEqual(sink, {job: None} if disabled else
                                                 ({job: payload} if export_json else {}))
                            if disabled:
                                self.ui.warning_line.assert_called_once()
                                self.ui.success_line.assert_not_called()
                                fonts.assert_not_called()
                            else:
                                fonts.assert_called_once()
                        else:
                            with self.assertRaisesRegex(pipeline.CompileError, "Failed to capture multikey metadata"):
                                pipeline.compile_one_job(
                                    self.ui, Mock(), cfg, job, multikey_payload_sink=sink
                                )
                            self.assertFalse(output.exists())
                            self.assertFalse(resultlist.exists())
                            fonts.assert_not_called()
                        engraving.assert_called_once()
                        self.assertEqual(len(passes), 3)
                finally:
                    resultlist.delete()

    def test_coordinator_skips_only_explicit_disabled_payload(self) -> None:
        ordinary, multikey = self.job(), self.job(multikey=True)
        directory = self.result / "json"
        directory.mkdir()
        for disabled in (True, False):
            with self.subTest(disabled=disabled):
                companion = directory / (build_job_basename(multikey) + ".json")
                companion.write_text("stale companion")
                resultlist.initialize(self.result, "disabled-coordinator")
                try:
                    def compile_job(ui, assets, cfg, job, *, multikey_payload_sink, disabled=disabled):
                        if job.multikey:
                            if disabled:
                                multikey_payload_sink[job] = None
                        else:
                            name = build_job_basename(job) + ".json"
                            (directory / name).write_text('{"book_info": {}}')
                            resultlist.append_line(RESULT_TYPE_JSON, name)
                        return int(job.multikey)

                    with patch.object(pipeline, "compile_one_job", side_effect=compile_job):
                        outcome = pipeline.run_jobs_parallel(self.ui, [ordinary, multikey], Mock(), self.cfg)
                    self.assertEqual([failure.job for failure in outcome.failures],
                                     [] if disabled else [multikey])
                    self.assertEqual(companion.read_text(), "stale companion")
                    self.assertNotIn(f"{RESULT_TYPE_JSON}\t{companion.name}", resultlist.lines())
                finally:
                    resultlist.delete()

    def test_parallel_companion_copies_final_matching_metadata_after_cleanup(self) -> None:
        for variant, enabled in product(("default", "charango", "bassclef"), (False, True)):
            with self.subTest(variant=variant, json=enabled):
                ordinary = self.job(variant)
                multikey = self.job(variant, multikey=True)
                mk_finished = threading.Event()
                payload = {"schema_version": 1, "layer_protocol": "ulsbs:transpose:v1",
                           "coordinate_space": "pdf-user-space", "songs": [
                               {"song_id": "song", "occurrence": 1, "original_key": "Am",
                                "key_labels": ["Am", "Bbm"], "layer_prefix": "ulsbs:transpose:v1:id:song",
                                "page_index": 3, "anchor": {"x": 12.5, "y": 300},
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

                def compile_job(ui, assets, cfg, job, *, multikey_payload_sink,
                                payload=payload, mk_finished=mk_finished, metadata=metadata):
                    if job.multikey:
                        if cfg.json:
                            multikey_payload_sink[job] = payload
                        shutil.rmtree(job.compile_dir)
                        mk_finished.set()
                        return 1
                    self.assertTrue(mk_finished.wait(5), "ordinary did not wait for multikey cleanup")
                    if cfg.json:
                        directory = self.result / "json"
                        directory.mkdir(exist_ok=True)
                        name = build_job_basename(job) + ".json"
                        (directory / name).write_text(json.dumps(metadata), encoding="utf-8")
                        resultlist.append_line(RESULT_TYPE_JSON, name)
                    return 2

                resultlist.initialize(self.result, f"parallel-{variant}-{enabled}")
                try:
                    with patch.object(pipeline, "compile_one_job", side_effect=compile_job):
                        outcome = pipeline.run_jobs_parallel(
                            self.ui, [multikey, ordinary], Mock(),
                            replace(self.cfg, json=enabled, max_parallel=2),
                        )
                    self.assertEqual(outcome.failures, [])
                    self.assertEqual(outcome.total_warnings, 3)
                    companion = self.result / "json" / (build_job_basename(multikey) + ".json")
                    if enabled:
                        data = json.loads(companion.read_text(encoding="utf-8"))
                        self.assertEqual(data.pop("multikey_info"), payload)
                        self.assertIs(data.pop("has_multikey_info"), True)
                        self.assertEqual(data["book_info"].pop("output_basename"), build_job_basename(multikey))
                        expected = json.loads(json.dumps(metadata))
                        expected.pop("multikey_info")
                        expected.pop("has_multikey_info")
                        expected["book_info"].pop("output_basename")
                        self.assertEqual(data, expected)
                        self.assertIn(f"{RESULT_TYPE_JSON}\t{companion.name}", resultlist.lines())
                        self.assertEqual(json.loads((companion.parent / (build_job_basename(ordinary) + ".json")).read_text()), metadata)
                    else:
                        self.assertFalse(companion.exists())
                finally:
                    resultlist.delete()
                    if (self.result / "json").exists():
                        shutil.rmtree(self.result / "json")

    def test_parallel_failed_or_missing_ordinary_export_never_reads_stale_json(self) -> None:
        for failed in (False, True):
            with self.subTest(ordinary_failed=failed):
                ordinary, multikey = self.job(), self.job(multikey=True)
                directory = self.result / "json"
                directory.mkdir(exist_ok=True)
                (directory / (build_job_basename(ordinary) + ".json")).write_text("stale invalid JSON")
                resultlist.initialize(self.result, "stale")
                try:
                    def compile_job(ui, assets, cfg, job, *, multikey_payload_sink, failed=failed):
                        if job.multikey:
                            multikey_payload_sink[job] = {"songs": []}
                        elif failed:
                            # A failed ordinary job may already have published its JSON.
                            resultlist.append_line(RESULT_TYPE_JSON, build_job_basename(job) + ".json")
                            raise pipeline.CompileError("ordinary failed")
                        return 0

                    with patch.object(pipeline, "compile_one_job", side_effect=compile_job):
                        outcome = pipeline.run_jobs_parallel(self.ui, [ordinary, multikey], Mock(), self.cfg)
                    self.assertEqual([failure.job for failure in outcome.failures], [ordinary] if failed else [])
                    self.assertFalse((directory / (build_job_basename(multikey) + ".json")).exists())
                finally:
                    resultlist.delete()

    def test_parallel_companion_merge_failure_marks_multikey_failed(self) -> None:
        ordinary, multikey = self.job(), self.job(multikey=True)
        directory = self.result / "json"
        directory.mkdir()
        resultlist.initialize(self.result, "bad-merge")
        self.addCleanup(resultlist.delete)

        def compile_job(ui, assets, cfg, job, *, multikey_payload_sink):
            if job.multikey:
                multikey_payload_sink[job] = {"songs": []}
            else:
                name = build_job_basename(job) + ".json"
                (directory / name).write_text("invalid JSON", encoding="utf-8")
                resultlist.append_line(RESULT_TYPE_JSON, name)
            return 3

        with patch.object(pipeline, "compile_one_job", side_effect=compile_job):
            outcome = pipeline.run_jobs_parallel(self.ui, [ordinary, multikey], Mock(), self.cfg)
        self.assertEqual([success.job for success in outcome.successes], [ordinary])
        self.assertEqual([failure.job for failure in outcome.failures], [multikey])
        self.assertIn("Failed to publish multikey JSON", outcome.failures[0].reason)
        self.assertEqual(outcome.total_warnings, 3)

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
                    self.ui.space_line.assert_not_called()
                    continue
                self.assertEqual(self.ui.space_line.call_count, 2)
                source, outputs = [call.args[0] for call in self.ui.space_line.call_args_list]
                directory = self.result / RESULT_MULTIKEY_SUBDIRNAME if multikey else self.result
                for detail in (f"Source: {self.doc}", f"variant: {variant}",
                               f"edition: {'multikey' if multikey else 'standard'}",
                               f"compile: {job.compile_dir}",
                               f"PDF: {directory / (build_job_basename(job) + '.pdf')}"):
                    self.assertIn(detail, source)
                midi, audio = pipeline._midi_audio_enabled(cfg, job)
                self.assertIn(f"printouts={not multikey and enabled}", outputs)
                self.assertIn(f"MIDI={midi}, audio={audio}", outputs)
                self.assertIn(f"JSON={'companion' if multikey and enabled else enabled}", outputs)
                self.assertIn(f"covers={not multikey and enabled}", outputs)
                layers = cfg.multikey_books and multikey and variant != "lyrics"
                self.assertIn(f"layers={layers}", outputs)
                self.assertEqual("strict IDs=" in outputs, layers)
                self.assertEqual("layer UI=" in outputs, layers)

    def test_deployment_routes_multikey_pdfs_without_moving_json_or_old_pdfs(self) -> None:
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
                (RESULT_TYPE_JSON, "book_MULTIKEY_A5.json"),
            ):
                directory = self.result
                if result_type == RESULT_TYPE_MULTIKEY_PDF:
                    directory /= RESULT_MULTIKEY_SUBDIRNAME
                elif result_type == RESULT_TYPE_JSON:
                    directory /= "json"
                (directory / name).write_bytes(name.encode())
                resultlist.append_line(result_type, name)
            deploy_results(self.ui, self.cfg)
            self.assertEqual(
                {path.name for path in self.deploy.iterdir()},
                {"book_A5.pdf", "book_MULTIKEY_A5.pdf", "multikey", "json"},
            )
            self.assertEqual(
                (self.deploy / DEPLOY_MULTIKEY_SUBDIRNAME / "book_MULTIKEY_A5.pdf").read_bytes(),
                b"book_MULTIKEY_A5.pdf",
            )
            self.assertEqual(old_result.read_bytes(), b"old result")
            self.assertEqual(old_deploy.read_bytes(), b"old deploy")
            self.assertEqual(
                {path.name for path in (self.deploy / "multikey").iterdir()},
                {"book_MULTIKEY_A5.pdf"},
            )
            self.assertEqual(
                (self.deploy / "json" / "book_MULTIKEY_A5.json").read_bytes(),
                b"book_MULTIKEY_A5.json",
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
